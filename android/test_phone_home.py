import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch, Mock

import phone_remote as remote
import phone_service as service
import phone_host as host
from phone_account import save_json
import test_phone_host as base_tests
API = base_tests.API
snapshot = base_tests.snapshot


class PrivateRemoteUI(base_tests.LocalUI):
    def setUp(self):
        super().setUp()
        self.remote = 'okx-fold-home.tailfixture.ts.net:8443'
        self.mobile.set_remote(self.remote)
        self.remote_origin = 'https://' + self.remote

    def test_https_secure_cookie_and_private_control(self):
        status, _, cookie = self.post('/login', {'password': 'fixture-password'}, origin=self.remote_origin, hostname=self.remote)
        self.assertEqual(status, 200)
        self.assertIn('; Secure', cookie)
        self.cookie = cookie.split(';')[0]
        result = self.post('/api/control/prepare', {'client_id': 'remote-fixture-1'}, origin=self.remote_origin, hostname=self.remote)
        self.assertEqual(result[0], 202)
        self.assertEqual(self.mobile.control_commands.get_nowait()['op'], 'prepare')
        self.assertEqual(self.mobile.server.server_address[0], '127.0.0.1')

    def test_remote_http_origin_and_mixed_origin_rejected(self):
        for origin, hostname in [('http://'+self.remote, self.remote), (self.remote_origin, self.address), (self.origin, self.remote)]:
            self.assertEqual(self.post('/login', {'password': 'fixture-password'}, origin=origin, hostname=hostname)[0], 403)

    def test_remote_revoked_without_engine_restart(self):
        self.mobile.set_remote('')
        self.assertEqual(self.post('/login', {'password': 'fixture-password'}, origin=self.remote_origin, hostname=self.remote)[0], 403)
        self.login()

    def test_host_restricts_exact_hostname(self):
        for name in ['evil.invalid', '0.0.0.0:8768', 'okx.tailfixture.ts.net:443', 'https://okx.tailfixture.ts.net:8443', 'a.b.ts.net:8443/']:
            with self.assertRaises(ValueError):
                self.mobile.set_remote(name)


class FreshServiceStart(unittest.TestCase):
    setUp = base_tests.HostGuards.setUp
    tearDown = base_tests.HostGuards.tearDown
    own = base_tests.HostGuards.own
    def test_pending_claim_requires_empty_account_again(self):
        self.own()
        host.verify_service_start(self.root, self.runtime, API(), self.pins)
        data = snapshot(); data['positions'] = [dict(pos='1')]
        with self.assertRaises(ValueError):
            host.verify_service_start(self.root, self.runtime, API([data]), self.pins)

    def test_consumed_pending_cannot_recreate_deleted_journal(self):
        self.own()
        owner = host.read_json(self.root/'phone_owner.json'); owner['first_start_pending'] = False
        save_json(self.root/'phone_owner.json', owner)
        with self.assertRaises(ValueError):
            host.verify_service_start(self.root, self.runtime, API(), self.pins)

    def test_partial_initialization_cannot_reset_orphan_files(self):
        self.own()
        (self.runtime/'pending-orders.json').write_text('{}')
        with self.assertRaises(ValueError):
            host.verify_service_start(self.root, self.runtime, API(), self.pins)

    def test_owned_journal_recovery_does_not_require_flat(self):
        self.own()
        (self.runtime/'bot_state.json').write_text(json.dumps(dict(account=hashlib.sha256(b'fixture-account').hexdigest())))
        data = snapshot(); data['positions'] = [dict(pos='1')]
        host.verify_service_start(self.root, self.runtime, API([data]), self.pins)


