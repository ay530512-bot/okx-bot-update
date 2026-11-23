"""Native five-minute high minus low relative to prior close, alongside frozen true range."""
from pathlib import Path
import json,sys
sys.path.insert(0,'study')
import scan
from statistics import median,quantiles
def pace(bars,stamp):
    f=300000
    if len(bars)<40 or int(bars[-1][0])+f!=stamp:return 'unknown'
    w=bars[-40:]
    if any(int(b[0])-int(a[0])!=f for a,b in zip(w,w[1:])):return 'unknown'
    if any(float(a[4])<=0 for a in w[:-1]):return 'unknown'
    tr=[(float(b[2])-float(b[3]))/float(a[4]) for a,b in zip(w,w[1:])]
    cash=[float(r[7]) for r in w[1:]]
    q=quantiles(tr[:36],n=4,method='inclusive')[2];v=median(cash[:36])
    return 'fast' if sum(x>q and y>v for x,y in zip(tr[36:],cash[36:]))>=2 else 'normal'
if __name__=='__main__':
    day=json.loads(Path('day/cache/coverage.json').read_bytes())['day_kst']
    scan.native_pace=pace
    scan.scan(day,Path('day/cache'),Path('frozen/OKX_PC_PACKAGE'),Path('day/range_scan.json'))
