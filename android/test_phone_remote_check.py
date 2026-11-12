import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import phone_remote_check as check


class SafeDiagnostics(unittest.TestCase):
    def test_mask_private_values_and_terminal_controls(self):
        source = ('https://login.tailscale.com/a/sensitive user@example.com 192.168.1.2:8768 '
                  'node.tailprivate.ts.net:8443 privkey:aaaa tskey-auth-secret '
                  'token=secret-one secret=secret-two 0123456789abcdef0123456789abcdef '
                  '\x1b[31mpanic: denied')
        result = check.mask(source)
        for value in ('sensitive', 'user@example.com', '192.168.1.2', 'tailprivate', 'aaaa',
                      'tskey-auth-secret', 'secret-one', 'secret-two', '0123456789abcdef', '\x1b'):
            self.assertNotIn(value, result)
        self.assertIn('panic: denied', result)

    def test_metadata_whitelist_never_echoes_extra_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'phone_service_status.json').write_text(json.dumps(dict(state='running', mode='watch',
                AuthURL='secret-url', secret='do-not-print', remote_restarts=2)))
            result = check.metadata(root)
            self.assertEqual(result['remote_restarts'], 2)
            self.assertNotIn('secret', json.dumps(result))
            self.assertNotIn('AuthURL', result)

    def test_never_reads_keys_journal_or_tailscale_state_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'remote-private').mkdir()
            for name in ('phone_credentials.json', 'strategy_config.json', 'bot_state.json', 'remote-private/tailscaled.state'):
                (root/name).write_text('DO NOT READ')
            (root/'remote.log').write_text('panic: denied for user@example.com\nfeature/androidbin\n')
            old = Path.open
            def guarded(path, *args, **kwargs):
                if path.name in ('phone_credentials.json', 'strategy_config.json', 'bot_state.json', 'tailscaled.state'):
                    self.fail('private contents opened')
                return old(path, *args, **kwargs)
            with patch.object(Path, 'open', guarded):
                result = check.diagnostic(root, pause=lambda _:None, status=lambda _:dict(state='NeedsLogin'))
            self.assertEqual(result['state_file_bytes'], 11)
            self.assertIn('프로세스 패닉', result['log_signals'])
            self.assertNotIn('user@example.com', json.dumps(result))

    def test_symlink_log_ignored_and_tail_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); private = root/'private'; private.write_text('secret')
            (root/'remote.log').symlink_to(private)
            self.assertEqual(check.tail(root/'remote.log'), '')
            (root/'large.log').write_text('a'*10000+'panic: end')
            self.assertLessEqual(len(check.tail(root/'large.log',100)),100)

    def test_cli_runs_status_only_and_discards_auth_url_peers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); binary = root/'tailscale-1.104.6-arm64'/'tailscale'; binary.parent.mkdir(); binary.write_bytes(b'fixture')
            response = SimpleNamespace(returncode=0, stdout=json.dumps(dict(BackendState='Running', AuthURL='secret', Peer={'private':'private'})), stderr='')
            run = Mock(return_value=response)
            with patch.dict(check.BIN_HASHES, {'arm64': hashlib.sha256(b'fixture').hexdigest()}):
                result = check.local_status(root, run)
            self.assertEqual(result, dict(state='Running', exit_code=0))
            self.assertEqual(run.call_args.args[0][-2:], ['status','--json'])

    def test_corrupt_binary_is_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); binary = root/'tailscale-1.104.6-arm64'/'tailscale'; binary.parent.mkdir(); binary.write_bytes(b'wrong')
            run = Mock()
            self.assertEqual(check.local_status(root, run)['state'], 'binary_not_verified')
            run.assert_not_called()

    def test_native_binary_preferred_over_legacy_and_exit_signal_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for arch in ('android-arm64-r1','arm64'):
                p=root/f'tailscale-1.104.6-{arch}'/'tailscale'; p.parent.mkdir(); p.write_bytes(b'fixture')
            response=SimpleNamespace(returncode=0,stdout='{"BackendState":"Running"}',stderr='')
            run=Mock(return_value=response)
            digest=hashlib.sha256(b'fixture').hexdigest()
            with patch.dict(check.BIN_HASHES, {'android-arm64-r1':digest,'arm64':digest}):
                self.assertEqual(check.local_status(root,run)['state'],'Running')
            self.assertIn('android-arm64-r1',run.call_args.args[0][0])
            (root/'phone_service_status.json').write_text(json.dumps(dict(service_version='phone-service-3',remote_last_exit_code=-31)))
            self.assertEqual(check.metadata(root)['remote_last_exit_code'],-31)

    def test_clock_is_preserved_but_real_ipv6_is_hidden(self):
        value = check.mask('2026/11/13 08:04:21 [2001:db8::1]:443 ::1 fe80::abcd%wlan0')
        self.assertIn('2026/11/13 08:04:21', value)
        self.assertNotIn('2001:db8', value)
        self.assertNotIn('::1', value)
        self.assertNotIn('fe80', value)

    def test_exit_without_error_word_survives_later_startup_warnings(self):
        log = ('Program starting: v1.104.6\n'
               '2026/11/13 07:51:01 RegisterReq: machineAuthorized=true\n'
               '2026/11/13 07:51:02 exiting process with status 1 per controlplane\n'
               'logtail started\nProgram starting: v1.104.6\n'
               + 'warning: operation not permitted; using kernel default values\n' * 40)
        result = check.exit_context(log, Path('/phone'))
        self.assertEqual(result['starts_in_log_tail'], 2)
        self.assertTrue(result['critical_header_found'])
        text = '\n'.join(result['before_restart'])
        self.assertIn('07:51:02 exiting process with status 1', text)

    def test_panic_header_survives_long_stack_and_restart(self):
        log = ('Program starting: v1.104.6\npanic: fixture failure\n'
               + 'goroutine stack fixture\n' * 200
               + 'Program starting: v1.104.6\nwarning: operation not permitted\n')
        result = check.exit_context(log, Path('/phone'))
        self.assertIn('panic: fixture failure', '\n'.join(result['before_restart']))
        self.assertLessEqual(len(result['before_restart']), 20)

    def test_restart_context_masks_login_and_peer_identity(self):
        log = ('Program starting: v1.104.6\n'
               'Login: https://login.tailscale.com/a/private-token user@example.com\n'
               'node=[abcde] machine=[fghij] {"DisplayName":"Private Person"}\n'
               'Program starting: v1.104.6\n')
        value = json.dumps(check.exit_context(log, Path('/phone')))
        for private in ('private-token', 'user@example.com', 'abcde', 'fghij', 'Private Person'):
            self.assertNotIn(private, value)

    def test_permission_fallback_is_not_a_fatal_diagnosis(self):
        result = check.exit_context('Program starting: v1.104.6\n'
            'failed to force-set UDP buffer: operation not permitted; using kernel default values', Path('/phone'))
        self.assertFalse(result['critical_header_found'])
        self.assertIn('종료 원인 확정 아님', check.signals('operation not permitted')[0])


if __name__ == '__main__':
    unittest.main()
