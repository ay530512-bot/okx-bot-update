"""Reconcile confirmed external reductions on the serialized order worker.

Never adopt a new/increased/reopened position. A matching posId alone is not
ownership evidence: OKX can reuse it after a complete close. Replay the fill
history from the recorded entry, then protect the independently observed
remainder. Existing stops stay live until replacement protection is verified.
"""
import copy
import hashlib
import inspect
import json
from pathlib import Path
import textwrap
import time
import uuid

STATE = 'external_reduction167'


def number(value):
    from decimal import Decimal
    x = Decimal(str(value))
    if not x.is_finite():
        raise ValueError('수량·가격 수치 확인 필요')
    return x


def records(journal):
    return [r for r in [journal.get('owned'), journal.get('extra_owned'),
                       *journal.get('additional_owned', [])] if r]


def matching(record, snapshot):
    rows = [p for p in snapshot['positions'] if
            (p.get('instId'), p.get('posSide')) == (record['symbol'], record['direction'])
            and number(p.get('pos') or 0) != 0]
    if len(rows) > 1:
        raise ValueError('동일 방향 포지션 중복 확인 필요')
    return rows[0] if rows else None


def identity(record, position):
    from phone_handover import entry_average
    if (not record.get('posId') or position.get('posId') != record['posId']
            or position.get('mgnMode') != 'isolated'
            or number(position.get('lever')) != number(record['leverage'])
            or number(position.get('avgPx')) != entry_average(record)):
        raise ValueError('포지션 식별·방향·배율·평균가 변경: 잔량 인계 보류')


def fill_proof(api, record, position, snapshot_ms):
    """GET-only proof of an uninterrupted original position, including closes.

    Fill history is requested only when actual quantity decreased. Pagination
    must finish; absent/truncated/conflicting history never counts as proof.
    No assumption that posId changes on a close/reopen, or that ACK is a fill.
    """
    identity(record, position)
    before, after = number(record['quantity']), number(position['pos'])
    if not 0 < after < before:
        raise ValueError('부분청산 잔량 범위 확인 필요')
    start, end = int(record['entry_ms']), int(snapshot_ms)
    if not 0 < start <= end:
        raise ValueError('진입·조회 시각 확인 필요')
    rows, cursor, seen_pages = [], None, set()
    for _ in range(20):
        params = dict(instType='SWAP', instId=record['symbol'], begin=str(start),
                      end=str(end), limit='100')
        if cursor is not None:
            params['after'] = cursor
        page = api.get('/api/v5/trade/fills-history', **params)
        if not isinstance(page, list):
            raise ValueError('체결 내역 응답 형식 확인 필요')
        rows.extend(page)
        if len(page) < 100:
            break
        cursor = str(page[-1].get('billId') or '')
        if not cursor or cursor in seen_pages:
            raise ValueError('체결 내역 페이지 불완전: 잔량 인계 대기')
        seen_pages.add(cursor)
    else:
        raise ValueError('체결 내역 조회 범위 초과: 잔량 인계 대기')
    unique = {}
    for row in rows:
        if row.get('instId') != record['symbol'] or row.get('posSide') != record['direction']:
            continue
        at = int(row.get('fillTime') or 0)
        if not start <= at <= end:
            continue
        key = str(row.get('billId') or '')
        if not key:
            raise ValueError('체결 식별자 누락: 잔량 인계 대기')
        if key in unique and unique[key] != row:
            raise ValueError('서로 다른 중복 체결 내역')
        unique[key] = row
    ordered = sorted(unique.values(), key=lambda r: (int(r['fillTime']), int(r['billId'])))
    opening = 'buy' if record['direction'] == 'long' else 'sell'
    balance = number(0)
    peak = number(0)
    closed = number(0)
    opens = 0
    for row in ordered:
        quantity = number(row['fillSz'])
        if quantity <= 0 or row.get('side') not in ('buy', 'sell'):
            raise ValueError('체결 수량·방향 확인 필요')
        if row['side'] == opening:
            if row.get('clOrdId') != record['client_id'] or closed:
                raise ValueError('추가 진입 또는 재진입 발견: 원래 포지션으로 인수하지 않음')
            balance += quantity
            opens += 1
            peak = max(peak, balance)
        else:
            if not opens or quantity >= balance:
                raise ValueError('전량 청산·재진입 또는 체결 누락: 잔량 인계 보류')
            balance -= quantity
            closed += quantity
    if not opens or peak < before or balance != after:
        raise ValueError('체결 합계와 실제 잔량 대조 대기')
    return dict(before=str(before), after=str(after), opened=str(peak),
                closed=str(closed), snapshot_ms=end, fills=len(ordered),
                fill_digest=hashlib.sha256(json.dumps(ordered, sort_keys=True).encode()).hexdigest())


