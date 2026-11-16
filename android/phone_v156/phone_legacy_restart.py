"""One-time checkpoint restart for pinned hosts with the missing avg_px bug.

No broker writes. Ordinary updates keep using the cooperative handover. Only a
paused, frozen legacy writer with two matching REST protection checks can be
retired. A separate process thaws it on pre-commit failure/installer death.
"""
import copy
import os
from pathlib import Path
import secrets
import re
import signal
import subprocess
import sys
import time

from phone_account import save_json, atomic_private
from phone_handover import commit_lock, digest, load, validate_protected, records
from phone_migrate import child_pids, process_token, transport_released
import phone_service as service

WATCHERS = []


def descendants(pid):
    found=set(child_pids(pid))
    # Multiprocessing may be launched by the engine's worker thread.
    for path in (Path('/proc')/str(pid)/'task').glob('*/children'):
        try: found.update(int(x) for x in path.read_text().split())
        except FileNotFoundError: pass
    for child in tuple(found): found.update(descendants(child))
    return sorted(found)


def matches(pid, token):
    return type(pid) is int and pid > 1 and token is not None and process_token(pid) == token


def signal_exact(pid, token, sig):
    if not matches(pid, token): raise ValueError('재시작 대상 프로세스가 바뀌었습니다.')
    os.kill(pid, sig)


def frozen(pid, token):
    if not matches(pid, token): return False
    tasks = list((Path('/proc')/str(pid)/'task').glob('*/status'))
    return bool(tasks) and all(any(line.startswith('State:') and line.split()[1] in ('T','t')
                                 for line in p.read_text().splitlines()) for p in tasks)


def thaw(row):
    for key in ('host', 'supervisor'):
        pid, token = row[key]
        if matches(pid, token): os.kill(pid, signal.SIGCONT)


