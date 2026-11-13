"""Offline regression tests; never contact an exchange or use credentials."""
import concurrent.futures
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from phone_clock import SharedClock


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.calls = 0
        self.mutex = threading.Lock()
        self.failure = False
        self.bad = None
        self.shared = SharedClock(RuntimeError, lambda: self.now)

    def request(self, method, path, **kwargs):
        self.assertEqual((method, path, kwargs),
                         ('GET', '/api/v5/public/time', {'private': False}))
        with self.mutex:
            self.calls += 1
        time.sleep(.01)  # Let all concurrent clients contend during one read.
        if self.failure:
            raise RuntimeError('HTTP429 simulated')
        return [{'ts': self.bad if self.bad is not None else '1794528000000'}]

    def batch(self, sync):
        barrier = threading.Barrier(24)
        def one(_):
            api = SimpleNamespace(request=self.request, server_ms=0, anchor=0, synced=0)
            barrier.wait(timeout=5)
            try:
                sync(api)
                return api
            except Exception as error:
                return error
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            return list(pool.map(one, range(24)))

    def test_original_24_vs_shared_1_and_next_scan_cache(self):
        # Exact original sync implementation (core integration tested below).
        def original(api):
            data = api.request('GET', '/api/v5/public/time', private=False)
            api.server_ms = int(data[0]['ts'])
            api.anchor = api.synced = self.now
        self.batch(original)
        self.assertEqual(self.calls, 24)
        self.calls = 0
        rows = self.batch(self.shared.sync)
        self.assertEqual(self.calls, 1)
        self.assertTrue(all(row.synced == 1000 for row in rows))
        self.now += 30
        rows = self.batch(self.shared.sync)
        self.assertEqual(self.calls, 1)
        self.assertTrue(all(row.synced == 1000 for row in rows))
        self.assertEqual(rows[0].server_ms + int((self.now-rows[0].anchor)*1000), 1794528030000)
        self.now += 30
        self.batch(self.shared.sync)
        self.assertEqual(self.calls, 2)

    def test_failure_single_flight_cooldown_and_recovery(self):
        self.failure = True
        rows = self.batch(self.shared.sync)
        self.assertTrue(all(isinstance(row, RuntimeError) for row in rows))
        self.assertEqual(self.calls, 1)
        self.now += 1.99
        self.batch(self.shared.sync)
        self.assertEqual(self.calls, 1)
        self.now += .02
        self.batch(self.shared.sync)
        self.assertEqual(self.calls, 2)
        self.assertAlmostEqual(self.shared.retry_at, self.now + 4)
        self.failure = False
        self.now += 4
        rows = self.batch(self.shared.sync)
        self.assertEqual(self.calls, 3)
        self.assertTrue(all(not isinstance(row, Exception) for row in rows))

    def test_expired_sample_failure_does_not_copy_stale_sample(self):
        self.batch(self.shared.sync)
        self.now += 61
        self.failure = True
        api = SimpleNamespace(request=self.request, server_ms=17, anchor=5, synced=5)
        with self.assertRaises(RuntimeError):
            self.shared.sync(api)
        self.assertEqual((api.server_ms, api.anchor, api.synced), (17, 5, 5))

    def test_invalid_timestamp_does_not_become_usable(self):
        for invalid in ('nan', 'inf', '-1', '0', '1.5', '１２３'):
            with self.subTest(invalid=invalid):
                self.shared = SharedClock(RuntimeError, lambda: self.now)
                self.bad = invalid
                rows = self.batch(self.shared.sync)
                self.assertTrue(all(isinstance(row, Exception) for row in rows))
                self.assertIsNone(self.shared.sample)


class CoreIntegration(unittest.TestCase):
    @unittest.skipUnless('--core' in sys.argv, 'pass --core PATH for pinned-core integration')
    def test_actual_original_core_and_installed_patch(self):
        import okx_core
        import phone_clock
        from unittest.mock import patch
        calls = []
        class Response:
            status_code = 200
            def json(self):
                return {'code': '0', 'data': [{'ts': '1794528000000'}]}
        class Session:
            def request(self, method, url, **kwargs):
                calls.append((method, url))
                return Response()
            def close(self):
                pass
        keys = dict(OKX_API_KEY='fake-key', OKX_SECRET_KEY='fake-secret', OKX_PASSPHRASE='fake-pass')
        before = Path(okx_core.__file__).read_bytes()
        with patch('okx_network.okx_session', Session):
            for _ in range(24):
                okx_core.OKX(keys).now_ms()
            self.assertEqual(len(calls), 24)
            calls.clear()
            shared = phone_clock.install()
            self.assertIs(phone_clock.install(), shared)
            with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
                results = list(pool.map(lambda _: okx_core.OKX(keys).now_ms(), range(24)))
            self.assertEqual(len(calls), 1)
            self.assertTrue(all(value > 0 for value in results))
            self.assertEqual(calls[0], ('GET', okx_core.BASE+'/api/v5/public/time'))
        self.assertEqual(Path(okx_core.__file__).read_bytes(), before)


if __name__ == '__main__':
    if '--core' in sys.argv:
        at = sys.argv.index('--core')
        sys.path.insert(0, sys.argv[at+1])
        # Preserve the option for the skipUnless check, remove for unittest.
        argv = [sys.argv[0]] + sys.argv[1:at] + sys.argv[at+2:]
    else:
        argv = sys.argv
    unittest.main(argv=argv)
