import importlib.util
import errno
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

import build_phone_host_bundle as bundle
import phone_migrate as migrate
import phone_remote as remote
import phone_service as service
from phone_account import save_json
import test_phone_home as home_tests


class NativePreflight(unittest.TestCase):
    def test_native_folder_keeps_old_binary_and_state_paths(self):
        self.assertEqual(remote.binary_folder(Path('/phone'), 'arm64').name,
                         'tailscale-1.104.6-android-arm64-r1')
        with tempfile.TemporaryDirectory() as tmp, patch.object(remote, 'architecture', return_value='arm64'), patch.object(remote, 'verify_binaries'):
            args = remote.daemon_command(Path(tmp))
            self.assertIn('--state='+tmp+'/remote-private/tailscaled.state', args)
            self.assertIn('android-arm64-r1/tailscaled', args[0])

    def test_native_preflight_accepts_only_expected_version(self):
        good = [SimpleNamespace(returncode=0, stdout='{"short":"1.104.6"}'),
                SimpleNamespace(returncode=0, stdout='1.104.6-phone-android-r1\n')]
        with patch.object(remote.subprocess, 'run', side_effect=good) as run:
            remote.verify_native_runtime(Path('/fixture'), 'arm64')
        self.assertEqual(run.call_count, 2)
        for bad in [SimpleNamespace(returncode=-31, stdout=''),
                    SimpleNamespace(returncode=0, stdout='null'),
                    SimpleNamespace(returncode=0, stdout='{"short":"1.100.0"}')]:
            with patch.object(remote.subprocess, 'run', return_value=bad), self.assertRaises(ValueError):
                remote.verify_native_runtime(Path('/fixture'), 'arm64')

    def test_failed_preflight_does_not_publish_new_binary_or_delete_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'remote-private').mkdir()
            state=root/'remote-private/tailscaled.state'; state.write_bytes(b'fixture-login')
            old=root/'tailscale-1.104.6-arm64'; old.mkdir(); (old/'tailscaled').write_bytes(b'old')
            response=Mock(); response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=False)
            response.read.return_value=b'fixture-archive'
            with patch.object(remote, 'architecture', return_value='arm64'), patch.object(remote.urllib.request, 'urlopen', return_value=response), patch.object(remote, 'unpack'), patch.object(remote, 'verify_native_runtime', side_effect=ValueError('failed')):
                with self.assertRaises(ValueError): remote.install(root)
            self.assertEqual(state.read_bytes(), b'fixture-login')
            self.assertEqual((old/'tailscaled').read_bytes(), b'old')
            self.assertFalse(remote.binary_folder(root, 'arm64').exists())
            self.assertFalse(list(root.glob('.tailscale-*')))