def reduction_proofs(api, journal, snapshot):
    out = {}
    for record in records(journal):
        p = matching(record, snapshot)
        if p and 0 < number(p['pos']) < number(record['quantity']):
            if record.get('phase') != 'active' or record.get('pending_add'):
                raise ValueError('주문·손절 변경 처리 중: 인계 대기')
            out[record['client_id']] = fill_proof(api, record, p, snapshot['ms'])
    return out


def prepare(engine, record, p, proof):
    """Persist a replacement intention; never place an order in snapshot()."""
    from okx_core import fmt
    from okx_scale import legs_for
    from okx_profit_guard714 import effective_stop
    before, after = number(record['quantity']), number(p['pos'])
    old = {leg['algo_client_id']: copy.deepcopy(leg) for leg in
           legs_for(record) + record.get('cleanup_legs', [])}
    targets = [number(effective_stop(record)), number(record['stop_px']),
               *(number(leg['stop_px']) for leg in old.values())]
    if record.get('target_stop_px'):
        targets.append(number(record['target_stop_px']))
    target = max(targets) if record['direction'] == 'long' else min(targets)
    if target <= 0:
        raise ValueError('기존 보호 가격 확인 필요')
    event = dict(proof, event_id='XR'+uuid.uuid4().hex[:28],
                 remaining=str(after), removed=str(before-after),
                 observed_ms=int(proof['snapshot_ms']))
    state = dict(event, request_sent=False)
    record['manual_reductions167'] = (record.get('manual_reductions167', [])+[event])[-50:]
    # A manual size reduction is not evidence that the automatic profit target
    # was hit. Keep that distinction while suppressing a second automatic half.
    record.setdefault('external_partial_only167', not bool(record.get('partial_used')))
    record[STATE] = state
    record['cleanup_legs'] = list(old.values())
    record['quantity'] = fmt(after)
    if record.get('committed_margin') is not None:
        record['committed_margin'] = fmt(number(record['committed_margin'])*after/before)
    record['partial'] = dict(client_id=event['event_id'], quantity=fmt(before-after),
        filled=fmt(before-after), before=fmt(before), started_ms=proof['snapshot_ms'],
        reason='수동 부분청산 확인 · 잔량 자동 관리', avg_px='미확인')
    record['legs'] = [dict(algo_client_id='OS'+uuid.uuid4().hex[:28],
                          quantity=fmt(after), stop_px=fmt(target))]
    record.update(phase='resizing', partial_used=True, protection_verified=False,
                  resize_started_ms=engine.api.now_ms())
    record.pop('target_stop_px', None)
    # No pre-manual-reduction funding observation exists. Use the existing
    # conservative remaining-cost fallback instead of inventing a funding split.
    record['long_wick_partial_cost732'] = {}
    engine.journal.save()
    engine.log(record['symbol']+' / 수동 부분청산 '+fmt(before-after)+
               '계약 확인 · 잔량 '+fmt(after)+'계약 보호 대조 중')


def synchronize(engine, snapshot):
    errors = {}
    for record in records(engine.journal.data):
        p = matching(record, snapshot)
        if not p or not 0 < number(p['pos']) < number(record['quantity']):
            continue
        phase = record.get('phase')
        if phase not in ('active', 'protecting', 'resizing', 'partial_closing'):
            continue
        if record.get('pending_add'):
            continue
        if phase == 'partial_closing':
            partial = record['partial']
            order = engine.api.get('/api/v5/trade/order', instId=record['symbol'],
                                   clOrdId=partial['client_id'])[0]
            if order.get('state') not in ('filled', 'canceled'):
                continue
            expected = number(partial['before'])-number(order.get('accFillSz') or 0)
            if number(p['pos']) >= expected:
                continue  # Existing bot partial-close reconciler owns this case.
        key = (record['client_id'], str(p['pos']))
        waits = getattr(engine, '_external_reduction_waits167', {})
        if time.monotonic() < waits.get(key, 0):
            errors[record['client_id']] = '수동 부분청산 체결·잔량 재대조 대기'
            continue
        try:
            proof = fill_proof(engine.api, record, p, snapshot['ms'])
            prepare(engine, record, p, proof)
            waits.pop(key, None)
        except Exception as error:
            waits[key] = time.monotonic()+3
            engine._external_reduction_waits167 = dict(list(waits.items())[-20:])
            message = str(error) if isinstance(error, ValueError) else '체결 조회 지연: 잔량 보호 대조 대기'
            errors[record['client_id']] = message
            engine.log(record['symbol']+' / '+message)
    engine._manual_reduction_errors167 = errors


