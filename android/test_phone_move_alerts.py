import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import phone_move_alerts as m


def bar(start=900, opening=100, close=110, confirm='1'):
    return [str(start * 1000), str(opening), str(max(opening, close)),
            str(min(opening, close)), str(close), '1', '1', '1', confirm]


class DetectionTests(unittest.TestCase):
    def test_threshold_inclusive_both_directions(self):
        for close, change in [(110, .10), (90, -.10), (120, .20), (80, -.20)]:
            found, alert = m.candle_signal('TIA-USDT-SWAP', [bar(close=close)], 900, 1803)
            self.assertTrue(found)
            self.assertAlmostEqual(alert['change'], change)
            self.assertEqual(alert['end'] - alert['start'], 900)

    def test_below_ten_percent(self):
        for close in (109.99, 90.01, 100):
            self.assertEqual(m.candle_signal('TIA-USDT-SWAP', [bar(close=close)], 900, 1803),
                             (True, None))

    def test_unconfirmed_old_future_and_unaligned_rejected(self):
        for rows, target, now in [([bar(confirm='0')], 900, 1803),
                                 ([bar(0)], 900, 1803), ([bar(1800)], 900, 1803),
                                 ([bar()], 900, 1799), ([bar()], 900, 2700),
                                 ([bar(901)], 901, 1803)]:
            self.assertEqual(m.candle_signal('TIA-USDT-SWAP', rows, target, now), (False, None))

    def test_high_low_range_is_not_signal(self):
        r = bar(close=101)
        r[2], r[3] = '150', '50'
        self.assertEqual(m.candle_signal('TIA-USDT-SWAP', [r], 900, 1803), (True, None))

    def test_invalid_candles(self):
        for value in ('nan', 'inf', '-1', '0', 'bad'):
            r = bar(); r[1] = value
            self.assertEqual(m.candle_signal('TIA-USDT-SWAP', [r], 900, 1803), (False, None))
        r = bar(); r[2] = '95'
        self.assertEqual(m.candle_signal('TIA-USDT-SWAP', [r], 900, 1803), (False, None))

    def test_mixed_response_selects_target_confirmed_candle(self):
        rows = [bar(1800, close=140, confirm='0'), bar(), bar(0)]
        self.assertEqual(m.candle_signal('TIA-USDT-SWAP', rows, 900, 1803)[1]['start'], 900)

    def test_dedup_survives_restart_next_candle_allowed(self):
        alert = m.candle_signal('TIA-USDT-SWAP', [bar()], 900, 1803)[1]
        state = {'seen': {}}
        self.assertTrue(m.eligible(state, alert, 1803))
        m.reserve(state, [alert], 1803)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            m.write_private(p / 'candle_state.json', state)
            restored = m.state_load(p)
        self.assertFalse(m.eligible(restored, alert, 1850))
        next_alert = m.candle_signal('TIA-USDT-SWAP', [bar(1800)], 1800, 2703)[1]
        self.assertTrue(m.eligible(restored, next_alert, 2703))
        self.assertFalse(m.eligible({'seen': {}}, alert, 2700))

    def test_scope_excludes_stock(self):
        i = dict(instId='TIA-USDT-SWAP', state='live', instCategory='1', groupId='4',
                 settleCcy='USDT', ctType='linear', ctValCcy='TIA')
        self.assertTrue(m.allowed(i, set()))
        self.assertFalse(m.allowed(i, {'TIA-USDT-SWAP'}))
        self.assertFalse(m.allowed(dict(i, instCategory='3'), set()))
        self.assertFalse(m.allowed(dict(i, groupId='6'), set()))

    def test_message_labels_and_length(self):
        alert = m.candle_signal('TIA-USDT-SWAP', [bar()], 900, 1803)[1]
        text = m.message([alert] * 20, 10)
        for label in ('15분봉', '시가', '종가', '+10.00%', 'KST'):
            self.assertIn(label, text)
        self.assertLess(len(text), 4096)


