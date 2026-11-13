"""Offline updater guards and transaction tests. No exchange/order endpoints."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch, Mock

import phone_button_upgrade as upgrade
import build_phone_button


class UpgradeGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.root = self.home/'okx-phone'
        (self.root/'runtime-q2x').mkdir(parents=True)
        self.journal = self.root/'runtime-q2x'/'bot_state.json'
        self.initial = dict(version=1, owned=None, extra_owned=None, additional_owned=[None, None],
                            entry_continuity732={'schema': 1, 'requested': False})
        self.journal.write_text(json.dumps(self.initial))
        self.boot = self.home/'.termux'/'boot'/'40-okx-home'
        self.boot.parent.mkdir(parents=True)
        self.boot.write_text('# OKX phone service v8 managed boot hook\noriginal boot\n')

    def tearDown(self):
        self.temp.cleanup()

    def test_paused_empty_passes_active_or_unknown_or_owned_fails(self):
        upgrade.require_paused_flat_journal(self.root)
        for extra in ({'entry_continuity732': {'schema': 1, 'requested': True}},
                      {'entry_continuity732': {}}, {'owned': {'id': 1}},
                      {'extra_owned': {'id': 1}}, {'additional_owned': [None, {'id': 1}]},
                      {'manual_closes716': {'id': 1}}):
            with self.subTest(extra=extra):
                self.journal.write_text(json.dumps(dict(self.initial, **extra)))
                with self.assertRaises(ValueError):
                    upgrade.require_paused_flat_journal(self.root)

    def test_exchange_positions_orders_algos_unknown_response_block(self):
        api = Mock()
        clean = dict(config={'uid': 'test', 'acctLv': '2', 'posMode': 'long_short_mode'},
                     positions=[], orders=[])
        with patch.object(upgrade, 'verify_owner'), patch.object(upgrade, 'verify_restart_journal'):
            for positions, orders, algos in (([{'pos': '1'}], [], []), ([], [{}], []), ([], [], [{}]),
                                            ([{'pos': 'NaN'}], [], [])):
                api.snapshot.return_value = dict(clean, positions=positions, orders=orders)
                api.pending_algos.return_value = algos
                with self.assertRaises(ValueError):
                    upgrade.read_flat_account(api, self.root, {})
            api.snapshot.side_effect = RuntimeError('HTTP429')
            with self.assertRaises(RuntimeError):
                upgrade.read_flat_account(api, self.root, {})

    def transaction(self, *, exchange_error=False, readiness_error=False, stop_error=False, active=False, current=False):
        events = []
        if active:
            row = dict(self.initial, entry_continuity732={'schema': 1, 'requested': True})
            self.journal.write_text(json.dumps(row))
        service_state = {'service_version': 'phone-service-10' if current else 'phone-service-8'}
        (self.root/'phone_service_status.json').write_text(json.dumps(service_state))
        api = Mock()
        def account(*_):
            events.append('flat')
            if exchange_error:
                raise RuntimeError('unavailable')
            return 'same-account'
        def stop(*a, **kw):
            events.append('stop')
            if stop_error:
                raise ValueError('still protecting')
        def ready(*_):
            events.append('ready')
            if readiness_error:
                raise RuntimeError('cannot bind')
        patches = [patch.object(Path, 'home', return_value=self.home),
            patch.object(upgrade, 'verify_old', return_value=self.root/'host-v8'),
            patch.object(upgrade, 'verified_installation', return_value=(None, {})),
            patch.object(upgrade, 'running_tokens', return_value={}),
            patch.object(upgrade, 'wait_released', side_effect=lambda *a: events.append('released')),
            patch.object(upgrade, 'read_flat_account', side_effect=account),
            patch.object(upgrade, 'readonly_client', return_value=api),
            patch.object(upgrade, 'validate_keys', return_value={}),
            patch.object(upgrade, 'wait_ready', side_effect=ready),
            patch.object(upgrade, 'rollback', side_effect=lambda *a: events.append('rollback')),
            patch.object(upgrade.time, 'sleep'),
            patch.object(upgrade.service, 'running', return_value=True),
            patch.object(upgrade.service, 'config', return_value={'mode': 'run', 'enabled': True}),
            patch.object(upgrade.service, 'request_stop', side_effect=stop),
            patch.object(upgrade.service, 'boot_script', side_effect=lambda *a: events.append('boot')),
            patch.object(upgrade.service, 'start', side_effect=lambda *a, **kw: events.append('start'))]
        (self.root/'phone_credentials.json').write_text('{}')
        error = None
        with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
            for mocked in patches:
                stack.enter_context(mocked)
            try:
                upgrade.upgrade(self.root)
            except Exception as exc:
                error = exc
        return events, error

    def test_unknown_exchange_state_does_not_stop_host(self):
        events, error = self.transaction(exchange_error=True)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(events, ['flat'])

    def test_active_entry_intent_does_not_query_or_stop_host(self):
        events, error = self.transaction(active=True)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(events, [])

    def test_already_installed_noop_even_while_active(self):
        events, error = self.transaction(active=True, current=True)
        self.assertIsNone(error)
        self.assertEqual(events, [])

    def test_success_rechecks_flat_after_stop_preserves_journal(self):
        before = self.journal.read_bytes()
        protected = ['phone_notifications.json','strategy_config.json',
                     'phone_remote_auth.json','runtime-q2x/trade_notifications.json']
        for name in protected:
            (self.root/name).write_text('untouched fixture')
        events, error = self.transaction()
        self.assertIsNone(error)
        self.assertEqual(events, ['flat', 'flat', 'stop', 'released', 'flat', 'boot', 'start', 'ready'])
        self.assertEqual(self.journal.read_bytes(), before)
        for name in protected:
            self.assertEqual((self.root/name).read_text(),'untouched fixture')
        self.assertEqual(json.loads((self.root/'phone_update_result.json').read_text())['phase'], 'installed')

    def test_refused_stop_never_starts_second_host(self):
        events, error = self.transaction(stop_error=True)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(events, ['flat', 'flat', 'stop'])

    def test_failed_start_requests_rollback(self):
        events, error = self.transaction(readiness_error=True)
        self.assertIsInstance(error, ValueError)
        self.assertEqual(events[-1], 'rollback')
        self.assertEqual(json.loads((self.root/'phone_update_result.json').read_text())['phase'], 'rolled_back')

    def test_rollback_restores_exact_boot_before_starting_old_host(self):
        original = self.boot.read_bytes()
        self.boot.write_text(upgrade.service.MARKER+'\nnew boot\n')
        calls = []
        with patch.object(upgrade, 'running_tokens', return_value={}), \
             patch.object(upgrade, 'wait_released'), \
             patch.object(upgrade.service, 'request_stop'), \
             patch.object(upgrade.subprocess, 'run', side_effect=lambda *a, **kw: calls.append(a[0])):
            upgrade.rollback(self.root, self.root/'host-v8', self.boot, original)
        self.assertEqual(self.boot.read_bytes(), original)
        self.assertIn(str(self.root/'host-v8'/'phone_service.py'), calls[0])
        self.assertIn('--start', calls[0])


class BundleTests(unittest.TestCase):
    def run_bootstrap(self, returncode):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home/'okx-phone'
            root.mkdir()
            for name in ('phone_owner.json', 'phone_installation.json', 'phone_credentials.json', 'strategy_config.json'):
                (root/name).write_text('{}')
            out = build_phone_button.build(home/'installer.py')
            with patch.object(Path, 'home', return_value=home), \
                 patch('sys.argv', [str(out)]), \
                 patch('subprocess.run', return_value=Mock(returncode=returncode)) as run, \
                 patch('os.execv') as execute, contextlib.redirect_stdout(io.StringIO()):
                if returncode:
                    with self.assertRaises(SystemExit) as exit_result:
                        runpy.run_path(str(out), run_name='__main__')
                    self.assertEqual(exit_result.exception.code, returncode)
                    execute.assert_not_called()
                else:
                    runpy.run_path(str(out), run_name='__main__')
                    execute.assert_not_called()
                self.assertEqual(run.call_count, 1)
                self.assertTrue(run.call_args.args[0][-1].endswith('phone_button_upgrade.py'))

    def test_bootstrap_starts_collection_only_after_success(self):
        self.run_bootstrap(0)

    def test_bootstrap_stops_on_failed_install_without_collection(self):
        self.run_bootstrap(1)

    def test_build_is_reproducible_and_staging_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'root'
            root.mkdir()
            for name in ('phone_owner.json', 'phone_installation.json', 'phone_credentials.json', 'strategy_config.json'):
                (root/name).write_bytes(b'unchanged')
            out = Path(tmp)/'installer.py'
            build_phone_button.build(out)
            before = out.read_bytes()
            build_phone_button.build(out)
            self.assertEqual(out.read_bytes(), before)
            ns = runpy.run_path(str(out))
            script = ns['install'](root)
            self.assertTrue(script.is_file())
            self.assertEqual(ns['install'](root), script)
            for name in build_phone_button.FILES:
                self.assertEqual((root/'host-v10'/name).read_bytes(), (Path(__file__).parent/name).read_bytes())
                self.assertEqual((root/'host-v10'/name).stat().st_mode & 0o777, 0o600)
            script.write_text('modified')
            with self.assertRaises(ValueError):
                ns['install'](root)
            self.assertEqual(script.read_text(), 'modified')
            self.assertEqual((root/'phone_credentials.json').read_bytes(), b'unchanged')


if __name__ == '__main__':
    unittest.main()
