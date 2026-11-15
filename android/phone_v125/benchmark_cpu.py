"""Reproducible offline 1.2.4/1.2.5 comparison, never a Fold CPU estimate.
Usage: OKX_TEST_CORE=... OKX_TEST_HOST=... python -B benchmark_cpu.py
"""
import copy, hashlib, json, os, queue, statistics, sys, time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path[:0]=[os.environ['OKX_TEST_HOST'],os.environ['OKX_TEST_CORE']]
import okx_band_flow as band, okx_channel701 as ch, okx_pattern15 as trend
from okx_stream import MarketStream
from phone_signal_cache import install
from phone_performance import Timing

fixture=json.loads((Path(__file__).parents[1]/'phone_v118/test_signal_fixture.json').read_text())
now=int(fixture['now']);positive=copy.deepcopy(fixture['row']);positive['instrument']['lever']='100'
for bars in positive['live_frames'].values():
    for row in bars:row[0]=int(row[0])
rows=[positive]
for i in range(288):
    frames={name:[[r[0],100.,101.,99.,100.,100.] for r in bars] for name,bars in positive['live_frames'].items()}
    rows.append(dict(symbol=f'X{i}-USDT-SWAP',instrument={'lever':'100','instCategory':'1'},live_frames=frames))
inputs_sha=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
timer=Timing('/tmp');timer.local.group='optimized'
cache=install(timer,json.loads((Path(os.environ['OKX_TEST_HOST'])/'phone_sources.json').read_text()))
# Exercise the same production completed-candle producer in each release.
for row in rows:
    row['live_frames']={f:band.merge_completed(None,b,f,now,300) for f,b in row['live_frames'].items()}
cfg={'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]}}
e=NS(api=NS(now_ms=lambda:now),can_open_position=lambda:True,universe=NS(read=lambda:({'rows':rows},None)),
     records=lambda:[],blocked_manual_symbols=lambda:set(),cfg=cfg,journal=NS(data={}),
     stream=NS(watch=lambda _:None,ready=lambda *a:False),chat=NS(watch=lambda:[]),pipeline=lambda *a,**kw:None,events=queue.Queue())
with patch.object(trend,'allowed',return_value=True):
    ch.candidate(e)
    cold=cache.report();trials=[]
    for _ in range(5):
        start=time.process_time()
        for scan in range(30):ch.candidate(e)
        trials.append((time.process_time()-start)/30)
out=dict(host=Path(os.environ['OKX_TEST_HOST']).name,inputs_sha256=inputs_sha,
    symbols=289,scans_per_trial=30,trials=5,scan_cpu_s=trials,scan_median_cpu_s=statistics.median(trials),
    result_sha256=hashlib.sha256(json.dumps(e.channel_pending,sort_keys=True).encode()).hexdigest(),
    cache_before=cold,cache_after=cache.report())
def message(i,price):
    return json.dumps({'arg':{'instId':f'X{i%289}','channel':'tickers'},'data':[{'ts':str(now+i),'last':str(price)}]})
feed={}
for name in ('repeated_prices','changing_prices'):
    messages=[message(i,100. if name=='repeated_prices' else 100.+((i//289)%17)*.01) for i in range(30000)]
    trials=[]
    for _ in range(5):
        s=MarketStream();s.connected=True;s.generation=1
        start=time.process_time()
        for text in messages:s.feed(text)
        trials.append(time.process_time()-start)
    feed[name]=dict(frames=30000,cpu_s=trials,median_cpu_s=statistics.median(trials),
        final_bars_sha256=hashlib.sha256(repr(sorted(s.band_prices.items())).encode()).hexdigest())
out['feed']=feed
out['limitations']='Synthetic offline workstation CPU time; excludes network, account API, OS scheduling and real Fold thermals. No profitability claim.'
print(json.dumps(out,ensure_ascii=False,indent=2))
