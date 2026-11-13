"""Offline checks: sanitized log scopes and one same-host GET, no trading."""
import json
import contextlib
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import phone_delay_check_v2 as diagnostic


class DiagnosticsTests(unittest.TestCase):
    def test_only_recent_post_install_rows_are_reported(self):
        now = datetime(2026, 11, 13, 11, 20, tzinfo=diagnostic.KST)
        since = datetime(2026, 11, 13, 10, 55, tzinfo=diagnostic.KST).timestamp()
        logs = '\n'.join(['11-13 10:30:02  OKX 50011 old',
                          '11-13 10:53:02  OKX 50011 before-install',
                          '11-13 11:12:55  연결 끊김/재연결: private-token-SECRET',
                          '11-13 11:12:58  공개 WS: 연결 / 계정 WS: 수신 확인',
                          '11-13 11:21:00  OKX 50011 future'])
        result = diagnostic.log_summary(logs, now, since)
        self.assertEqual(result['matching_log_lines'], 2)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertNotIn('OKX 50011', result['counts'])
        self.assertTrue(result['filtered_after_clock_install'])

    def test_safe_error_paths_not_raw_private_text(self):
        result = diagnostic.classify('OKX 50011 요청 제한 /api/v5/account/positions secret=PRIVATE https://example.invalid/login/TOKEN')
        self.assertIn('오류 경로 /api/v5/account/positions', result)
        self.assertNotIn('PRIVATE', str(result))
        self.assertNotIn('TOKEN', str(result))

    def test_same_host_readonly_single_probe_success(self):
        calls = []
        class Response:
            status = 200
            def read(self, size):
                return b'{"code":"0","data":[{"ts":"1794528000000"}]}'
        class Connection:
            def __init__(self, host, timeout):
                calls.append(host)
            def request(self, method, path, headers):
                calls.append((method, path))
            def getresponse(self):
                return Response()
            def close(self):
                pass
        with patch.object(diagnostic, 'PublicIPv4', Connection):
            result = diagnostic.public_probe()
        self.assertTrue(result['ok'])
        self.assertEqual(calls, ['openapi.okx.com', ('GET', '/api/v5/public/time')])

    def test_unreadable_or_symlink_file_does_not_leak(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            secret = root/'secret'
            secret.write_text('PRIVATE')
            (root/'host.log').symlink_to(secret)
            self.assertEqual(diagnostic.read_bounded(root, 'host.log'), '')
            report, since = diagnostic.clock_installation(root)
            self.assertIsNone(since)
            self.assertEqual(report['phase'], 'unknown')

    def test_service_allowlist_drops_extra_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'phone_service_status.json').write_text(json.dumps({'state': 'running', 'mode': 'run',
                'service_version': 'phone-service-5', 'secret': 'PRIVATE', 'token': 'TOKEN'}))
            value = diagnostic.service(root)
            self.assertEqual(value['service_version'], 'phone-service-5')
            self.assertNotIn('PRIVATE', str(value))
            self.assertNotIn('TOKEN', str(value))

    def test_runner_launches_one_public_probe_and_writes_no_files(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            root = Path(folder)
            with patch.object(diagnostic.time, 'sleep'), patch.object(diagnostic.subprocess, 'run',
                    return_value=SimpleNamespace(returncode=0, stdout='{"ok":false,"http_status":429}')) as probe:
                diagnostic.run(root)
                self.assertEqual(probe.call_count, 1)
                self.assertIn('--public-probe', probe.call_args.args[0])
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
