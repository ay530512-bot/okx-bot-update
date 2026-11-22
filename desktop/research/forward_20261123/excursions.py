"""Clip boundary minutes by exact exchange trade IDs; retain uncertainty when prints are missing."""
import gzip,json,sys
from pathlib import Path
from direct_ticks import M
def enrich(root):
    f=root/'result/event_paths.json';events=json.loads(f.read_bytes());cache={}
    for e in events:
        if 'fill_ref' not in e:continue
        sym=e['sym'];ts,i,entry=e['fill_ref']
        if sym not in cache:
            d=json.load(gzip.open(root/'cache'/(sym+'.json.gz')));cache[sym]={int(r[0]):r for r in d['1m']}
        bars=cache[sym]
        for arm in 'ABCD':
            p=e.get(arm,{})
            if 'net' not in p:continue
            et=p['exit_time'];end_id=p['exit_trade_id'];es=e['trend_side'] if arm=='C' else -e['side'] if arm=='D' else e['side']
            pp=[entry,p['exit_raw']];unknown=False
            for t in range(ts//M*M,et//M*M+1,M):
                if t>ts and t+M<=et:
                    if t not in bars:unknown=True;continue
                    r=bars[t]
                    if float(r[5]):pp.extend([float(r[2]),float(r[3])])
                else:
                    z=root/'ticks'/(sym+'-'+str(t)+'.json.gz')
                    if not z.exists():unknown=True;continue
                    pp.extend(r[2] for r in json.load(gzip.open(z)) if (ts,i)<=(r[0],r[1])<=(et,end_id))
            v=[es*(x/entry-1) for x in pp]
            p['excursion_observed']=dict(mfe=max(v),mae=min(v),exact=not unknown,basis='public last trade against raw entry; clipped by trade id; partial extrema are lower bounds on magnitude')
    f.write_text(json.dumps(events,separators=(',',':'),allow_nan=False))
if __name__=='__main__':enrich(Path(sys.argv[1]))
