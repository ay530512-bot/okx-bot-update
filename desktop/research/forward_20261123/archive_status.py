"""Check both OKX UTC+8 daily archives spanning a just-closed KST day."""
import sys,json
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from cache_day import SYMBOLS
def one(job):
    sym,day=job
    url=f"https://static.okx.com/cdn/okex/traderecords/trades/daily/{day.replace('-','')}/{sym}-USDT-SWAP-trades-{day}.zip"
    code=None;size=None
    for attempt in range(3):
        try:
            with urlopen(Request(url,method='HEAD'),timeout=15) as r:code=r.status;size=r.headers.get('Content-Length')
            break
        except HTTPError as exc:
            code=exc.code
            if code in (403,404):break
        except OSError:pass
    return {'symbol':sym,'source_date_utc8':day,'http':code,'bytes':int(size) if size else None,'url':url}
if __name__=='__main__':
    day=date.fromisoformat(sys.argv[1])
    with ThreadPoolExecutor(12) as pool:rows=list(pool.map(one,[(s,str(d)) for s in SYMBOLS for d in (day-timedelta(days=1),day)]))
    Path(sys.argv[2]).write_text(json.dumps(rows,indent=1))
