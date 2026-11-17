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
