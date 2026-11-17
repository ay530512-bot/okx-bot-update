"""Read-only display of received private account data, independent of engine work.

No order, account freshness, risk, sizing or reconciliation inputs are changed.
The original private feed runs first; this observer never swallows its errors.
"""
import copy
from decimal import Decimal, InvalidOperation
import json
import threading
import time


def number(value):
    try:
        n = Decimal(str(value))
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def install_projection():
    import okx_dashboard_data as module
    original = module.dashboard_snapshot
    if getattr(original, '_phone_live_basis', False): return
    def dashboard(snapshot, records, day, *args, **kwargs):
        out = original(snapshot, records, day, *args, **kwargs)
        # Keep equity and its PnL baseline in the same published observation.
        out.update(equity=str(snapshot['equity']), available=str(snapshot['available']),
            display_basis=dict(snapshot_ms=snapshot['ms'], day={k:day[k]
                for k in ('date','base','start_equity','baseline_source','flow_status',
                          'display_available_base','display_available_ms') if k in (day or {})}))
        return out
    dashboard._phone_live_basis = True
    module.dashboard_snapshot = dashboard


class PrivateDisplay:
    def __init__(self, stream, clock):
        self.stream, self.clock = stream, clock
        self.lock = threading.Lock()
        self.account = None
        self.positions = {}
        self.errors = 0
        original = stream.feed
        def feed(message):
            result = original(message)
            try: self.observe(message)
            except Exception: self.errors += 1
            return result
        stream.feed = feed

    def observe(self, message):
        if message == 'pong': return
        obj = json.loads(message)
        channel = obj.get('arg', {}).get('channel')
        if channel not in ('account','positions'): return
        now, mono, generation = self.clock(), time.monotonic(), self.stream.generation
        for row in obj.get('data', []):
            if channel == 'account':
                for detail in row.get('details', []):
                    if detail.get('ccy') != 'USDT': continue
                    eq, available = number(detail.get('eq')), number(detail.get('availBal'))
                    if eq is None: continue
                    stamp = int(detail.get('uTime') or row.get('uTime') or now)
                    item = dict(equity=str(eq), available=str(available) if available is not None else None,
                                stamp=stamp, received_ms=now, mono=mono, generation=generation)
                    with self.lock:
                        old = self.account
                        if old and old['generation']==generation and stamp<old['stamp']: continue
                        self.account = item
            elif row.get('instType') == 'SWAP' and str(row.get('instId','')).endswith('-USDT-SWAP'):
                allowed = ('instId','posSide','pos','avgPx','markPx','uplRatio','upl','margin','imr','uTime')
                clean = {k:row.get(k) for k in allowed}
                key = (clean['instId'],clean['posSide'])
                if key[1] not in ('long','short'): continue
                stamp = int(row.get('uTime') or now)
                with self.lock:
                    old = self.positions.get(key)
                    if old and old['generation']==generation and stamp<old['stamp']: continue
                    self.positions[key] = dict(row=clean, stamp=stamp, received_ms=now, mono=mono, generation=generation)
                    self.positions = {k:v for k,v in self.positions.items() if mono-v['mono']<120 and v['generation']==generation}
                    while len(self.positions)>256: self.positions.pop(next(iter(self.positions)))

    def project(self, data, basis, now):
        from okx_live_display732 import apply_position
        from okx_daily_goal728 import daily_goal
        from okx_core import day_key
        mono = time.monotonic()
        generation, connected = self.stream.generation, self.stream.connected
        with self.lock:
            account = self.account
            positions = dict(self.positions)
        def fresh(item):
            return bool(connected and item and item['generation']==generation
                        and 0<=mono-item['mono']<=5 and -500<=now-item['received_ms']<=5000)
        meta = dict(account_live=False, position_updates=0, connected=bool(connected),
                    received_ms=None, observation_errors=self.errors)
        state = data.get('state') or {}
        data['state'] = state
        baseline_at = basis.get('snapshot_ms',0) or 0
        if fresh(account) and account['received_ms']>=baseline_at:
            state['equity'] = account['equity']
            if account['available'] is not None: state['available'] = account['available']
            day = basis.get('day') or {}
            base = number(day.get('base'))
            if day.get('date')==day_key(now) and base is not None:
                state['day_profit'] = str(number(account['equity'])-base)
                goal = state.get('daily_goal') or {}
                if goal.get('date')==day['date'] and goal.get('ai_cost') is not None:
                    state['daily_goal'] = daily_goal(day,account['equity'],goal['ai_cost'],day_key(now))
            else:
                state['day_profit'] = None
            meta.update(account_live=True, received_ms=account['received_ms'])
        for p in data.get('positions') or []:
            item = positions.get((p.get('symbol'),p.get('direction')))
            if not fresh(item) or item['received_ms']<baseline_at: continue
            row = item['row']
            if number(row.get('pos'))!=number(p.get('quantity')) or number(row.get('avgPx'))!=number(p.get('entry')):
                p['live_note'] = '수량·진입가 변경 확인 중'
                continue
            if apply_position([p],dict(row=row,received_ms=item['received_ms']),now):
                # Exchange fields, never PnL inferred from a public last price.
                margin = number(row.get('margin'))
                if margin is not None and margin>=0 and p.get('margin_basis')=='거래소 포지션 증거금': p['margin']=str(margin)
                meta['position_updates'] += 1
        data['account_live'] = meta


