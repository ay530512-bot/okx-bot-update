#!/usr/bin/env python3
"""Verified OKX mobile GUI button updater: 1.1.8 -> 1.1.9.
Stages pinned source; asks existing host to safely hand over and preserve orders.
Never trades, cancels, or closes orders; no credentials are packaged.
"""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, sys, tempfile

PINNED = {'phone_host.py': 'abb926541d5acf4c646288dad4fb7bc2ee43e0a5fe5112e8951bd556123b8224', 'phone_mobile.py': '3a576f4b4e24723451a04a4da97542eb74683e67d60a628fe1f8246e8273e6b7', 'phone_account.py': '3c4c9f9cccaeaa60a41cc3ff3fdde68c04372aabcd8861098cefb8d918406f81', 'phone_sources.json': '1e8a54e5baff2e9f77aa48e1335dea650ae74cc1e5ebfaf562d796960d0838c7', 'phone_remote.py': 'f891e8cc8c8e822eb7f75ccd22d441b4b451162de0bf87a134b3c925e9073e97', 'phone_service.py': '72978d1bc756e37e8455b00e43861a79be0a1fe28d67382287bb32a56c7584c5', 'phone_migrate.py': 'aafbe024259d3f4dffc81b9b4ec7c9e9307a3487efeb969b1feed257f66399fb', 'phone_migration_sources.json': '214293c5bf0d7fd79838b1037ab9499a2a5428c91758fe3df7c439d790e3691d', 'phone_remote_check.py': '7d20cb6dcbbd2d784dab6c9fd8131722175d2f684b2202c3499fc13e8fd194d1', 'phone_clock.py': 'c1465b5e7d796937e16897c28d29d6ea78d4523b1c3a235a3384a97c2af7074c', 'phone_connection_trace.py': '7bd09c14dca5a97069448106800b2afa640620e8e33472f440b7ec34afec68fb', 'phone_public_ws.py': 'b1a860e524a04b68da73438b1b47238b1ce143caaf167611574dea53b11a84b9', 'phone_performance.py': '11a2f7648e97f0eaa52e53561aca97cc9fa656020fbe4842dedb850c1ac5e146', 'phone_signal_cache.py': '33369286afede27b4231c36ad650c51259e33f55ba2a7b1d675646121e371aba', 'phone_update.py': 'b3fff81ece54b3927ff413690c1899a24908f8a22544cbe87ebd1373d22bb11c', 'phone_update_ui.js': 'db7e902358753679a89de868b75b0b269cd0517de33bf1ed614df33359b2c6d9', 'phone_button_upgrade.py': 'dd7698cf0cfa1909098ce79d51df11b19d247ca36927c31a74091e15c09e5c32', 'phone_button_old_sources.json': 'a77afc78a4ac7017917255be935d5ead82db957e710f41ebe5a9641700d5eae9', 'phone_handover.py': '11d26680baa581043998005af8b2016a40a4df1eff7730d9d34b10706c89523c'}
OLD_HEARTBEAT = "def ping_if_due(stream, ws):\n    # OKX documents a ping/pong liveness timer N < 30 seconds and reconnect\n    # when pong does not arrive within N. Keep 20s sends, use a 20s reply limit.\n    # This changes transport recovery only; quote freshness/admission stay intact.\n    now = time.monotonic()\n    with stream.lock:\n        if stream.ws is not ws or not stream.connected:\n            return\n        generation = stream.generation\n        d = diagnostics(stream)\n        pending = d['pending_ping_at']\n        if pending is not None and now-pending >= PONG_TIMEOUT_SECONDS:\n            raise PublicHeartbeatTimeout('public heartbeat reply expired')\n        if now-stream.last_ping < PING_INTERVAL_SECONDS:\n            return\n        d['stage'] = 'ping'\n    ws.send('ping')\n    with stream.lock:\n        if stream.ws is not ws or stream.generation != generation or not stream.connected:\n            return\n        stream.last_ping = time.monotonic()\n        d = diagnostics(stream)\n        d['text_pings'] += 1\n        if d['pending_ping_at'] is None:\n            d['pending_ping_at'] = stream.last_ping\n"
NEW_HEARTBEAT = "def ping_if_due(stream, ws):\n    # OKX public WS guidance: send text 'ping' only after N seconds with NO\n    # inbound frame. The per-symbol quote freshness rules remain unchanged.\n    # An inbound frame after a ping proves the socket is alive, even if a\n    # separate text pong was delayed behind high-volume market frames.\n    now = time.monotonic()\n    with stream.lock:\n        if stream.ws is not ws or not stream.connected:\n            return\n        generation = stream.generation\n        d = diagnostics(stream)\n        pending = d['pending_ping_at']\n        last_frame = d['frame_at']\n        if pending is not None:\n            if last_frame is not None and last_frame > pending:\n                # Inbound traffic resumed; no reason to reset the stream.\n                d['pending_ping_at'] = None\n            elif now - pending >= PONG_TIMEOUT_SECONDS:\n                # A genuinely silent socket has failed the idle heartbeat.\n                raise PublicHeartbeatTimeout('public heartbeat reply expired')\n            else:\n                return  # Only one outstanding ping, never a repeated flood.\n        idle_since = last_frame if last_frame is not None else stream.last_ping\n        if now - idle_since < PING_INTERVAL_SECONDS:\n            return\n        d['stage'] = 'ping'\n    ws.send('ping')\n    with stream.lock:\n        if stream.ws is not ws or stream.generation != generation or not stream.connected:\n            return\n        stream.last_ping = time.monotonic()\n        d = diagnostics(stream)\n        d['text_pings'] += 1\n        d['pending_ping_at'] = stream.last_ping\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(text, before, after, file):
    if text.count(before) != 1:
        raise ValueError(file + ': 수정 대상이 정확히 일치하지 않습니다. 변경 안 함')
    return text.replace(before, after, 1)


