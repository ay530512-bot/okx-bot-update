"""Synthetic full frame receive/feed throughput, not a Fold3/live benchmark."""
import hashlib
import json
from pathlib import Path
import sys
import time

D=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(D/'phone_v152'),str(D.parent.parent/'core121')]
import websocket
import okx_stream
import phone_public_ws as transport
import phone_feed_fast
phone_feed_fast.install(json.loads((D/'phone_v152/phone_sources.json').read_text()))


def benchmark(count, fast):
    row={'instId':'TEST-USDT-SWAP','last':'0.2341','lastSz':'123','askPx':'0.2342',
         'askSz':'421','bidPx':'0.2340','bidSz':'144','open24h':'0.221','high24h':'0.231',
         'low24h':'0.211','volCcy24h':'123456789.12','vol24h':'12345678',
         'ts':'1794836700000','sodUtc0':'0.22','sodUtc8':'0.21'}
    data=json.dumps({'arg':{'channel':'tickers','instId':'TEST-USDT-SWAP'},'data':[row]},separators=(',',':')).encode()
    def frame():return websocket.ABNF.create_frame(data,websocket.ABNF.OPCODE_TEXT)
    ws=websocket.WebSocket(skip_utf8_validation=fast)
    ws.recv_frame=frame
    s=okx_stream.MarketStream();s.connected=True;s.generation=1
    t=time.perf_counter();cpu=time.process_time()
    for _ in range(count):s.feed(transport.receive(ws,websocket,s))
    elapsed=time.perf_counter()-t;cpu=time.process_time()-cpu
    return dict(frames=count,wall_s=round(elapsed,6),cpu_s=round(cpu,6),
                messages_per_second=round(count/elapsed),final=s.data,band_prices=s.band_prices)


if __name__=='__main__':
    old=benchmark(60000,False);new=benchmark(60000,True)
    assert [(k,v[0]) for k,v in old.pop('final').items()]==[(k,v[0]) for k,v in new.pop('final').items()]
    assert old.pop('band_prices')==new.pop('band_prices')
    report=dict(synthetic=True,actual_phone_tested=False,websocket_client=websocket.__version__,
        before=old,after=new,cpu_reduction_pct=round((1-new['cpu_s']/old['cpu_s'])*100,2),
        throughput_ratio=round(new['messages_per_second']/old['messages_per_second'],2),
        note='Same 60000 unmasked 340-byte ticker payloads; frame assembly, strict text validation, JSON parsing and original optimized feed. No network/Android timing claim.')
    Path(__file__).with_name('receive_benchmark.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
