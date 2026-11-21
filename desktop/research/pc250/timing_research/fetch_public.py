"""Download public OKX minute candles and settled funding for the replay. Run beside OKX_PC_PACKAGE/."""
import argparse
import concurrent.futures
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile, ZIP_DEFLATED
from replay import COINS, DAY, MINUTE, stamp

RAW=Path('raw'); API='https://www.okx.com'; CDN='https://static.okx.com/cdn/okex/traderecords'

def get(url):
    for attempt in range(4):
        try:
            with urlopen(Request(url,headers={'User-Agent':'OKX-public-replay/2.5'}),timeout=25) as r:return r.read()
        except (HTTPError,OSError) as e:
            if getattr(e,'code',None)==404 or attempt==3:raise
            time.sleep(1+2*attempt)

def api(path,**params):
    obj=json.loads(get(API+'/api/v5/'+path+'?'+urlencode(params)))
    if obj['code']!='0':raise ValueError('public request failed: '+str(obj['code']))
    return obj['data']

def archive(sym,period,kind):
    name=f'{sym}-USDT-SWAP-{kind}-{period}.zip';target=RAW/name
    if target.exists():return True
    frequency='daily' if len(period)>7 else 'monthly';category='swaprates' if kind=='fundingrates' else 'candlesticks'
    try:raw=get(f'{CDN}/{category}/{frequency}/{period.replace("-","")}/{name}')
    except HTTPError as e:
        if e.code==404:return False
        raise
    with ZipFile(io.BytesIO(raw)) as z:
        if z.testzip() is not None:raise ValueError('archive checksum')
    tmp=target.with_suffix('.tmp');tmp.write_bytes(raw);os.replace(tmp,target);return True

def months(lo,hi):
    first=datetime.fromtimestamp(lo/1000,timezone.utc).replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    while first.timestamp()*1000<hi:
        nxt=(first+timedelta(days=32)).replace(day=1);yield first,nxt;first=nxt

def bootstrap(job):
    sym,lo,hi=job;instrument=sym+'-USDT-SWAP';cut=int(time.time()*1000);fund_start=hi
    for first,nxt in months(lo,hi):
        month=first.strftime('%Y-%m');finished=nxt.timestamp()*1000<=cut
        if not finished or not archive(sym,month,'fundingrates'):fund_start=min(fund_start,max(lo,int(first.timestamp()*1000)))
        if finished and archive(sym,month,'candlesticks'):continue
        day=first
        while day<nxt and day.timestamp()*1000<hi:
            start=int(day.timestamp()*1000);stop=min(start+DAY,hi);date=day.strftime('%Y-%m-%d');day+=timedelta(days=1)
            if stop<=lo:continue
            if stop==start+DAY and archive(sym,date,'candlesticks'):continue
            # Partial UTC day at 00:30 KST. Store a patch separately so newer bars can be added on the next run.
            rows=[];cursor=stop
            while cursor>max(start,lo):
                data=api('market/history-candles',instId=instrument,bar='1m',after=cursor,limit='300')
                if not data:break
                rows.extend([[int(r[0]),*r[1:6]] for r in data if max(start,lo)<=int(r[0])<stop and r[8]=='1'])
                last=min(int(r[0]) for r in data)
                if last>=cursor:raise ValueError('candle cursor')
                cursor=last;time.sleep(.15)
            if rows:
                patch=RAW/(sym+'patch.csv');old={}
                if patch.exists():
                    with patch.open() as f:old={int(r[0]):r for r in list(csv.reader(f))[1:]}
                old.update({r[0]:r for r in rows});tmp=patch.with_suffix('.tmp')
                with tmp.open('w',newline='') as f:
                    writer=csv.writer(f);writer.writerow(['open_time','open','high','low','close','vol']);writer.writerows(old[t] for t in sorted(old))
                os.replace(tmp,patch)
    if fund_start<hi:
        target=RAW/(sym+'rates.json');funds=json.loads(target.read_text()) if target.exists() else {};cursor=hi
        while cursor>fund_start:
            rows=api('public/funding-rate-history',instId=instrument,after=cursor,limit='100')
            if not rows:raise ValueError(sym+' missing funding')
            funds.update({r['fundingTime']:float(r['realizedRate']) for r in rows});last=min(int(r['fundingTime']) for r in rows)
            if last>=cursor:raise ValueError('funding cursor')
            cursor=last
        tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(funds));os.replace(tmp,target)
    return sym

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--start',required=True);ap.add_argument('--end',required=True);a=ap.parse_args()
    RAW.mkdir(exist_ok=True);lo=(stamp(a.start)-4*DAY)//DAY*DAY;hi=stamp(a.end)
    if hi>int(time.time()*1000) or lo>=hi:raise ValueError('use completed days only')
    rows=api('public/instruments',instType='SWAP');Path('ins.json').write_text(json.dumps({'data':rows}))
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        for s in pool.map(bootstrap,[(s,lo,hi) for s in COINS]):print(s,flush=True)
