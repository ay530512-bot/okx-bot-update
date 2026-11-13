"""Public WS snapshots only; never places orders. TLS verification remains enabled."""
import json
import socket
import ssl
import threading
import time


class MarketStream:
    CHANNELS=('tickers','trades','books5','mark-price')
    def __init__(self):
        self.lock=threading.RLock(); self.symbols=set(); self.monitor_symbols=set(); self.data={}; self.connected=False
        self.active_pairs=set();self.last_subscription=-float('inf');self.watch_changed=-float('inf');self.last_ping=0.;self.retry_delay=2
        self.band_prices={};self.generation=0; self.stop_event=threading.Event(); self.ws=None; self.error='미연결'
    def start(self):
        threading.Thread(target=self.run,daemon=True,name='okx-public-ws').start()
    def reconnect(self):
        with self.lock:
            self.connected=False;self.data={};self.generation+=1;self.error='수동 재연결 중'
            ws=self.ws
        if ws:
            try:ws.close()
            except Exception:pass

    def pairs(self):return {(s,ch) for s in self.symbols for ch in self.CHANNELS}|{(s,'tickers') for s in self.monitor_symbols}
    def subscription(self,op,pairs):
        # Only the receiving worker writes subscription frames. At most360/hour.
        items=sorted(pairs,key=lambda p:(p[1]=='tickers',p[0],p[1]))[:100]
        if not items:return
        self.ws.send(json.dumps({'op':op,'args':[{'channel':ch,'instId':s} for s,ch in items]}))
        if op=='subscribe':self.active_pairs.update(items)
        else:self.active_pairs.difference_update(items)
        self.last_subscription=time.monotonic()
    def flush_subscriptions(self):
        with self.lock:
            now=time.monotonic()
            if not self.connected or not self.ws or now-self.last_subscription<10:return
            if now-self.watch_changed<2:return
            desired=self.pairs();removed=self.active_pairs-desired;added=desired-self.active_pairs
            if removed:self.subscription('unsubscribe',removed)
            elif added:self.subscription('subscribe',added)
    def update_watch(self,symbols,monitor=False):
        with self.lock:
            before=self.pairs()
            if monitor:
                # Several consumers request ticker coverage. Their requests must not
                # alternately unsubscribe each other's symbols; keep their union.
                self.monitor_symbols.update(symbols)
            else:
                proposed=set(symbols)
                if proposed!=self.symbols:self.watch_changed=time.monotonic()
                self.symbols=proposed
            after=self.pairs()
            for key in before^after:self.data.pop(key,None)
    def retry_seconds(self):
        if self.error and '60014' in self.error:
            self.retry_delay=max(60,self.retry_delay)
        delay=self.retry_delay;self.retry_delay=min(300,self.retry_delay*2)
        return delay
    def watch(self,symbols):self.update_watch(symbols)
    def monitor(self,symbols):self.update_watch(symbols,True)
    def feed(self,message):
        if message=='pong': return
        obj=json.loads(message)
        if obj.get('event')=='error': raise ValueError('공개 WS 구독 거절: '+str(obj.get('code','unknown')))
        channel=obj.get('arg',{}).get('channel'); symbol=obj.get('arg',{}).get('instId')
        if channel not in self.CHANNELS or not obj.get('data'): return
        with self.lock:
            row=obj['data'][0]
            old=self.data.get((symbol,channel))
            if old and int(row['ts'])<int(old[0]['ts']): return
            self.data[(symbol,channel)]=(row,time.monotonic(),self.generation)
            if channel=='tickers' and row.get('last'):
                try:
                    price=float(row['last']);stamp=int(row['ts'])
                    import math
                    if not math.isfinite(price) or price<=0:raise ValueError('invalid price')
                    for frame,step in (('5m',300000),('15m',900000),('1H',3600000),('4H',14400000)):
                        start=stamp//step*step;key=(symbol,frame);previous=self.band_prices.get(key)
                        if previous and previous[0]==start and previous[4]==self.generation:
                            self.band_prices[key]=(start,max(previous[1],price),min(previous[2],price),price,self.generation)
                        else:self.band_prices[key]=(start,price,price,price,self.generation)
                except (ValueError,TypeError,OverflowError):pass

        if channel=='mark-price':
            callback=getattr(self,'on_mark',None)
            if callback:callback(dict(row))

    def band_bar(self,symbol,frame,base):
        with self.lock:
            value=self.band_prices.get((symbol,frame));result=list(base)
            if value and value[0]==base[0] and value[4]==self.generation:
                result[2]=max(result[2],value[1]);result[3]=min(result[3],value[2]);result[4]=value[3]
            return result
    def read(self,symbol,channel,max_age=15,now_ms=None):
        with self.lock:
            item=self.data.get((symbol,channel))
            if not self.connected or not item or item[2]!=self.generation or time.monotonic()-item[1]>max_age: return None
            if now_ms is not None and not -500<=now_ms-int(item[0]['ts'])<=max_age*1000: return None
            return dict(item[0])
    def ready(self,symbol,c,now_ms):
        age=c['liquidity']['ws_max_age_seconds']
        return all(self.read(symbol,ch,c['liquidity'].get('trade_max_age_seconds',age) if ch=='trades' else age,now_ms) is not None for ch in self.CHANNELS)
    def missing(self,symbol,c,now_ms):
        age=c['liquidity']['ws_max_age_seconds']
        return [ch for ch in self.CHANNELS if self.read(symbol,ch,c['liquidity'].get('trade_max_age_seconds',age) if ch=='trades' else age,now_ms) is None]
    def run(self):
        import websocket
        while not self.stop_event.is_set():
            sock=None
            try:
                with self.lock: symbols=sorted(self.symbols|self.monitor_symbols)
                if not symbols:
                    self.stop_event.wait(.5); continue
                # Explicit IPv4 socket to match signed REST routing; wss still wraps verified TLS/SNI.
                errors=[]
                for info in socket.getaddrinfo('ws.okx.com',443,socket.AF_INET,socket.SOCK_STREAM):
                    sock=socket.socket(info[0],info[1],info[2]); sock.settimeout(10)
                    try: sock.connect(info[4]); break
                    except OSError as error: errors.append(error); sock.close(); sock=None
                if sock is None: raise OSError('WS IPv4 접속 실패')
                sock=ssl.create_default_context().wrap_socket(sock,server_hostname='ws.okx.com')
                ws=websocket.create_connection('wss://ws.okx.com/ws/v5/public',timeout=10,socket=sock)
                ws.settimeout(1)
                with self.lock:
                    self.ws=ws; self.generation+=1; self.connected=True; self.data={}; self.error=None
                    self.active_pairs=set();self.last_subscription=-float('inf');self.last_ping=time.monotonic()
                while not self.stop_event.is_set():
                    self.flush_subscriptions()
                    if time.monotonic()-self.last_ping>=20:
                        ws.send('ping');self.last_ping=time.monotonic()
                    try:
                        msg=ws.recv()
                        if not msg: raise OSError('WS 연결 종료')
                        self.feed(msg)
                        self.retry_delay=2
                    except websocket.WebSocketTimeoutException:
                        continue
            except Exception as error:
                with self.lock: self.error=str(error)[:160] if isinstance(error,ValueError) else type(error).__name__
            finally:
                with self.lock:
                    self.connected=False
                    if self.ws:
                        try: self.ws.close()
                        except Exception: pass
                    self.ws=None
                if sock: sock.close()
            self.stop_event.wait(self.retry_seconds())
    def stop(self):
        self.stop_event.set()
        if self.ws: self.ws.close()


