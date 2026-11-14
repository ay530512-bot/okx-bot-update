#!/usr/bin/env python3
"""Verified Fold3 update: 1.1.9 to 1.2.0 (host-v17 to host-v18).

Build from an exact supported 1.1.9 installation. Preserve its idle WS
heartbeat, pinned Q2X source and user settings. Stage before requesting the
existing serial owner handover; never place or amend exchange orders here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PINNED = {
    'phone_host.py': 'abb926541d5acf4c646288dad4fb7bc2ee43e0a5fe5112e8951bd556123b8224',
    'phone_mobile.py': '3c214dbf42d68aa9e23964abe32524ce57430d4a9cc48912bbe2af0ecb033de1',
    'phone_account.py': '3c4c9f9cccaeaa60a41cc3ff3fdde68c04372aabcd8861098cefb8d918406f81',
    'phone_sources.json': '1e8a54e5baff2e9f77aa48e1335dea650ae74cc1e5ebfaf562d796960d0838c7',
    'phone_remote.py': 'f891e8cc8c8e822eb7f75ccd22d441b4b451162de0bf87a134b3c925e9073e97',
    'phone_service.py': '302689dcf8684d564374d7da3534319b9927ac363214acc34f7388f8b971e2b7',
    'phone_migrate.py': 'aafbe024259d3f4dffc81b9b4ec7c9e9307a3487efeb969b1feed257f66399fb',
    'phone_migration_sources.json': '214293c5bf0d7fd79838b1037ab9499a2a5428c91758fe3df7c439d790e3691d',
    'phone_remote_check.py': '7d20cb6dcbbd2d784dab6c9fd8131722175d2f684b2202c3499fc13e8fd194d1',
    'phone_clock.py': 'c1465b5e7d796937e16897c28d29d6ea78d4523b1c3a235a3384a97c2af7074c',
    'phone_connection_trace.py': '7bd09c14dca5a97069448106800b2afa640620e8e33472f440b7ec34afec68fb',
    'phone_public_ws.py': 'ba48a1e7dfc866545f9d67d81cde2bd14786bf45feb0333705bc3c171a2a5a95',
    'phone_performance.py': '11a2f7648e97f0eaa52e53561aca97cc9fa656020fbe4842dedb850c1ac5e146',
    'phone_signal_cache.py': '33369286afede27b4231c36ad650c51259e33f55ba2a7b1d675646121e371aba',
    'phone_update.py': 'f47d75829821bec6a2ee2f4b12e92cb7d9ecfa27f62dfa9b7690fcc85b6d8dbc',
    'phone_update_ui.js': 'db7e902358753679a89de868b75b0b269cd0517de33bf1ed614df33359b2c6d9',
    'phone_button_upgrade.py': '2fe1c14cf41706fdc7d89c51d0ae94e857e0bee0a3df454c6db0f6668d8fe195',
    'phone_button_old_sources.json': '432db7aae61eee9dfcb236d41f90c495b6452374e28837761bd0ccd173888b5f',
    'phone_handover.py': '11d26680baa581043998005af8b2016a40a4df1eff7730d9d34b10706c89523c',
}
# The audited manual setup differs from the button installer only in these
# two old-manifest checks (a valid older release remains noninstallable).
MANUAL_UPDATE_PIN = '285e9677afb59aee45707c9f8328a775114cbb7731909dec160fa1aa93b7dd5c'
HOST_V17 = 'host-v17'
HOST_V18 = 'host-v18'
MARGIN_MODULE = '"""Phone 1.2.0: quarter-size only a selected automatic 7.32 pullback long.\n\nKeeps Q2X\'s pinned original files, order proof, shared equity, reserve, leverage,\nlot rounding, depth checks and deterministic final recomputation. No I/O to the\nexchange, config changes, or changes to positions already open.\n"""\nimport ast\nfrom functools import wraps\nimport hashlib\nfrom pathlib import Path\nfrom types import FunctionType\n\nRISK_SOURCE_SHA256 = \'49fb7681b2ddbd894f40f1ea9e4985eeaec6c868568fb1fd37c2ffb95a37bd1d\'\nORIGINAL_TARGET = \'    target = equity / 4\\n\'\nSMALL_TARGET = \'    target = equity / 16\\n\'\n\n\ndef reduced(signal, direction):\n    if (direction != \'long\' or signal.get(\'action\') != \'LONG\'\n            or not signal.get(\'rule_channel701\')\n            or any(signal.get(k) for k in (\'click716\', \'user_chat_order\', \'selected_ai_order\'))):\n        return False\n    proof = (signal.get(\'decision_record\') or {}).get(\'volume_wick_proof\') or {}\n    return proof.get(\'route721\') == \'trend_pullback\' and proof.get(\'action\') == \'LONG\'\n\n\ndef install(source):\n    import okx_risk732 as policy\n\n    path = Path(source) / \'okx_risk732.py\'\n    if (path.is_symlink() or not path.is_file()\n            or Path(policy.__file__).resolve() != path.resolve()):\n        raise ValueError(\'눌림목 주문량 규칙 · Q2X 원본 경로 불일치\')\n    raw = path.read_bytes()\n    if hashlib.sha256(raw).hexdigest() != RISK_SOURCE_SHA256:\n        raise ValueError(\'눌림목 주문량 규칙 · Q2X 원본 해시 불일치\')\n\n    original = policy.cap_plan\n    if getattr(original, \'phone_pullback_quarter_v120\', False):\n        return\n    text = raw.decode(\'utf-8\')\n    matches = [node for node in ast.parse(text).body\n               if isinstance(node, ast.FunctionDef) and node.name == \'cap_plan\']\n    if len(matches) != 1:\n        raise ValueError(\'눌림목 주문량 규칙 · Q2X 수량 함수 불일치\')\n    node = matches[0]\n    cap_source = \'\'.join(text.splitlines(keepends=True)[node.lineno-1:node.end_lineno])\n    if (original.__code__.co_firstlineno != node.lineno\n            or cap_source.count(ORIGINAL_TARGET) != 1\n            or cap_source.count(\'시드 1/4\') != 3):\n        raise ValueError(\'눌림목 주문량 규칙 · Q2X 증거금 계산 불일치\')\n    cap_source = cap_source.replace(ORIGINAL_TARGET, SMALL_TARGET, 1)\n    cap_source = cap_source.replace(\'시드 1/4\', \'눌림목 롱 증거금\')\n    namespace = {}\n    exec(compile(\'\\n\'*(node.lineno-1)+cap_source, str(path), \'exec\'), namespace)\n    small = FunctionType(namespace[\'cap_plan\'].__code__, policy.__dict__, \'cap_plan\')\n\n    @wraps(original)\n    def cap_plan(e, plan, i, s, direction, snapshot, fee):\n        if not reduced(s, direction):\n            return original(e, plan, i, s, direction, snapshot, fee)\n        result = small(e, plan, i, s, direction, snapshot, fee)\n        result[\'risk732\'][\'target_multiplier\'] = \'0.25\'\n        return result\n\n    cap_plan.phone_pullback_quarter_v120 = True\n    policy.cap_plan = cap_plan\n'
HOST_ANCHOR = '    if run_engine:\n        from phone_public_ws import install as install_public_ws\n'
HOST_REPLACEMENT = '    if run_engine:\n        from phone_pullback_size import install as install_pullback_size\n        install_pullback_size(source)\n        from phone_public_ws import install as install_public_ws\n'


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
    old = root/HOST_V17
    if old.is_symlink() or not old.is_dir():
        raise ValueError('현재 1.1.9 host-v17 폴더를 확인하지 못했습니다.')
    originals = {}
    for name, checksum in PINNED.items():
        file = old/name
        if file.is_symlink() or not file.is_file():
            raise ValueError(name + ': 필수 원본 파일이 없습니다.')
        data = file.read_bytes()
        actual = digest(data)
        if actual != checksum and not (name == 'phone_update.py' and actual == MANUAL_UPDATE_PIN):
            raise ValueError(name + ': 승인된 1.1.9 원본과 다릅니다. 자동 변경하지 않았습니다.')
        originals[name] = data
    for file in old.rglob('*'):
        rel = file.relative_to(old)
        if file.is_symlink():
            raise ValueError('이전 실행기 안에 파일 링크가 있어 중단합니다.')
        if file.is_file() and '__pycache__' not in rel.parts and rel.as_posix() not in PINNED:
            raise ValueError('1.1.9 실행기에 예상하지 않은 파일이 있어 중단합니다: ' + str(rel))
    return originals


