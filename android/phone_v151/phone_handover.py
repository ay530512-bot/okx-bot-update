"""Versioned, local update handover. No order/close/cancel endpoints.

The serial engine worker finishes its current action before checking handover.
Exchange SL orders remain live during the short process replacement. Local
trailing/profit management resumes in the replacement process, not during exit.
"""
import copy
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from decimal import Decimal

from phone_account import save_json
from phone_migrate import process_token

PROTOCOL = 1
REQUEST = 'phone_handover_request.json'
ACK = 'phone_handover_ack.json'
CANCEL = 'phone_handover_cancel.json'


@contextmanager
def commit_lock(root):
    path = root/'phone_handover_commit.lock'
    if path.is_symlink():
        raise ValueError('인계 잠금 링크 오류')
    with path.open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def load(path):
    if path.is_symlink():
        raise ValueError('업데이트 기록 링크 오류')
    return json.loads(path.read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def number(value):
    x = Decimal(str(value))
    if not x.is_finite():
        raise ValueError('유효하지 않은 거래소 수량/가격')
    return x


def records(journal):
    if journal.get('version') != 1 or 'owned' not in journal:
        raise ValueError('운용 기록 형식 확인 실패')
    return [r for r in [journal['owned'], journal.get('extra_owned'),
                       *journal.get('additional_owned', [])] if r]


def validate_protected(journal, snapshot, algos):
    """Strict read-only reconciliation; never call engine.verify_protection().

    Unknown/manual positions or orders defer handover; no adoption or cleanup.
    Return only stable ownership/protection facts, excluding changing prices/PnL.
    """
    cfg = snapshot['config']
    uid = cfg.get('uid')
    if (not uid or cfg.get('acctLv') != '2' or cfg.get('posMode') != 'long_short_mode'
            or hashlib.sha256(uid.encode()).hexdigest() != journal.get('account')):
        raise ValueError('계정/포지션 모드 인계 대조 실패')
    if snapshot['orders'] or journal.get('manual_closes716'):
        raise ValueError('체결/청산 처리 중 · 기존 관리 유지, 설치 보류')
    owned = records(journal)
    positions = [p for p in snapshot['positions'] if number(p.get('pos', '0')) != 0]
    if len(positions) != len(owned) or len({r['symbol'] for r in owned}) != len(owned):
        raise ValueError('보유 기록과 실제 포지션 수가 다릅니다.')
    seen = set()
    facts = []
    for r in owned:
        if (r.get('phase') != 'active' or any(r.get(k) for k in
                ('close_requested', 'pending_add', 'market_fill_check_pending', 'cleanup_legs'))):
            raise ValueError('진입/분할/손절 변경 처리 중 · 기존 관리 유지, 설치 보류')
        ps = [p for p in positions if p.get('instId') == r['symbol']
              and p.get('posSide') == r['direction'] and p.get('mgnMode') == 'isolated']
        if len(ps) != 1 or number(ps[0]['pos']) != number(r['quantity']) or number(r['quantity']) <= 0:
            raise ValueError('포지션 소유/수량 인계 대조 실패')
        p = ps[0]
        if number(p['avgPx']) != number(r['avg_px']):
            raise ValueError('진입 평균가 인계 대조 실패')
        legs = r.get('legs') or [dict(algo_client_id=r['algo_client_id'],
                                    quantity=r['quantity'], stop_px=r['stop_px'])]
        if sum((number(l['quantity']) for l in legs), Decimal(0)) != number(p['pos']):
            raise ValueError('분할 포지션 수량 대조 실패')
        stops = []
        for leg in legs:
            key = leg['algo_client_id']
            rows = [a for a in algos if a.get('algoClOrdId') == key]
            if not key or key in seen or len(rows) != 1:
                raise ValueError('보호 손절 식별/중복 대조 실패')
            a = rows[0]
            full = a.get('closeFraction') == '1'
            if (a.get('instId') != r['symbol'] or a.get('posSide') != r['direction']
                    or a.get('side') != ('sell' if r['direction'] == 'long' else 'buy')
                    or a.get('tdMode') != 'isolated' or a.get('state') != 'live'
                    or a.get('slTriggerPxType') != 'mark' or a.get('slOrdPx') != '-1'
                    or number(a.get('slTriggerPx', '0')) != number(leg['stop_px'])
                    or number(leg['stop_px']) <= 0 or number(leg['quantity']) <= 0
                    or (full and len(legs) != 1)
                    or (not full and number(a.get('sz') or '0') != number(leg['quantity']))):
                raise ValueError('거래소 보호 손절 대조 실패 · 기존 관리 유지')
            seen.add(key)
            stops.append((key, str(number(leg['quantity'])), str(number(leg['stop_px'])), a.get('algoId')))
        facts.append((r['symbol'], r['direction'], str(number(p['pos'])),
                      str(number(p['avgPx'])), tuple(stops)))
    if len(algos) != len(seen):
        raise ValueError('기록 외 조건주문이 있어 인계를 보류합니다.')
    return digest({'account': journal['account'], 'positions': sorted(facts)})


def valid_request(root, request, now=None):
    now = time.time() if now is None else now
    try:
        if load(root/REQUEST).get('nonce') != request.get('nonce'):
            return False
    except (OSError, ValueError):
        return False
    if (request.get('protocol') != PROTOCOL
            or not re.fullmatch('[0-9a-f]{32}', str(request.get('nonce', '')))
            or not 0 <= now-request.get('created_at', 0) < 90
            or request.get('host_pid') != os.getpid()
            or request.get('host_token') != process_token(os.getpid())
            or type(request.get('installer_pid')) is not int
            or request['installer_pid'] < 2
            or request.get('installer_token') is None
            or process_token(request['installer_pid']) != request['installer_token']):
        return False
    target = Path(request.get('target', ''))
    return (target.parent == root and re.fullmatch(r'host-v[0-9]+', target.name)
            and target.is_dir() and not target.is_symlink())


def start_watchdog(root, request):
    """Independent recovery survives the installer/old host going away."""
    here = Path(__file__).resolve().parent
    boot = Path.home()/'.termux/boot/40-okx-home'
    if boot.is_symlink() or str(here/'phone_service.py') not in boot.read_text():
        raise ValueError('복구용 자동 시작 경로 확인 실패')
    saved = root/('phone-handover-recovery-'+request['nonce']+'.json')
    save_json(saved, dict(request, old=str(here), boot=str(boot),
                         boot_before=base64.b64encode(boot.read_bytes()).decode()))
    child = subprocess.Popen([sys.executable, '-B', str(here/'phone_handover.py'),
                              '--recover', str(saved)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, close_fds=True)
    if child.poll() is not None:
        raise ValueError('업데이트 복구 감시를 시작하지 못했습니다.')


def recover(saved):
    """No broker writes and no kills. Restart the verified prior owner only
    after installer death AND all previous owner/transport locks are released.
    """
    import phone_service as service
    from phone_migrate import transport_released
    from phone_account import atomic_private
    from phone_button_upgrade import apply_late_stop
    saved = Path(saved)
    r = load(saved)
    root = saved.parent
    old = Path(r['old'])
    if old != Path(__file__).resolve().parent or old.parent != root:
        raise ValueError('복구 소스 경로 불일치')
    while process_token(r['installer_pid']) == r['installer_token']:
        time.sleep(.5)
    ack = load(root/ACK) if (root/ACK).exists() else {}
    if ack.get('nonce') != r['nonce'] or ack.get('phase') != 'released':
        return  # The old engine never handed over; it still manages positions.
    deadline = time.monotonic()+300
    while time.monotonic() < deadline:
        if process_token(r['host_pid']) == r['host_token']:
            time.sleep(.5)
            continue
        status_path = root/'phone_service_status.json'
        status = load(status_path) if status_path.exists() else {}
        if (status.get('host_pid') != r['host_pid'] and status.get('host_process_running')
                and status.get('state') == 'running'
                and 0 <= time.time()-status.get('observed_at', 0) < 15
                and service.running(root) and service.running(root, 'phone_host.lock')):
            return  # Replacement or rollback owner is already managing.
        if service.running(root) or service.running(root, 'phone_host.lock') or not transport_released(root):
            time.sleep(.5)
            continue
        try:
            with service.lock(root, 'phone_clock_upgrade.lock'):
                if service.running(root) or service.running(root, 'phone_host.lock') or not transport_released(root):
                    continue
                # A later installer may have completed while we waited for lock.
                current_ack = load(root/ACK)
                if current_ack.get('nonce') != r['nonce']:
                    return
                boot = Path(r['boot'])
                text = boot.read_text() if not boot.is_symlink() else ''
                if not any(str(Path(folder)/'phone_service.py') in text for folder in (r['old'], r['target'])):
                    raise ValueError('복구 자동 시작 파일 변경 감지')
                apply_late_stop(root, ack)
                atomic_private(boot, base64.b64decode(r['boot_before'], validate=True))
                boot.chmod(0o700)
                service.start(root, enable=True)
                save_json(root/'phone_update_result.json', dict(phase='recovered_previous',
                          observed_at=time.time(), message='설치 프로세스 종료 감지 · 기존 관리 실행기 복구'))
                return
        except ValueError:
            time.sleep(.5)
    save_json(root/'phone_update_result.json', dict(phase='recovery_required', observed_at=time.time(),
              message='이전 프로세스 종료/새 관리 실행기 확인 지연 · 중복 시작 차단'))


class EngineHandover:
    def __init__(self, engine, root):
        self.engine, self.root = engine, Path(root)
        self.seen = None
        self.committed = None
        self.gate = threading.RLock()
        self.original_handle, self.original_send = engine.handle, engine.send
        engine.handle, engine.send = self.handle, self.send

    def poll(self):
        path = self.root/REQUEST
        if not path.exists():
            return
        try:
            r = load(path)
            if r.get('nonce') == self.seen or not valid_request(self.root, r):
                return
            self.seen = r['nonce']
            self.original_send('phone_update_handover', request=r)
        except (OSError, ValueError, TypeError, KeyError):
            return

    def send(self, action, **kwargs):
        with self.gate:
            if not self.committed:
                return self.original_send(action, **kwargs)
            op = kwargs.get('op') if action == 'mobile_control' else action
            if op in ('pause', 'quit', 'close', 'close_all', 'close_one'):
                # A stop arriving at the last instant must defeat auto-resume.
                save_json(self.root/CANCEL, dict(nonce=self.committed['nonce'], requested=False))
            if action == 'mobile_control':
                self.engine.events.put(('mobile_control_result', dict(request_id=kwargs.get('request_id'),
                    owner=kwargs.get('owner'), status='failed',
                    message='업데이트 인계 중 · 주문은 실행하지 않았습니다. 재연결 후 확인하세요.')))

    def handle(self, action, kwargs):
        if self.committed:
            return
        if action != 'phone_update_handover':
            return self.original_handle(action, kwargs)
        r = kwargs['request']
        if not valid_request(self.root, r):
            return
        e = self.engine
        was_requested = bool(getattr(e, 'run_requested', False))
        # Called under the real engine.lock, after any in-flight write completes.
        e.entry_cancel.set()
        e.enabled = e.preview = False
        e.user_paused = True
        e.resume_pending = False
        e.invalidate()
        try:
            if (not e.commands.empty() or not e.risk_queue.empty() or e.queued_risks
                    or getattr(e, 'executing_signal', None) or getattr(e, 'approval', None)
                    or getattr(e, 'click_pending716', None)):
                raise ValueError('처리 중인 명령/보호 작업이 있어 설치 보류')
            journal = copy.deepcopy(e.journal.data)
            if bool(journal.get('entry_continuity732', {}).get('requested')) != was_requested:
                raise ValueError('진입 운용 의도 대조 실패')
            first = validate_protected(journal, e.api.snapshot(), e.api.pending_algos(full=True))
            second = validate_protected(journal, e.api.snapshot(), e.api.pending_algos(full=True))
            if first != second:
                raise ValueError('대조 중 포지션/보호 주문이 바뀌어 설치 보류')
            start_watchdog(self.root, r)
            with self.gate, commit_lock(self.root):
                if (not valid_request(self.root, r) or not e.commands.empty()
                        or not e.risk_queue.empty() or e.queued_risks
                        or digest(e.journal.data) != digest(journal)):
                    raise ValueError('대조 중 새로운 명령/보호 작업이 발생해 설치 보류')
                e.journal.save()
                ack = dict(protocol=PROTOCOL, nonce=r['nonce'], phase='released',
                           host_pid=os.getpid(), host_token=process_token(os.getpid()),
                           journal_sha=digest(journal), requested=was_requested,
                           protection_sha=first, target=r['target'], observed_at=time.time())
                save_json(self.root/ACK, ack)
                self.committed = r
                e.stop_event.set()
                e.command_wake.set()
                e.events.put(('quit', None))
        except Exception as error:
            # Resume only through the original account/order/SL recovery checks.
            e.run_requested = was_requested
            e.resume_pending = was_requested
            e.user_paused = not was_requested
            e.recovering = True
            e.good_snapshots = 0
            e.resume_reason = '업데이트 보류 · 기존 계정/보호 대조 후 복귀'
            message = str(error) if isinstance(error, ValueError) else '인계 조회 실패 · 기존 관리 유지'
            save_json(self.root/ACK, dict(protocol=PROTOCOL, nonce=r['nonce'],
                      phase='deferred', message=message, observed_at=time.time()))
            e.log(message)


def install(engine, root):
    return EngineHandover(engine, root)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--recover':
        recover(sys.argv[2])
