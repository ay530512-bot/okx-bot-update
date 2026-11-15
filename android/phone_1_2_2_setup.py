#!/usr/bin/env python3
"""Verified 1.2.1 -> 1.2.2 candidate latency patch. Stage then safe serial handover. No exchange orders here."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PINNED = {'phone_host.py': '21b9139454ff32c6afc7a4f0c9dece4540cc4cc9eb1d2a619c8e895f2b8afdce', 'phone_mobile.py': '6bd591a8465a4e7cfdd46fbf5f97f714d70936ea435dc35e8491aecf4f239f3b', 'phone_account.py': '3c4c9f9cccaeaa60a41cc3ff3fdde68c04372aabcd8861098cefb8d918406f81', 'phone_sources.json': '1e8a54e5baff2e9f77aa48e1335dea650ae74cc1e5ebfaf562d796960d0838c7', 'phone_remote.py': 'f891e8cc8c8e822eb7f75ccd22d441b4b451162de0bf87a134b3c925e9073e97', 'phone_service.py': 'c71ca1a07dc6be0e4006571068669417c57f331c1ac8c8bf3dfa6f8fb893ef05', 'phone_migrate.py': 'aafbe024259d3f4dffc81b9b4ec7c9e9307a3487efeb969b1feed257f66399fb', 'phone_migration_sources.json': '214293c5bf0d7fd79838b1037ab9499a2a5428c91758fe3df7c439d790e3691d', 'phone_remote_check.py': '7d20cb6dcbbd2d784dab6c9fd8131722175d2f684b2202c3499fc13e8fd194d1', 'phone_clock.py': 'c1465b5e7d796937e16897c28d29d6ea78d4523b1c3a235a3384a97c2af7074c', 'phone_connection_trace.py': '7bd09c14dca5a97069448106800b2afa640620e8e33472f440b7ec34afec68fb', 'phone_public_ws.py': 'ba48a1e7dfc866545f9d67d81cde2bd14786bf45feb0333705bc3c171a2a5a95', 'phone_performance.py': '11a2f7648e97f0eaa52e53561aca97cc9fa656020fbe4842dedb850c1ac5e146', 'phone_signal_cache.py': '071eb2defa234b3055d439ab775e8c9ec0384b8f36b8d0464d241ac442d94827', 'phone_update.py': '89e002091dab870c464aa121a03a8326ad224b42713058beade54e019c12da3a', 'phone_update_ui.js': 'db7e902358753679a89de868b75b0b269cd0517de33bf1ed614df33359b2c6d9', 'phone_button_upgrade.py': 'dd4c43adee07235ced4ccfe817f28b2a9341cd8934ac25019abb50bc0719bad6', 'phone_button_old_sources.json': '1e1591661ac4d6d4796023dc944b48da9a3083e18ad9a1fa264d05527f3c9814', 'phone_handover.py': '11d26680baa581043998005af8b2016a40a4df1eff7730d9d34b10706c89523c', 'phone_pullback_size.py': '556c076220d5af838cd6082a224388f1ac23869fd7f0c479a220d2f381887f41', 'phone_candidate_fast.py': '1223b04bf70658c845a91a062702745ac56d5ebf0843150c63d5aa7cb9a5598c'}
HOST_OLD = 'host-v19'
HOST_NEW = 'host-v20'
FAST_MODULE = '"""Candidate-only lazy auxiliary analysis, uncached original closed-bar validation.\nNo quote, signal expiry, admission, position protection or order is cached.\n"""\nimport ast\nimport functools\nimport hashlib\nimport inspect\nfrom pathlib import Path\nimport threading\nfrom types import FunctionType\n\n\ndef install(channel, cache, pins):\n    path = Path(inspect.getsourcefile(channel))\n    raw = path.read_bytes()\n    if hashlib.sha256(raw).hexdigest() != pins[\'files\'][path.name]:\n        raise ValueError(\'candidate fast path source hash mismatch\')\n    original_packet, original_candidate, original_closed = channel.packet, channel.candidate, channel.closed\n    state = threading.local()\n    tree = ast.parse(raw)\n    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == \'packet\')\n    matches = [i for i,n in enumerate(node.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0]) == \'(v, or_status)\']\n    if len(matches) != 1:\n        raise ValueError(\'candidate select anchor mismatch\')\n    node.body.insert(matches[0]+1, ast.parse("if not v:\\n return dict(entry_setups=[], or_status=or_status)").body[0])\n    unit = ast.Module(body=[node],type_ignores=[]); ast.fix_missing_locations(unit)\n    ns = {}; exec(compile(unit, str(path)+\'<candidate-fast>\', \'exec\'), ns)\n    fast = FunctionType(ns[\'packet\'].__code__, channel.__dict__, \'packet\', original_packet.__defaults__)\n    def enabled():\n        return getattr(state,\'candidate\',False) and getattr(cache.timer.local,\'group\',None)==\'optimized\'\n    @functools.wraps(original_candidate)\n    def candidate(*args, **kwargs):\n        previous = getattr(state,\'candidate\',False); state.candidate=True\n        try:return original_candidate(*args, **kwargs)\n        finally:state.candidate=previous\n    @functools.wraps(original_packet)\n    def packet(*args, **kwargs):\n        with cache.timer.scope(\'signal.packet_body\'):\n            return (fast if enabled() else original_packet)(*args, **kwargs)\n    @functools.wraps(original_closed)\n    def closed(b,now,step=900000,required=22):\n        # Returning a deep-copied full candle array cost more than validation\n        # on the deployed phone. Always validate original input, including the\n        # exact current cutoff, without serializing/copying a candle cache.\n        with cache.timer.scope(\'signal.closed_validation.compute\'):\n            return original_closed(b,now,step,required)\n    channel.candidate=candidate;channel.packet=packet;channel.closed=closed\n'

def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(text, before, after, file):
    if not before or text.count(before) != 1:
        raise ValueError(file + ': 수정 대상이 정확히 일치하지 않습니다. 변경 안 함')
    return text.replace(before, after, 1)


def safe_path(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ValueError('운용 루트 폴더가 없거나 링크입니다.')
    return path.resolve(strict=True)


def read_pins(root):
    old = root/HOST_OLD
    if old.is_symlink() or not old.is_dir():
        raise ValueError('현재 1.2.1 host-v19 폴더를 확인하지 못했습니다.')
    originals = {}
    for name, checksum in PINNED.items():
        file = old/name
        if file.is_symlink() or not file.is_file():
            raise ValueError(name + ': 필수 원본 파일이 없습니다.')
        data = file.read_bytes()
        actual = digest(data)
        if actual != checksum:
            raise ValueError(name + ': 승인된 1.2.1 원본과 다릅니다. 자동 변경하지 않았습니다.')
        originals[name] = data
    for file in old.rglob('*'):
        rel = file.relative_to(old)
        if file.is_symlink():
            raise ValueError('이전 실행기 안에 파일 링크가 있어 중단합니다.')
        if file.is_file() and '__pycache__' not in rel.parts and rel.as_posix() not in PINNED:
            raise ValueError('1.2.1 실행기에 예상하지 않은 파일이 있어 중단합니다: ' + str(rel))
    return originals


def candidate(originals):
    files = dict(originals)
    files['phone_candidate_fast.py'] = FAST_MODULE.encode('utf-8')
    service = originals['phone_service.py'].decode()
    service = replace_once(service,"VERSION = 'phone-service-19'","VERSION = 'phone-service-20'",'phone_service.py')
    service = replace_once(service,"MARKER = '# OKX phone service v19 managed boot hook'","MARKER = '# OKX phone service v20 managed boot hook'",'phone_service.py')
    service = replace_once(service,'LEGACY_MARKERS = (',"LEGACY_MARKERS = ('# OKX phone service v19 managed boot hook', ",'phone_service.py')
    files['phone_service.py'] = service.encode()
    mobile = originals['phone_mobile.py'].decode()
    if mobile.count('1.2.1') != 4: raise ValueError('mobile version mismatch')
    files['phone_mobile.py'] = mobile.replace('1.2.1','1.2.2').encode()
    update = originals['phone_update.py'].decode()
    update = replace_once(update,'CURRENT = 19','CURRENT = 20','phone_update.py')
    update = replace_once(update,"DISPLAY_VERSION = '1.2.1'","DISPLAY_VERSION = '1.2.2'",'phone_update.py')
    files['phone_update.py'] = update.encode()
    up = originals['phone_button_upgrade.py'].decode().replace('1.2.1','1.2.2')
    up = replace_once(up,"if matches != ['host-v18']:","if matches != ['host-v19']:",'phone_button_upgrade.py')
    files['phone_button_upgrade.py'] = up.encode()
    oldpins=json.loads(originals['phone_button_old_sources.json'])
    if HOST_OLD in oldpins: raise ValueError('duplicate predecessor')
    oldpins[HOST_OLD]=PINNED
    files['phone_button_old_sources.json']=(json.dumps(oldpins,ensure_ascii=False,indent=2)+'\n').encode()
    for name,data in files.items():
        if name.endswith('.py'): compile(data,name,'exec')
    return files


def stage(root, files):
    dest = root/HOST_NEW
    if dest.is_symlink():
        raise ValueError('host-v20 경로 링크 오류')
    if dest.exists():
        if not dest.is_dir():
            raise ValueError('host-v20은 폴더가 아닙니다.')
        seen = {}
        for file in dest.rglob('*'):
            rel = file.relative_to(dest)
            if file.is_symlink():
                raise ValueError('host-v20 내 파일 링크 오류')
            if file.is_file() and '__pycache__' not in rel.parts:
                seen[rel.as_posix()] = file.read_bytes()
        if seen != files:
            raise ValueError('다른 host-v20이 존재합니다. 덮어쓰지 않았습니다.')
        print('이미 검증된 1.2.2 파일이 준비되어 있습니다.')
        return dest
    tmp = Path(tempfile.mkdtemp(prefix='.host-v20-stage-', dir=root))
    try:
        for name, data in files.items():
            target = tmp/name
            with target.open('xb') as fp:
                fp.write(data)
                os.fchmod(fp.fileno(), 0o600)
        for name, data in files.items():
            if (tmp/name).read_bytes() != data:
                raise ValueError('설치 파일 저장 검증 실패')
        tmp.rename(dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    print('해시 확인된 1.2.2 파일 준비:', dest)
    return dest


def main():
    parser = argparse.ArgumentParser(description='OKX Fold3 1.2.2 신호 계산 지연 개선')
    parser.add_argument('--root', default=str(Path.home()/'okx-phone'))
    parser.add_argument('--stage-only', action='store_true', help='검증 및 파일 준비만 수행; 실행기 인계 없음')
    args = parser.parse_args()
    root = safe_path(args.root)
    dest = stage(root, candidate(read_pins(root)))
    if args.stage_only:
        return
    print('기존 보유/미체결/보호주문을 확인하고 안전 인계를 요청합니다.')
    print('보호 상태가 불확실하면 기존 실행기를 유지하고 설치를 보류합니다.')
    proc = subprocess.run([sys.executable, '-B', str(dest/'phone_button_upgrade.py'), '--root', str(root)],
                          cwd=str(dest), check=False)
    if proc.returncode:
        raise SystemExit('업데이트 보류: 기존 앱이 보유분 보호 중일 수 있습니다. 강제 종료하지 마세요.')
    print('설치 완료: 모바일 버전 1.2.2, 기존 운용 상태를 확인하세요.')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, UnicodeError) as exc:
        print('설치 보류:', str(exc))
        raise SystemExit(1)
