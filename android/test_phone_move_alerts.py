import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import phone_move_alerts as m


def row(t, price=100, symbol='TIA-USDT-SWAP'):
    return dict(instId=symbol, ts=str(int(t * 1000)), last=str(price))


def history(detector, start=1000, price=100, symbol='TIA-USDT-SWAP'):
    for t in range(start, start + 300, 15):
        assert detector.sample(row(t, price, symbol), t) is None


class DetectionTests(unittest.TestCase):
    def test_rise_drop_and_price_percentage(self):
        for price, direction, change in [(103, 'up', .03), (97, 'down', -.03)]:
            d = m.Detector()
            history(d)
            alert = d.sample(row(1300, price), 1300)
            self.assertEqual(alert['direction'], direction)
            self.assertAlmostEqual(alert['change'], change)
            self.assertEqual(alert['end'] - alert['start'], 300)

    def test_below_threshold_and_warmup(self):
        d = m.Detector()
        self.assertIsNone(d.sample(row(1000, 100), 1000))
        self.assertIsNone(d.sample(row(1015, 150), 1015))
        d = m.Detector()
        history(d)
        self.assertIsNone(d.sample(row(1300, 102.99), 1300))

    def test_gap_stale_duplicate_out_of_order(self):
        for stamp, now in [(1300, 1400), (1300, 1280), (1285, 1285), (1270, 1270)]:
            d = m.Detector()
            history(d)
            self.assertIsNone(d.sample(row(stamp, 110), now))
        d = m.Detector()
        history(d)
        self.assertIsNone(d.sample(row(1400, 110), 1400))
        self.assertEqual(len(d.history['TIA-USDT-SWAP']), 1)

    def test_rolling_window_not_day_change(self):
        d = m.Detector()
        history(d)
        for t in range(1300, 1600, 15):
            d.sample(row(t, 110), t)
        self.assertIsNone(d.sample(row(1600, 110), 1600))

    def test_many_symbols_independent(self):
        d = m.Detector()
        for symbol in ['TIA-USDT-SWAP', 'DOGE-USDT-SWAP']:
            history(d, symbol=symbol)
        self.assertEqual(d.sample(row(1300, 104), 1300)['direction'], 'up')
        self.assertEqual(d.sample(row(1300, 96, 'DOGE-USDT-SWAP'), 1300)['direction'], 'down')

    def test_invalid_quotes(self):
        d = m.Detector()
        history(d)
        for price in ['nan', 'inf', -1, 0, None, 'bad']:
            self.assertIsNone(d.sample(row(1300, price), 1300))

    def test_cooldown_survives_restart_and_independent_direction(self):
        d = m.Detector()
        history(d)
        alert = d.sample(row(1300, 103), 1300)
        state = {'cooldown': {}}
        self.assertTrue(m.eligible(state, alert, 1300))
        m.reserve(state, [alert], 1300)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            m.write_private(p / 'state.json', state)
            restored = m.state_load(p)
        self.assertFalse(m.eligible(restored, alert, 3099))
        self.assertTrue(m.eligible(restored, alert, 3100))
        self.assertTrue(m.eligible(restored, dict(alert, direction='down'), 1301))

    def test_scope_excludes_stock_and_invalid_instruments(self):
        instrument = dict(instId='TIA-USDT-SWAP', state='live', instCategory='1',
                          groupId='4', settleCcy='USDT', ctType='linear', ctValCcy='TIA')
        self.assertTrue(m.allowed(instrument, set()))
        self.assertFalse(m.allowed(instrument, {'TIA-USDT-SWAP'}))
        for field, value in [('instCategory', '3'), ('groupId', '6'), ('state', 'suspend'),
                             ('ctType', 'inverse'), ('settleCcy', 'BTC'), ('ctValCcy', 'USDT')]:
            self.assertFalse(m.allowed(dict(instrument, **{field: value}), set()))

    def test_message_has_times_and_is_bounded(self):
        d = m.Detector()
        history(d)
        alert = d.sample(row(1300, 103), 1300)
        text = m.message([alert] * 20, 200)
        self.assertIn('KST', text)
        self.assertIn('+3.00%', text)
        self.assertIn('200종 추가', text)
        self.assertLess(len(text), 4096)