class TransportTests(unittest.TestCase):
    def test_upgrade_stops_only_old_alert_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / 'okx-phone'; root.mkdir()
            directory = root / 'move-alerts-v1'; directory.mkdir()
            m.write_private(root / 'phone_notifications.json', {
                'TELEGRAM_BOT_TOKEN': '1234:' + 'x' * 24, 'TELEGRAM_CHAT_ID': '1234'})
            m.write_private(root / 'strategy_config.json', {'selection': {}})
            m.write_private(directory / 'phone_move_alerts.py', '# old alert version')
            m.write_private(directory / 'enabled.json', {'enabled': True})
            before = (root / 'strategy_config.json').read_bytes()
            original_write = m.write_private
            changes = []
            def write(path, value):
                if path.name == 'enabled.json': changes.append(value['enabled'])
                return original_write(path, value)
            with patch.object(m.Path, 'home', return_value=home), \
                 patch.object(m, 'running', side_effect=[True, False, False]), \
                 patch.object(m, 'write_private', side_effect=write), \
                 patch.object(m, 'start') as start, \
                 patch.object(sys, 'argv', [m.__file__, '--install', '--root', str(root)]):
                m.main()
            self.assertEqual(changes, [False, True])
            start.assert_called_once_with(root, directory)
            self.assertEqual(before, (root / 'strategy_config.json').read_bytes())
            self.assertEqual((directory / 'phone_move_alerts.py').read_text(), Path(m.__file__).read_text())

    def test_candle_url_scope_is_strict(self):
        with patch.object(m, 'request_json') as request:
            for path in ['/api/v5/trade/order',
                         '/api/v5/market/candles?instId=TIA-USDT-SWAP&bar=1m&limit=3',
                         '/api/v5/market/candles?instId=TIA-USDT-SWAP&bar=15m&limit=3&x=1']:
                with self.assertRaises(ValueError): m.public(path)
            request.assert_not_called()

    def test_worker_end_to_end_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / 'move-alerts-v1'
            directory.mkdir()
            m.write_private(root / 'phone_notifications.json', {
                'TELEGRAM_BOT_TOKEN': '1234:' + 'x' * 24, 'TELEGRAM_CHAT_ID': '1234'})
            m.write_private(root / 'strategy_config.json', {'selection': {}})
            m.write_private(directory / 'enabled.json', {'enabled': True})
            clock = [1803.]
            class Event:
                flag = False
                def is_set(self): return self.flag
                def set(self): self.flag = True
                def wait(self, seconds):
                    clock[0] += seconds
                    if clock[0] >= 2800:
                        self.flag = True
            instrument = dict(instId='TIA-USDT-SWAP', state='live', instCategory='1',
                              groupId='4', settleCcy='USDT', ctType='linear', ctValCcy='TIA')
            def public(path):
                if 'instruments' in path:
                    return [instrument]
                return [bar(1800 if clock[0] >= 2700 else 900)]
            with patch('threading.Event', Event), patch.object(m.signal, 'signal'), \
                 patch.object(m.time, 'time', lambda: clock[0]), \
                 patch.object(m.time, 'monotonic', lambda: clock[0]), \
                 patch.object(m, 'public', side_effect=public), \
                 patch.object(m, 'telegram', return_value=('sent', 60)) as send:
                m.run(root, directory)
            self.assertEqual(send.call_count, 3)  # setup and one notification per closed bar
            self.assertIn('15분봉 ±10% 알림 연결', send.call_args_list[0].args[2])
            self.assertIn('TIA-USDT-SWAP +10.00%', send.call_args_list[1].args[2])
            self.assertEqual(m.read_json(directory / 'status.json')['state'], 'stopped')
            self.assertIn('TIA-USDT-SWAP:900', m.state_load(directory)['seen'])

    def test_private_exchange_requests_rejected(self):
        with patch.object(m, 'request_json') as request:
            with self.assertRaises(ValueError):
                m.public('/api/v5/trade/order')
            request.assert_not_called()

    def test_public_rate_limit(self):
        for response in [(429, {}), (200, {'code': '50011'})]:
            with patch.object(m, 'request_json', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'public_rate_limit'):
                    m.public('/api/v5/market/candles?instId=TIA-USDT-SWAP&bar=15m&limit=3')

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