class Dashboard:
    FIELDS = ('ui_version','state','positions','movers','entry_gate','controls_enabled',
              'status','captured_ms','account_age_seconds')
    def __init__(self, mobile, engine=None):
        self.mobile = mobile
        self.clock = engine.api.now_ms if engine else lambda:int(time.time()*1000)
        self.private = PrivateDisplay(engine.account_stream,self.clock) if engine else None
        self.slots = threading.BoundedSemaphore(4)

    def snapshot(self, full=False, part='home'):
        if part not in ('home','market','chart','settings'): raise ValueError('화면 오류')
        with self.mobile.lock:
            original = self.mobile.snapshot
            data = copy.deepcopy(original if full else {k:original.get(k) for k in self.FIELDS})
            if not full and part=='market': data['futures']=copy.deepcopy(original.get('futures'))
            basis = copy.deepcopy(getattr(self.mobile,'display_basis',{}))
        now = self.clock()
        if self.private: self.private.project(data,basis,now)
        from phone_home_assets import profit_basis
        data['profit_basis'] = profit_basis(data.get('state') or {}, basis, now)
        assets = getattr(self.mobile, 'home_assets', None)
        if assets: data['home_assets'] = assets.snapshot()
        data['display_ms'] = now
        return data

    def serve(self, handler, part, streaming):
        if not streaming:
            handler.reply(200,self.snapshot(part=part));return
        if part not in ('home','market','chart','settings'): raise ValueError('화면 오류')
        if not self.slots.acquire(blocking=False):
            handler.reply(429,{'error':'화면 연결 수 초과 · 재연결 대기'});return
        try:
            handler.send_response(200)
            for key,value in [('Content-Type','text/event-stream; charset=utf-8'),
                              ('Cache-Control','no-store'),('X-Accel-Buffering','no'),
                              ('X-Content-Type-Options','nosniff'),('Connection','close')]:
                handler.send_header(key,value)
            handler.end_headers();handler.close_connection=True
            deadline=time.monotonic()+25
            previous={}
            while not self.mobile.closed.is_set() and time.monotonic()<deadline:
                if not handler.authorized(): break
                current=self.snapshot(part=part)
                delta={}
                for key,value in current.items():
                    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
                    if raw!=previous.get(key): delta[key]=value;previous[key]=raw
                raw=json.dumps(delta,ensure_ascii=False,allow_nan=False,separators=(',',':'))
                handler.wfile.write(('data: '+raw+'\nretry: 500\n\n').encode());handler.wfile.flush()
                self.mobile.closed.wait(.25)
        except (BrokenPipeError,ConnectionError,TimeoutError,OSError): pass
        finally: self.slots.release()


def bind(mobile, engine=None, keys=None):
    install_projection()
    from phone_home_assets import install_basis, HomeAssets
    if engine: install_basis(engine)
    if keys:
        mobile.home_assets = HomeAssets(keys, mobile.closed)
        mobile.home_assets.start()
    mobile.live_dashboard=Dashboard(mobile,engine)
