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
        self.boot.write_text('# OKX phone service v14 managed boot hook\noriginal boot\n')

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
                self.assertEqual((root/'host-v16'/name).read_bytes(), (Path(__file__).parent/name).read_bytes())
                self.assertEqual((root/'host-v16'/name).stat().st_mode & 0o777, 0o600)
            script.write_text('modified')
            with self.assertRaises(ValueError):
                ns['install'](root)
            self.assertEqual(script.read_text(), 'modified')
            self.assertEqual((root/'phone_credentials.json').read_bytes(), b'unchanged')


if __name__ == '__main__':
    unittest.main()
