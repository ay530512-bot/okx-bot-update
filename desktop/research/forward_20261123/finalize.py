"""Make a dated, explicitly retrospective inspection ledger from raw cache and paired event paths."""
import argparse,gzip,json,sys
from collections import Counter
from datetime import datetime,timezone,date,timedelta
from pathlib import Path
from statistics import median
from bisect import bisect_right
from accounts import simulate
from cache_day import SYMBOLS
from scan import native_pace
def summarize(root,package,previous=None):
    sys.path.insert(0,str(package/'runtime'))
    from pc_symbol_flow import assess_market
    cache=root/'cache';scan=json.loads((root/'work/scan_day.json').read_bytes())
    cov=json.loads((cache/'coverage.json').read_bytes());summary={};all_events=[];info={};all_w=[];all_direct=[]
    complete={x:True for x in ['native_fast_direct','deployed_wick15']}
    for sym in SYMBOLS:
        x=scan[sym];z=json.load(gzip.open(cache/(sym+'.json.gz')))
        frames={k:[(int(r[0]),*map(float,r[1:6])) for r in z[k]] for k in ['1m','5m','15m','1H']}
        times={k:[r[0] for r in v] for k,v in frames.items()}
        def hist(k,t,step):
            i=bisect_right(times[k],t-step);return frames[k][max(0,i-260):i]
        info[sym]=dict(ct=float(z['instrument'][0]['ctVal']),lot=float(z['instrument'][0]['lotSz']),minq=float(z['instrument'][0]['minSz']),marks={int(r[0]):list(map(float,r[1:5])) for r in z['mark1m']},funding=[(int(r['fundingTime']),float(r['realizedRate'])) for r in z['funding']])
        def first_after(t,symbol=sym):
            rawcache=root/'ticks'
            end=cov['end_exclusive_ms']
            for m in range(t//60000*60000,end,60000):
                key=rawcache/(symbol+'-'+str(m)+'.json.gz')
                if not key.exists():return None
                for r in json.load(gzip.open(key)):
                    if r[0]>t:return r
            return None
        info[sym]['first_after']=first_after
        def load(folder):
            p=root/folder/(sym+'.json');return json.loads(p.read_bytes()) if p.exists() else None
        d=load('direct');w=load('wick15');e=load('paired_all')
        if d is None or len(d)!=len(x['native_fast_tick_windows']) or any(r['status'] in ('missing','earlier_unverified','reaction_fill_unverified') for r in d):complete['native_fast_direct']=False
        if w is None or w['unverified_anchor_windows']:complete['deployed_wick15']=False
        direct=d or [];wick=(w or {}).get('events',[])
        all_w.extend(dict(sym=sym,**r) for r in wick)
        all_direct.extend(dict(sym=sym,**r) for r in direct)
        expected={'native_fast_direct':sum(r['status']=='reaction' for r in direct),'deployed_wick15':len(wick)}
        for k,v in expected.items():
            if e is None or sum(r.get('source')==k for r in e)!=v:complete[k]=False
        for r in e or []:
            if 'fill_ref' not in r:continue
            t=r['signal'];s=r['side'];i=bisect_right(times['5m'],t-300000)
            r['native_pace']=native_pace(z['5m'][max(0,i-40):i],t//300000*300000)
            dec=assess_market(hist('15m',t,900000),hist('5m',t,300000),hist('1H',t,3600000),t,s,hist('1m',t,60000))
            r.update(release_pace=dec['pace'],release_selected_side=dec['side'],release_reason=dec['reason'],prior_anchor_state='unknown' if r['anchor']<cov['start_ms'] else 'known')
            if r['prior_anchor_state']=='unknown':complete[r['source']]=False
            all_events.append(r)
        summary[sym]=dict(pace=x['counts'],fast_minute_windows=len(x['native_fast_tick_windows']),fast_status=dict(Counter(r['status'] for r in direct)),native_15m_first_wicks=len(x['fifteen_min_first_wicks']),signals_15m=len(wick) if w is not None else None,unverified_anchor_windows=(w or {}).get('unverified_anchor_windows'),paired_cases=len(e) if e is not None else None)
    def stats(events,k):
        paths=[(r,r[k]) for r in events if k in r and 'net' in r[k]]
        groups={}
        for name,take in [('win',lambda x:x>0),('loss',lambda x:x<0),('flat',lambda x:x==0)]:
            rr=[(r,p) for r,p in paths if take(p['net'])]
            def dist(key):
                a=sorted(r['pre'][key] for r,_ in rr if r.get('pre') and key in r['pre'])
                return dict(n=len(a),minimum=min(a),median=median(a),maximum=max(a)) if a else {'n':0}
            groups[name]=dict(n=len(rr),sum_net=sum(p['net'] for _,p in rr),sum_gross=sum(p['gross'] for _,p in rr),mean_net=sum(p['net'] for _,p in rr)/len(rr) if rr else None,features={k:dist(k) for k in ['rv','slope','stretch','location','atr_pct','rsi_direction']})
        return dict(checked=len(paths),groups=groups,unverified=sum('unverified' in r.get(k,{}) for r in events),net_same_quantity=sum(p['net'] for _,p in paths),stress=sum(p['stressed_net_same_quantity'] for _,p in paths),net_without_best=sum(p['net'] for _,p in paths)-max([0]+[p['net'] for _,p in paths]))
    daily={}
    day=cov['day_kst']
    if previous and previous.get('date_kst')!=str(date.fromisoformat(day)-timedelta(days=1)):
        raise ValueError('opening account must use immediately preceding KST date')
    def opening(cohort,book,arm):
        if previous:
            if previous.get('cohort_id')!='native-matched-first-20261124':
                raise ValueError('previous book is from a different registration')
            return previous['books'][cohort][book][arm].get('closing_nav')
        return 150 if day in ('2026-11-22','2026-11-24') else None
    for source in [*complete,None]:
        cohort=[r for r in all_events if not source or r.get('source')==source]
        all_known=complete[source] if source else all(complete.values())
        daily[source or 'shared']=dict(complete_events=all_known,paired_stats={arm:stats(cohort,arm) for arm in 'ABCD'},both_sides_lost=sum(r['B']['net']<0 and r['D']['net']<0 for r in cohort if 'net' in r.get('B',{}) and 'net' in r.get('D',{})),accounts={arm:simulate(cohort,arm,source,opening(source or 'shared','accounts',arm),info,all_known) for arm in 'ABCDE'},locked_accounts={arm:simulate(cohort,arm,source,opening(source or 'shared','locked_accounts',arm),info,all_known,lock=True) for arm in 'ABCD'})
    save=root/'result';save.mkdir(exist_ok=True)
    def put(name,value):
        (save/name).write_text(json.dumps(value,separators=(',',':'),allow_nan=False))
    put('sources.json',summary);put('opportunities.json',dict(raw_15m=all_w,raw_fast=all_direct));put('event_paths.json',all_events);put('development_accounts.json',daily)
    put('daily_state.json',dict(date_kst=day,cohort_id='native-matched-first-20261124' if day>='2026-11-24' else 'retrospective',books=daily))
    return summary,all_events,daily
if __name__=='__main__':summarize(*map(Path,sys.argv[1:]))