def safe_path(path):
    path = pathlib.Path(path).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ValueError('운용 루트 폴더가 없거나 링크입니다.')
    return path.resolve(strict=True)


def read_pins(root):
    old = root/'host-v16'
    if old.is_symlink() or not old.is_dir():
        raise ValueError('현재 1.1.8 host-v16 폴더를 찾을 수 없습니다. 다른 버전은 수정하지 않습니다.')
    originals = {}
    for name, checksum in PINNED.items():
        file = old/name
        if file.is_symlink() or not file.is_file():
            raise ValueError(name+': 필수 원본 파일이 없습니다.')
        data = file.read_bytes()
        if digest(data) != checksum:
            raise ValueError(name+': 1.1.8 승인 원본 SHA256과 다릅니다. 자동 변경하지 않습니다.')
        originals[name] = data
    for file in old.rglob('*'):
        rel = file.relative_to(old)
        if file.is_symlink():
            raise ValueError('이전 실행기 안에 파일 링크가 있어 중단합니다.')
        if file.is_file() and '__pycache__' not in rel.parts and rel.as_posix() not in PINNED:
            raise ValueError('1.1.8 실행기에 예상하지 않은 파일이 있어 중단합니다: '+str(rel))
    return originals


def candidate(originals):
    files = dict(originals)
    ws = originals['phone_public_ws.py'].decode('utf-8')
    files['phone_public_ws.py'] = replace_once(ws, OLD_HEARTBEAT, NEW_HEARTBEAT, 'phone_public_ws.py').encode()
    service = originals['phone_service.py'].decode('utf-8')
    service = replace_once(service,"VERSION = 'phone-service-16'","VERSION = 'phone-service-17'",'phone_service.py')
    service = replace_once(service,"MARKER = '# OKX phone service v16 managed boot hook'","MARKER = '# OKX phone service v17 managed boot hook'",'phone_service.py')
    service = replace_once(service,"LEGACY_MARKERS = (","LEGACY_MARKERS = ('# OKX phone service v16 managed boot hook', ",'phone_service.py')
    files['phone_service.py']=service.encode()
    mobile = originals['phone_mobile.py'].decode('utf-8')
    if mobile.count('1.1.8') != 4:
        raise ValueError('모바일 버전 표기 검증 실패')
    files['phone_mobile.py']=mobile.replace('1.1.8','1.1.9').encode()
    update = originals['phone_update.py'].decode('utf-8')
    update = replace_once(update,'CURRENT = 16','CURRENT = 17','phone_update.py')
    update = replace_once(update,"DISPLAY_VERSION = '1.1.8'","DISPLAY_VERSION = '1.1.9'",'phone_update.py')
    files['phone_update.py']=update.encode()
    up = originals['phone_button_upgrade.py'].decode('utf-8')
    up = replace_once(up,"VERSION = 'phone-upgrade-1.1.8'","VERSION = 'phone-upgrade-1.1.9'",'phone_button_upgrade.py')
    if up.count('1.1.8') != 3:
        raise ValueError('업데이트기 버전 표기 검증 실패')
    files['phone_button_upgrade.py']=up.replace('1.1.8','1.1.9').encode()
    oldpins = json.loads(originals['phone_button_old_sources.json'])
    if 'host-v16' in oldpins:
        raise ValueError('원본에 알 수 없는 host-v16 고정값이 있습니다.')
    oldpins['host-v16'] = dict(PINNED)
    files['phone_button_old_sources.json']=(json.dumps(oldpins,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    # Static syntax check without importing or starting any exchange client.
    for name, data in files.items():
        if name.endswith('.py'):
            compile(data.decode('utf-8'),name,'exec')
    return files


def stage(root, files):
    dest = root/'host-v17'
    if dest.is_symlink():
        raise ValueError('host-v17 경로 링크 오류')
    if dest.exists():
        if not dest.is_dir():
            raise ValueError('host-v17은 폴더가 아닙니다.')
        seen={}
        for file in dest.rglob('*'):
            rel=file.relative_to(dest)
            if file.is_symlink():
                raise ValueError('host-v17 내 파일 링크 오류')
            if file.is_file() and '__pycache__' not in rel.parts:
                seen[rel.as_posix()]=file.read_bytes()
        if seen != files:
            raise ValueError('다른 host-v17이 존재합니다. 덮어쓰지 않았습니다.')
        print('이미 검증된 1.1.9 파일이 준비되어 있습니다.')
        return dest
    tmp=pathlib.Path(tempfile.mkdtemp(prefix='.host-v17-stage-',dir=root))
    try:
        for name,data in files.items():
            target=tmp/name
            with target.open('xb') as fp:
                fp.write(data)
                os.fchmod(fp.fileno(),0o600)
        # Re-read every staged byte before promotion.
        for name,data in files.items():
            if (tmp/name).read_bytes()!=data:raise ValueError('설치 파일 저장 검증 실패')
        tmp.rename(dest)
    finally:
        if tmp.exists():shutil.rmtree(tmp)
    print('해시 확인된 1.1.9 파일 준비:', dest)
    return dest


def main():
    parser=argparse.ArgumentParser(description='OKX Fold3 공개 WS 연결 수정 1.1.9')
    parser.add_argument('--root',default=str(pathlib.Path.home()/'okx-phone'))
    args=parser.parse_args()
    root=safe_path(args.root)
    originals=read_pins(root)
    prepared=candidate(originals)
    dest=stage(root,prepared)
    print('현재 매매 프로그램, 거래소 주문, SL, 설정은 아직 변경하지 않았습니다.')
    print('안전 전환 요청: 기존 실행기의 포지션/주문/SL 대조와 인계·롤백 절차를 시작합니다.')
    print('보호 상태가 불확실하면 기존 실행기를 유지하고 설치를 보류합니다.')
    proc=subprocess.run([sys.executable,'-B',str(dest/'phone_button_upgrade.py')],
        cwd=str(dest),check=False)
    if proc.returncode:
        raise SystemExit('업데이트 보류: 기존 앱이 보유분 보호 중일 수 있습니다. 강제 종료하지 마세요.')
    print('설치 완료: 모바일 버전 1.1.9, 기존 매매 설정/포지션/손절 관리 상태를 확인하세요.')

if __name__=='__main__':
    os.umask(0o077)
    try:main()
    except (OSError,ValueError,UnicodeError) as exc:
        print('설치 보류:',str(exc))
        raise SystemExit(1)