def send_protection(engine, snapshot, record):
    from okx_core import Rejected
    p = matching(record, snapshot)
    if not p:
        return
    state = record[STATE]
    if state['request_sent']:
        return
    leg = record['legs'][0]
    side = 1 if record['direction'] == 'long' else -1
    if (number(p['markPx'])-number(leg['stop_px']))*side <= 0:
        engine.close(snapshot, '수동 부분청산 잔량: 기존 보호선 도달')
        return
    state['request_sent'] = True
    record['resize_started_ms'] = engine.api.now_ms()
    engine.journal.save()  # An unknown POST result is reconciled, never resent.
    try:
        engine.api.post('/api/v5/trade/order-algo', dict(instId=record['symbol'],
            tdMode='isolated', posSide=record['direction'], side='sell' if side==1 else 'buy',
            ordType='conditional', sz=record['quantity'], algoClOrdId=leg['algo_client_id'],
            slTriggerPx=leg['stop_px'], slTriggerPxType='mark', slOrdPx='-1'))
    except Rejected:
        state['rejected'] = True
        engine.journal.save()
        engine.close(snapshot, '수동 부분청산 잔량 보호 등록 거절')


def install(source):
    from okx_engine import Engine
    from okx_v5 import RuleEngine
    from okx_portfolio import PortfolioEngine
    if getattr(Engine.snapshot, '_manual_reduction167', False):
        return
    pins = json.loads(Path(__file__).with_name('phone_sources.json').read_text())['files']
    for name in ('okx_engine.py', 'okx_v5.py', 'okx_partial.py', 'okx_portfolio.py',
                 'okx_profit_guard714.py'):
        if hashlib.sha256((Path(source)/name).read_bytes()).hexdigest() != pins[name]:
            raise ValueError('잔량 관리 원본 확인 실패: '+name)
    # An unresolved reduction blocks that slot's existing strict checks and all
    # new entries, but must not abort the portfolio BEFORE other slots are run.
    fn = PortfolioEngine.snapshot
    raw = textwrap.dedent(inspect.getsource(fn))
    anchor = 'owned_position(record,[p])'
    if raw.count(anchor) != 1:
        raise ValueError('포트폴리오 잔량 대조 위치 확인 실패')
    raw = raw.replace(anchor, "if record.get('client_id') not in getattr(self, '_manual_reduction_errors167', {}):\n            "+anchor)
    namespace = dict(fn.__globals__)
    # The original uses zero-argument super(), whose __class__ closure is not
    # present in a compiled standalone method.
    raw = raw.replace('super().snapshot()', 'Engine.snapshot(self)')
    exec(compile(raw, str(Path(source)/'okx_portfolio.py'), 'exec'), namespace)
    PortfolioEngine.snapshot = namespace['snapshot']
    original_snapshot, original_reconcile, original_entry = Engine.snapshot, RuleEngine.reconcile, RuleEngine.entry
    original_close = RuleEngine.close
    def snapshot(self):
        value = original_snapshot(self)
        synchronize(self, value)
        return value
    snapshot._manual_reduction167 = True
    Engine.snapshot = snapshot
    def reconcile(self, snap):
        record = self.journal.data.get('owned')
        if record and record.get(STATE) and record.get('phase') == 'resizing':
            send_protection(self, snap, record)
        result = original_reconcile(self, snap)
        record = self.journal.data.get('owned')
        if record and record.get(STATE) and record.get('phase') == 'active':
            record[STATE]['completed_ms'] = self.api.now_ms()
            record['last_manual_reduction167'] = record.pop(STATE)
            self.journal.save()
            self.log(record['symbol']+' / 잔량 '+record['quantity']+
                     '계약 보호 확인 · 원래 규칙으로 자동 관리 계속')
        return result
    RuleEngine.reconcile = reconcile
    def entry(self, *args, **kwargs):
        from okx_core import BotError
        if getattr(self, '_manual_reduction_errors167', {}):
            raise BotError('수동 부분청산 잔량 대조 중: 신규 진입 대기')
        return original_entry(self, *args, **kwargs)
    RuleEngine.entry = entry
    def close(self, snap, reason, end_day=False):
        record = self.journal.data.get('owned')
        if record and record.get(STATE) and record.get('phase') == 'resizing':
            # Unlike a pending partial market order, this decrease is already
            # confirmed. A risk/user full-close must not wait for SL resizing.
            record['phase'] = 'active'
            self.journal.save()
        return original_close(self, snap, reason, end_day)
    RuleEngine.close = close
    import okx_profit_guard714 as guard
    original_desired_stop = guard.desired_stop
    def desired_stop(owned, *args, **kwargs):
        if owned.get('external_partial_only167'):
            # Preserve actual observed profit latches/peaks and tighter stops.
            # Only remove the synthetic implication "manual reduction = TP".
            owned = dict(owned, partial_used=False)
        return original_desired_stop(owned, *args, **kwargs)
    guard.desired_stop = desired_stop
