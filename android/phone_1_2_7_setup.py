#!/usr/bin/env python3
"""Verified 1.2.6 -> 1.2.7 restore uniform quarter allocation. Stage then safe serial handover. No exchange orders here."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PINNED = {'phone_migrate.py': 'aafbe024259d3f4dffc81b9b4ec7c9e9307a3487efeb969b1feed257f66399fb', 'phone_candidate_fast.py': '5680ed73e7fccd910847d6eecf8e0a428c47965139616583fe7402068d720b77', 'phone_account.py': '3c4c9f9cccaeaa60a41cc3ff3fdde68c04372aabcd8861098cefb8d918406f81', 'phone_migration_sources.json': '214293c5bf0d7fd79838b1037ab9499a2a5428c91758fe3df7c439d790e3691d', 'phone_clock.py': 'c1465b5e7d796937e16897c28d29d6ea78d4523b1c3a235a3384a97c2af7074c', 'phone_button_upgrade.py': '1ab69ef6eeb352fed6e9c2a2fb829b04ac76555f1024a35821eda24d0aa88c1e', 'phone_runtime_health.py': '4177c24e5da1806dd0ebc9afcfb13629562474e763c8a97cfe40af608905a38e', 'phone_performance.py': '44e502d4ac7491df5eb1a2759224a31787e0fce12225c99338a98610ecd4c535', 'phone_pullback_size.py': '556c076220d5af838cd6082a224388f1ac23869fd7f0c479a220d2f381887f41', 'phone_public_ws.py': '81e7a423c4a62081e25dbc7a30271d067fd09c84286311967fe4b6239b5b4582', 'phone_remote_check.py': '7d20cb6dcbbd2d784dab6c9fd8131722175d2f684b2202c3499fc13e8fd194d1', 'phone_button_old_sources.json': '9298e1f565f91003028210e1d99c6668c19f6248eec66843539c2d0728418e62', 'phone_feed_fast.py': '7dfd89a43397ef0e180b12bb0bac3537b04832b0018747fd425ee9b722641e8e', 'phone_connection_trace.py': '6beaf1d2bad2f0043a50c16c309cbd200dc4692c0686cab00cc519900249face', 'phone_handover.py': '11d26680baa581043998005af8b2016a40a4df1eff7730d9d34b10706c89523c', 'phone_sources.json': '1e8a54e5baff2e9f77aa48e1335dea650ae74cc1e5ebfaf562d796960d0838c7', 'phone_update_ui.js': '46ec3e67bfa0a16d8bd6b2f216eabad4e414e8193ae66a077990ee0e9ccb07cb', 'phone_update.py': '686a60c195b2459313885d4eae071159df064ac212e24d9a457e2ff4fc4f7372', 'phone_parallel.py': '63787c1d13932479b77fa10d7f18230daac679f1421da50834437fa957db5893', 'phone_frozen_bars.py': '03fbd57f0116046d27791b9e4dbbf3c1ddf8b17076b1115b066e28650ed674e2', 'phone_host.py': '21b9139454ff32c6afc7a4f0c9dece4540cc4cc9eb1d2a619c8e895f2b8afdce', 'phone_remote.py': 'f891e8cc8c8e822eb7f75ccd22d441b4b451162de0bf87a134b3c925e9073e97', 'phone_service.py': '17e8f8bdf667e846efcfa6b73760f6befcb9aa9f973655a6488d5cd04be1c3da', 'phone_signal_cache.py': '802a29462eac71f3e00d8bbbd30dd8de66aff2976b87f9b3b057754883931008', 'phone_mobile.py': '3fb0b6699681936f04c9deba03f4cc49a91b3eb8e48514a3ef509bc75183cc00'}
HOST_OLD = 'host-v24'
HOST_NEW = 'host-v25'
MODULES = {'phone_pullback_size.py': '"""Phone 1.2.7: use the pinned original quarter allocation for every route.\n\nThe former pullback-long sixteenth overlay is deliberately not installed.\nExisting positions, risk guards, and exchange configuration are untouched.\nThe updater starts a fresh interpreter before this validation runs.\n"""\nimport hashlib\nfrom pathlib import Path\n\nRISK_SOURCE_SHA256 = \'49fb7681b2ddbd894f40f1ea9e4985eeaec6c868568fb1fd37c2ffb95a37bd1d\'\n\n\ndef install(source):\n    import okx_risk732 as policy\n    path = Path(source) / \'okx_risk732.py\'\n    if (path.is_symlink() or not path.is_file()\n            or Path(policy.__file__).resolve() != path.resolve()):\n        raise ValueError(\'기본 1/4 주문량 규칙 · Q2X 원본 경로 불일치\')\n    if hashlib.sha256(path.read_bytes()).hexdigest() != RISK_SOURCE_SHA256:\n        raise ValueError(\'기본 1/4 주문량 규칙 · Q2X 원본 해시 불일치\')\n    if getattr(policy.cap_plan, \'phone_pullback_quarter_v120\', False):\n        raise ValueError(\'이전 1/16 주문량 규칙이 남아 있습니다. 새 실행기로 재시작 필요\')\n    if Path(policy.cap_plan.__code__.co_filename).resolve() != path.resolve():\n        raise ValueError(\'기본 1/4 주문량 함수 경로 불일치\')\n    # Retain the original function object, including reserve/lot/depth checks.\n', 'phone_mobile.py': '"""Loopback dashboard, optionally reached through private Tailscale HTTPS Serve.\n\nStrategy/engine modules are never patched. Desktop updater is unavailable here.\n"""\nimport types\nimport time\nfrom functools import lru_cache\nfrom pathlib import Path\nfrom phone_update import PhoneUpdater\nfrom phone_remote import valid_host\n\n\ndef mover_groups(rows):\n    return (sorted((r for r in rows if r.get(\'change\', 0) > 0), key=lambda r: -r[\'change\'])[:5],\n            sorted((r for r in rows if r.get(\'change\', 0) < 0), key=lambda r: r[\'change\'])[:5])\n\n\ndef mobile_module(source):\n    text = (source / \'okx_mobile.py\').read_text()\n    patches = {\n        \'from okx_compact_chart import mover_groups\': \'from phone_mobile import mover_groups\',\n        "if received_origin not in (origin,\'https://\'+service.config[\'https_host\']):":\n            \'if received_origin != origin:\',\n        "if received_origin!=\'https://\'+service.config[\'https_host\']:":\n            \'if received_origin != origin:\',\n    }\n    for old, new in patches.items():\n        if text.count(old) != 1:\n            raise ValueError(\'Unsupported mobile source; refusing adaptation\')\n        text = text.replace(old, new)\n    old_route = "\'/api/control/update\':\'update\'"\n    if text.count(old_route) != 1: raise ValueError("control route mismatch")\n    text = text.replace(old_route, old_route+",\'/api/control/calculation\':\'calculation\'")\n    module = types.ModuleType(\'phone_q2x_mobile\')\n    exec(compile(text, str(source / \'okx_mobile.py\'), \'exec\'), module.__dict__)\n    module.valid_config = lambda c: (\n        (c.get(\'https_host\') == \'\' or valid_host(c.get(\'https_host\'))) and\n        bool(module.re.fullmatch(\'[0-9a-f]{32}\', c.get(\'salt\', \'\'))) and\n        bool(module.re.fullmatch(\'[0-9a-f]{128}\', c.get(\'password_hash\', \'\'))))\n    original_asset = module.asset\n\n    @lru_cache(maxsize=3)\n    def asset(name):\n        data = original_asset(name).decode(\'utf-8\')\n        data = data.replace(\'PC\', \'폰\').replace(\'집 폰\', \'이 폰\')\n        data = data.replace(\'폰와 프로그램 및 Tailscale 연결을 유지하세요.\', \'Termux와 인터넷 연결을 유지하세요.\')\n        if name == \'index.html\':\n            data = data.replace(\'<main>\', \'<main><p class="phone-host-notice">OKX Ai trade - 1.2.7</p>\', 1)\n            data = data.replace(\'보유·미체결·조건주문이 있으면 설치 보류 · 자동 청산하지 않습니다.\',\n                \'신규 진입 자동 일시정지 · 보유분/거래소 손절 인계 후 기존 운용 복구 · 처리 중인 주문은 인계 보류\')\n        if name == \'style.css\':\n            data += \'\\n.phone-host-notice{padding:12px;border:1px solid #444;border-radius:16px;color:#d0ff61}\\n\'\n        if name == \'app.js\':\n            data += \'\\n\' + Path(__file__).with_name(\'phone_update_ui.js\').read_text()\n        if name == \'index.html\':\n            import re\n            data = re.sub(r\'<title>.*?</title>\', \'<title>OKX · 1.2.7</title>\', data)\n            data = re.sub(r\'(<p id="mobileBuild"[^>]*>).*?(</p>)\', r\'\\g<1>버전 1.2.7 · 15분봉 · KST 09시 기준\\g<2>\', data)\n        if name == \'app.js\':\n            data += \'\\nconst versionRender112 = render; render = function(d){versionRender112(d); $("mobileBuild").textContent="버전 1.2.7 · 15분봉 · KST 09시 기준";};\\n\'\n        if name == \'style.css\':\n            data += \'\\n#part-settings #programUpdate{margin-top:32px;}\\n\'\n        return data.encode(\'utf-8\')\n    module.asset = asset\n\n    class PhoneMobile(module.Mobile):\n        def __init__(self, *args, **kwargs):\n            super().__init__(*args, **kwargs)\n            self.calculation_root = Path(args[0]).parent\n            self._view_revision = None\n            self.capture_rebuilds = 0\n            self.capture_reuses = 0\n            self.updater = PhoneUpdater(Path(args[0]).parent, self)\n            self.hosts = {f\'127.0.0.1:{self.port}\', f\'localhost:{self.port}\'}\n            self.set_remote(self.config.get(\'https_host\', \'\'))\n\n        def set_remote(self, host):\n            if host and not valid_host(host):\n                raise ValueError(\'허용되지 않은 원격 주소\')\n            with self.lock:\n                self.config[\'https_host\'] = host\n                self.hosts = {f\'127.0.0.1:{self.port}\', f\'localhost:{self.port}\'}\n                if host:\n                    self.hosts.add(host)\n\n        def enqueue_control(self, op, *args, **kwargs):\n            if op == \'calculation\':\n                if not self.config.get(\'controls_enabled\', False) or self.updater.installing:\n                    raise ValueError(\'계산 방식 변경 대기\')\n                choice = kwargs.get(\'key\')\n                if choice not in (\'serial\', \'parallel4\'):\n                    raise ValueError(\'계산 방식 오류\')\n                owner, client_id = args[:2]\n                if not module.re.fullmatch(r\'[A-Za-z0-9_-]{12,80}\', client_id): raise ValueError(\'request id\')\n                request_id = module.hashlib.sha256((owner+\':\'+client_id).encode()).hexdigest()[:32]\n                from phone_parallel import set_preference\n                with self.lock:\n                    if request_id in self.control_results: return dict(self.control_results[request_id][\'public\'])\n                    now = time.monotonic()\n                    self.control_results = {k:v for k,v in self.control_results.items() if now-v[\'at\']<600}\n                    if len(self.control_results)>=128: raise ValueError(\'requests\')\n                    set_preference(self.calculation_root, 0 if choice == \'serial\' else 4)\n                    public = dict(request_id=request_id, status=\'done\', message=(\'기존 1.2.5 계산 방식 복원 요청\' if choice == \'serial\' else \'4개 분산 요청\')+\' · 다음 신호 검사부터 반영\')\n                    self.control_results[request_id] = dict(owner=owner, at=now, public=public)\n                    return public\n            if op not in {\'update\', \'prepare\', \'confirm\', \'pause\', \'entry\', \'close_one\', \'close_all\'}:\n                raise ValueError(\'폰에서는 PC 업데이트를 실행할 수 없습니다.\')\n            if not self.config.get(\'controls_enabled\', False):\n                raise ValueError(\'조회 모드입니다. PC 종료 후 Termux에서 전환하세요.\')\n            if self.updater.installing and op in {\'prepare\', \'confirm\', \'entry\'}:\n                raise ValueError(\'업데이트 설치 중입니다. 신규 진입을 시작하지 마세요.\')\n            return super().enqueue_control(op, *args, **kwargs)\n\n        def capture(self, view):\n            self.update_state = self.updater.snapshot()\n            revision = getattr(view, \'revision\', None)\n            if revision is None or revision != self._view_revision or not self.snapshot:\n                super().capture(view)\n                self._view_revision = revision\n                self.capture_rebuilds += 1\n            else:\n                # Reuse presentation arrays only until the next incoming event.\n                # Refresh age and controls every loop; never cache market reads.\n                with self.lock:\n                    self.snapshot[\'captured_ms\'] = int(time.time()*1000)\n                    self.snapshot[\'account_age_seconds\'] = max(0,time.monotonic()-view.data_seen) if view.data_seen else None\n                    self.snapshot[\'program_update\'] = module.clean(self.update_state,self.hidden)\n                    self.snapshot[\'controls_enabled\'] = self.config.get(\'controls_enabled\',True)\n                self.capture_reuses += 1\n            with self.lock:\n                self.snapshot[\'phone_host\'] = True\n                self.snapshot[\'display_work\'] = dict(rebuilds=self.capture_rebuilds,reuses=self.capture_reuses)\n                if hasattr(self, \'performance\'):\n                    self.snapshot[\'performance\'] = dict(self.performance.summary_cache)\n                self.snapshot[\'external_access\'] = bool(self.config.get(\'https_host\'))\n\n    module.PhoneMobile = PhoneMobile\n    return module\n'}

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
        raise ValueError('현재 1.2.6 host-v24 폴더를 확인하지 못했습니다.')
    originals = {}
    for name, checksum in PINNED.items():
        file = old/name
        if file.is_symlink() or not file.is_file():
            raise ValueError(name + ': 필수 원본 파일이 없습니다.')
        data = file.read_bytes()
        actual = digest(data)
        if actual != checksum:
            raise ValueError(name + ': 승인된 1.2.6 원본과 다릅니다. 자동 변경하지 않았습니다.')
        originals[name] = data
    for file in old.rglob('*'):
        rel = file.relative_to(old)
        if file.is_symlink():
            raise ValueError('이전 실행기 안에 파일 링크가 있어 중단합니다.')
        if file.is_file() and '__pycache__' not in rel.parts and rel.as_posix() not in PINNED:
            raise ValueError('1.2.6 실행기에 예상하지 않은 파일이 있어 중단합니다: ' + str(rel))
    return originals


def candidate(originals):
    files = dict(originals)
    for name, text in MODULES.items():
        files[name] = text.encode('utf-8')
    service = originals['phone_service.py'].decode()
    service = replace_once(service,"VERSION = 'phone-service-24'","VERSION = 'phone-service-25'",'phone_service.py')
    service = replace_once(service,"MARKER = '# OKX phone service v24 managed boot hook'","MARKER = '# OKX phone service v25 managed boot hook'",'phone_service.py')
    service = replace_once(service,'LEGACY_MARKERS = (',"LEGACY_MARKERS = ('# OKX phone service v24 managed boot hook', ",'phone_service.py')
    files['phone_service.py'] = service.encode()
    update = originals['phone_update.py'].decode()
    update = replace_once(update,'CURRENT = 24','CURRENT = 25','phone_update.py')
    update = replace_once(update,"DISPLAY_VERSION = '1.2.6'","DISPLAY_VERSION = '1.2.7'",'phone_update.py')
    files['phone_update.py'] = update.encode()
    up = originals['phone_button_upgrade.py'].decode().replace('1.2.6','1.2.7')
    up = replace_once(up,"if matches != ['host-v23']:","if matches != ['host-v24']:",'phone_button_upgrade.py')
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
        raise ValueError('host-v25 경로 링크 오류')
    if dest.exists():
        if not dest.is_dir():
            raise ValueError('host-v25은 폴더가 아닙니다.')
        seen = {}
        for file in dest.rglob('*'):
            rel = file.relative_to(dest)
            if file.is_symlink():
                raise ValueError('host-v25 내 파일 링크 오류')
            if file.is_file() and '__pycache__' not in rel.parts:
                seen[rel.as_posix()] = file.read_bytes()
        if seen != files:
            raise ValueError('다른 host-v25이 존재합니다. 덮어쓰지 않았습니다.')
        print('이미 검증된 1.2.7 파일이 준비되어 있습니다.')
        return dest
    tmp = Path(tempfile.mkdtemp(prefix='.host-v25-stage-', dir=root))
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
    print('해시 확인된 1.2.7 파일 준비:', dest)
    return dest


def main():
    parser = argparse.ArgumentParser(description='OKX Fold3 1.2.7 신규 진입 증거금 기본 1/4 통일')
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
    print('설치 완료: 모바일 버전 1.2.7, 기존 운용 상태를 확인하세요.')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, UnicodeError) as exc:
        print('설치 보류:', str(exc))
        raise SystemExit(1)
