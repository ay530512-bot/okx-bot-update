"""Single mobile candidate owner; pure work is polled without blocking orders.

No strategy threshold, sizing, protective order or financial write is defined
here. Every returned candidate still uses the original REST admission checks.
"""
import time
from pathlib import Path
import phone_entry_journey as journey
import phone_similar_candidates as similar
from phone_entry_diagnostics import accumulate


def rejection(error):
    for text, label in (
        ('최신 완료봉 대기','최신 확정봉 대기'), ('완료봉 자료 부족','봉 자료 부족'),
        ('봉 수치 오류','봉 수치 오류'), ('봉 연속성 오류','봉 간격 오류'),
        ('90초 만료','90초 만료'), ('신호 만료','90초 만료'),
        ('손절 유효성','가격·손절 범위'), ('초기SL 도달','대기 중 손절선 도달'),
        ('원래 완료봉 신호 변경','원래 신호 변경'), ('진입 경로 변경','진입 경로 변경')):
        if text in str(error): return label
    return '자료·신호 검사 거절'


class Coordinator:
    def __init__(self, channel, timer):
        self.channel = channel
        self.timer = timer

    def __call__(self, e):
        started = time.perf_counter()
        d = dict(observed_at=time.time(), reasons={}, waiting=[])
        result = None
        try:
            result = self.evaluate(e, d)
            if result: journey.signal(e, result, e.api.now_ms(), 'admission')
            return result
        finally:
            d.update(duration_s=round(time.perf_counter()-started, 3),
                pending=len(getattr(e, 'channel_pending', {})), observed_at=time.time(),
                result='주문 전 최종 검사로 전달' if result else '진입 후보 대기',
                architecture='mobile140')
            old = getattr(e, 'phone_entry_totals', {})
            totals = dict(scans=old.get('scans', 0)+1,
                candidate_returns=old.get('candidate_returns', 0)+int(result is not None),
                reasons=dict(old.get('reasons', {})))
            for label, count in d['reasons'].items():
                totals['reasons'][label] = totals['reasons'].get(label, 0)+count
            e.phone_entry_totals = totals
            e.phone_entry_diagnostic = d

    @staticmethod
    def gate(d, label):
        d['reasons'][label] = d['reasons'].get(label, 0)+1

    def market_ready(self, e, s, d):
        now = e.api.now_ms()
        if not s['valid_from_ms'] <= now <= s['expires_ms']:
            self.gate(d, '90초 만료')
            return None
        if not e.stream.ready(s['symbol'], e.cfg, now):
            self.gate(d, '실시간 자료 대기')
            journey.market_wait(e, s['symbol'], s, now)
            if len(d['waiting']) < 4:
                d['waiting'].append(dict(symbol=s['symbol'], remaining_s=round((s['expires_ms']-now)/1000,1),
                    channels=e.stream.missing(s['symbol'], e.cfg, now)))
            return None
        q = e.stream.read(s['symbol'], 'tickers', 15, e.api.now_ms())
        if not q or not q.get('last'):
            self.gate(d, '최신 체결가 대기')
            return None
        journey.signal(e,s,e.api.now_ms(),'market_ready')
        return q

    def evaluate(self, e, d):
        from okx_core import BotError
        from okx_pattern15 import allowed
        from okx_channel4h730 import is_signal as retired
        import phone_trend_slot as trend
        import phone_morning_short as morning
        ch = self.channel
        reference, similarity_status = similar.anchor(e)
        packets = {}
        d['similarity'] = similar.view(reference, similarity_status, {}, {}, e.api.now_ms())
        if not hasattr(e, 'channel_pending'): e.channel_pending = {}
        held = {o['symbol'] for o in e.records()}
        manual = e.blocked_manual_symbols()
        seen = e.journal.data.get('seen_signals', {})
        now = e.api.now_ms()
        for symbol, s in list(e.channel_pending.items()):
            if (retired(s) or now > s['expires_ms'] or symbol in held or symbol in manual or
                    symbol+':'+s['signal_id'] in seen):
                if now > s['expires_ms']: self.gate(d, '90초 만료')
                e.channel_pending.pop(symbol, None)
        if not e.can_open_position():
            e.pipeline('holding', '포지션 개수 한도 · 신규 탐색 중지')
            return None
        # Jobs receive immutable market inputs, never this engine or account.
        self.timer.parallel.prepare(e)
        snapshot, _ = e.universe.read()
        rows = snapshot.get('rows', []) if snapshot else []
        checked = breakouts = 0
        for row in rows:
            symbol = row['symbol']
            if symbol in held or symbol in manual or not allowed(row['instrument'], e.cfg): continue
            try:
                p = self.timer.parallel.lookup(row, e.cfg, e.api.now_ms())
                if p is None:
                    self.gate(d, '모바일 계산 결과 대기')
                    continue
                checked += 1
                packets[symbol] = p
                accumulate(d, p, symbol)
                journey.packet(e, p, symbol, e.api.now_ms(),
                    timing=self.timer.parallel.timing(symbol))
                if not p['entry_setups']:
                    detail = p.get('entry_diagnostic', {})
                    self.gate(d, '기존·두꼬리 방향 충돌' if p.get('or_status') == 'conflict' else
                        '자료 대기: '+detail['data_issue'] if detail.get('data_issue') else '확정봉 규칙 조건 미충족')
                    if p.get('or_status') == 'conflict': e.channel_pending.pop(symbol, None)
                    continue
                breakouts += 1
                try:
                    s = ch.make_signal(dict(action=p['entry_setups'][0]['action']), p, e.cfg, e.api.now_ms())
                    similar.attach(s, p)
                except (BotError, ValueError, KeyError):
                    for v in p['entry_setups']:
                        journey.record(e, symbol, v['confirmation_ms'], v['action'], e.api.now_ms(), 'construction_rejected')
                    raise
                if float(row['instrument'].get('lever') or 0) < s['leverage']:
                    self.gate(d, '거래소 배율 한도'); continue
                if symbol+':'+s['signal_id'] in seen:
                    self.gate(d, '이미 처리한 신호'); continue
                e.channel_pending[symbol] = s
                journey.signal(e, s, e.api.now_ms(), 'valid')
            except (BotError, ValueError, KeyError) as error:
                self.gate(d, rejection(error))
        # One owner manages both candidate routes and their quote subscriptions.
        total, trends, commons = trend.slot_counts(e)
        s = trend.scan(e)
        short_signal = morning.scan(e)
        if short_signal:
            journey.signal(e, short_signal, e.api.now_ms(), 'valid',
                timing=getattr(e, 'phone_morning_timing', {}))
        if s: journey.signal(e, s, e.api.now_ms(), 'valid',
            timing=getattr(e,'phone_trend_timing',{}))
        s = short_signal or s  # Disjoint entry windows; original long scan is retained.
        if s:
            similar.attach(s, packets.get(s['symbol']))
            similar.capture_selected(s, rows)
        d['similarity'] = similar.view(reference, similarity_status, packets, e.channel_pending, e.api.now_ms())
        watches = list(e.channel_pending)+list(held)+e.chat.watch()+([s['symbol']] if s else [])
        if hasattr(e, 'phone_quote_registry'):
            e.phone_quote_registry.set_candidates(watches)
        else:
            e.stream.watch(watches)
        e.last_channel_scan = (e.api.now_ms(), len(rows), checked, breakouts, len(e.channel_pending))
        try:
            held_for_install = (Path(e.root).parent/'phone_trend_activation_hold').exists()
            if s and total < 4 and trends == 0 and not held_for_install:
                trend.require_slot(e, s)
                q = self.market_ready(e, s, d)
                if q:
                    ch.check_entry(e, s, q['last'])
                    e.pipeline('approved', s['reason'], count='signals')
                    return s
        except BotError as error:
            if morning.is_signal(s):
                e.phone_morning_status = str(error)
            else:
                e.phone_trend_status = str(error)
            journey.signal(e, s, e.api.now_ms(), 'validation_rejected', rejection=rejection(error))
            self.gate(d, rejection(error))
        if total >= 4 or commons >= 3:
            e.pipeline('signal_wait', '기존3자리 사용 중 · 추세1자리 조건 대기')
            return None
        for symbol, s in similar.ordered(e.channel_pending.items(), reference, ch.rank_item):
            q = self.market_ready(e, s, d)
            if not q: continue
            try:
                ch.check_entry(e, s, float(q['last']))
            except BotError as error:
                journey.signal(e, s, e.api.now_ms(), 'validation_rejected', rejection=rejection(error))
                self.gate(d, rejection(error)); e.channel_pending.pop(symbol, None)
                e.pipeline('signal_wait', symbol+' / '+str(error))
                continue
            e.band_focus = symbol
            e.events.put(('timeframes', dict(symbol=symbol,
                frames={f:x['analysis'] for f,x in s['decision_record']['frames'].items()})))
            e.pipeline('approved', symbol+' / '+s['reason']+' · AI 호출 없음', count='signals')
            return s
        e.pipeline('signal_wait', 'V7.32 15분봉 규칙 확인 대기 / 준비 신호 '+str(len(e.channel_pending))+'개 / AI 호출 없음')
        return None


def install(channel, timer):
    channel.candidate = Coordinator(channel, timer)

