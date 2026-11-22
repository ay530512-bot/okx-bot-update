"""Second-level OHLC-safe pruning for high-volume public retest reconstruction."""
from concurrent.futures import ThreadPoolExecutor
import gzip,json,math,sys
from pathlib import Path
from direct_ticks import M,F
from cache_day import api
def replay(sym,windows,cache,tape):
    d=json.load(gzip.open(cache/(sym+'.json.gz')));bars={int(r[0]):r for r in d['1m']};inst=sym+'-USDT-SWAP'
    def read(key,fetch):
        p=tape/(key+'.json.gz')
        if p.exists():return json.load(gzip.open(p))
        v=fetch();p.write_bytes(gzip.compress(json.dumps(v,separators=(',',':')).encode(),mtime=0));return v
    def native(m):
        def fetch():
            rows=api('market/history-candles',instId=inst,bar='1s',after=m+M,limit=60)
            rows=sorted([r for r in rows if r[-1]=='1' and m<=int(r[0])<m+M],key=lambda r:int(r[0]))
            if [int(r[0]) for r in rows]!=list(range(m,m+M,1000)):raise ValueError('1s candle gap')
            active=[r for r in rows if float(r[5])]
            check(active,bars[m],raw=True)
            return rows
        return read('seconds-'+sym+'-'+str(m),fetch)
    def check(rows,bar,raw):
        if raw:
            volume=sum(float(x[5]) for x in rows)
            ohlc=[float(rows[0][1]),max(float(x[2]) for x in rows),min(float(x[3]) for x in rows),float(rows[-1][4])] if rows else []
        else:
            prices=[r[2] for r in rows];volume=sum(x[3] for x in rows)
            ohlc=[prices[0],max(prices),min(prices),prices[-1]] if rows else []
        if not math.isclose(volume,float(bar[5]),rel_tol=1e-7) or any(not math.isclose(a,float(b),rel_tol=1e-9) for a,b in zip(ohlc,bar[1:5])):raise ValueError('reconciliation failed')
    def second(bar):
        ts=int(bar[0])
        def fetch():
            rr={};c={'type':2,'after':ts+1000}
            while True:
                a=api('market/history-trades',instId=inst,limit=100,**c)
                if not a:break
                for r in a:
                    if ts<=int(r['ts'])<ts+1000:
                        i=int(r['tradeId']);rr[i]=[int(r['ts']),i,float(r['px']),float(r['sz']),r['side']]
                if min(int(r['ts']) for r in a)<ts:break
                k=min(int(r['tradeId']) for r in a)
                if c['type']==1 and k>=c['after']:raise ValueError('nondecreasing ID cursor')
                c={'type':1,'after':k}
            rows=sorted(rr.values(),key=lambda r:(r[0],r[1]))
            if any(b[1]!=a[1]+1 for a,b in zip(rows,rows[1:])):raise ValueError('gap in second tape')
            check(rows,bar,False)
            return rows
        return read('secondtrades-'+sym+'-'+str(ts),fetch)
    seen=set();unknown=set();result=[]
    for w in windows:
        side=w['side'];tick=w['tick'];floor=side*w['level'];ceiling=floor+max(tick,w['atr']/4)
        def one():
            ext=None;hit=None
            for m in range(w['minutes'][0],w['time']+F+M,M):
                bar=bars[m];partial=tape/(sym+'-'+str(m)+'.json.gz')
                if m>=w['time']+F and not hit:break
                if partial.exists():groups=[(None,json.load(gzip.open(partial)))]
                else:
                    if not hit and ext is None and min(side*float(bar[2]),side*float(bar[3]))>ceiling+tick*1e-7:continue
                    groups=((r,None) for r in native(m) if float(r[5]))
                for one_sec,known in groups:
                    if one_sec and not hit and ext is None and min(side*float(one_sec[2]),side*float(one_sec[3]))>ceiling+tick*1e-7:continue
                    for ts,tid,p,_,_ in known if known is not None else second(one_sec):
                        if hit:
                            if ts>hit['ts']:return dict(status='reaction',**hit,fill_ref=[ts,tid,p])
                            continue
                        v=side*p
                        if v<=floor+tick*1e-7:return {'status':'first_extreme_breached'}
                        if v<=ceiling+tick*1e-7:ext=v if ext is None else min(ext,v)
                        if ext is not None and v>=ext+tick*(1-1e-7):hit=dict(ts=ts,trade_id=tid,price=p,second=side*ext)
            return dict(status='reaction_fill_unverified',**hit) if hit else {'status':'no_reaction'}
        key=(side,w['anchor'])
        if key in seen:r={'status':'duplicate_first_anchor'}
        elif key in unknown:r={'status':'earlier_unverified'}
        else:
            try:r=one()
            except Exception as err:r={'status':'missing','reason':str(err)};unknown.add(key)
            if r['status'].startswith('reaction'):seen.add(key)
        result.append(dict(window=w['time'],side=side,anchor=w['anchor'],first=w['level'],atr=w['atr'],**r))
    return result
if __name__=='__main__':
    sym,root=sys.argv[1],Path(sys.argv[2]);win=json.loads((root/'work/scan_day.json').read_bytes())[sym]['native_fast_tick_windows']
    a=replay(sym,win,root/'cache',root/'ticks');(root/('busy-'+sym+'.json')).write_text(json.dumps(a))
