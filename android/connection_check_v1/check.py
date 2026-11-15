"""Ten-minute public-only experiment. No bot imports, credentials or order calls.

Uses only the verified 1.2.3 public socket adapter (does not call install()).
Two AAVE ticker connections: idle heartbeat vs periodic heartbeat. Different
server routes and much lower load than the bot prevent causal attribution.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import threading
import time

ROOT = Path.home() / 'okx-phone'
OUT = ROOT / 'connection-check'
ADAPTER_HASH = '09c2a06ca2a093dc267aa576505203590d670839fe69def9c8e3a5df59691dce'


def dependencies():
    import websocket
    path = ROOT / 'host-v21/phone_public_ws.py'
    if hashlib.sha256(path.read_bytes()).hexdigest() != ADAPTER_HASH:
        raise RuntimeError('1.2.3 수신 모듈과 일치하지 않습니다. 진단을 시작하지 않았습니다.')
    spec = importlib.util.spec_from_file_location('checked_public_adapter', path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    return websocket, adapter


def bot_sample(root=ROOT):
    d = json.loads((root / 'phone_connection_trace.json').read_text())
    public = d.get('latest', {}).get('public', {})
    tr = public.get('transport') or {}
    last = tr.get('last_disconnect') or {}
    return dict(pid=d.get('host_pid'), age=round(time.time()-d['observed_at'], 2),
                connected=public.get('connected'), count=tr.get('disconnect_count'),
                generation=public.get('generation'), last={k:last.get(k) for k in
                ('observed_at','cause','error','close_code','connection_uptime_s','frame_age_s')})


def due(mode, now, last_rx, last_ping):
    return now-last_ping >= 20 and (mode == 'periodic' or now-last_rx >= 20)


def summarize(samples, stats, seconds):
    valid = [s for s in samples if 0 <= s.get('age', 999) <= 10 and isinstance(s.get('count'), int) and isinstance(s.get('pid'),int)]
    pids = {s.get('pid') for s in valid}
    delta = valid[-1]['count']-valid[0]['count'] if len(pids)==1 and len(valid)>1 else None
    if delta is not None and delta < 0:
        delta = None
    lines = ['OKX 연결 비교 진단 (매매 설정/주문 변경 없음)', f'검사 시간: {seconds}초',
             f'봇 신규 끊김: {delta if delta is not None else "판정 불가"}',
             f'봇 유효 표본: {len(valid)}/{len(samples)}',
             f'봇 실행 변경 감지: {len(pids)>1}']
    for name, v in stats.items():
        lines.append(f'{name}: 연결 {v["connections"]}, 시세 {v["market_frames"]}건, '
                     f'종료 {v["disconnects"]}회, 접속 실패 {v["connect_failures"]}회, '
                     f'ping/pong {v["pings"]}/{v["pongs"]}')
        for item in v.get('failures', [])[-5:]:
            stamp=time.strftime('%H:%M:%S',time.gmtime(item['at']+9*3600))
            lines.append(f'  {stamp} KST {item["error"]} / {item["cause"]}')
    if valid:
        lines.append('봇 마지막 종료: '+json.dumps(valid[-1].get('last'),ensure_ascii=False))
    lines += ['판정: 이 검사는 원인 비교용이며 연결 문제 해결 완료 판정이 아닙니다.',
              '봇만 끊겨도 프로그램 결함으로 확정하지 않습니다(구독량/서버 경로가 다름).',
              '두 별도 연결도 함께 끊기면 공통 통신 경로 또는 서버 요인을 우선 조사합니다.',
              '정기 ping 연결만 안정적이어도 한 번의 10분 결과로 효과를 확정하지 않습니다.',
              '검사 중 휴대폰/봇 재시작, 유효 표본 부족, 시세 미수신은 비교 한계입니다.']
    return '\n'.join(lines)+'\n'


def run(seconds):
    wsmod, adapter = dependencies()
    OUT.mkdir(parents=True, exist_ok=True)
    lock = (OUT/'run.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        print('이미 연결 진단 실행 중입니다.', flush=True)
        return
    stop = threading.Event()
    mutex = threading.Lock()
    stats = {name:dict(connections=0,market_frames=0,disconnects=0,connect_failures=0,pings=0,pongs=0,failures=[])
             for name in ('idle','periodic')}
    samples = []
    started = time.time()
    log = (OUT/'events.jsonl').open('w', buffering=1)
    def event(kind, **data):
        with mutex:
            log.write(json.dumps(dict(at=time.time(),kind=kind,**data),ensure_ascii=False)+'\n')
    def inc(name, key):
        with mutex:
            stats[name][key] += 1
    def worker(name, stagger):
        if stop.wait(stagger): return
        delay = 2
        while not stop.is_set():
            raw = ws = None
            connected = False
            began = last_rx = last_ping = time.monotonic()
            try:
                # Same IPv4/TLS route as bot. Public unauthenticated ticker only.
                infos = socket.getaddrinfo('ws.okx.com',443,socket.AF_INET,socket.SOCK_STREAM)
                for info in infos:
                    raw = socket.socket(info[0],info[1],info[2]);raw.settimeout(10)
                    try:
                        raw.connect(info[4]);break
                    except OSError:
                        raw.close();raw=None
                if raw is None: raise OSError('connect failed')
                raw = ssl.create_default_context().wrap_socket(raw,server_hostname='ws.okx.com')
                ws = wsmod.create_connection('wss://ws.okx.com/ws/v5/public',socket=raw,
                    timeout=10,class_=adapter.public_socket_class(wsmod))
                ws.settimeout(1)
                ws.send(json.dumps({'op':'subscribe','args':[{'channel':'tickers','instId':'AAVE-USDT-SWAP'}]}))
                connected=True;inc(name,'connections')
                began=last_rx=last_ping=time.monotonic()
                event('connected',arm=name)
                while not stop.is_set():
                    now=time.monotonic()
                    if due(name,now,last_rx,last_ping):
                        ws.send('ping');last_ping=now;inc(name,'pings')
                    if now-last_rx >= 45: raise TimeoutError('silent connection')
                    try:
                        op, frame=ws.recv_data_frame(control_frame=True)
                    except wsmod.WebSocketTimeoutException:
                        continue
                    last_rx=time.monotonic()
                    if op==wsmod.ABNF.OPCODE_CLOSE:
                        data=frame.data
                        event('peer_close',arm=name,code=int.from_bytes(data[:2],'big') if isinstance(data,bytes) and len(data)>=2 else None)
                        raise adapter.PublicPeerClosed('peer close')
                    if op not in (wsmod.ABNF.OPCODE_TEXT,wsmod.ABNF.OPCODE_BINARY):continue
                    message=frame.data.decode() if isinstance(frame.data,bytes) else frame.data
                    if message=='pong':inc(name,'pongs');continue
                    obj=json.loads(message)
                    if obj.get('event')=='error':
                        event('subscription_error',arm=name,code=str(obj.get('code'))[:16])
                        raise ValueError('subscription rejected')
                    if obj.get('data'):
                        inc(name,'market_frames');delay=2
            except Exception as exc:
                if not stop.is_set():
                    inc(name,'disconnects' if connected else 'connect_failures')
                    with mutex:
                        stats[name]['failures'].append(dict(at=time.time(),error=type(exc).__name__,cause=adapter.failure_kind(exc)))
                    event('disconnect' if connected else 'connect_failure',arm=name,
                          error=type(exc).__name__,cause=adapter.failure_kind(exc),
                          uptime=round(time.monotonic()-began,3),
                          frame_age=round(time.monotonic()-last_rx,3))
            finally:
                if ws:
                    try:ws.close(timeout=1)
                    except Exception:pass
                if raw:
                    try:raw.close()
                    except Exception:pass
            if stop.wait(delay):return
            delay=min(30,delay*2)
    (OUT/'result.txt').write_text('진단 진행 중. 약 10분 후 이 파일에 결과가 저장됩니다.\n')
    event('start',seconds=seconds,python=sys.version.split()[0],websocket=getattr(wsmod,'__version__','unknown'))
    threads=[threading.Thread(target=worker,args=(name,i),daemon=True) for i,name in enumerate(stats)]
    for thread in threads:thread.start()
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            sample=bot_sample();samples.append(sample);event('bot',**sample)
        except Exception as exc:event('bot_read_error',error=type(exc).__name__)
        stop.wait(min(2,max(0,deadline-time.monotonic())))
    stop.set()
    for thread in threads:thread.join(timeout=2)
    with mutex:
        frozen=json.loads(json.dumps(stats))
    result=summarize(samples,frozen,seconds)
    report=dict(started_at=started,finished_at=time.time(),seconds=seconds,stats=frozen,
                bot_samples=samples,worker_pending=any(t.is_alive() for t in threads))
    (OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (OUT/'result.txt').write_text(result)
    print(result,flush=True)
    if not report['worker_pending']:
        log.close();lock.close()
    # Daemon workers end with this read-only diagnostic process, not the bot.


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if args.run:
        run(600);return
    dependencies()  # Fail before launch if prerequisites are absent/mismatched.
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'run.lock').open('a') as check:
        try:fcntl.flock(check,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('이미 진단 중입니다. 완료 후 result.txt를 확인하세요.');return
    with (OUT/'launcher.log').open('a') as output:
        subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--run'],
                         stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True)
    print('10분 연결 비교 진단을 시작했습니다. Termius 연결을 닫아도 계속 실행됩니다.\n'
          '완료 후: cat ~/okx-phone/connection-check/result.txt\n'
          'Android가 Termux 프로세스를 종료하면 검사는 중단됩니다.')


if __name__=='__main__':main()
