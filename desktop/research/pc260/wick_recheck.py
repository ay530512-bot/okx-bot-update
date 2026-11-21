"""Reweight the frozen tick-level research on first and second wicks using PC 2.6 budgets."""
import json,math,os,subprocess,sys,tempfile
from bisect import bisect_right
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np
here=Path(__file__).resolve().parent
package=Path(os.environ.get('PC_PACKAGE',here/'OKX_PC_PACKAGE')).resolve()
old=Path(os.environ.get('PC_WICK_RESEARCH',Path.cwd()/'wick_touch_review')).resolve()
sys.path[:0]=[str(package/'runtime'),str(package/'core')]
from pc_sizing import leverage_for
from pc_timing import indicators
sys.path.insert(0,str(old))
import tick_replay as tr
from collections import Counter

def symbol_events(symbol):
    section='recent';base,begin,end=tr.dates(section)
    rows=np.load(tr.location(section)/f'{symbol}-1.npy',mmap_mode='r')
    five=np.load(tr.location(section)/f'{symbol}-5.npy',mmap_mode='r')
    op5=np.ascontiguousarray(five[:,0])
    active,_=tr.eligible_setups(section,symbol,rows)
    t,p,*_=tr.locations(section,symbol);ts=np.load(t,mmap_mode='r');px=np.load(p,mmap_mode='r')
    funding=np.flatnonzero(rows[:,5]!=0);ft=base+funding*tr.MINUTE
    instrument=tr.meta()[symbol];spec=tr.configs();events=[]
    for setup in active:
        c=spec[setup.rule]
        for stress,slip in ((False,.0005),(True,.001)):
            status,v=tr.public_path(setup,rows,op5,ts,px,base,c['hold'],slip)
            if status!=2 or not tr.in_session(v[0],c) or not begin<=v[0]<end-c['hold']*tr.MINUTE or v[4]>=end:continue
            # Indicator inputs stop strictly before the five-minute candle of the trigger.
            idx=int((v[0]-base)//(5*tr.MINUTE));last=five[idx-32:idx,:5]
            if len(last)!=32 or not np.isfinite(last).all():continue
            evidence=indicators([[0,*x] for x in last],setup.side,setup.atr)
            if evidence is None:continue
            evidence['stop']=v[8]
            level=leverage_for(evidence,v[1],float(instrument['lever']))
            if not level:continue
            ids=funding[np.searchsorted(ft,v[3],side='right'):np.searchsorted(ft,v[4],side='right')]
            carry=-setup.side*rows[ids,0]*rows[ids,5]/v[5]
            events.append(dict(rule=setup.rule,symbol=symbol,side=setup.side,quality=setup.quality,stress=stress,
                signal=int(v[0]),ref=v[1],fill=int(v[3]),exit=int(v[4]),price=v[5],risk=v[6],leverage=level,
                net=float(v[7]+carry.sum()),stop=v[8],tick=setup.tick,funding_t=(base+ids*tr.MINUTE).tolist(),funding=carry.tolist()))
    return events

def account(rows,mkt,stress):
    cash=peak=150.;dd=0.;positions={};day_count=Counter();ledger=[];max_open=0
    fee=.0005;slip=.001 if stress else .0005
    def settle(t):
        nonlocal cash,peak,dd
        for key,p in sorted(list(positions.items()),key=lambda item:item[1]['exit']):
            if p['exit']>t:break
            pnl=p['notional']*p['net'];cash+=pnl;peak=max(peak,cash);dd=max(dd,(1-cash/peak)*100)
            ledger.append(pnl);del positions[key]
    for r in rows:
        t=r['signal'];settle(t);key=r['rule'];day=(t+9*3600000)//86400000
        if len(positions)>=3 or key in positions or any(p['symbol']==r['symbol'] for p in positions.values()) or day_count[day,key]>=4:continue
        equity=cash;used=risk=0.
        for p in positions.values():
            mark,stop=mkt.mark_and_stop(p,t);nom=p['notional']
            carry=sum(p['funding'][:bisect_right(p['funding_t'],t)])
            equity+=nom*(p['side']*(mark/p['price']-1)-fee+carry)
            used+=nom/p['leverage']
            risk+=nom/p['price']*(max(0,p['side']*(mark-stop))+2*(fee+slip)*mark)
        seed=max(0,equity-3);target=seed/3
        expected=r['ref']*(1+r['side']*slip);dist=r['side']*(expected-r['stop'])/expected
        if dist<=0:continue
        instrument=mkt.instruments[r['symbol']]
        ct,lot,mn,mx=(float(instrument[k]) for k in ('ctVal','lotSz','minSz','maxMktSz'))
        # No future fill price in the entry admission or order quantity.
        lev=r['leverage'];qty=math.floor(target/(expected*ct*(1/lev+fee)*lot))*lot
        nom=qty*ct*expected
        if not mn<=qty<=mx or nom/lev<.97*target or nom*(1/lev+fee)>seed-used or nom*(dist+2*(fee+slip))>min(.005*seed,.02*seed-risk):continue
        positions[key]=dict(r,notional=qty*ct*r['price']);day_count[day,key]+=1;max_open=max(max_open,len(positions))
    settle(2**62)
    return dict(final=round(cash,4),net_pct=round((cash/150-1)*100,3),trades=len(ledger),
                wins=int(sum(p>0 for p in ledger)),max_open=max_open,closed_drawdown_pct=round(dd,3))

def main():
    with tempfile.TemporaryDirectory() as temp:
        src=tr.SOURCE.read_text();old_expr='support-std::max(2*tick,.25*atr)'
        assert src.count(old_expr)==1
        cpp=Path(temp)/'wick.cpp';cpp.write_text(src.replace(old_expr,'support-std::max(2*tick,(reversal?.15:.25)*atr)'))
        tr.LIB=Path(temp)/'wick.so'
        subprocess.run(['g++','-std=c++17','-O3','-shared','-fPIC',str(cpp),'-o',str(tr.LIB)],check=True)
        results=[]
        with ProcessPoolExecutor(5) as pool:
            for sym,data in zip(tr.COINS,pool.map(symbol_events,tr.COINS)):
                results.extend(data)
        results.sort(key=lambda r:(r['signal'],r['rule'],-r['quality'],r['symbol']))
        out={};mkt=tr.Market('recent')
        for stress in (False,True):
            rows=[r for r in results if r['stress']==stress]
            out['double_slippage' if stress else 'base']=dict(combined=account(rows,mkt,stress),
                individual={k:account([r for r in rows if r['rule']==k],mkt,stress) for k in tr.configs()})
        print(json.dumps(out,indent=2))
if __name__=='__main__':main()
