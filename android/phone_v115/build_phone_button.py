"""Build deterministic offline host-v13 updater from these reviewed files."""
import base64
import hashlib
import io
from pathlib import Path
import zipfile

FILES = ('phone_host.py', 'phone_mobile.py', 'phone_account.py', 'phone_sources.json',
         'phone_remote.py', 'phone_service.py', 'phone_migrate.py', 'phone_migration_sources.json',
         'phone_remote_check.py', 'phone_clock.py', 'phone_connection_trace.py', 'phone_public_ws.py', 'phone_performance.py', 'phone_signal_cache.py', 'phone_update.py', 'phone_update_ui.js', 'phone_button_upgrade.py', 'phone_button_old_sources.json')

BOOTSTRAP = r'''#!/usr/bin/env python3
"""Public market recovery update. Stage immutable files; apply only to a flat, paused phone."""
import base64, hashlib, io, os, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path
PAYLOAD = __PAYLOAD__
DIGEST = __DIGEST__
FILES = __FILES__

def install(root=None):
    os.umask(0o077)
    root = Path(root or Path.home()/'okx-phone')
    if root.is_symlink() or not root.is_dir():
        raise ValueError('기존 폰 설치 폴더가 없습니다.')
    for name in ('phone_owner.json', 'phone_installation.json', 'phone_credentials.json', 'strategy_config.json'):
        if (root/name).is_symlink() or not (root/name).is_file():
            raise ValueError('폰 전환 완료 기록 또는 설정 파일이 없습니다.')
    raw = base64.b64decode(PAYLOAD, validate=True)
    if hashlib.sha256(raw).hexdigest() != DIGEST:
        raise ValueError('설치 파일 검증 실패')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if set(z.namelist()) != set(FILES) or len(z.namelist()) != len(FILES):
            raise ValueError('설치 구성 불일치')
        parts = {name: z.read(name) for name in FILES}
    for name, data in parts.items():
        if name.endswith('.py'):
            compile(data, name, 'exec')
    target = root/'host-v13'
    if target.is_symlink():
        raise ValueError('새 실행기 폴더 링크 오류')
    if target.exists():
        for name, data in parts.items():
            p = target/name
            if p.is_symlink() or not p.is_file() or p.read_bytes() != data:
                raise ValueError('이미 있는 host-v13 내용이 다릅니다. 덮어쓰지 않았습니다.')
        for p in target.rglob('*'):
            rel = p.relative_to(target)
            if p.is_symlink() or (p.is_file() and '__pycache__' not in rel.parts and rel.as_posix() not in FILES):
                raise ValueError('새 실행기 폴더에 알 수 없는 파일이 있습니다.')
    else:
        temp = Path(tempfile.mkdtemp(prefix='.public-fix-', dir=root))
        try:
            for name, data in parts.items():
                p = temp/name
                p.write_bytes(data)
                p.chmod(0o600)
            os.rename(temp, target)
        finally:
            if temp.exists():
                shutil.rmtree(temp)
    return target/'phone_button_upgrade.py'

if __name__ == '__main__':
    try:
        if '--report' in sys.argv:
            script = Path.home()/'okx-phone'/'host-v13'/'phone_connection_trace.py'
            os.execv(sys.executable, [sys.executable, '-B', str(script)])
        script = install()
        print('모바일 업데이트 파일 검증 완료 · 적용 전 보유/주문/중지 상태를 확인합니다.', flush=True)
        if '--install-only' not in sys.argv:
            completed = subprocess.run([sys.executable, '-B', str(script)], check=False)
            if completed.returncode != 0:
                sys.exit(completed.returncode)
            print('설치 완료. 아이폰 화면을 새로고침하고 1.1.5을 확인하세요.', flush=True)
    except Exception as error:
        print('설치 보류:', str(error) if isinstance(error, ValueError) else type(error).__name__, flush=True)
        sys.exit(1)
'''


def build(output=None):
    here = Path(__file__).resolve().parent
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in FILES:
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 13, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, (here/name).read_bytes())
    raw = buffer.getvalue()
    text = BOOTSTRAP.replace('__PAYLOAD__', repr(base64.b64encode(raw).decode()))
    text = text.replace('__DIGEST__', repr(hashlib.sha256(raw).hexdigest()))
    text = text.replace('__FILES__', repr(FILES))
    path = Path(output or here.parent/'phone_1_1_5_setup.py')
    path.write_text(text)
    return path


if __name__ == '__main__':
    print(build())
