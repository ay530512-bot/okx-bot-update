"""Authenticated display-only chart deltas from the existing public WS cache.

Never supplies strategy candles, order admission, position PnL or stop prices.
Official REST candles own open/volume/confirmation; only the forming candle's
price/high/low are overlaid. A missing new candle is never fabricated.
"""
import copy
import json
import math
import threading
import time

STEPS = {'1m':60000,'5m':300000,'15m':900000,'1H':3600000,'4H':14400000,
         '1D':86400000,'1W':604800000}


class LiveChart:
    def __init__(self, mobile, stream, clock=None, owns_stream=False):
        self.mobile, self.stream = mobile, stream
        self.clock = clock or (lambda:int(time.time()*1000))
        self.owns_stream = owns_stream
        self.slots = threading.BoundedSemaphore(4)

    def validate(self, symbol, frame):
        if frame not in STEPS: raise ValueError('차트 시간봉 오류')
        with self.mobile.lock:
            data = self.mobile.snapshot
            allowed = {p['symbol'] for p in data.get('positions',[])+data.get('movers',[])
                       +data.get('futures',{}).get('rows',[])}
        if symbol not in allowed: raise ValueError('차트 종목 확인 필요')

    def select(self, symbol, frame):
        self.validate(symbol, frame)
        self.stream.monitor([symbol])
        with self.mobile.lock:
            self.mobile.touched = time.monotonic()
            self.mobile.feed.select(symbol, frame)

    def packet(self, symbol, frame):
        now = self.clock()
        with self.mobile.lock:
            cached = self.mobile.chart_cache.get((symbol,frame),{})
            tail = [list(b) for b in cached.get('bars',[])[-2:]]
            candle_ms = cached.get('observed_ms')
            candle_error = cached.get('error')
        q = self.stream.read(symbol,'tickers',3,now)
        quote, fresh = None, False
        if q:
            try:
                price, stamp = float(q['last']), int(q['ts'])
                fresh = math.isfinite(price) and price > 0 and -500 <= now-stamp <= 3000
                if fresh: quote = dict(last=price,ts=stamp)
            except (ValueError,KeyError,TypeError,OverflowError):pass
        if fresh and tail:
            last = tail[-1]
            step = STEPS[frame];offset = 345600000 if frame=='1W' else 0
            start = (quote['ts']-offset)//step*step+offset
            if last[0] == start and not last[6]:
                # Reuse all-tick extremes for frames already collected by the
                # public stream. Other frames retain REST + observed last price.
                last = self.stream.band_bar(symbol,frame,last)
                last[2] = max(last[2],quote['last']);last[3] = min(last[3],quote['last'])
                last[4] = quote['last'];tail[-1] = last
        return dict(symbol=symbol,frame=frame,server_ms=now,quote=quote,live=fresh,
                    bars=tail,candle_ms=candle_ms,candle_error=candle_error)

    def serve(self, handler, symbol, frame, streaming):
        self.select(symbol,frame)
        if not streaming:
            handler.reply(200,self.packet(symbol,frame));return
        if not self.slots.acquire(blocking=False):
            handler.reply(429,{'error':'차트 연결 수 초과 · 잠시 후 재연결'});return
        try:
            handler.send_response(200)
            for key,value in [('Content-Type','text/event-stream; charset=utf-8'),
                              ('Cache-Control','no-store'),('X-Accel-Buffering','no'),
                              ('X-Content-Type-Options','nosniff'),('Connection','close')]:
                handler.send_header(key,value)
            handler.end_headers();handler.close_connection=True
            deadline=time.monotonic()+25
            while not self.mobile.closed.is_set() and time.monotonic()<deadline:
                if not handler.authorized():break
                packet=self.packet(symbol,frame)
                raw=json.dumps(packet,ensure_ascii=False,allow_nan=False,separators=(',',':'))
                handler.wfile.write(('data: '+raw+'\n\n').encode());handler.wfile.flush()
                self.mobile.closed.wait(.25)
        except (BrokenPipeError,ConnectionError,TimeoutError,OSError):
            pass
        finally:self.slots.release()

    def close(self):
        if self.owns_stream:self.stream.stop()


def accept(mobile, data):
    """A REST timeout must not erase an already displayed chart."""
    key=(data['symbol'],data['frame'])
    with mobile.lock:
        previous=mobile.chart_cache.get(key)
        if not data.get('bars') and previous and previous.get('bars'):
            data=dict(previous,stale=True,error=data.get('error') or '봉 조회 대기')
        mobile.chart_cache[key]=copy.deepcopy(data)


def bind(mobile, engine=None):
    if engine is not None:
        mobile.live_chart=LiveChart(mobile,engine.stream,engine.api.now_ms)
    else:
        from okx_stream import MarketStream
        stream=MarketStream();stream.start()
        mobile.live_chart=LiveChart(mobile,stream,owns_stream=True)
