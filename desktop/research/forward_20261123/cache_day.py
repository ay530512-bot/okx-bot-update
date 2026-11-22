"""Cache original confirmed native candles and settlement inputs for a closed KST date."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import gzip,hashlib,json,threading,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

SYMBOLS="AAVE ACT ADA APT ARB ATOM AVAX BCH BONK BREV CRV DOGE DOT EDGE ETC FIL INIT INJ LDO LINK LTC NEAR OP PENDLE PEPE SUI TRX UNI WIF XRP ZEC".split()
KST=timezone(timedelta(hours=9))
LOCK=threading.Lock()
last=0.
def get(url):
    global last
    for attempt in range(3):
        try:
            with LOCK:
                time.sleep(max(0.,last+.12-time.monotonic()));last=time.monotonic()
            with urlopen(Request(url,headers={'User-Agent':'market-data-research'}),timeout=18) as resp:
                return resp.read()
        except HTTPError as exc:
            if exc.code==429:
                try:delay=max(10*(attempt+1),float(exc.headers.get('Retry-After',0)))
                except (ValueError,TypeError):delay=15*(attempt+1)
                with LOCK:last=max(last,time.monotonic()+delay)
            if attempt==2 or exc.code not in (429,500,502,503,504):raise
            time.sleep(attempt+1)
        except OSError:
            if attempt==2:raise
            time.sleep(attempt+1)
def api(path,**params):
    payload=json.loads(get('https://www.okx.com/api/v5/'+path+'?'+urlencode(params)))
    if payload['code']!='0':raise ValueError(payload['code'])
    return payload['data']
def candles(sym,frame,step,warm,start,end,mark=False):
    path='market/history-'+('mark-price-' if mark else '')+'candles'
    begin=start-step*warm; cursor=end; rows={}
    while cursor>begin:
        page=api(path,instId=sym+'-USDT-SWAP',bar=frame,after=cursor,limit=100 if mark else 300)
        if not page:break
        for r in page:
            t=int(r[0])
            if begin<=t<end and r[-1]=='1':rows[t]=r
        oldest=min(int(r[0]) for r in page)
        if oldest>=cursor:raise ValueError('cursor did not decrease')
        cursor=oldest
    missing=sorted(set(range(begin,end,step))-rows.keys())
    return [rows[t] for t in sorted(rows)],dict(day_missing=sum(t>=start for t in missing),warmup_missing=sum(t<start for t in missing),off_grid=sum((t-begin)%step!=0 for t in rows))
def main(day,root):
    start=int(datetime.fromisoformat(day).replace(tzinfo=KST).timestamp()*1000);end=start+86400000
    if end>time.time()*1000:raise ValueError('day has not closed')
    root.mkdir(parents=True,exist_ok=True)
    def one(sym):
        data={};state={};inst=sym+'-USDT-SWAP'
        for key,step,warm in [('1m',60000,60),('5m',300000,260),('15m',900000,260),('1H',3600000,64),('mark1m',60000,0)]:
            try:data[key],state[key]=candles(sym,key.removeprefix('mark'),step,warm,start,end,key.startswith('mark'))
            except Exception as exc:state[key]={'error':str(exc)}
        for key,path,params in [('instrument','public/instruments',dict(instType='SWAP',instId=inst)),('funding','public/funding-rate-history',dict(instId=inst,after=end,limit=100))]:
            try:
                rows=api(path,**params)
                data[key]=rows if key=='instrument' else [r for r in rows if start<=int(r['fundingTime'])<end]
                state[key]={'rows':len(data[key])}
                if key=='funding':state[key]['history_reaches_open']=any(int(r['fundingTime'])<=start for r in rows)
            except Exception as exc:state[key]={'error':str(exc)}
        blob=gzip.compress(json.dumps(data,separators=(',',':')).encode(),mtime=0)
        (root/(sym+'.json.gz')).write_bytes(blob)
        return sym,dict(inputs=state,bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest())
    with ThreadPoolExecutor(9) as pool:coverage=dict(pool.map(one,SYMBOLS))
    (root/'coverage.json').write_text(json.dumps(dict(day_kst=day,start_ms=start,end_exclusive_ms=end,symbols=coverage),indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('day');parser.add_argument('output',type=Path)
    args=parser.parse_args();main(args.day,args.output)
