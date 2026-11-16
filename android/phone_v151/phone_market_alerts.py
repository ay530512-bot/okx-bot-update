"""Read-only 15m move list from the bot's existing confirmed candle cache.

No network, notification, signal, order, or strategy calls. This is a local
reconstruction of the Telegram alert's displayed +/-10% open-to-close rule,
not a Telegram inbox mirror. Missing cached candles are explicitly uncovered.
"""
import json
import math
import re
import threading
import time
from decimal import Decimal
from pathlib import Path

STEP = 900000
DAY = 86400000
LIMIT = 100
SYMBOL = re.compile(r'[A-Z0-9]{1,32}-USDT-SWAP')


def candle_event(symbol, row, now):
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
        return None
    try:
        t, opening, high, low, close = row[:5]
        if type(t) is not int or t % STEP or not now-DAY <= t+STEP <= now:
            return None
        if not all(math.isfinite(float(x)) and float(x) > 0 for x in (opening, high, low, close)):
            return None
        if not low <= min(opening, close) <= max(opening, close) <= high:
            return None
        o, c = Decimal(str(opening)), Decimal(str(close))
        # Decimal makes exact +/-10% boundaries inclusive in both directions.
        if abs(c-o) < o*Decimal('.10'):
            return None
        return dict(id=symbol+':'+str(t), symbol=symbol, start_ms=t,
                    close_ms=t+STEP, opening=float(opening), close=float(close),
                    change_pct=float((c/o-1)*100), direction='up' if c>o else 'down')
    except (TypeError, ValueError, OverflowError, ArithmeticError):
        return None


class AlertFeed:
    def __init__(self, root, universe=None, clock=None):
        self.path=Path(root)/'phone_market_alerts.json'
        self.universe=universe
        self.clock=clock or (lambda:int(time.time()*1000))
        self.lock=threading.Lock();self.stop_event=threading.Event()
        self.items={};self.errors=0;self.save_errors=0;self.signature=None;self.seen={}
        self.summary=dict(items=[],checked_at_ms=None,coverage_fresh=0,coverage_total=0,
                          status='수신봉 검사 대기',source='confirmed_bot_cache',save_errors=0)
        try:
            if self.path.exists():
                if self.path.stat().st_size>262144:raise ValueError('size')
                now=self.clock()
                for x in json.loads(self.path.read_text()).get('items',[])[:LIMIT]:
                    # Revalidate persisted public fields, never trust arbitrary JSON.
                    o,c=x['opening'],x['close']
                    e=candle_event(x['symbol'],[x['start_ms'],o,max(o,c),min(o,c),c],now)
                    if e:self.items[e['id']]=e
        except Exception:
            self.errors+=1

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True,name='phone-move-list')
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if hasattr(self,'thread'):self.thread.join(timeout=1)

    def snapshot(self):
        with self.lock:
            return dict(self.summary,items=[dict(x) for x in self.summary['items']])

    def poll(self):
        market=getattr(self.universe,'full_market',None)
        if market is None:
            with self.lock:self.summary.update(status='자동매매 탐색기의 수신봉 대기')
            return
        # Copy just references while holding the scanner lock. Published bars
        # are immutable/replaced by the producer; no full history deep copy.
        with self.universe.lock:
            instruments=set(market.instruments)
            cached=[(s,value[1]) for (s,f),value in getattr(market,'band_cache',{}).items()
                    if f=='15m' and s in instruments]
        self.observe(cached,len(instruments),self.clock())

    def observe(self, cached, total, now):
        cutoff=now//STEP*STEP;fresh=set()
        seen={}
        for symbol,bars in cached:
            if any(row and type(row[0]) is int and row[0]+STEP==cutoff for row in bars[-2:]):fresh.add(symbol)
            if isinstance(bars,tuple):
                seen[symbol]=bars
                if self.seen.get(symbol) is bars:continue
            # At most 97 candles per symbol, and only on this background thread.
            for row in bars[-97:]:
                event=candle_event(symbol,row,now)
                if event:self.items[event['id']]=event
        self.seen=seen
        items=sorted((e for e in self.items.values() if now-DAY<=e['close_ms']<=now),
                     key=lambda e:(-e['close_ms'],e['symbol']))[:LIMIT]
        self.items={e['id']:e for e in items}
        text=json.dumps(dict(version=1,items=items),ensure_ascii=False,separators=(',',':'))
        if text!=self.signature:
            try:
                temp=self.path.with_suffix('.json.tmp');temp.write_text(text);temp.replace(self.path)
                self.signature=text
            except OSError:self.save_errors+=1
        summary=dict(items=items,checked_at_ms=now,latest_close_ms=cutoff,
                     coverage_fresh=len(fresh),coverage_total=total,save_errors=self.save_errors,
                     source='confirmed_bot_cache',status='검사 중' if total else '수신봉 대기')
        with self.lock:self.summary=summary

    def run(self):
        while not self.stop_event.is_set():
            try:self.poll()
            except Exception:
                self.errors+=1
                with self.lock:self.summary=dict(self.summary,status='수신봉 검사 지연')
            self.stop_event.wait(5)
