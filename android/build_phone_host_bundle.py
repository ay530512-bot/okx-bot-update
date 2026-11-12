"""Build a generic host installer: no API keys, user config or account journal."""
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile

FILES = ('phone_host.py', 'phone_mobile.py', 'phone_account.py', 'phone_sources.json',
         'phone_remote.py', 'phone_service.py')
BOOTSTRAP = r'''#!/usr/bin/env python3
"""Generic phone host setup. Uses the already configured private phone directory."""
import base64, hashlib, io, os, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path
PAYLOAD = __PAYLOAD__
DIGEST = __DIGEST__
FILES = __FILES__

def install(root=None):
    os.umask(0o077)
    root = Path(root or Path.home()/'okx-phone')
    if root.is_symlink(): raise ValueError('폰 폴더 링크는 사용할 수 없습니다.')
    for name in ('phone_credentials.json','phone_installation.json','strategy_config.json'):
        if not (root/name).is_file() or (root/name).is_symlink():
            raise ValueError('기존 폰 계정 설정 파일이 없습니다: '+name)
    raw = base64.b64decode(PAYLOAD, validate=True)
    if hashlib.sha256(raw).hexdigest()!=DIGEST: raise ValueError('실행기 해시 불일치')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if set(z.namelist())!=set(FILES) or len(z.namelist())!=len(FILES):
            raise ValueError('실행기 구성 오류')
        parts={name:z.read(name) for name in FILES}
    target=root/'host-v2'
    if target.is_symlink(): raise ValueError('기존 실행기 링크는 사용할 수 없습니다.')
    if target.exists():
        for name,data in parts.items():
            p=target/name
            if p.is_symlink() or not p.is_file() or p.read_bytes()!=data:
                raise ValueError('기존 폰 실행기가 다릅니다. 덮어쓰지 않았습니다.')
        for p in target.rglob('*'):
            rel=p.relative_to(target)
            if p.is_symlink() or (p.is_file() and '__pycache__' not in rel.parts and rel.as_posix() not in FILES):
                raise ValueError('폰 실행기에 추가 파일이 있습니다. 덮어쓰지 않았습니다.')
    else:
        temp=Path(tempfile.mkdtemp(prefix='.host-',dir=root))
        try:
            for name,data in parts.items():
                p=temp/name;p.write_bytes(data);p.chmod(0o600)
            os.rename(temp,target)
        finally:
            if temp.exists(): shutil.rmtree(temp)
    return target/'phone_service.py'

if __name__=='__main__':
    try:
        host=install()
        print('집 폰 실행기 설치 완료 · 기존 설정/계정/PC 파일 유지',flush=True)
        if '--install-only' not in sys.argv:
            wake=shutil.which('termux-wake-lock')
            if wake: subprocess.run([wake],check=False)
            os.execv(sys.executable,[sys.executable,'-B',str(host),'--setup'])
    except Exception as exc:
        print('설치 보류:',str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        sys.exit(1)
'''


def build(output=None):
    here = Path(__file__).resolve().parent
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in FILES:
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 13, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (here/name).read_bytes())
    raw = payload.getvalue()
    script = BOOTSTRAP.replace('__PAYLOAD__', repr(base64.b64encode(raw).decode()))
    script = script.replace('__DIGEST__', repr(hashlib.sha256(raw).hexdigest()))
    script = script.replace('__FILES__', repr(FILES))
    path = Path(output or here/'phone_home_setup.py')
    path.write_text(script)
    return path


if __name__ == '__main__':
    print(build())