class Transport(unittest.TestCase):
    def test_status_must_be_authenticated_and_exact_private_dns(self):
        data = dict(BackendState='Running', Self=dict(DNSName='okx-fold-home.tailfixture.ts.net.'))
        self.assertEqual(remote.host_from_status(data), 'okx-fold-home.tailfixture.ts.net:8443')
        for other in [dict(data, BackendState='NeedsLogin'), dict(data, Self=dict(DNSName='evil.invalid'))]:
            with self.assertRaises(ValueError):
                remote.host_from_status(other)

    def test_serve_only_private_exact_local_backend(self):
        hostname = 'okx-fold-home.tailfixture.ts.net:8443'
        data = dict(TCP={'8443': {'HTTPS': True}}, Web={hostname: {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8768'}}}})
        remote.verify_serve(data, hostname)
        variants = [dict(data, AllowFunnel={hostname: True}), dict(data, TCP={'8443': {'HTTPS': False}}), dict(data, Services={'x': {}})]
        changed = copy.deepcopy(data); changed['Web'][hostname]['Handlers']['/']['Proxy'] = 'http://192.168.1.1:80'
        variants.append(changed)
        for invalid in variants:
            with self.assertRaises(ValueError):
                remote.verify_serve(invalid, hostname)

    def test_corrupt_download_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                remote.unpack(b'not an archive', Path(tmp), 'arm64')
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_binary_hash_or_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'tailscale').write_bytes(b'wrong')
            (root/'tailscaled').symlink_to(root/'tailscale')
            with self.assertRaises(ValueError):
                remote.verify_binaries(root, 'arm64')

    def test_no_routes_public_proxy_or_privileged_tun(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(remote, 'verify_binaries'):
            args = remote.daemon_command(Path(tmp))
            self.assertIn('--tun=userspace-networking', args)
            self.assertFalse(any('socks5' in x or 'http-proxy' in x for x in args))
            self.assertTrue(any(x.endswith('tailscaled.state') for x in args))


class ServiceSettings(unittest.TestCase):
    def test_boot_preserves_normal_stop_and_never_claims_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_json(root/'phone_service.json', dict(mode='watch', enabled=False))
            with patch.object(service, 'spawn_logged') as spawn:
                service.start(root)
                spawn.assert_not_called()
            self.assertNotIn('--takeover', service.worker_command(root, 'watch'))
            self.assertNotIn('--takeover', service.worker_command(root, 'run'))
            self.assertIn('--run', service.worker_command(root, 'run'))

    def test_watch_owner_and_missing_owner_run_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_json(root/'phone_service.json', dict(mode='run', enabled=True))
            with self.assertRaises(ValueError): service.config(root)
            (root/'phone_owner.json').write_text('{}')
            save_json(root/'phone_service.json', dict(mode='watch', enabled=True))
            with self.assertRaises(ValueError): service.config(root)

    def test_boot_script_quoted_and_unrelated_hook_preserved(self):
        with tempfile.TemporaryDirectory(prefix='phone home ') as tmp:
            home = Path(tmp); root = home/'okx-phone'; root.mkdir()
            service.boot_script(root, home)
            hook = home/'.termux/boot/40-okx-home'
            self.assertIn('--boot', hook.read_text())
            self.assertNotIn('--handover', hook.read_text())
            subprocess.run(['sh', '-n', str(hook)], check=True)
            hook.write_text('unrelated custom hook')
            with self.assertRaises(ValueError): service.boot_script(root, home)
            self.assertEqual(hook.read_text(), 'unrelated custom hook')

    def test_log_bounded_and_lock_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root/'host.log'
            path.write_bytes(b'x'*(5*1024*1024))
            service.trim_log(path)
            self.assertEqual(path.stat().st_size, 1024*1024)
            with service.lock(root, 'fixture.lock'):
                self.assertTrue(service.running(root, 'fixture.lock'))
            self.assertFalse(service.running(root, 'fixture.lock'))
        self.assertEqual(service.retry_delay(100), 60)


STUB_WORKER = '''import sys, signal, time, fcntl, pathlib, json
root=pathlib.Path(sys.argv[sys.argv.index('--root')+1]);lock=(root/'phone_host.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
count=root/'starts';n=int(count.read_text())+1 if count.exists() else 1;count.write_text(str(n))
if (root/'crash-first').exists() and n==1:sys.exit(7)
stop=[False]
def request(*args):
 (root/'stop-seen').write_text('yes')
 if not (root/'protected-position').exists():stop[0]=True
signal.signal(signal.SIGTERM,request)
while not stop[0]:time.sleep(.1)
'''
STUB_REMOTE = '''import sys
def daemon_command(root):
 return [sys.executable,'-c','import time; time.sleep(300)']
'''
STUB_WORKER = ('import json\ndef read_json(path): return json.loads(path.read_text())\n'
               'if __name__ == "__main__":\n' + textwrap.indent(STUB_WORKER, ' '))


class SupervisorProcess(unittest.TestCase):
    def prepare(self, root):
        for name in ('phone_service.py', 'phone_account.py'):
            shutil.copyfile(Path(__file__).parent/name, root/name)
        (root/'phone_host.py').write_text(STUB_WORKER)
        (root/'phone_remote.py').write_text(STUB_REMOTE)
        save_json(root/'phone_service.json', dict(mode='watch', enabled=True))
        (root/'journal-sentinel').write_bytes(b'existing immutable test record')

    def wait_for(self, predicate, seconds=12):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.1)
        self.fail('timed out')

    def test_crash_restart_duplicate_guard_and_clean_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.prepare(root); (root/'crash-first').touch()
            p = subprocess.Popen([sys.executable, str(root/'phone_service.py'), '--root', str(root), '--supervise'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.wait_for(lambda: (root/'starts').exists() and (root/'starts').read_text() == '2')
                second = subprocess.run([sys.executable, str(root/'phone_service.py'), '--root', str(root), '--supervise'], capture_output=True, timeout=3)
                self.assertNotEqual(second.returncode, 0)
                save_json(root/'phone_stop_request.json', {})
                p.wait(timeout=12)
                self.assertEqual(p.returncode, 0)
                self.assertFalse(json.loads((root/'phone_service.json').read_text())['enabled'])
                self.assertEqual((root/'journal-sentinel').read_bytes(), b'existing immutable test record')
                self.assertEqual((root/'starts').read_text(), '2')
            finally:
                if p.poll() is None:
                    p.terminate(); p.wait(timeout=12)

    def test_stop_does_not_force_kill_worker_with_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.prepare(root); (root/'protected-position').touch()
            p = subprocess.Popen([sys.executable, str(root/'phone_service.py'), '--root', str(root), '--supervise'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.wait_for(lambda: (root/'starts').exists())
                save_json(root/'phone_stop_request.json', {})
                self.wait_for(lambda: (root/'stop-seen').exists())
                self.assertIsNone(p.poll())
                self.assertTrue(service.running(root, 'phone_host.lock'))
                (root/'protected-position').unlink()
                save_json(root/'phone_stop_request.json', {})
                p.wait(timeout=12)
                self.assertEqual((root/'starts').read_text(), '1')
            finally:
                (root/'protected-position').unlink(missing_ok=True)
                if p.poll() is None:
                    save_json(root/'phone_stop_request.json', {})
                    try:
                        p.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        p.terminate(); p.wait(timeout=12)


if __name__ == '__main__':
    unittest.main()
