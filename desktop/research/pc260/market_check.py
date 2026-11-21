"""Replay the released PC 2.6 scheduled rules on preverified public minute data."""
"""Replay closed-candle signals against subsequent one-minute OKX trades. Public data only.
Run from a study directory with OKX_PC_PACKAGE/, raw/, and ins.json. --help lists options.
"""
import argparse
import os
import concurrent.futures
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(os.environ.get('PC_PACKAGE','OKX_PC_PACKAGE')).resolve()
sys.path[:0] = [str(ROOT/'runtime'), str(ROOT/'core')]
import pc_monthly as m
import pc_scalp as sc
import pc_timing as timing

MINUTE = 60000
HOUR = 60*MINUTE
DAY = 24*HOUR
COINS = [s.split('-')[0] for s in sc.SYMBOLS]
FIELDS = ['open','high','low','close','vol']
CACHE = Path('market_cache')
SOURCE = Path(os.environ.get('PC_REPLAY_INPUT','target_cache/recent'))
INSTRUMENTS = Path(os.environ.get('PC_INSTRUMENTS','ins.json'))


def stamp(v):
    return int(pd.Timestamp(v,tz='Asia/Seoul').timestamp()*1000)


def prepare(job):
    sym,base,end=job
    source=np.load(SOURCE/f'{sym}-1.npy',mmap_mode='r')
    assert len(source)==(end-base)//MINUTE
    for step in (1,15,60):
        if step<60:
            a=np.load(SOURCE/f'{sym}-{step}.npy',mmap_mode='r')[:,:5]
        else:
            view=source[:len(source)//60*60,:5].reshape(-1,60,5)
            a=np.column_stack((view[:,0,0],view[:,:,1].max(1),view[:,:,2].min(1),view[:,-1,3],view[:,:,4].sum(1)))
            a[~np.isfinite(view).all(axis=(1,2))]=np.nan
        np.save(CACHE/f'{sym}-{step}.npy',a)
    return sym,int(np.isnan(source[:,3]).sum())


def market(base,end):
    tt=np.arange(base,end,15*MINUTE)
    arr={s:np.load(CACHE/f'{s}-15.npy',mmap_mode='r') for s in COINS}
    prices=pd.DataFrame({s:a[:,3] for s,a in arr.items()},index=tt+15*MINUTE)
    opens=pd.DataFrame({s:a[:,0] for s,a in arr.items()},index=tt)
    days=prices.index//DAY*DAY
    day_open=opens.reindex(days); day_open.index=prices.index
    gains=prices/day_open-1
    prev=(prices.reindex(opens.index[opens.index%DAY==0])/opens.loc[opens.index%DAY==0].shift(1)-1)
    leader=gains.rank(axis=1,ascending=False,method='min').eq(1)&gains.gt(0)
    ranked=(prev.rank(axis=1,ascending=False,method='min').le(3)&prev.gt(0)).reindex(days).fillna(False)
    med=prices.pct_change(8,fill_method=None).median(axis=1).values
    return {s:(med,leader[s].values,ranked[s].values) for s in COINS}


def lengths(rule):
    if rule=='scalp_double':return 15,30
    if rule in ('scalp_break','scalp_higher'):return 30,60
    return 60,120


def fill_path(start_i, data, side, entry, stop, tick, durations, rates_by_i, fee, slip, close_only, target_r=0):
    """An active stop has priority inside each bar. A newly raised stop starts next minute."""
    risk=side*(entry-stop); current=stop; funding=0.; results={}
    for j in range(start_i,min(len(data),start_i+max(durations))):
        op,hi,lo,cl,_=data[j]
        if not math.isfinite(cl):return results
        if j>start_i and j in rates_by_i:funding-=side*op*rates_by_i[j]
        adverse=lo if side==1 else hi
        best=cl if close_only else hi if side==1 else lo
        exit_price=None
        if side*(adverse-current)<=0:exit_price=min(op,current) if side==1 else max(op,current)
        elif target_r and side*(best-entry)>=target_r*risk:
            tgt=entry+side*target_r*risk;exit_price=max(tgt,op) if side==1 else min(tgt,op)
        held=j-start_i+1
        if exit_price is not None or held in durations:
            px=(cl if exit_price is None else exit_price)*(1-side*slip)
            net=(side*(px-entry)+funding-fee*(entry+px))/entry
            for duration in durations:
                if duration==held or (duration>held and exit_price is not None):results[duration]=(j+1,net)
            if exit_price is not None:break
        if (best-entry)*side>=risk:
            trail=(math.floor((best-side*risk)/tick+1e-10) if side==1 else math.ceil((best-side*risk)/tick-1e-10))*tick
            if (trail-current)*side>0:current=trail
    return results


def signals(job):
    sym, base, start, end, rank, fee, slip, close_only = job
    spec = json.loads(INSTRUMENTS.read_text())['data']
    instrument=next(i for i in spec if i['instId']==sym+'-USDT-SWAP')
    tick=float(instrument['tickSz']); series={}; bars={}; rows=[]
    for n in (1,15,60):
        d=series[n]=np.load(CACHE/f'{sym}-{n}.npy',mmap_mode='r')
        times=np.arange(base,end,n*MINUTE)
        bars[n]=np.column_stack((times,d))
    funding=np.load(SOURCE/f'{sym}-1.npy',mmap_mode='r')[:,5]
    rates_by_i={int(i):funding[i] for i in np.flatnonzero(funding)}
    median_market, leaders, top_three=rank
    def add(t,k,n,route,ref,atr,side,rv,segment):
        if not m.active(route,t):return
        j=(t-base)//MINUTE
        if j>=len(series[1]):return
        px=series[1][j,0]*(1+side*slip)
        ev=timing.evidence(route,segment,side,tick,atr)
        if ev is None:return
        mask=sum((1<<idx) for idx,f in enumerate(timing.FILTERS) if timing.passes(f,ev))
        if not mask:return
        from pc_sizing import leverage_for
        policy=timing.policies()[route]
        if not timing.passes(policy['filter'],ev):return
        leverage=leverage_for(ev,ref,float(instrument['lever']))
        if not leverage:return
        ds=(policy['minutes'],)
        exits={}
        if math.isfinite(px) and abs(px-ref)<=.5*atr and side*(px-ev['stop'])>0 and (abs(px-ev['stop'])/px+.002)*leverage/3<=.005:
            exits=fill_path(j,series[1],side,px,ev['stop'],tick,ds,rates_by_i,fee,slip,close_only)
        for duration in ds:
            out_i,net=exits.get(duration,(j,math.nan))
            rows.append([t,base+out_i*MINUTE,route,sym,side,rv,mask,duration,px,ev['stop'],net,leverage])
    # Rank signals use the same 09 KST day boundary as the exchange day open.
    all_routes=set(m.WINDOWS)
    qb=bars[15].tolist();hb=bars[60].tolist()
    qvalid=np.isfinite(series[15]).all(axis=1);hvalid=np.isfinite(series[60]).all(axis=1)
    qvalid=pd.Series(qvalid).rolling(65).sum().to_numpy()==65
    hvalid=pd.Series(hvalid).rolling(50).sum().to_numpy()==50
    for k in range(max(100,(start-base)//(15*MINUTE)-1),len(qb)-1):
        if not qvalid[k]:continue
        t=base+(k+1)*15*MINUTE
        routes={r for r in all_routes if m.active(r,t)}
        if not routes:continue
        if not leaders[k]:routes.discard('trend_long')
        if not top_three[k]:routes.discard('rank_short')
        hcount=(k+1)//4
        hourly=hb[max(0,hcount-100):hcount] if hvalid[hcount-1] else []
        if hourly and not all(math.isfinite(x[4]) for x in hourly):hourly=hourly[-50:]
        seg=qb[max(0,k-299):k+1]
        # Run moving averages on a contiguous run, including after an archive gap.
        for back in range(len(seg)-66,-1,-1):
            if not math.isfinite(seg[back][4]):seg=seg[back+1:];break
        for route,(rv,c,a,side) in m.proof(seg,hourly,instrument,median_market[k],routes).items():
            add(t,k,15,route,c,a,side,rv,seg)
    for route,spec in sc.SPECS.items():
        n=spec[3];b=bars[n];o,h,l,c,vol=series[n].T
        with np.errstate(divide='ignore',invalid='ignore'):
            tr=np.maximum.reduce([h-l,abs(h-np.roll(c,1)),abs(l-np.roll(c,1))]);a=pd.Series(tr).rolling(14).mean().to_numpy()
            valid=(b[:,0]+n*MINUTE>=start)&(b[:,0]+n*MINUTE<end)&(np.arange(len(c))>=98)
            valid&=(pd.Series(np.isfinite(c)).rolling(99).sum().to_numpy()==99)
            if route=='scalp_double': valid&=(c>o)&(c/np.roll(c,30)-1>=.01)&(np.minimum(o,c)-l>=.2*(h-l))
            elif route=='scalp_break':valid&=(c>np.roll(h,1))&(a/c>=.002)
            else:
                valid&=(c>o)&(a/c>=.002)
                # At least one candidate second wick satisfying matches() in the last four completed bars.
                sec=(np.minimum(o,c)-l>=.12*(h-l))&(c<o)&(l<=pd.Series(l).shift(1).rolling(4).min().to_numpy())
                valid&=np.logical_or.reduce([np.roll(sec,back)&(c>np.roll(h,back)) for back in range(1,5)])
            rv=vol/np.maximum(1,pd.Series(vol).shift(1).rolling(20).mean().to_numpy())
        policy=timing.policies()[route]; hours=((b[:,0]+n*MINUTE)//HOUR+9)%24
        valid&=(hours-policy['start'])%24 < (policy['end']-policy['start'])%24
        for k in np.flatnonzero(valid):
            seg=b[k-98:k+1].tolist()
            if sc.matches(route,seg):add(int(b[k,0])+n*MINUTE,k,n,route,c[k],a[k],1,rv[k],seg)
    return rows


def run(args):
    start,end=stamp(args.start),stamp(args.end)
    base=(start-4*DAY)//DAY*DAY
    CACHE.mkdir(exist_ok=True)
    with concurrent.futures.ProcessPoolExecutor(args.workers) as p:
        cov=dict(p.map(prepare,[(s,base,end) for s in COINS]));print('missing warmup + replay minutes',cov,flush=True)
        rank=market(base,end)
        jobs=[(s,base,start,end,rank[s],args.fee,args.slip,args.close_only) for s in COINS]
        chunks=[]
        for sym,rows in zip(COINS,p.map(signals,jobs)):
            chunks.extend(rows);print(sym,len(rows),flush=True)
    frame=pd.DataFrame(chunks,columns='entry exit rule symbol side rv mask hold price stop net leverage'.split())
    frame.sort_values(['entry','rule','rv','symbol'],ascending=[True,True,False,True]).to_pickle(args.out)
    print('opportunities by duration',len(frame),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--start',default='2026-09-22');ap.add_argument('--end',default='2026-11-21');ap.add_argument('--fee',type=float,default=.0005);ap.add_argument('--slip',type=float,default=.0005);ap.add_argument('--close-only',action='store_true');ap.add_argument('--workers',type=int,default=5);ap.add_argument('--out',default='market_cache/opportunities.pkl');run(ap.parse_args())
