"""Causal closed-bar routing with a separate enumeration of minutes needing real prints."""
import argparse,gzip,json,sys
from bisect import bisect_right
from collections import Counter
from pathlib import Path
from statistics import median,quantiles
from datetime import datetime
from cache_day import KST,SYMBOLS
M=60000; F=5*M
def native_pace(rows,stamp):
    if len(rows)<40 or int(rows[-1][0])+F!=stamp or any(int(b[0])-int(a[0])!=F for a,b in zip(rows[-40:-1],rows[-39:])):
        return 'unknown'
    ranges=[];turns=[]
    for a,b in zip(rows[-40:-1],rows[-39:]):
        prev=float(a[4]);ranges.append((max(float(b[2]),prev)-min(float(b[3]),prev))/prev);turns.append(float(b[7]))
    q=quantiles(ranges[:36],n=4,method='inclusive')[2];v=median(turns[:36])
    return 'fast' if sum(r>q and w>v for r,w in zip(ranges[-3:],turns[-3:]))>=2 else 'normal'
def pivot(bars,side,tick):
    floors=[min(side*r[2],side*r[3]) for r in bars];ceil=[max(side*r[2],side*r[3]) for r in bars]
    for i in range(len(bars)-2,max(13,len(bars)-13),-1):
        if floors[i]>=min(floors[i-1],floors[i+1]) or min(floors[i+1:])<floors[i]:continue
        atr=sum(max(bars[j][2],bars[j-1][4])-min(bars[j][3],bars[j-1][4]) for j in range(i-13,i+1))/14
        if max(ceil[i+1:])>=floors[i]+max(2*tick,.5*atr):
            return (int(bars[i][0]),side*floors[i],atr)
    return None
def scan(day,cache,pkg,out):
    sys.path.insert(0,str(pkg/'runtime'));sys.path.insert(0,str(pkg/'core'))
    from pc_symbol_flow import pace,assess_market
    from pc_fast_setup import fast_setup
    from pc_wick_alert import first_wick,oriented
    begin=int(datetime.fromisoformat(day).replace(tzinfo=KST).timestamp()*1000);end=begin+86400000
    result={}
    for sym in SYMBOLS:
        f=cache/(sym+'.json.gz')
        if not f.exists():continue
        d=json.load(gzip.open(f));counts=Counter();events=[];windows=[];firsts=[]
        if not all(d.get(k) for k in ('1m','5m','15m','1H','instrument')):
            result[sym]={'status':'missing_inputs'};continue
        frames={k:[(int(r[0]),*map(float,r[1:6])) for r in d[k]] for k in ['1m','5m','15m','1H']}
        tick=float(d['instrument'][0]['tickSz'])
        idx={k:[r[0] for r in v] for k,v in frames.items()}
        def closed(k,t,step,n):
            i=bisect_right(idx[k],t-step);return frames[k][max(0,i-n):i]
        for t in range(begin,end,F):
            five=closed('5m',t,F,260);i=bisect_right(idx['5m'],t-F)
            speed=native_pace(d['5m'][max(0,i-40):i],t)
            proxy=pace(five,t)['pace']
            counts[speed]+=1;counts['pace_disagrees']+=int(speed!=proxy)
            if t%(15*M)==0:
                q=closed('15m',t,15*M,65)
                if q and q[-1][0]+15*M==t:
                    for s in (1,-1):
                        a=first_wick([oriented(r,s) for r in q],tick)
                        if a:firsts.append(dict(timestamp=t,side=s,anchor=a.stamp,level=s*a.low))
            if speed!='fast':continue
            # Diagnostic from the pinned product, distinct from first intrabar reaction.
            setup=fast_setup(five,tick)
            if setup:
                counts['closed_setup']+=1
                decision=assess_market(closed('15m',t,15*M,220),five,closed('1H',t,60*M,64),t,setup['side'],closed('1m',t,M,10))
                events.append(dict(time=t,side=setup['side'],anchor=setup['anchor_ms'],second=setup['second'],raw_close=setup['price'],release_pace=proxy,release_side=decision['side'],reason=decision['reason']))
            for s in (1,-1):
                p=pivot(five,s,tick)
                if p is None:continue
                anchor,level,atr=p; floor=s*level; zone=floor+max(tick,.25*atr)
                # This OHLC exclusion is for fetching data only. It never authorizes a fill.
                mins=[r for r in frames['1m'][bisect_right(idx['1m'],t-1):bisect_right(idx['1m'],t+F-1)]]
                if len(mins)!=5:counts['unresolved_minute_coverage']+=1;continue
                need=[]
                for r in mins:
                    low=min(s*r[2],s*r[3])
                    if low<=zone+tick*1e-7:need.append(r[0])
                    if low<=floor+tick*1e-7:break
                if need:windows.append(dict(time=t,side=s,anchor=anchor,level=level,atr=atr,tick=tick,minutes=need))
        result[sym]=dict(counts=dict(counts),fast_close_controls=events,native_fast_tick_windows=windows,fifteen_min_first_wicks=firsts)
    out.write_text(json.dumps(result,separators=(',',':')))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('day');p.add_argument('cache',type=Path);p.add_argument('package',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();scan(a.day,a.cache,a.package,a.out)
