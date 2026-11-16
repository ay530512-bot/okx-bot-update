"""Offline TLS/WebSocket replay: identical bytes and original ticker feed.

Uses a local MemoryBIO TLS handshake, not an exchange socket. The certificate is
temporary and verified by a dedicated test CA context. No timing claim about a
phone or WAN is made. Replays include all 290 symbols without sampling/drops.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import ssl
import statistics
import subprocess
import sys
import tempfile
import time

D=Path(__file__).resolve().parent;ROOT=D.parent
sys.path[:0]=[str(ROOT/'phone_v164'),str(D.parents[2]/'core121')]
import websocket
import phone_public_ws as transport
from okx_stream import MarketStream
from phone_feed_fast import install as fast_feed
fast_feed(json.loads((ROOT/'phone_v164/phone_sources.json').read_text()))
spec=importlib.util.spec_from_file_location('monitor_before',ROOT/'phone_v163/phone_public_ws.py')
before_transport=importlib.util.module_from_spec(spec);spec.loader.exec_module(before_transport)


class TLSReplay:
    def __init__(self, context, cert, key, wire):
        server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_context.load_cert_chain(cert,key)
        ci,co,si,so=(ssl.MemoryBIO() for _ in range(4))
        client=context.wrap_bio(ci,co,server_hostname='localhost')
        server=server_context.wrap_bio(si,so,server_side=True)
        complete=set()
        for _ in range(20):
            for i,obj in enumerate((client,server)):
                try:obj.do_handshake();complete.add(i)
                except ssl.SSLWantReadError:pass
            if co.pending:si.write(co.read())
            if so.pending:ci.write(so.read())
            if len(complete)==2:break
        assert len(complete)==2
        for start in range(0,len(wire),16384):
            server.write(wire[start:start+16384]);ci.write(so.read())
        self.client,self.input=client,ci
        self.calls=0
    def gettimeout(self):return 1
    def recv(self,size):self.calls+=1;return self.client.read(size)
    def close(self):pass


def replay(context,cert,key,wire,count,ahead):
    sock=TLSReplay(context,cert,key,wire)
    implementation=transport if ahead else before_transport
    cls=transport.public_socket_class(websocket,read_ahead=ahead) if ahead else before_transport.public_socket_class(websocket)
    ws=cls(skip_utf8_validation=True)
    ws.sock=sock;ws.connected=True
    stream=MarketStream();stream.connected=True;stream.generation=1
    clock=time.perf_counter();cpu=time.process_time()
    digest=hashlib.sha256()
    for _ in range(count):
        message=implementation.receive(ws,websocket,stream)
        digest.update(message.encode());stream.feed(message)
    elapsed=time.perf_counter()-clock;used=time.process_time()-cpu
    last={s:[r[0]['ts'],r[0]['last']] for (s,c),r in stream.data.items()}
    return dict(frames=count,wall_s=round(elapsed,6),cpu_s=round(used,6),
        tls_reads=sock.calls,frames_per_second=round(count/elapsed),
        messages_sha256=digest.hexdigest(),symbols=len(last),
        latest_sha256=hashlib.sha256(json.dumps(last,sort_keys=True).encode()).hexdigest(),
        bands_sha256=hashlib.sha256(repr(sorted(stream.band_prices.items())).encode()).hexdigest())


def main():
    count=60000;frames=[]
    for i in range(count):
        symbol=f'TEST{i%290:03}-USDT-SWAP';stamp=1794855600000+i
        body=json.dumps(dict(arg=dict(channel='tickers',instId=symbol),data=[dict(
            instType='SWAP',instId=symbol,last=str(10+(i%97)/100),lastSz='1.2',
            askPx='11',askSz='19',bidPx='9',bidSz='18',open24h='10',high24h='12',
            low24h='8',volCcy24h='50000',vol24h='5000',sodUtc0='9',ts=str(stamp))]),separators=(',',':'))
        frames.append(websocket.ABNF(fin=1,opcode=1,mask_value=0,data=body.encode()).format())
    wire=b''.join(frames)
    with tempfile.TemporaryDirectory() as td:
        cert=str(Path(td)/'cert.pem');key=str(Path(td)/'key.pem')
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1',
            '-keyout',key,'-out',cert,'-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        context=ssl.create_default_context(cafile=cert)
        samples=[]
        for order in ((0,16384),(16384,0),(0,16384)):
            pair={}
            for ahead in order:pair['after' if ahead else 'before']=replay(context,cert,key,wire,count,ahead)
            samples.append(pair)
    for pair in samples:
        for field in ('frames','messages_sha256','symbols','latest_sha256','bands_sha256'):
            assert pair['before'][field]==pair['after'][field],field
    before=statistics.median(x['before']['cpu_s'] for x in samples)
    after=statistics.median(x['after']['cpu_s'] for x in samples)
    out=dict(synthetic=True,actual_phone_tested=False,actual_exchange_connections=0,
        websocket_client=websocket.__version__,tls=ssl.OPENSSL_VERSION,samples=samples,
        median_cpu_before_s=before,median_cpu_after_s=after,
        cpu_reduction_pct=round((1-after/before)*100,2),
        note='Verified in-memory TLS records; full unchanged WebSocket frame decoding and ticker feed. Local CPU, not Android/network latency.')
    (D/'monitor_benchmark.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k!='samples'}))


if __name__=='__main__':main()
