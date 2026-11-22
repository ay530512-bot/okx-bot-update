"""Simulate only the active release's two-wick signal using reconciled trade order."""
import json,gzip,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from direct_ticks import minute,M
from scan import native_pace
from bisect import bisect_right
def run(sym,cache,tape,package):
    sys.path[:0]=[str(package/'runtime'),str(package/'core')]
    from pc_wick_alert import Detector,oriented,retest_window
    data=json.load(gzip.open(cache/(sym+'.json.gz')))
    bars=[(int(r[0]),*map(float,r[1:6])) for r in data['15m']]
    ones={int(r[0]):r for r in data['1m']};fives=data['5m'];timestamps=[int(r[0]) for r in fives]
    tick=float(data['instrument'][0]['tickSz'])
    end=max(ones)+M;start=end-24*60*M
    pre=[b for b in bars if b[0]<start];ds={s:Detector(tick,retest_window(s)) for s in (1,-1)}
    for side,det in ds.items():det.seed([oriented(b,side) for b in pre])
    result=[];missing=[]
    for b in bars:
        t=b[0]
        if t<start:continue
        for side,d in ds.items():
            row=oriented(b,side);a=d.anchor
            if a is not None and row[3]<=a.zone+d.eps and (a.away or row[2]>=a.depart-d.eps):
                try:
                    for m in range(t,t+15*M,M):
                        # Once a hit or invalidation consumed this anchor no other can form before close.
                        if d.anchor is None:break
                        for ts,tid,px,_,_ in minute(sym,m,ones,tape):
                            h=d.trade(ts,tid,side*px,covered_from_open=True)
                            if h is not None:
                                i=bisect_right(timestamps,ts//(5*M)*(5*M)-5*M)
                                h.update(side=side,first=h['first']*side,second=h['second']*side,price=px,speed=native_pace(fives[max(0,i-40):i],ts//(5*M)*(5*M)),status='public_reaction')
                                result.append(h);break
                except Exception as err:
                    missing.append(dict(window=t,side=side,anchor=a.stamp,error=str(err)))
                    d.anchor=None
            d.closed(row)
    return dict(events=result,unverified_anchor_windows=missing,signal_only=True)
if __name__=='__main__':
    cache,tape,package,out=map(Path,sys.argv[1:]);out.mkdir(exist_ok=True)
    def one(p):
        dest=out/(p.stem.split('.')[0]+'.json')
        if not dest.exists():
            res=run(p.name.split('.')[0],cache,tape,package)
            dest.write_text(json.dumps(res,separators=(',',':')))
    with ThreadPoolExecutor(12) as pool:list(pool.map(one,sorted(cache.glob('*.json.gz'))))
