"""Fixed chronological selection. Freeze per-rule choices before opening the final interval."""
import argparse
import collections
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from replay import ROOT, DAY, HOUR, MINUTE, COINS, FIELDS, stamp, sc, m, timing, lengths

TRAIN=stamp('2026-07-06'); MID=stamp('2026-08-03'); VALID=stamp('2026-09-01'); FINAL=stamp('2026-09-22'); END=stamp('2026-11-21')
WINDOWS=[(k,k+4) for k in range(0,24,4)]
OLD_HOURS=dict(m.WINDOWS,**{k:(x[1],x[2]) for k,x in sc.SPECS.items()})

def read_rules(path):return json.loads(Path(path).read_text())['rules']


def opportunities(df,route,window,mode,duration,start,end):
    x=df[(df.rule==route)&(df.hold==duration)&(df.entry>=start)&(df.entry<end)&((df['mask']&(1<<timing.FILTERS.index(mode)))!=0)]
    hours=(x.entry//HOUR+9)%24
    a,b=window; x=x[(hours-a)%24<(b-a)%24]
    # One deterministic symbol per route and close. The fill test is applied after ranking.
    return x.drop_duplicates('entry',keep='first')


def instruments():
    rows=json.loads((ROOT/'ins.json').read_text())['data']
    keys=('ctVal','lotSz','minSz','maxMktSz')
    return {i['instId'].split('-')[0]:tuple(float(i[k]) for k in keys) for i in rows if i['instId'].endswith('-USDT-SWAP')}


def account(frame,start,end,ins, fee=.0005, slip=.0005):
    balance=peak=150.;dd=0.;days=collections.Counter();positions={};ledger=[]
    if frame.empty:return dict(n=0,net=0.,dd=0.,wins=0,final=150.,trades=[])
    x=frame.copy();x['scalp']=x.rule.isin(sc.SPECS);x['common']=~x.rule.isin(m.RESERVED)
    x=x.sort_values(['entry','scalp','common','rv','symbol'],ascending=[True,True,True,False,True])
    def settle(t):
        nonlocal balance,peak,dd
        for k,p in sorted(list(positions.items()),key=lambda kv:kv[1][0]):
            ts,sym,margin,risk,pnl,opened= p
            if ts>t:continue
            balance+=pnl;peak=max(peak,balance);dd=max(dd,1-balance/peak);del positions[k]
            ledger.append([opened,ts,k,sym,pnl])
    for r in x.itertuples(index=False):
        t=r.entry;settle(t)
        if not math.isfinite(r.net) or t<start or t>=end or r.exit>end:continue
        cap=sc.SPECS[r.rule][-1] if r.rule in sc.SPECS else 1
        day=(t+(9*HOUR if r.rule in sc.SPECS else 0))//DAY
        if r.rule in positions or days[day,r.rule]>=cap or any(p[1]==r.symbol for p in positions.values()):continue
        if r.rule in m.RESERVED and m.RESERVED.intersection(positions):continue
        if len(positions)>=10 or (r.rule not in m.RESERVED and sum(k not in m.RESERVED for k in positions)>=9):continue
        lev=5 if r.rule in m.RESERVED else 10
        ct,lot,mn,mx=ins[r.symbol]; equity=max(0.,balance-3)
        distance=abs(r.price-r.stop)/r.price+2*(fee+slip)
        remaining=max(0.,equity*.02-sum(p[3] for p in positions.values()))
        target_notional=min(equity*.1*lev, min(equity*.005,remaining)/distance)
        q=math.floor(target_notional/(ct*r.price*lot)+1e-12)*lot
        if q<mn or q>mx:continue
        nominal=q*ct*r.price;margin=nominal/lev
        if margin+nominal*fee>equity-sum(p[2] for p in positions.values()):continue
        positions[r.rule]=(r.exit,r.symbol,margin,nominal*distance,r.net*nominal,t);days[day,r.rule]+=1
    settle(end)
    return dict(n=len(ledger),net=(balance/150-1)*100,dd=dd*100,wins=sum(r[-1]>0 for r in ledger),final=balance,trades=ledger)


def summary(result):return {k:round(v,5) if isinstance(v,float) else v for k,v in result.items() if k!='trades'}


def select(df,ins):
    rules={};audit={};trial_count=0
    for route,original in OLD_HOURS.items():
        part=df[(df.rule==route)&(df.entry<FINAL)]; best=None; num=0
        for win in dict.fromkeys([original,*WINDOWS]):
            for mode in timing.FILTERS:
                for dur in lengths(route):
                    trial_count+=1;num+=1
                    xs=opportunities(part,route,win,mode,dur,TRAIN,VALID)
                    a=account(xs,TRAIN,MID,ins);b=account(xs,MID,VALID,ins)
                    if min(a['n'],b['n'])<7 or min(a['net'],b['net'])<=0:continue
                    # Do not let one large winner carry both chronological training blocks.
                    winner=max(tr[-1] for tr in a['trades']+b['trades'])
                    if a['final']+b['final']-300<=winner:continue
                    score=min(a['net'],b['net'])+.2*(a['net']+b['net'])-.15*max(a['dd'],b['dd'])
                    if best is None or score>best[0]:best=(score,win,mode,dur,summary(a),summary(b))
        enabled=False
        if best is not None:
            _,win,mode,dur,a,b=best
            v=account(opportunities(part,route,win,mode,dur,VALID,FINAL),VALID,FINAL,ins)
            enabled=v['n']>=6 and v['net']>0
            audit[route]={'train_1':a,'train_2':b,'validation':summary(v),'configs':num}
        else:
            win=original;mode='reclaim';dur=lengths(route)[0];audit[route]={'configs':num,'reason':'development'}
        rules[route]={'enabled':enabled,'start':win[0], 'end':win[1], 'filter':mode,'minutes':dur}
    return {'rules':rules,'development_count':trial_count,'qualification':audit}


def trade_frame(df,pol,start,end):
    chunks=[opportunities(df,k,(p['start'],p['end']),p['filter'],p['minutes'],start,end) for k,p in pol.items() if p['enabled']]
    return pd.concat(chunks) if chunks else df.iloc[:0]


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['freeze','test']);ap.add_argument('--data',default='timing_cache/opportunities.pkl');ap.add_argument('--policy',default='timing_cache/frozen.json');ap.add_argument('--start',default='2026-09-22');ap.add_argument('--end',default='2026-11-21');ap.add_argument('--out',default='timing_cache/outcome.json');args=ap.parse_args()
    df=pd.read_pickle(args.data);ins=instruments()
    if args.action=='freeze':
        obj=select(df,ins);Path(args.policy).write_text(json.dumps(obj,indent=2));print(obj)
    else:
        start,end=stamp(args.start),stamp(args.end); rules=read_rules(args.policy)
        rows=trade_frame(df,rules,start,end);result=account(rows,start,end,ins);Path(args.out).write_text(json.dumps(result,indent=2));print(summary(result))