def calculation_workers(pairs):
    """Never retire arbitrary descendants: the button installer is one too.

    Only the pinned host's Python multiprocessing children are disposable.
    Recheck argv AND start token, including when consuming a 1.5.4 record.
    Installer ancestors and recovery watchers cannot match this allowlist.
    """
    out=[]
    for pid, token in pairs:
        if pid == os.getpid() or not matches(pid, token): continue
        try:
            args=(Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError: continue
        # Python inherits flags such as -B from the phone host before -c.
        if b'-c' not in args: continue
        index=args.index(b'-c')
        if index+1>=len(args): continue
        code=args[index+1]
        spawn=(code.startswith(b'from multiprocessing.spawn import spawn_main; spawn_main(')
               and b'--multiprocessing-fork' in args)
        tracker=code.startswith(b'from multiprocessing.resource_tracker import main;main(')
        if spawn or tracker: out.append([pid,token])
    return out


def retire(row):
    """Commit is durable before killing the verified frozen legacy writer."""
    pid, token = row['host']
    if matches(pid, token):
        if not frozen(pid, token): raise ValueError('일시정지되지 않은 실행기는 교체하지 않습니다.')
        # SIGTERM is deliberately refused by the old core when it owns a
        # position. This narrow one-time path follows a persisted pause and
        # frozen read-only checkpoint; it is not a timeout kill escalation.
        os.kill(pid, signal.SIGKILL)
    for pid, token in calculation_workers(row.get('children', [])):
        if matches(pid, token): os.kill(pid, signal.SIGTERM)
    pid, token = row['supervisor']
    if matches(pid, token):
        os.kill(pid, signal.SIGTERM)
        os.kill(pid, signal.SIGCONT)


def wait_old_ready(root, old):
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        s=load(root/'phone_service_status.json')
        if (s.get('service_version')=='phone-service-'+old.name.removeprefix('host-v')
                and s.get('state')=='running' and s.get('host_process_running')
                and s.get('remote_process_running') and 0<=time.time()-s.get('observed_at',0)<15):
            return
        time.sleep(.25)
    raise ValueError('기존 관리 복구 준비 대기 · 운용 기록은 유지됩니다.')


def repair_stalled(root, old):
    """Recover a dead button installer before requiring a fresh service heartbeat.

    1.5.4 may have left a SIGSTOP supervisor after killing its own installer.
    No process-name kill, lock deletion, journal reset, or broker write occurs.
    Restore the authenticated old manager first, so its usual reconciliation
    handles fills that may have occurred during the outage.
    """
    from phone_button_upgrade import journal_path, wait_released, result
    for path in sorted(root.glob('phone-legacy-restart-*.json')):
        if not re.fullmatch(r'phone-legacy-restart-[0-9a-f]{32}\.json',path.name): continue
        if path.is_symlink() or path.stat().st_size>262144: raise ValueError('복구 기록 파일 오류')
        row=load(path)
        if row.get('phase') not in ('prepared','committed'): continue
        if row.get('old')!=str(old): continue
        if matches(*row['installer']): raise ValueError('기존 설치 작업이 아직 실행 중입니다.')
        if row.get('target') not in (str(root/'host-v44'),str(Path(__file__).resolve().parent)):
            raise ValueError('복구 대상 설치 경로 불일치')
        boot=Path.home()/'.termux/boot/40-okx-home'
        if boot.read_bytes().hex()!=row.get('boot_hex'): raise ValueError('복구 이후 자동시작 등록 변경')
        current=load(root/'phone_service_status.json')
        # A previous recovery can die after starting the old manager but before
        # completing its marker. Verify that replacement instead of touching it.
        if (current.get('host_pid')!=row['host'][0] and current.get('state')=='running'
                and current.get('host_process_running') and current.get('remote_process_running')
                and 0<=time.time()-current.get('observed_at',0)<15):
            pids=((current.get('host_pid'),'phone_host.py'),(current.get('pid'),'phone_service.py'))
            if all(type(p) is int and process_token(p) is not None and
                   str(old/script).encode() in (Path('/proc')/str(p)/'cmdline').read_bytes().split(b'\0')
                   for p,script in pids):
                with commit_lock(root):
                    row['phase']='complete';save_json(path,row)
                continue
        for key,script in (('host','phone_host.py'),('supervisor','phone_service.py')):
            pid,token=row[key]
            if matches(pid,token):
                args=(Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0')
                if str(old/script).encode() not in args: raise ValueError('복구 프로세스 경로 불일치')
                if not frozen(pid,token): raise ValueError('기존 관리가 실행 중이므로 중단하지 않습니다.')
        with commit_lock(root):
            if load(path)!=row: raise ValueError('복구 기록이 변경되었습니다.')
            # Old watcher has the same unsafe retire() implementation. Stop only
            # its exact script+transaction process, then use this fixed watcher.
            for proc in Path('/proc').iterdir():
                if not proc.name.isdigit(): continue
                pid=int(proc.name)
                try:
                    if proc.stat().st_uid!=os.getuid(): continue
                    args=(proc/'cmdline').read_bytes().split(b'\0')
                except (FileNotFoundError,PermissionError,ProcessLookupError): continue
                if (str(Path(row['target'])/'phone_legacy_restart.py').encode() in args
                        and b'--recover' in args and str(path).encode() in args):
                    token=process_token(pid)
                    if token is not None: signal_exact(pid,token,signal.SIGTERM)
            if row['phase']=='prepared':
                thaw(row);row['phase']='aborted';save_json(path,row)
                continue
            journal=load(journal_path(root))
            if (digest(journal)!=row.get('journal_sha')
                    or journal.get('entry_continuity732',{}).get('requested') is not False):
                raise ValueError('중단 당시 운용 기록과 달라 자동 복구를 보류합니다.')
            row['children']=calculation_workers(row.get('children',[]))
            row['installer']=[os.getpid(),process_token(os.getpid())]
            row['recovered_by']='1.5.5'
            save_json(path,row)
            watcher=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--recover',str(path)],
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                start_new_session=True,close_fds=True)
            WATCHERS.append(watcher)
            result(root,'recovering',message='중단된 1.5.4 설치 복구 · 기존 보유분 관리 재시작')
            print('중단된 설치 복구 중 · 보유 기록을 유지하고 관리 프로그램을 먼저 재시작합니다.',flush=True)
            retire(row)
        wait_released(root,dict([row['host'],row['supervisor'],*row['children']]))
        restore_old(root,row)
        wait_old_ready(root,old)
        complete(dict(checkpoint_path=str(path)))
        # 1.5.4 did not save original entry intent. Never guess it from history.
        print('기존 관리 복구 확인 · 신규 진입 중지 상태는 유지하고 새 버전을 설치합니다.',flush=True)


def previous_pause(root, old, host, token):
    for path in root.glob('phone-legacy-restart-*.json'):
        row=load(path)
        if (row.get('phase')=='aborted' and row.get('old')==str(old)
                and row.get('host')==[host,token] and not matches(*row['installer'])):
            return True
    return False


def restore_old(root, row):
    old = Path(row['old'])
    if old.parent != root or old.is_symlink() or not old.is_dir():
        raise ValueError('복구 실행기 경로 오류')
    boot = Path.home()/'.termux/boot/40-okx-home'
    if boot.is_symlink() or not boot.is_file(): raise ValueError('복구 자동시작 파일 오류')
    # Never overwrite an unrelated registration or start a competing writer.
    if not any(str(Path(x)/'phone_service.py') in boot.read_text() for x in (row['old'], row['target'])):
        raise ValueError('자동시작 등록이 바뀌어 복구를 보류합니다.')
    atomic_private(boot, bytes.fromhex(row['boot_hex']));boot.chmod(0o700)
    subprocess.run([sys.executable,'-B',str(old/'phone_service.py'),'--root',str(root),'--start'],
                   check=True,timeout=25,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def recover(path):
    path = Path(path);root = path.parent
    while True:
        row = load(path)
        if row['phase'] in ('aborted','complete'): return
        alive = matches(*row['installer'])
        expired = time.monotonic() >= row['deadline']
        if not alive or (expired and row['phase'] != 'committed'):
            with commit_lock(root):
                row = load(path)
                if row['phase'] in ('aborted','complete'): return
                if row['phase'] != 'committed':
                    thaw(row);row['phase']='aborted';save_json(path,row);return
                retire(row)
            break
        time.sleep(.2)
    # A committed restart can be recovered only after every old owner exits.
    deadline = time.monotonic()+120
    while time.monotonic()<deadline:
        if not service.running(root) and not service.running(root,'phone_host.lock') and transport_released(root):
            try:
                with service.lock(root,'phone_clock_upgrade.lock'):
                    if service.running(root) or service.running(root,'phone_host.lock'): return
                    restore_old(root,row)
                    row['phase']='complete';save_json(path,row)
                    return
            except ValueError: pass
        # An installer/rollback already started a replacement; never stop it.
        status = root/'phone_service_status.json'
        if status.exists():
            s=load(status)
            if (s.get('host_pid')!=row['host'][0] and s.get('host_process_running')
                    and s.get('state')=='running' and 0<=time.time()-s.get('observed_at',0)<15): return
        time.sleep(.25)


def needs_checkpoint(old, journal):
    # verify_old() has already authenticated the complete immutable old host.
    code=(old/'phone_handover.py').read_text()
    return bool(records(journal) and "number(r['avg_px'])" in code and
                any('avg_px' not in r for r in records(journal)))


def pause_events(before, after):
    c0,c1=before.get('entry_continuity732',{}),after.get('entry_continuity732',{})
    if c1.get('schema')!=1 or c1.get('requested') is not False: return None
    for key in ('schema','account','exchange','policy_hash','budget'):
        if c0.get(key)!=c1.get(key): return None
    previous=c0.get('history',[]);history=c1.get('history',[])
    if previous:
        matches=[i for i,x in enumerate(history) if x==previous[-1]]
        if len(matches)!=1:return None
        suffix=history[matches[0]+1:]
    else:suffix=history
    return [(x.get('event'),x.get('reason')) for x in suffix
            if x.get('event') in ('operator_stop','started','auto_resumed')]


def restore_intent(root, before, after):
    # The actual Q2X rejects quit BEFORE recording a quit event when held.
    # A flat exit does record it. Any additional operator stop defeats resume.
    events=pause_events(before,after)
    pause=[('operator_stop','사용자가 신규 진입 중지')]
    if before.get('entry_continuity732',{}).get('requested') is True and events in (
            pause,pause+[('operator_stop','사용자가 프로그램 종료')]):
        c=after['entry_continuity732'];c.update(requested=True,event='update_resume_requested',
            reason='보유분 보호 대조 후 업데이트 전 운용 요청 복구',ms=int(time.time()*1000))
        c['history']=(c.get('history',[])+[dict(ms=c['ms'],event=c['event'],reason=c['reason'])])[-100:]
        save_json(root/'runtime-q2x/bot_state.json',after)
    return after


def checkpoint_restart(root, old, target, tokens, api, pins):
    from phone_button_upgrade import (inspect_account, journal_path,
                                      wait_released, result)
    state=load(root/'phone_service_status.json')
    host,supervisor=state.get('host_pid'),state.get('pid')
    for pid,script in ((host,'phone_host.py'),(supervisor,'phone_service.py')):
        if pid not in tokens or not matches(pid,tokens[pid]): raise ValueError('구버전 프로세스 식별 실패')
        if str(old/script).encode() not in (Path('/proc')/str(pid)/'cmdline').read_bytes().split(b'\0'):
            raise ValueError('구버전 프로세스 경로 불일치')
    before=copy.deepcopy(load(journal_path(root)))
    inspect_account(api,root,pins)
    result(root,'preparing',message='구버전 보유분 보호 대조 · 관리 프로세스 재시작 준비')
    # Old host disables controls and queues pause then quit, serially behind
    # any in-flight action. Wait for a NEW persisted pause, not an old flag.
    already_paused=(before.get('entry_continuity732',{}).get('requested') is False
                    and previous_pause(root,old,host,tokens[host]))
    signal_exact(host,tokens[host],signal.SIGTERM)
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        journal=load(journal_path(root));events=pause_events(before,journal)
        if already_paused or (events and events[-1]==('operator_stop','사용자가 신규 진입 중지')):break
        if not matches(host,tokens[host]):
            wait_released(root,tokens)
            after=restore_intent(root,before,load(journal_path(root)))
            return dict(legacy=True,requested=after['entry_continuity732'].get('requested') is True)
        time.sleep(.1)
    else: raise ValueError('진입 중지 처리 확인 대기 · 기존 보유분 관리를 유지합니다.')
    row=dict(phase='prepared',installer=[os.getpid(),process_token(os.getpid())],
             host=[host,tokens[host]],supervisor=[supervisor,tokens[supervisor]],
             old=str(old),target=str(target),deadline=time.monotonic()+60,
             before_continuity=before.get('entry_continuity732',{}),
             boot_hex=(Path.home()/'.termux/boot/40-okx-home').read_bytes().hex())
    path=root/('phone-legacy-restart-'+secrets.token_hex(16)+'.json');save_json(path,row)
    watcher=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--recover',str(path)],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        start_new_session=True,close_fds=True)
    if watcher.poll() is not None: raise ValueError('재시작 복구 감시 시작 실패')
    WATCHERS.append(watcher)
    committed=False
    try:
        with commit_lock(root):
            if load(path)['phase']!='prepared': raise ValueError('재시작 준비가 취소되었습니다.')
            signal_exact(host,tokens[host],signal.SIGSTOP)
            signal_exact(supervisor,tokens[supervisor],signal.SIGSTOP)
        freeze_end=time.monotonic()+3
        while not (frozen(host,tokens[host]) and frozen(supervisor,tokens[supervisor])):
            if time.monotonic()>freeze_end: raise ValueError('관리 프로세스 일시정지 확인 실패')
            time.sleep(.02)
        journal=load(journal_path(root));journal_hash=digest(journal)
        if journal.get('entry_continuity732',{}).get('requested') is not False:
            raise ValueError('신규 진입 중지 기록 변경 · 재시작 취소')
        # Persisted write intent must be settled; raw REST verifies every SL.
        first=inspect_account(api,root,pins)
        second=inspect_account(api,root,pins)
        if first!=second or digest(load(journal_path(root)))!=journal_hash:
            raise ValueError('보유/손절/기록 변경 · 기존 관리 재개')
        with commit_lock(root):
            if (load(path)['phase']!='prepared' or time.monotonic()>=row['deadline']
                or not frozen(host,tokens[host]) or not frozen(supervisor,tokens[supervisor])):
                raise ValueError('보호 대조 시간 초과 · 기존 관리 재개')
            row.update(phase='committed',journal_sha=journal_hash,protection_sha=first,
                       children=calculation_workers([[p,process_token(p)] for p in descendants(host)]))
            save_json(path,row);committed=True
            retire(row)
        wait_released(root,{**tokens,**{p:t for p,t in row['children']}})
        # Writer is gone. Only our exact pause/quit suffix may restore intent.
        after=load(journal_path(root))
        if digest(after)!=journal_hash: raise ValueError('중지 이후 운용 기록 변경')
        after=restore_intent(root,before,after)
        # Caller has the upgrade lock and must install or restore before exit.
        return dict(legacy=True,checkpoint_path=str(path),requested=after['entry_continuity732'].get('requested') is True)
    except Exception:
        with commit_lock(root):
            if not committed:
                thaw(row);row['phase']='aborted';save_json(path,row)
        raise


def complete(ack):
    if ack.get('checkpoint_path'):
        p=Path(ack['checkpoint_path']);row=load(p);row['phase']='complete';save_json(p,row)
    for watcher in list(WATCHERS):
        try: watcher.wait(timeout=1)
        except subprocess.TimeoutExpired: continue
        WATCHERS.remove(watcher)


if __name__=='__main__' and len(sys.argv)==3 and sys.argv[1]=='--recover':
    recover(sys.argv[2])