class AccountStream:
    """Private account/position observations. Callback may latch risk, never sends orders."""
    def __init__(self,settings,callback):
        self.settings=settings; self.callback=callback; self.connected=False; self.generation=0
        self.received=0; self.equity=None; self.stop_event=threading.Event(); self.ws=None
        self.error='미연결'
    def start(self): threading.Thread(target=self.run,daemon=True,name='okx-private-ws').start()
    def reconnect(self):
        self.connected=False;self.equity=None;self.received=0;self.generation+=1;self.error='수동 재연결 중'
        ws=self.ws
        if ws:
            try:ws.close()
            except Exception:pass

    def fresh(self): return self.connected and self.equity is not None and time.monotonic()-self.received<30
    def feed(self,msg):
        if msg=='pong': return
        obj=json.loads(msg)
        if obj.get('event')=='error': raise ValueError('계정 WS 구독 오류: '+str(obj.get('code','unknown')))
        channel=obj.get('arg',{}).get('channel')
        for row in obj.get('data',[]):
            if channel=='account':
                for d in row.get('details',[]):
                    if d.get('ccy')=='USDT' and d.get('eq') not in (None,''):
                        self.equity=float(d['eq']); self.received=time.monotonic()
                        self.error=None
                        self.callback('equity',dict(equity=self.equity,ms=int(d.get('uTime') or row.get('uTime') or time.time()*1000)))
            elif channel=='positions' and row.get('instType')=='SWAP': self.callback('position',row)
    def run(self):
        import websocket
        from okx_core import signed_header
        while not self.stop_event.is_set():
            sock=None
            try:
                for info in socket.getaddrinfo('ws.okx.com',443,socket.AF_INET,socket.SOCK_STREAM):
                    sock=socket.socket(info[0],info[1],info[2]); sock.settimeout(10)
                    try: sock.connect(info[4]); break
                    except OSError: sock.close(); sock=None
                if sock is None: raise OSError('Private WS 접속 실패')
                sock=ssl.create_default_context().wrap_socket(sock,server_hostname='ws.okx.com')
                ws=websocket.create_connection('wss://ws.okx.com/ws/v5/private',timeout=10,socket=sock)
                self.ws=ws; stamp=str(int(time.time()))
                ws.send(json.dumps({'op':'login','args':[{'apiKey':self.settings['OKX_API_KEY'],
                    'passphrase':self.settings['OKX_PASSPHRASE'],'timestamp':stamp,
                    'sign':signed_header(self.settings['OKX_SECRET_KEY'],stamp,'GET','/users/self/verify')}]}))
                response=json.loads(ws.recv())
                if response.get('event')!='login' or response.get('code')!='0': raise ValueError('계정 WS 로그인 실패: '+str(response.get('code','unknown')))
                self.connected=True; self.generation+=1; self.equity=None; self.received=0
                self.error=None
                ws.send(json.dumps({'op':'subscribe','args':[{'channel':'account','ccy':'USDT'},{'channel':'positions','instType':'SWAP'}]}))
                while not self.stop_event.is_set():
                    try:
                        msg=ws.recv()
                        if not msg: raise OSError('Private WS 끊김')
                        self.feed(msg)
                    except websocket.WebSocketTimeoutException:
                        ws.send('ping')
                        msg=ws.recv()
                        if msg!='pong': self.feed(msg)
            except Exception as error:
                self.error=str(error)[:160] if isinstance(error,ValueError) else type(error).__name__
            finally:
                self.connected=False; self.received=0
                if self.ws:
                    try: self.ws.close()
                    except Exception: pass
                if sock: sock.close()
                self.ws=None
            self.stop_event.wait(2)
    def stop(self):
        self.stop_event.set()
        if self.ws: self.ws.close()
