"""Chronological shadow-gate replay. Uses trade-bar OHLC; deployed watcher also checks mark bars and live quotes."""
import argparse
import collections
import json
from pathlib import Path
import pandas as pd
from replay import DAY,HOUR,MINUTE,stamp,sc,timing
from select_rules import opportunities, account, instruments, summary
from pc_forward import qualifies


def replay(df, policy, start, end, *, out_start=None):
    ins=instruments();chunks=[];counts={}; passes={}
    for key,p in policy.items():
        cand=opportunities(df,key,(p['start'],p['end']),p['filter'],p['minutes'],start,end)
        daily=collections.Counter();hist=[];pending=None;live=[];n=0
        for row in cand.itertuples():
            t=row.entry
            if pending is not None:
                known,r=pending
                if t<known:continue
                hist=(hist+[r])[-60:];pending=None
            day=(t+(9*HOUR if key in sc.SPECS else 0))//DAY
            cap=sc.SPECS[key][-1] if key in sc.SPECS else 1
            if daily[day]>=cap or not pd.notna(row.net):continue
            n+=1;daily[day]+=1
            if qualifies(hist,t):live.append(row.Index)
            risk=abs(row.price-row.stop)/row.price+.002
            pending=(row.entry+(row.hold+2)*MINUTE,dict(entry_ms=row.entry,exit_ms=row.exit,net_r=row.net/risk))
        counts[key]=n;passes[key]=len(live);chunks.append(cand.loc[live])
    res=account(pd.concat(chunks),out_start or start,end,ins)
    return dict(summary=summary(res),shadow=counts,admitted=passes,trades=res['trades'])


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data',required=True);ap.add_argument('--start',required=True);ap.add_argument('--end',required=True);ap.add_argument('--report-from');ap.add_argument('--out',required=True);a=ap.parse_args()
    x=replay(pd.read_pickle(a.data),timing.policies(),stamp(a.start),stamp(a.end),out_start=stamp(a.report_from) if a.report_from else None)
    Path(a.out).write_text(json.dumps(x,indent=2));print(x['summary'],sum(x['shadow'].values()),x['admitted'])
