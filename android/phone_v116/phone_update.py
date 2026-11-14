"""Phone-only, on-demand GitHub release check; no trading API or core edits."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.request

CURRENT = 14
DISPLAY_VERSION = '1.1.6'
BASE = 'https://raw.githubusercontent.com/ay530512-bot/okx-bot-update/'
CHANNEL = BASE + 'main/android/phone_latest.json'
MAX_INSTALLER = 2_000_000

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('다운로드 주소 변경을 허용하지 않습니다.')

def download(url, limit):
    request = urllib.request.Request(url, headers={'User-Agent': 'OKX-Phone-Updater/1', 'Cache-Control': 'no-cache'})
    deadline = time.monotonic() + 25
    with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
        if response.status != 200:
            raise ValueError('GitHub 응답 오류')
        chunks, size = [], 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                return b''.join(chunks)
            size += len(chunk)
            if size > limit or time.monotonic() > deadline:
                raise ValueError('다운로드 크기 또는 시간 제한 초과')
            chunks.append(chunk)

def validate_manifest(data):
    if not isinstance(data, dict) or data.get('format') != 'okx-phone-release-1':
        raise ValueError('폰 전용 배포 형식이 아닙니다.')
    if type(data.get('version')) is not int or data['version'] < CURRENT:
        raise ValueError('이전 버전으로 자동 변경하지 않습니다.')
    if not isinstance(data.get('notes'), str) or len(data['notes']) > 2000:
        raise ValueError('변경 내용 형식 오류')
    if not re.fullmatch('[0-9a-f]{40}', str(data.get('commit', ''))):
        raise ValueError('고정 배포 커밋 오류')
    if not re.fullmatch(r'android/[A-Za-z0-9_/-]+\.py', str(data.get('installer', ''))) or '..' in data['installer']:
        raise ValueError('설치 경로 오류')
    if not re.fullmatch('[0-9a-f]{64}', str(data.get('sha256', ''))):
        raise ValueError('파일 해시 오류')
    if type(data.get('bytes')) is not int or not 0 < data['bytes'] <= MAX_INSTALLER:
        raise ValueError('설치 크기 오류')
    if data['version'] > CURRENT and CURRENT not in data.get('from_versions', []):
        raise ValueError('현재 폰 버전에서 설치할 수 없는 배포입니다.')
    if 'display_version' in data and not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', str(data['display_version'])):
        raise ValueError('표시 버전 형식 오류')
    return data

class PhoneUpdater:
    def __init__(self, root, mobile):
        self.root, self.mobile = Path(root), mobile
        self.lock = threading.RLock()
        self.installing = False
        self.candidate = None
        self.state = dict(busy=False, current_version=CURRENT, display_version=DISPLAY_VERSION, message='현재 버전 '+DISPLAY_VERSION+' · 새 버전 확인')

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def finish(self, command, message, failed=False):
        self.mobile.complete_control(dict(request_id=command['request_id'], owner=command['owner'],
            status='failed' if failed else 'done', message=message))

    def request(self, command):
        with self.lock:
            if self.state['busy'] or time.monotonic()-command['issued_at'] > 30:
                self.finish(command, '다른 업데이트 요청 처리 중이거나 요청이 만료되었습니다.', True)
                return
            self.state.update(busy=True, message='GitHub 폰 배포 확인 중…')
            threading.Thread(target=self.run, args=(dict(command),), daemon=True).start()

    def run(self, command):
        try:
            if command.get('ticket'):
                self.install(command)
            else:
                self.check(command)
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else '연결 또는 설치 확인 실패 · 기존 실행 상태를 확인하세요.'
            with self.lock:
                self.state.update(message=message)
            self.finish(command, message, True)
        finally:
            with self.lock:
                self.state['busy'] = False
                self.installing = False

    def check(self, command):
        with self.lock:
            self.candidate = None
            self.state.pop('ticket', None)
            self.state.pop('notes', None)
        manifest = validate_manifest(json.loads(download(CHANNEL, 16384)))
        if manifest['version'] == CURRENT:
            message = '최신 폰 버전입니다. 재시작하지 않았습니다.'
        else:
            raw = download(BASE+manifest['commit']+'/'+manifest['installer'], MAX_INSTALLER)
            if len(raw) != manifest['bytes'] or hashlib.sha256(raw).hexdigest() != manifest['sha256']:
                raise ValueError('설치 파일 검증 실패 · 실행하지 않았습니다.')
            compile(raw, 'verified_phone_update.py', 'exec')
            token = secrets.token_urlsafe(32)
            with self.lock:
                self.candidate = dict(manifest=manifest, raw=raw, ticket=token, owner=command['owner'], expires=time.monotonic()+600)
                self.state.update(ticket=token, target_version=manifest.get('display_version', str(manifest['version'])), notes=manifest['notes'])
            message = '새 폰 버전 '+manifest.get('display_version', str(manifest['version']))+' 준비 · 변경 내용 확인 후 설치하세요.'
        with self.lock:
            self.state['message'] = message
        self.finish(command, message)

    def install(self, command):
        from phone_button_upgrade import require_paused_flat_journal
        from phone_account import atomic_private
        with self.lock:
            candidate = self.candidate
            if (not candidate or candidate['owner'] != command['owner'] or time.monotonic() >= candidate['expires']
                    or not secrets.compare_digest(candidate['ticket'], str(command['ticket']))):
                self.candidate = None
                self.state.pop('ticket', None)
                raise ValueError('설치 확인이 만료되었거나 요청자가 다릅니다. 새 버전을 다시 확인하세요.')
            require_paused_flat_journal(self.root)
            self.installing = True
            self.candidate = None
            self.state.pop('ticket', None)
            self.state['message'] = '설치 준비 · 계정/주문 확인 후 재시작합니다. 완료 후 새로고침하세요.'
        # The reviewed release installer rechecks exchange positions/orders before
        # and after graceful shutdown. Detached child survives the old host exit.
        cache = self.root/'phone-update-cache'
        if cache.is_symlink():
            raise ValueError('업데이트 폴더 링크 오류')
        cache.mkdir(mode=0o700, exist_ok=True)
        path = cache/(candidate['manifest']['sha256']+'.py')
        if path.is_symlink():
            raise ValueError('업데이트 파일 링크 오류')
        atomic_private(path, candidate['raw'])
        log = cache/'last-install.log'
        if log.is_symlink():
            raise ValueError('업데이트 기록 링크 오류')
        fd = os.open(log, os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as out:
            child = subprocess.Popen([sys.executable, '-B', str(path)], stdin=subprocess.DEVNULL,
                stdout=out, stderr=out, start_new_session=True, close_fds=True)
        self.finish(command, self.state['message'])
        code = child.wait()
        if code:
            raise ValueError('설치 보류 또는 복원됨 · 보유/주문·신규 진입 중지 상태를 확인하세요. 상세: phone-update-cache/last-install.log')
        with self.lock:
            self.state['message'] = '설치 절차 종료 · 화면 새로고침 후 버전과 실행 상태를 확인하세요.'