class TransportTests(unittest.TestCase):
    def test_worker_end_to_end_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / 'move-alerts-v1'
            directory.mkdir()
            m.write_private(root / 'phone_notifications.json', {
                'TELEGRAM_BOT_TOKEN': '1234:' + 'x' * 24, 'TELEGRAM_CHAT_ID': '1234'})
            m.write_private(root / 'strategy_config.json', {'selection': {}})
            m.write_private(directory / 'enabled.json', {'enabled': True})
            clock = [1000.]
            class Event:
                flag = False
                def is_set(self): return self.flag
                def set(self): self.flag = True
                def wait(self, seconds):
                    clock[0] += seconds
                    if clock[0] >= 1400:
                        self.flag = True
            instrument = dict(instId='TIA-USDT-SWAP', state='live', instCategory='1',
                              groupId='4', settleCcy='USDT', ctType='linear', ctValCcy='TIA')
            def public(path):
                if 'instruments' in path:
                    return [instrument]
                return [row(clock[0], 103 if clock[0] >= 1300 else 100)]
            with patch('threading.Event', Event), patch.object(m.signal, 'signal'), \
                 patch.object(m.time, 'time', lambda: clock[0]), \
                 patch.object(m.time, 'monotonic', lambda: clock[0]), \
                 patch.object(m, 'public', side_effect=public), \
                 patch.object(m, 'telegram', return_value=('sent', 60)) as send:
                m.run(root, directory)
            self.assertEqual(send.call_count, 2)  # one setup notice and one price alert
            self.assertIn('급등·급락 알림 연결', send.call_args_list[0].args[2])
            self.assertIn('TIA-USDT-SWAP +3.00%', send.call_args_list[1].args[2])
            self.assertEqual(m.read_json(directory / 'status.json')['state'], 'stopped')
            self.assertIn('TIA-USDT-SWAP:up', m.state_load(directory)['cooldown'])

    def test_private_exchange_requests_rejected(self):
        with patch.object(m, 'request_json') as request:
            with self.assertRaises(ValueError):
                m.public('/api/v5/trade/order')
            request.assert_not_called()

    def test_public_rate_limit(self):
        for response in [(429, {}), (200, {'code': '50011'})]:
            with patch.object(m, 'request_json', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'public_rate_limit'):
                    m.public('/api/v5/market/tickers?instType=SWAP')

    def test_telegram_rate_limit_and_rejection(self):
        with patch.object(m, 'request_json', return_value=(429, {'parameters': {'retry_after': 321}})):
            self.assertEqual(m.telegram('fake', 'fake', 'text'), ('rate_limited', 321))
        with patch.object(m, 'request_json', return_value=(403, {})):
            self.assertEqual(m.telegram('fake', 'fake', 'text'), ('rejected', 60))
        with patch.object(m, 'request_json', return_value=(200, {'ok': True})):
            self.assertEqual(m.telegram('fake', 'fake', 'text'), ('sent', 60))

    def test_install_stays_inside_addon_and_keeps_secrets_out_of_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / 'okx-phone'
            root.mkdir()
            token = '1234:' + 'x' * 24
            notices = {'TELEGRAM_BOT_TOKEN': token, 'TELEGRAM_CHAT_ID': '1234'}
            m.write_private(root / 'phone_notifications.json', notices)
            m.write_private(root / 'strategy_config.json', {'selection': {}})
            m.write_private(root / 'phone_credentials.json', {'sentinel': 'do-not-touch'})
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            with patch.object(m.Path, 'home', return_value=home), patch.object(m, 'start') as start:
                with patch.object(sys, 'argv', [str(Path(m.__file__)), '--install', '--root', str(root)]):
                    m.main()
                start.assert_called_once()
            for name, content in before.items():
                self.assertEqual((root / name).read_bytes(), content)
            hook = home / '.termux' / 'boot' / '95-okx-move-alerts'
            self.assertNotIn(token, hook.read_text())
            self.assertNotIn('phone_host', hook.read_text())
            self.assertIn('--start', hook.read_text())
            self.assertTrue((root / 'move-alerts-v1' / 'phone_move_alerts.py').exists())

    def test_credentials_not_in_error_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            token = 'secret-invalid'
            m.write_private(root / 'phone_notifications.json', {'TELEGRAM_BOT_TOKEN': token})
            result = subprocess.run([sys.executable, m.__file__, '--install', '--root', str(root)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(token, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
