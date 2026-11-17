"""Bounded per-signal observations. No I/O, orders, signal or clock mutations.
A first observation after expiry is not proof that a tradable signal was missed.
"""
from collections import OrderedDict
import copy
import threading

LABELS = {
 'pattern': '봉 조건 통과 · 진입 검사 전',
 'valid': '유효시간 내 후보 생성',
 'market_wait': '실시간 시세 준비 대기',
 'market_ready': '시세 준비 완료 · 주문 재검사 전',
 'validation_rejected': '후보 재검사에서 보류',
 'construction_rejected': '신호 생성 검사에서 보류',
 'admission': '주문 전 검사로 전달 · 체결 확인 아님',
 'expired_wait': '유효시간 내 확인했으나 전달 전 만료',
 'expired_rejected': '후보 검사 보류 후 90초 만료',
 'first_seen_expired': '첫 관측부터 90초 경과 · 진입 불가',
}


class Journey:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = OrderedDict()
        self.errors = 0

    def record(self, symbol, confirmation, action, now, stage, **extra):
        confirmation, now = int(confirmation), int(now)
        start = confirmation + 900000
        key = (symbol, action, confirmation)
        with self.lock:
            row = self.rows.get(key)
            if row is None:
                row = dict(symbol=symbol, action=action, confirmation_ms=confirmation,
                    valid_from_ms=start, expires_ms=start+90000, first_seen_ms=now,
                    first_delay_s=round((now-start)/1000, 3),
                    first_seen_expired=now>start+90000, ever_valid=False,
                    admission_count=0, stage='pattern')
                self.rows[key] = row
                if len(self.rows)>1024:
                    self.rows.popitem(last=False)
            row['last_seen_ms'] = now
            if stage == 'valid':
                row['ever_valid'] = True
            if stage == 'admission':
                row['admission_count'] += 1
                row['admission_at_ms'] = now
            # Repeated pattern detections must not erase the last useful gate.
            if stage not in ('pattern', 'valid') or row['stage'] in ('pattern', 'valid'):
                row['stage'] = stage
            if stage == 'market_wait':
                row.setdefault('first_market_wait_ms', now)
                row['last_market_wait_ms'] = now
            if stage == 'market_ready':
                row.setdefault('first_market_ready_ms', now)
            if stage == 'validation_rejected':
                row['last_rejected_ms'] = now
            if row.get('timing') and extra.get('timing'):
                extra.pop('timing')  # Keep the first observation's input timeline.
            row.update(extra)

    def report(self, now):
        with self.lock:
            retained = len(self.rows)
            late = sum(r["first_seen_expired"] for r in self.rows.values())
            rows = copy.deepcopy(list(self.rows.values())[-8:])
            errors = self.errors
        for row in rows:
            row['last_gate'] = row['stage']
            row['expired'] = now > row['expires_ms']
            if row['first_seen_expired']:
                row['stage'] = 'first_seen_expired'
            elif now > row['expires_ms'] and not row['admission_count']:
                row['stage'] = 'expired_rejected' if row['stage'] in ('validation_rejected','construction_rejected') else 'expired_wait'
            row['stage_label'] = LABELS[row['stage']]
        return dict(unique_observed=retained, first_seen_expired=late,
                    retained=retained, rows=rows[::-1], errors=errors)


def record(e, symbol, confirmation, action, now, stage, **extra):
    # Diagnostics must never alter original exception handling or decisions.
    try:
        journey = getattr(e, '_phone_journey137', None)
        if journey is None:
            journey = Journey()
            e._phone_journey137 = journey
        journey.record(symbol, confirmation, action, now, stage, **extra)
    except Exception:
        journey = getattr(e, '_phone_journey137', None)
        if journey is not None:
            journey.errors += 1


def signal(e, s, now, stage, **extra):
    if not isinstance(s, dict) or 'valid_from_ms' not in s:
        return
    try:
        record(e, s['symbol'], s['valid_from_ms']-900000, s['action'], now, stage,
               route=s.get('pattern','unknown'),
               signal_mode=(s.get('decision_record',{}).get('volume_wick_proof') or {}).get('mode'), **extra)
    except (KeyError, TypeError, ValueError):
        pass


def packet(e, p, symbol, now, **extra):
    try:
        for v in p.get('entry_setups', []):
            record(e, symbol, v['confirmation_ms'], v['action'], now, 'pattern',
                   route=v.get('route721', 'unknown'), **extra)
    except (KeyError, TypeError, ValueError):
        pass


def market_wait(e, symbol, s, now):
    try:
        from phone_entry_feed import quote_details
        detail = quote_details(e, symbol)
        signal(e, s, now, 'market_wait', last_market=detail)
    except Exception:
        pass
