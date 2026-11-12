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


if __name__ == '__main__':
    unittest.main()
