"""Replay causal alternatives on a continuous account and record every KST day's closing equity."""
import json
import math
import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(Path(os.environ['PC_WICK30_SOURCE']).resolve()))
import accounts as prior
from data import BASE,CACHE,DAY,END,M,START,bars

POLICY=json.loads((HERE/'policy.json').read_text())
ROUND_TRIP=2*(POLICY['costs']['fee_per_side']+POLICY['costs']['slippage_per_side'])
RULES=(prior.REV_LONG,prior.REV_SHORT,prior.SCALP)

def features(symbol,signals):
    one=bars(symbol,1);five=bars(symbol,5);fifteen=bars(symbol,15)
    c=pd.Series(five[:,3])
    mid=c.rolling(20).mean().to_numpy()
    upper=mid+2*c.rolling(20).std(ddof=0).to_numpy()
    # Within-symbol turnover proxy; the constant contract multiplier cancels.
    turnover=pd.Series(five[:,3]*five[:,4]).rolling(12).sum()
    turnover_ratio=(turnover/turnover.shift(12)).to_numpy()
    last=pd.Series(fifteen[:,3]).shift().to_numpy()
    true_range=np.maximum.reduce((fifteen[:,1]-fifteen[:,2],abs(fifteen[:,1]-last),abs(fifteen[:,2]-last)))
    median_range=pd.Series(true_range).rolling(8).median().to_numpy()
    rows=[]
    for r in signals.itertuples():
        k=(r.signal-BASE)//M;j=k//5-1;b=k//15-1
        window=one[k-3:k,:5]
        width=window[:,1]-window[:,2]
        valid=bool(np.all((window[:,4]>0)&(width>0)))
        pressure=False
        if valid:
            location=(window[:,3]-window[:,2])/width
            if r.side<0:location=1-location
            pressure=np.average(location,weights=window[:,4])>=.60
        target=upper[j] if r.rule==prior.SCALP else mid[j]
        room=r.side*(target-r.quote)/r.quote>=3*ROUND_TRIP
        rows.append((r.id,True,room,room and pressure,
                     median_range[b]/r.quote>=3*ROUND_TRIP and turnover_ratio[j]>=1.3 and pressure))
    return rows

def closing_equity(book,paths,cut,stress):
    """Cut is exclusive. Keep unrealized gains/losses, accrued carry and both trading costs in net liquidation value."""
    nav=150.
    slip=.001 if stress else .0005
    for trade in book:
        if trade['fill']>=cut:continue
        if trade['exit']<cut:
            nav+=trade['usd']
            continue
        r=paths[trade['id']]
        close=prior.tape(r.symbol).one[(cut-BASE)//M-1,3]
        if not math.isfinite(close) or close<=0:raise ValueError(f'Missing boundary price {r.symbol} at {cut}')
        liquidation=close*(1-r.side*slip)
        carry=sum(v for t,v in zip(r.funding_t,r.funding) if t<cut)
        nav+=trade['notional']*(r.side*(liquidation/r.price-1)-.0005*(1+liquidation/r.price)+carry)
    return nav

def main():
    prior.engine.past_mark=prior.past_mark
    reversals=prior.reversals()
    cases=pd.concat([reversals[reversals.qualifies],pd.read_pickle(CACHE/'scalp_paths.pkl')],ignore_index=True)
    fixed=cases[~cases.stress]
    filters=list(POLICY['filters'])
    f=pd.DataFrame([v for sym,g in fixed.groupby('symbol') for v in features(sym,g)],columns=['id',*filters])
    assert f.id.is_unique
    cases=cases.merge(f,on='id',validate='many_to_one')
    hours=(cases.signal//M//60+9)%24
    cohorts={rule:cases[cases.rule==rule] for rule in RULES[:2]}
    reversal_cases=cases[cases.rule.isin(RULES[:2])]
    for h in range(0,24,4):
        scalp=cases[(cases.rule==prior.SCALP)&(hours>=h)&(hours<h+4)]
        cohorts[f'scalp_{h:02}']=scalp
        cohorts[f'bundle_{h:02}']=pd.concat([reversal_cases,scalp],ignore_index=True)
    ledger=[];summary=[]
    for name,frame in cohorts.items():
        for variant in filters:
            filtered=frame[frame[variant]]
            groups=prior.engine.ordered(filtered) if len(filtered) else {}
            for stress in (False,True):
                rows=groups.get(('wick','current',stress),[])
                stats,book=prior.engine.simulate(rows,'base','current',START,END,'wick',stress)
                paths={r.id:r for r in rows}
                nav=150.;daily=[];counts=[]
                for begin in range(START,END,DAY):
                    cut=begin+DAY
                    close=closing_equity(book,paths,cut,stress)
                    pct=(close/nav-1)*100
                    n=sum(begin<=r['fill']<cut for r in book)
                    date=pd.Timestamp(begin,unit='ms',tz='UTC').tz_convert('Asia/Seoul').date().isoformat()
                    # The original fixed input stops admitting new opportunities shortly before the final cutoff.
                    censored=(cut==END and name in ('scalp_20','bundle_20'))
                    ledger.append((name,variant,stress,date,n,nav,close,pct,not censored,pct>=10-1e-10 and not censored))
                    daily.append(pct);counts.append(not censored);nav=close
                assert abs(nav-stats['final'])<1e-7 and len(daily)==60
                summary.append((name,variant,stress,len(book),sum(counts),sum(p>=10-1e-10 and ok for p,ok in zip(daily,counts)),min(daily),nav,'development_only'))
    pd.DataFrame(ledger,columns=['cohort','filter','stress','date_kst','entries','opening_nav','closing_nav','net_pct','complete_inputs','day_goal']).to_csv(HERE/'daily.csv.gz',index=False)
    s=pd.DataFrame(summary,columns=['cohort','filter','stress','fills','complete_days','target_days','worst_day_pct','closing_nav','status'])
    s.to_csv(HERE/'research_log.csv',index=False)
    assert len(s)==14*4*2
    print('Validated',len(s),'historical evaluations and',len(ledger),'daily accounting records.')
if __name__=='__main__':main()
