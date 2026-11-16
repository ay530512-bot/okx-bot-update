"""Explicit offline-installed release restore using the same safe handover.

No order/setting writes. Original host files and boot registration are verified.
Invoke only on the phone when the user chooses to return to the previous build.
"""
import hashlib
import os
from pathlib import Path
import re
import sys
import phone_button_upgrade as u


def verify(root):
    data = u.read_json(root/'phone_mobile151_previous.json')
    name = data.get('host', '')
    if not re.fullmatch(r'host-v[0-9]+', name): raise ValueError('복원 경로 오류')
    target = root/name
    pins = u.read_json(u.HERE/'phone_button_old_sources.json').get(name)
    if not pins or target.is_symlink(): raise ValueError('복원 원본 확인 실패')
    for n, h in pins.items():
        p = target/n
        if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            raise ValueError('이전 버전 원본이 변경되어 복원 보류')
    for p in target.rglob('*'):
        if p.is_symlink() or (p.is_file() and '__pycache__' not in p.relative_to(target).parts and p.relative_to(target).as_posix() not in pins):
            raise ValueError('이전 버전의 알 수 없는 파일')
    boot = bytes.fromhex(data['boot_hex'])
    if hashlib.sha256(boot).hexdigest() != data['boot_sha256'] or str(target/'phone_service.py').encode() not in boot:
        raise ValueError('복원 자동 시작 기록 오류')
    return target, boot


def restore(root):
    if root.is_symlink(): raise ValueError('폰 폴더 링크 오류')
    root = root.resolve(strict=True)
    with u.service.lock(root, 'phone_clock_upgrade.lock'):
        target, old_boot = verify(root)
        boot = Path.home()/'.termux/boot/40-okx-home'
        if any(p.is_symlink() for p in (boot, boot.parent, boot.parent.parent)):
            raise ValueError('자동 시작 파일 링크 오류')
        if str(u.HERE/'phone_service.py') not in boot.read_text():
            raise ValueError('현재 새 모바일 실행기가 아니므로 복원 보류')
        _, pins = u.verified_installation(root)
        api = u.readonly_client(u.validate_keys(u.read_json(root/'phone_credentials.json')))
        try:
            u.inspect_account(api, root, pins)
            u.rollback(root, target, boot, old_boot)
            u.result(root, 'restored_previous', message='이전 실행기로 복원 · 보유/보호 확인 후 운용 복구')
        finally:
            api.session.close()
        print('이전 버전 실행 요청 완료. 화면의 버전과 연결·보호 상태를 확인하세요.')


if __name__ == '__main__':
    os.umask(0o077)
    try: restore(Path.home()/'okx-phone')
    except Exception as error:
        print('복원 보류:', str(error) if isinstance(error, ValueError) else type(error).__name__)
        sys.exit(1)