def candidate(originals):
    if not all((MARGIN_MODULE, HOST_ANCHOR, HOST_REPLACEMENT)):
        raise ValueError('1.2.0 주문 크기 변경 파일이 포함되지 않았습니다.')
    files = dict(originals)
    host = originals['phone_host.py'].decode('utf-8')
    files['phone_host.py'] = replace_once(host, HOST_ANCHOR, HOST_REPLACEMENT, 'phone_host.py').encode('utf-8')
    files['phone_pullback_size.py'] = MARGIN_MODULE.encode('utf-8')

    service = originals['phone_service.py'].decode('utf-8')
    service = replace_once(service, "VERSION = 'phone-service-17'", "VERSION = 'phone-service-18'", 'phone_service.py')
    service = replace_once(service, "MARKER = '# OKX phone service v17 managed boot hook'",
                           "MARKER = '# OKX phone service v18 managed boot hook'", 'phone_service.py')
    service = replace_once(service, 'LEGACY_MARKERS = (',
                           "LEGACY_MARKERS = ('# OKX phone service v17 managed boot hook', ", 'phone_service.py')
    files['phone_service.py'] = service.encode('utf-8')

    mobile = originals['phone_mobile.py'].decode('utf-8')
    if mobile.count('1.1.9') != 4:
        raise ValueError('모바일 버전 표기 검증 실패')
    files['phone_mobile.py'] = mobile.replace('1.1.9', '1.2.0').encode('utf-8')

    update = originals['phone_update.py'].decode('utf-8')
    if digest(originals['phone_update.py']) == PINNED['phone_update.py']:
        update = replace_once(update, "or data['version'] < CURRENT:", "or data['version'] < 1:", 'phone_update.py')
        update = replace_once(update, "if manifest['version'] == CURRENT:", "if manifest['version'] <= CURRENT:", 'phone_update.py')
    elif digest(originals['phone_update.py']) != MANUAL_UPDATE_PIN:
        raise ValueError('지원하지 않는 1.1.9 업데이트기입니다.')
    update = replace_once(update, 'CURRENT = 17', 'CURRENT = 18', 'phone_update.py')
    update = replace_once(update, "DISPLAY_VERSION = '1.1.9'", "DISPLAY_VERSION = '1.2.0'", 'phone_update.py')
    files['phone_update.py'] = update.encode('utf-8')

    up = originals['phone_button_upgrade.py'].decode('utf-8')
    if up.count('1.1.9') != 4:
        raise ValueError('안전 인계 버전 표기 검증 실패')
    up = up.replace('1.1.9', '1.2.0')
    predecessor_error = "        raise ValueError('지원하는 기존 실행기를 확인하지 못했습니다.')"
    up = replace_once(up, '    if len(matches) != 1:\n' + predecessor_error,
                      "    if matches != ['host-v17']:\n" + predecessor_error, 'phone_button_upgrade.py')
    up = replace_once(up,
        "        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:\n"
        "            raise ValueError('기존 실행기 원본이 다릅니다. 자동 교체하지 않았습니다.')\n",
        "        if p.is_symlink() or not p.is_file():\n"
        "            raise ValueError('기존 실행기 원본이 다릅니다. 자동 교체하지 않았습니다.')\n"
        "        actual = hashlib.sha256(p.read_bytes()).hexdigest()\n"
        "        alternate = (folder.name == 'host-v17' and name == 'phone_update.py'\n"
        f"                     and actual == '{MANUAL_UPDATE_PIN}')\n"
        "        if actual != expected and not alternate:\n"
        "            raise ValueError('기존 실행기 원본이 다릅니다. 자동 교체하지 않았습니다.')\n",
        'phone_button_upgrade.py')
    up = replace_once(up, "            print('1.2.0 설치 완료 · 기존 매매 규칙/포지션 관리 기록/설정 유지', flush=True)",
        "            print('1.2.0 설치 완료 · 기존 포지션 기록/설정 유지 · 새 추세 눌림목 롱 주문 크기 1/4', flush=True)",
        'phone_button_upgrade.py')
    up = replace_once(up,
        "    try:\n        upgrade(Path.home()/'okx-phone')\n",
        "    import argparse\n"
        "    parser = argparse.ArgumentParser(description='Fold3 1.2.0 안전 인계')\n"
        "    parser.add_argument('--root', type=Path, default=Path.home()/'okx-phone')\n"
        "    args = parser.parse_args()\n"
        "    try:\n        upgrade(args.root)\n",
        'phone_button_upgrade.py')
    up = replace_once(up, "            result(Path.home()/'okx-phone', 'deferred'", "            result(args.root, 'deferred'",
                      'phone_button_upgrade.py')
    files['phone_button_upgrade.py'] = up.encode('utf-8')

    oldpins = json.loads(originals['phone_button_old_sources.json'])
    if HOST_V17 in oldpins:
        raise ValueError('원본에 알 수 없는 host-v17 고정값이 있습니다.')
    oldpins[HOST_V17] = dict(PINNED)
    files['phone_button_old_sources.json'] = (json.dumps(oldpins, ensure_ascii=False, indent=2)+'\n').encode('utf-8')

    for name, data in files.items():
        if name.endswith('.py'):
            compile(data.decode('utf-8'), name, 'exec')
    return files


