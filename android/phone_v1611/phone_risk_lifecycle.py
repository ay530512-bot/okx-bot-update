"""Retire risk callbacks only after the original confirmed-close cleanup succeeds.

WS callbacks can still hold an old guard row after finish_position returns.
An orphan queued_risks marker previously blocked recovery and updates forever.
No active risk, operator pause, entry predicate or broker request is bypassed.
"""
from collections import deque
import hashlib
import json
from pathlib import Path
import queue
import time


def take_risk(engine):
    """Persist an existing close decision at the exact consumption point.

    A later reconcile exception must not lose the reason while leaving its
    queued marker latched. A failed journal write puts the request back.
    This runs on the serialized engine thread, never the WS callback.
    """
    item = engine.risk_queue.get_nowait()
    identity, reason = item
    try:
        owned = next((r for r in engine.records() if r.get('client_id') == identity), None)
        if owned:
            if not owned.get('close_requested'):
                owned['close_requested'] = reason
            engine.journal.save()
        return item
    except Exception:
        engine.risk_queue.put(item)
        raise


def scan_watch(engine):
    last = (getattr(engine, 'phone_entry_diagnostic', {}) or {}).get('observed_at')
    age = round(max(0, time.time()-last), 1) if last else None
    if getattr(engine, 'user_paused', True): state = '사용자 중지'
    elif not getattr(engine, 'enabled', False): state = '운용 재개 대기'
    elif getattr(engine, 'recovering', True): state = '계정·보호 복구 대조'
    elif getattr(engine, 'queued_risks', ()): state = '보호 청산 처리 중'
    elif engine.entry_cancel.is_set(): state = '신규 진입 차단 · 대조 대기'
    elif (engine.journal.data.get('day') or {}).get('ended'): state = '당일 운용 한도 도달'
    elif not engine.can_open_position(): state = '포지션 한도 사용 중'
    elif age is None: state = '첫 검사 대기'
    elif age > 120: state = '검사 지연 · 차단 원인 확인 필요'
    else: state = '신규 진입 검사 진행'
    return dict(status=state, last_scan_age_s=age,
                run_requested=bool(getattr(engine, 'run_requested', False)))


def diagnostics(engine):
    if not hasattr(engine, 'risk_lock'):
        return {}
    with engine.risk_lock:
        pending = len(engine.queued_risks)
        queued = engine.risk_queue.qsize()
        ignored = getattr(engine, '_retired_callbacks169', 0)
    return dict(pending_risks=pending, queued_risk_events=queued,
                retired_callbacks=ignored,
                resume_reason=str(getattr(engine, 'resume_reason', '') or '')[:160])


def install(source):
    from okx_v5 import RuleEngine
    if getattr(RuleEngine.queue_risk, '_risk_lifecycle169', False):
        return
    pins = json.loads(Path(__file__).with_name('phone_sources.json').read_text())['files']
    for name in ('okx_v5.py', 'okx_engine.py', 'okx_portfolio.py'):
        if hashlib.sha256((Path(source)/name).read_bytes()).hexdigest() != pins[name]:
            raise ValueError('보호 요청 종료 처리 원본 확인 실패: '+name)
    finish = RuleEngine.finish_position

    def queue_risk(self, identity, reason):
        with self.risk_lock:
            if identity in getattr(self, '_retired_risks169', ()):
                self._retired_callbacks169 = getattr(self, '_retired_callbacks169', 0)+1
                return
            if identity not in self.queued_risks:
                self.queued_risks.add(identity)
                self.entry_cancel.set()
                self.risk_queue.put((identity, reason))
        self.command_wake.set()
    queue_risk._risk_lifecycle169 = True

    def finish_position(self):
        owned = self.journal.data.get('owned')
        identity = owned.get('client_id') if owned else None
        with self.risk_lock:
            pending = identity in self.queued_risks
        try:
            result = finish(self)
        except Exception:
            # The original discards its marker before fallible SL cleanup.
            # Failed cleanup must not advertise a completed protection request.
            if pending:
                with self.risk_lock:
                    self.queued_risks.add(identity)
                    self.entry_cancel.set()
            raise
        if identity and not any(r.get('client_id') == identity for r in self.records()):
            with self.risk_lock:
                retired = getattr(self, '_retired_risks169', None)
                if retired is None:
                    retired = self._retired_risks169 = deque(maxlen=1024)
                if identity not in retired:
                    retired.append(identity)
                self.queued_risks.discard(identity)
                # The engine thread is the only consumer; producers share this
                # lock. Keep every other position's event and its original order.
                keep = []
                while True:
                    try:
                        item = self.risk_queue.get_nowait()
                    except queue.Empty:
                        break
                    if item[0] != identity:
                        keep.append(item)
                for item in keep:
                    self.risk_queue.put(item)
                self.guard_rows = tuple(r for r in self.guard_rows if r['client_id'] != identity)
        # Do not clear entry_cancel: normal account/SL recovery owns that gate.
        return result

    RuleEngine.queue_risk = queue_risk
    RuleEngine.finish_position = finish_position
