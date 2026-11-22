"""Closed-candle observation for the separately frozen scalp-long control. Not a filled account."""
import gzip,json,sys
from pathlib import Path
from statistics import mean,pstdev
from datetime import datetime
from cache_day import KST,SYMBOLS
def control(root):
    start=json.loads((root/'cache/coverage.json').read_bytes())['start_ms'];end=start+86400000
    events=[]
    for sym in SYMBOLS:
        r=json.load(gzip.open(root/'cache'/(sym+'.json.gz')))
        rows=[(int(x[0]),*map(float,x[1:6])) for x in r['5m']]
        for i,(t,o,h,l,c,v) in enumerate(rows):
            signal=t+300000
            if i<20 or not start<=signal<end or c<=o or h<=l or o-l<(h-l)/2 or v<=0:continue
            av=mean(b[5] for b in rows[i-20:i])
            if av<=0 or v<2*av:continue
            datehour=datetime.fromtimestamp(signal/1000,KST).hour
            reason='window_extends_beyond_input';close=None
            for j in range(i+1,min(i+21,len(rows))):
                t2,o2,h2,l2,c2,_=rows[j]
                if t2+300000>=end:break
                cs=[z[4] for z in rows[j-19:j+1]]
                if c2<o2 and h2>l2 and h2-o2>=(h2-l2)/2 and h2>=mean(cs)+2*pstdev(cs):
                    reason='upper_band_wick_close';close=t2+300000;break
                if j==i+20:reason='twentieth_close';close=t2+300000
            events.append(dict(sym=sym,signal=signal,window_start_hour=datehour//4*4,relative_volume=v/av,low=l,close_price=c,nominal_candle_exit=close,nominal_reason=reason))
    (root/'result/scalp_control.json').write_text(json.dumps(dict(status='observations only; original stop/trailing may precede nominal close; no independent closed KST day yet',n=len(events),events=events),separators=(',',':')))
if __name__=='__main__':control(Path(sys.argv[1]))