def stage(root, files):
    dest = root/HOST_V18
    if dest.is_symlink():
        raise ValueError('host-v18 경로 링크 오류')
    if dest.exists():
        if not dest.is_dir():
            raise ValueError('host-v18은 폴더가 아닙니다.')
        seen = {}
        for file in dest.rglob('*'):
            rel = file.relative_to(dest)
            if file.is_symlink():
                raise ValueError('host-v18 내 파일 링크 오류')
            if file.is_file() and '__pycache__' not in rel.parts:
                seen[rel.as_posix()] = file.read_bytes()
        if seen != files:
            raise ValueError('다른 host-v18이 존재합니다. 덮어쓰지 않았습니다.')
        print('이미 검증된 1.2.0 파일이 준비되어 있습니다.')
        return dest
    tmp = Path(tempfile.mkdtemp(prefix='.host-v18-stage-', dir=root))
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
    print('해시 확인된 1.2.0 파일 준비:', dest)
    return dest


def main():
    parser = argparse.ArgumentParser(description='OKX Fold3 1.2.0 눌림목 롱 주문 크기 변경')
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
    print('설치 완료: 모바일 버전 1.2.0, 기존 운용 상태를 확인하세요.')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, UnicodeError) as exc:
        print('설치 보류:', str(exc))
        raise SystemExit(1)
