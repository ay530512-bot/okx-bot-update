"""Loopback dashboard, optionally reached through private Tailscale HTTPS Serve.

Strategy/engine modules are never patched. Desktop updater is unavailable here.
"""
import types
from pathlib import Path
from phone_update import PhoneUpdater
from phone_remote import valid_host


def mover_groups(rows):
    return (sorted((r for r in rows if r.get('change', 0) > 0), key=lambda r: -r['change'])[:5],
            sorted((r for r in rows if r.get('change', 0) < 0), key=lambda r: r['change'])[:5])


def mobile_module(source):
    text = (source / 'okx_mobile.py').read_text()
    patches = {
        'from okx_compact_chart import mover_groups': 'from phone_mobile import mover_groups',
        "if received_origin not in (origin,'https://'+service.config['https_host']):":
            'if received_origin != origin:',
        "if received_origin!='https://'+service.config['https_host']:":
            'if received_origin != origin:',
    }
    for old, new in patches.items():
        if text.count(old) != 1:
            raise ValueError('Unsupported mobile source; refusing adaptation')
        text = text.replace(old, new)
    module = types.ModuleType('phone_q2x_mobile')
    exec(compile(text, str(source / 'okx_mobile.py'), 'exec'), module.__dict__)
    module.valid_config = lambda c: (
        (c.get('https_host') == '' or valid_host(c.get('https_host'))) and
        bool(module.re.fullmatch('[0-9a-f]{32}', c.get('salt', ''))) and
        bool(module.re.fullmatch('[0-9a-f]{128}', c.get('password_hash', ''))))
    original_asset = module.asset

    def asset(name):
        data = original_asset(name).decode('utf-8')
        data = data.replace('PC', '폰').replace('집 폰', '이 폰')
        data = data.replace('폰와 프로그램 및 Tailscale 연결을 유지하세요.', 'Termux와 인터넷 연결을 유지하세요.')
        if name == 'index.html':
            data = data.replace('<main>', '<main><p class="phone-host-notice">집 폰 실행기 · 시각 조회 공유 v1 · 공개 시세 복구 v1 · 모바일 업데이트 v1 · 화면 여백 v1</p>', 1)
        if name == 'style.css':
            data += '\n.phone-host-notice{padding:12px;border:1px solid #444;border-radius:16px;color:#d0ff61}\n'
        if name == 'app.js':
            data += '\n' + Path(__file__).with_name('phone_update_ui.js').read_text()
        if name == 'style.css':
            data += '\n#part-settings #programUpdate{margin-top:32px;}\n'
        return data.encode('utf-8')
    module.asset = asset

    class PhoneMobile(module.Mobile):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.updater = PhoneUpdater(Path(args[0]).parent, self)
            self.hosts = {f'127.0.0.1:{self.port}', f'localhost:{self.port}'}
            self.set_remote(self.config.get('https_host', ''))

        def set_remote(self, host):
            if host and not valid_host(host):
                raise ValueError('허용되지 않은 원격 주소')
            with self.lock:
                self.config['https_host'] = host
                self.hosts = {f'127.0.0.1:{self.port}', f'localhost:{self.port}'}
                if host:
                    self.hosts.add(host)

        def enqueue_control(self, op, *args, **kwargs):
            if op not in {'update', 'prepare', 'confirm', 'pause', 'entry', 'close_one', 'close_all'}:
                raise ValueError('폰에서는 PC 업데이트를 실행할 수 없습니다.')
            if not self.config.get('controls_enabled', False):
                raise ValueError('조회 모드입니다. PC 종료 후 Termux에서 전환하세요.')
            if self.updater.installing and op in {'prepare', 'confirm', 'entry'}:
                raise ValueError('업데이트 설치 중입니다. 신규 진입을 시작하지 마세요.')
            return super().enqueue_control(op, *args, **kwargs)

        def capture(self, view):
            self.update_state = self.updater.snapshot()
            super().capture(view)
            with self.lock:
                self.snapshot['phone_host'] = True
                self.snapshot['external_access'] = bool(self.config.get('https_host'))

    module.PhoneMobile = PhoneMobile
    return module