class UpgradeGuards(unittest.TestCase):
    def test_owner_refused_even_without_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'phone_owner.json').write_text('{}')
            with patch.object(service, 'request_stop') as stop, self.assertRaises(ValueError):
                migrate.prepare_watch_upgrade(root)
            stop.assert_not_called()

    def test_live_socket_blocks_orphan_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'remote-private').mkdir()
            probe=Mock(); probe.__enter__=Mock(return_value=probe); probe.__exit__=Mock(return_value=False)
            probe.connect_ex.return_value=0
            with patch.object(migrate.socket,'socket',return_value=probe):
                self.assertFalse(migrate.transport_released(root))
                with self.assertRaises(ValueError): migrate.prepare_watch_upgrade(root)
                probe.connect_ex.return_value=errno.ECONNREFUSED
                self.assertTrue(migrate.transport_released(root))
                probe.connect_ex.return_value=errno.EACCES
                with self.assertRaises(ValueError): migrate.transport_released(root)

    def test_wrong_mode_or_old_status_does_not_stop_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); save_json(root/'phone_service.json', dict(mode='watch', enabled=True))
            for row in [dict(mode='run', state='running', observed_at=time.time()),
                        dict(mode='watch', state='running', observed_at=time.time()-60)]:
                save_json(root/'phone_service_status.json', row)
                with patch.object(service, 'running', return_value=True), patch.object(service, 'request_stop') as stop:
                    with self.assertRaises(ValueError): migrate.prepare_watch_upgrade(root)
                    stop.assert_not_called()

    def test_unrecognized_legacy_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'host-v2').mkdir()
            (root/'host-v2/phone_host.py').write_text('different')
            with self.assertRaises(ValueError): migrate.verify_legacy(root)

    def test_current_service_resume_does_not_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); save_json(root/'phone_service_status.json', dict(service_version=service.VERSION))
            with patch.object(service, 'running', return_value=True), patch.object(service, 'request_stop') as stop:
                migrate.prepare_watch_upgrade(root)
                stop.assert_not_called()

    def test_boot_replaces_only_known_v2_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); hook=root/'.termux/boot/40-okx-home'; hook.parent.mkdir(parents=True)
            hook.write_text(service.LEGACY_MARKER+'\n')
            service.boot_script(root, root)
            self.assertIn(service.MARKER, hook.read_text())
            self.assertNotIn('--handover', hook.read_text())

    def test_real_watch_supervisor_and_children_stop_before_upgrade(self):
        # Real subprocess locks, /proc identity, normal-stop request and child
        # lifetime; only the transport/account workers are local inert stubs.
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); old=root/'host-v2'; old.mkdir()
            home_tests.SupervisorProcess().prepare(old)
            script=old/'phone_service.py'
            script.write_text(script.read_text().replace('service_version=VERSION,', ''))
            save_json(root/'phone_service.json', dict(mode='watch', enabled=True))
            (root/'remote-private').mkdir()
            sentinels={name:('fixture-'+name).encode() for name in ('phone_credentials.json', 'strategy_config.json', 'remote-private/tailscaled.state')}
            for name,data in sentinels.items(): (root/name).write_bytes(data)
            old_bytes={p.name:p.read_bytes() for p in old.iterdir() if p.is_file()}
            p=subprocess.Popen([sys.executable, str(script), '--root', str(root), '--supervise'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+10
                while not (root/'starts').exists() or not (root/'phone_service_status.json').exists():
                    if time.monotonic()>deadline: self.fail('supervisor did not start')
                    time.sleep(.1)
                # Executor forbids AF_UNIX; only this local socket probe is
                # mocked. Supervisor/worker and /proc checks run for real.
                with patch.object(migrate, 'verify_legacy', return_value=old), patch.object(migrate,'transport_released',return_value=True):
                    migrate.prepare_watch_upgrade(root)
                p.wait(timeout=3)
                self.assertFalse(service.running(root))
                self.assertFalse(service.running(root, 'phone_host.lock'))
                self.assertFalse(json.loads((root/'phone_service.json').read_text())['enabled'])
                self.assertTrue((root/'phone_transport_migration.json').exists())
                for name,data in sentinels.items(): self.assertEqual((root/name).read_bytes(), data)
                for name,data in old_bytes.items(): self.assertEqual((old/name).read_bytes(), data)
            finally:
                if p.poll() is None:
                    p.terminate(); p.wait(timeout=15)


class GenericBundle(unittest.TestCase):
    def test_install_idempotent_private_files_unchanged_and_owner_guarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); entry=bundle.build(root/'setup.py')
            spec=importlib.util.spec_from_file_location('fixture_setup',entry)
            mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            names=('phone_credentials.json','phone_installation.json','strategy_config.json')
            for name in names: (root/name).write_bytes(b'private-fixture-'+name.encode())
            before={name:(root/name).read_bytes() for name in names}
            target=mod.install(root)
            self.assertEqual(target.parent.name,'host-v3')
            self.assertEqual(mod.install(root),target)
            for name,data in before.items(): self.assertEqual((root/name).read_bytes(),data)
            (root/'phone_owner.json').write_text('{}')
            with self.assertRaises(ValueError): mod.install(root)


if __name__ == '__main__': unittest.main()
