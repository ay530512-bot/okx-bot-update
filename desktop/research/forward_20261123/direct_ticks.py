"""Replay first fast 5m touch on public market prints; reconcile each consulted minute."""
import argparse,gzip,json,math,os,tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from cache_day import api
M=60000;F=5*M
def minute(sym,t,candles,cache):
    key=cache/(sym+'-'+str(t)+'.json.gz')
    if key.exists():return json.loads(gzip.decompress(key.read_bytes()))
    r=candles[t];rows={};cursor={'type':2,'after':t+M}
    if float(r[5])>0:
        while True:
            page=api('market/history-trades',instId=sym+'-USDT-SWAP',limit=100,**cursor)
            if not page:break
            for x in page:
                ts=int(x['ts'])
                if t<=ts<t+M:rows[int(x['tradeId'])]=[ts,int(x['tradeId']),float(x['px']),float(x['sz']),x['side']]
            if min(int(x['ts']) for x in page)<t:break
            n=min(int(x['tradeId']) for x in page)
            if cursor['type']==1 and n>=cursor['after']:raise ValueError('stalled trade cursor')
            cursor={'type':1,'after':n}
    ticks=sorted(rows.values(),key=lambda x:(x[0],x[1]))
    if ticks:
        points=[x[2] for x in ticks]
        if any(y[1]!=x[1]+1 for x,y in zip(ticks,ticks[1:])):raise ValueError('trade ID gap or nonmonotone times')
        if any(not math.isclose(a,float(b),rel_tol=1e-8,abs_tol=1e-15) for a,b in zip([points[0],max(points),min(points),points[-1]],r[1:5])):raise ValueError('OHLC mismatch')
    if not math.isclose(sum(x[3] for x in ticks),float(r[5]),rel_tol=1e-7,abs_tol=1e-9):raise ValueError('volume mismatch')
    with tempfile.NamedTemporaryFile(dir=cache,delete=False) as dst:
        dst.write(gzip.compress(json.dumps(ticks,separators=(',',':')).encode(),mtime=0))
    os.replace(dst.name,key)
    return ticks
def observe(sym,w,candles,cache):
    s=w['side'];tick=w['tick'];floor=s*w['level'];zone=floor+max(tick,.25*w['atr']);extreme=None;signal=None
    # Earliest possible touch through end of this speed interval. At most one signal per first anchor.
    for t in range(w['minutes'][0],w['time']+F,M):
        r=candles[t];bar_low=min(float(r[2])*s,float(r[3])*s)
        if extreme is None and bar_low>zone+tick*1e-7:continue
        for ts,tid,p,v,side in minute(sym,t,candles,cache):
            if signal:
                if ts>signal['ts']:
                    return dict(status='reaction',**signal,fill_ref=[ts,tid,p])
                continue
            v=s*p
            if v<=floor+tick*1e-7:return dict(status='first_extreme_breached')
            if v<=zone+tick*1e-7:extreme=v if extreme is None else min(extreme,v)
            if extreme is not None and v>=extreme+tick*(1-1e-7):
                signal=dict(ts=ts,trade_id=tid,price=p,second=s*extreme)
    if signal:
        for ts,tid,p,_,_ in minute(sym,w['time']+F,candles,cache):
            if ts>signal['ts']:return dict(status='reaction',**signal,fill_ref=[ts,tid,p])
        return dict(status='reaction_fill_unverified',**signal)
    return dict(status='no_reaction')
def main(scan,cache,tape,out):
    tape.mkdir(exist_ok=True);out.mkdir(exist_ok=True)
    data=json.loads(scan.read_bytes())
    def process(sym):
        target=out/(sym+'.json')
        if target.exists():return
        d=json.loads(gzip.decompress((cache/(sym+'.json.gz')).read_bytes()));bars={int(r[0]):r for r in d['1m']}
        seen=set();uncertain=set();rows=[]
        for w in data[sym].get('native_fast_tick_windows',[]):
            key=(w['side'],w['anchor'])
            if key in seen:r={'status':'duplicate_first_anchor'}
            elif key in uncertain:r={'status':'earlier_unverified'}
            else:
                try:r=observe(sym,w,bars,tape)
                except Exception as exc:r={'status':'missing','reason':str(exc)}
                if r['status'].startswith('reaction'):seen.add(key)
                if r['status']=='missing':uncertain.add(key)
            rows.append(dict(window=w['time'],side=w['side'],anchor=w['anchor'],first=w['level'],atr=w['atr'],**r))
        if any(r['status']=='missing' for r in rows):
            from busy_touch import replay
            alternate=replay(sym,data[sym]['native_fast_tick_windows'],cache,tape)
            unresolved=lambda rr:sum(r['status'] in ('missing','earlier_unverified','reaction_fill_unverified') for r in rr)
            pairs=zip(rows,alternate)
            agree=all(a==b for a,b in pairs if a['status'] not in ('missing','earlier_unverified','reaction_fill_unverified') and b['status'] not in ('missing','earlier_unverified','reaction_fill_unverified'))
            if agree and unresolved(alternate)<unresolved(rows):rows=alternate
        target.write_text(json.dumps(rows,separators=(',',':')))
    with ThreadPoolExecutor(18) as pool:list(pool.map(process,data))
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['scan','cache','tape','out']:p.add_argument(name,type=Path)
    main(**vars(p.parse_args()))
