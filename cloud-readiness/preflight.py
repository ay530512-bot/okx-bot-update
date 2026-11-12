"""Read-only host probe. Never reads credentials or sends exchange writes.
Run on target server: python preflight.py --network --output preflight.json
Results do NOT authorize live trading or prove the host has a static IP.
"""
import argparse,importlib.util,json,os,platform,shutil,statistics,time,urllib.request
from pathlib import Path
ENDPOINTS={'okx_time':'https://openapi.okx.com/api/v5/public/time','okx_candles':'https://openapi.okx.com/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=1m&limit=2','github_release':'https://api.github.com/repos/ay530512-bot/okx-bot-update/releases/latest'}
def probe(url,samples=5):
 durations=[];errors=[];offsets=[]
 for _ in range(samples):
  begin=time.monotonic();wall=time.time()
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'OKX-readonly-preflight'})
   with urllib.request.urlopen(req,timeout=5) as r:
    data=json.loads(r.read(200000));status=r.status
   if status!=200 or ('code' in data and data['code']!='0'):raise ValueError('non-success response')
   elapsed=(time.monotonic()-begin)*1000;durations.append(round(elapsed,1))
   if '/public/time' in url:offsets.append(round(int(data['data'][0]['ts'])-(wall*1000+elapsed/2),1))
  except Exception as exc:errors.append(type(exc).__name__)
 return {'samples':samples,'success':len(durations),'errors':errors,'latency_ms':durations,'median_ms':statistics.median(durations) if durations else None,'max_ms':max(durations) if durations else None,'clock_offset_estimates_ms':offsets,'status':'PASS_SAMPLE_ONLY' if len(durations)==samples else 'BLOCKED'}
def collect(network=False,samples=5):
 deps={k:importlib.util.find_spec(k) is not None for k in ('tkinter','requests','dotenv','websocket','openai','ccxt')}
 memory=None
 if Path('/proc/meminfo').exists():
  values={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()}
  memory={'total_bytes':values['MemTotal'],'available_bytes':values['MemAvailable'],'scope':'host; may differ from container limit'}
 result={'schema':1,'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'os':platform.system(),'python':platform.python_version(),'logical_cpus':os.cpu_count(),'memory':memory,'free_disk_bytes':shutil.disk_usage('.').free,'dependencies':deps,'display_environment_set':bool(os.environ.get('DISPLAY')),'live_ready':False,'unverified':['target-host identity','provider static IPv4 attachment and OKX allowlist','private account/order/SL read checks','single active host cutover','reboot and update recovery','24-hour CPU/memory/burst capacity','Tailscale HTTPS and device expiry','backup restore','order placement/latency under real load']}
 if network:result['public_get_probes']={k:probe(v,samples) for k,v in ENDPOINTS.items()}
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--network',action='store_true');p.add_argument('--samples',type=int,default=5,choices=range(1,11));p.add_argument('--output',default='preflight.json');a=p.parse_args()
 r=collect(a.network,a.samples);Path(a.output).write_text(json.dumps(r,ensure_ascii=False,indent=2));print(json.dumps(r,ensure_ascii=False,indent=2))
