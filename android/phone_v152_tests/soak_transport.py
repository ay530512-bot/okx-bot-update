"""Local TLS/WebSocket load + real EOF recovery. Never contacts an exchange.

Uses production run/receive/subscription/recovery methods. A self-signed test
certificate is explicitly trusted, with hostname verification still required.
Synthetic rates, two monitor EOFs and one execution EOF are reproducible inputs.
"""
import base64
import hashlib
import json
from pathlib import Path
import select
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

D=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(D/'phone_v152'),str(D.parent.parent/'core121')]
import websocket
import okx_stream
import phone_public_ws as transport
import phone_public_lanes as lanes
transport.install();lanes.install()


class Server:
    def __init__(self,context):
        self.context=context;self.stop=threading.Event();self.errors=[]
        self.listener=socket.socket();self.listener.bind(('127.0.0.1',0));self.listener.listen(10)
        self.listener.settimeout(.2);self.port=self.listener.getsockname()[1]
        self.peers=[];self.faults={'monitor':0,'execution':0};self.lock=threading.Lock()
        self.sent={'monitor':0,'execution':0};self.started=time.monotonic()
        self.thread=threading.Thread(target=self.accept,daemon=True);self.thread.start()

    def accept(self):
        while not self.stop.is_set():
            try:raw,_=self.listener.accept()
            except socket.timeout:continue
            except OSError:return
            threading.Thread(target=self.serve,args=(raw,),daemon=True).start()

    def serve(self,raw):
        conn=None
        try:
            conn=self.context.wrap_socket(raw,server_side=True);self.peers.append(conn)
            conn.settimeout(2);headers=b''
            while b'\r\n\r\n' not in headers:headers+=conn.recv(4096)
            key=next(x.split(b':',1)[1].strip() for x in headers.split(b'\r\n') if x.lower().startswith(b'sec-websocket-key:'))
            accept=base64.b64encode(hashlib.sha1(key+b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
            conn.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+b'\r\n\r\n')
            ws=websocket.WebSocket(skip_utf8_validation=True);ws.sock=conn;ws.connected=True
            pairs=set();lane=None;index=0;next_send=time.monotonic()
            def send(value):
                f=websocket.ABNF.create_frame(value,1);f.mask=0;conn.sendall(f.format())
            while not self.stop.is_set():
                if conn.pending() or select.select([conn],[],[],.001)[0]:
                    message=ws.recv()
                    if not message:return
                    if message=='ping':send('pong')
                    else:
                        obj=json.loads(message)
                        batch={(x['instId'],x['channel']) for x in obj['args']}
                        if obj['op']=='subscribe':pairs.update(batch)
                        else:pairs.difference_update(batch)
                        lane='monitor' if len(pairs)>20 else 'execution'
                        for arg in obj['args']:send(json.dumps({'event':obj['op'],'arg':arg}))
                now=time.monotonic();elapsed=now-self.started
                if lane:
                    with self.lock:
                        targets=[8,24] if lane=='monitor' else [16]
                        count=self.faults[lane]
                        fault=count<len(targets) and elapsed>=targets[count]
                        if fault:self.faults[lane]+=1
                    if fault:
                        conn.shutdown(socket.SHUT_RDWR);return # True EOF, no WS close frame.
                if pairs and now>=next_send:
                    ordered=sorted(pairs);n=24 if lane=='monitor' else len(ordered)
                    for i in range(n):
                        symbol,ch=ordered[(index+i)%len(ordered)]
                        row={'ts':str(int(time.time()*1000)),'last':'2','markPx':'2',
                             'bidPx':'1.9999','askPx':'2.0001','bids':[['1.9999','10000','0','1']],
                             'asks':[['2.0001','10000','0','1']],'px':'2','sz':'1'}
                        send(json.dumps({'arg':{'channel':ch,'instId':symbol},'data':[row]},separators=(',',':')))
                    self.sent[lane]+=n;index+=n
                    next_send=now+(.02 if lane=='monitor' else .05)
        except (OSError,websocket.WebSocketConnectionClosedException):
            pass
        except BaseException as e:self.errors.append(type(e).__name__)
        finally:
            if conn:conn.close()
            else:raw.close()

    def close(self):
        self.stop.set();self.listener.close()
        for s in self.peers:
            try:s.shutdown(socket.SHUT_RDWR);s.close()
            except OSError:pass
        self.thread.join(1)


def main(seconds=120):
    with tempfile.TemporaryDirectory() as tmp:
        key,cert=Path(tmp)/'key.pem',Path(tmp)/'cert.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),
            '-out',str(cert),'-days','1','-subj','/CN=ws.okx.com','-addext','subjectAltName=DNS:ws.okx.com'],
            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_context.load_cert_chain(cert,key)
        client_context=ssl.create_default_context(cafile=str(cert))
        assert client_context.check_hostname and client_context.verify_mode==ssl.CERT_REQUIRED
        server=Server(server_context)
        stream=okx_stream.MarketStream();stream.monitor([f'TEST{i}-USDT-SWAP' for i in range(290)])
        stream.watch(['TEST0-USDT-SWAP','TEST1-USDT-SWAP'])
        cfg={'liquidity':{'ws_max_age_seconds':15,'trade_max_age_seconds':60}}
        observations=[];start=time.monotonic();cpu=time.process_time()
        def local_dns(host,port,*a,**k):
            assert host=='ws.okx.com' and port==443
            return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',server.port))]
        try:
            with patch.object(transport.socket,'getaddrinfo',side_effect=local_dns),patch.object(transport.ssl,'create_default_context',return_value=client_context):
                stream.start()
                while time.monotonic()-start<seconds:
                    now=int(time.time()*1000);m=stream._phone_monitor_stream
                    observations.append(dict(t=round(time.monotonic()-start,3),execution=stream.connected,
                        monitor=m.connected,ready=stream.ready('TEST0-USDT-SWAP',cfg,now),
                        execution_generation=stream.generation,monitor_generation=m.generation))
                    time.sleep(.025)
                report=dict(local_tls_only=True,actual_phone_tested=False,actual_exchange_order_requests=0,
                    elapsed_s=round(time.monotonic()-start,2),cpu_s=round(time.process_time()-cpu,2),
                    websocket_client=websocket.__version__,sent=server.sent,injected_faults=server.faults,
                    execution=transport.diagnostics(stream).copy(),monitor=transport.diagnostics(m).copy(),
                    fresh_execution_while_monitor_down=sum(x['ready'] and not x['monitor'] for x in observations),
                    final_ready=observations[-1]['ready'],server_errors=server.errors)
                assert report['final_ready']
                assert server.faults=={'monitor':2,'execution':1},server.faults
                assert report['execution']['disconnect_count']==1,report['execution']
                assert report['monitor']['disconnect_count']==2,report['monitor']
                assert report['fresh_execution_while_monitor_down']>0
                assert not server.errors,server.errors
                # No snapshot is admitted when its owning execution socket is down.
                assert all(not x['ready'] for x in observations if not x['execution'])
                stream.stop()
                stream._phone_reader.join(3);m._phone_reader.join(3)
        finally:
            stream.stop();server.close()
        Path(__file__).with_name('local_soak.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ('execution','monitor')}))


if __name__=='__main__':main(int(sys.argv[1]) if len(sys.argv)>1 else 120)
