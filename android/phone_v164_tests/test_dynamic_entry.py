"""New candidate -> subscription -> frames -> engine order -> fill -> SL.

Exchange and socket I/O are simulated; production strategy, subscription,
frame decoding, quote admission, recovery and engine tick are exercised.
No quotes are preloaded for the candidate. No real exchange is contacted.
"""
import copy
import hashlib
import json
import time
import unittest
from unittest.mock import Mock

import websocket
from execution_harness import D, HOST, Harness, NETWORK_ATTEMPTS, trend
from test_morning import fixture as morning_fixture
import phone_morning_short as morning
import phone_public_ws as transport

FIXTURES = json.loads((D/'fixtures.json').read_text())['fixtures']
FIXTURES['morning_top1_SHORT'] = morning_fixture()
RESULTS = []


class DynamicEntry(unittest.TestCase):
    def setUp(self):
        self.h = None

    def tearDown(self):
        if self.h:
            self.h.close()
        self.assertEqual(NETWORK_ATTEMPTS, [])

    def frame(self, lane, symbol, channel):
        h = self.h
        q = h.api.quote(symbol)
        row = h.api.book(symbol) if channel == 'books5' else dict(q, px=q['last'], markPx=q['last'])
        raw = json.dumps(dict(arg=dict(instId=symbol, channel=channel), data=[row])).encode()
        lane.ws.recv_data_frame.return_value = (websocket.ABNF.OPCODE_TEXT, Mock(data=raw))
        message = transport.receive(lane.ws, websocket, lane)
        lane.feed(message)

    def connect(self, lane):
        # Simulate only the transport handshake result, as run() does after TLS.
        lane.ws = Mock()
        lane.generation += 1
        lane.connected = True
        lane.error = None
        lane.data.clear()
        lane.active_pairs.clear()
        lane.last_subscription = -float('inf')
        lane._phone_subscription_times = __import__('collections').deque()

    def quotes(self, lane, channels):
        for symbol in self.h.api.rows:
            for channel in channels:
                self.frame(lane, symbol, channel)

    def tick(self):
        self.h.e.account_stream.received = time.monotonic()
        self.h.e.tick()

    def pending(self):
        e = self.h.e
        signals = list(e.channel_pending.values())
        for state in (trend.STATE, morning.STATE):
            s = e.journal.data.get(state, {}).get('pending')
            if s:
                signals.append(s)
        self.assertTrue(signals, getattr(e, 'phone_entry_diagnostic', None))
        return signals[0]

    def exercise(self, key, scenario):
        f = copy.deepcopy(FIXTURES[key])
        h = self.h = Harness(f, 4)
        e, s = h.e, h.e.stream
        m = s._phone_monitor_stream
        # Remove the harness's convenience quotes; initially only monitor
        # tickers exist, and the execution lane watches its connectivity probe.
        s.data.clear()
        s.active_pairs.clear()
        s.symbols.clear()
        s.ws = Mock()
        s.watch(['AAVE-USDT-SWAP'])
        self.connect(m)
        s.monitor(list(h.api.rows)+[f'MONITOR{i}-USDT-SWAP' for i in range(289)])
        transport.flush_subscriptions(m)
        self.quotes(m, ['tickers'])
        self.assertTrue(all(ch == 'tickers' for _, ch in m.active_pairs))
        self.assertFalse(any(symbol in s.symbols for symbol in h.api.rows))

        if scenario == 'cold_start':
            s.connected = False
            h.compute()
            self.tick()
            self.assertTrue(e.recovering)
            self.assertEqual(h.api.opening_posts(), [])
            self.connect(s)

        h.compute()
        for _ in range(e.cfg['execution']['recovery_snapshots']):
            self.tick()
        if 'arming_rows' in f:
            self.assertTrue(e.journal.data[trend.STATE]['arm'])
            h.feed(f['rows'], f['now'], quotes=False)
            self.quotes(m, ['tickers'])
            h.compute()
            self.tick()

        signal = self.pending()
        identity = signal['signal_id']
        symbol = signal['symbol']
        self.assertEqual(h.api.opening_posts(), [])
        self.assertIn(symbol, s.symbols)
        transport.flush_subscriptions(s)
        expected = {(symbol, ch) for ch in s.CHANNELS}
        self.assertTrue(expected <= s.active_pairs)
        sent = [json.loads(call.args[0]) for call in s.ws.send.call_args_list]
        pairs = {(arg['instId'], arg['channel']) for msg in sent if msg['op'] == 'subscribe' for arg in msg['args']}
        self.assertTrue(expected <= pairs)

        if scenario == 'monitor_disconnect':
            generation = s.generation
            transport.disconnect(m, m.ws, m.generation, ConnectionResetError())
            self.tick()
            self.assertFalse(e.recovering)
            self.assertEqual(s.generation, generation)
            self.assertEqual(self.pending()['signal_id'], identity)

        if scenario == 'execution_recovery':
            self.quotes(s, s.CHANNELS)
            old = dict(s.data)
            transport.disconnect(s, s.ws, s.generation, ConnectionResetError())
            self.tick()
            self.assertTrue(e.recovering)
            self.assertEqual(h.api.opening_posts(), [])
            self.connect(s)
            s.data.update(old)  # An old socket's rows must never admit an order.
            transport.flush_subscriptions(s)
            for _ in range(e.cfg['execution']['recovery_snapshots']):
                self.tick()
            self.assertFalse(e.recovering)
            self.assertFalse(s.ready(symbol, e.cfg, h.api.now_ms()))
            self.assertEqual(h.api.opening_posts(), [])
            self.assertEqual(self.pending()['signal_id'], identity)

        # Receiving three channels, or an ACK, is not enough to place an order.
        self.quotes(s, [ch for ch in s.CHANNELS if ch != 'trades'])
        self.tick()
        self.assertEqual(h.api.opening_posts(), [])
        self.quotes(s, ['trades'])
        self.tick()
        self.assertEqual(len(h.api.opening_posts()), 1, getattr(e, 'phone_entry_diagnostic', None))
        self.assertEqual(len(e.records()), 1)
        order = e.records()[0]
        self.assertEqual(order['phase'], 'submitted')
        self.assertEqual(order['v4_signal']['signal_id'], identity)
        self.assertFalse(order.get('protection_verified'))

        h.api.fill(order['client_id'])
        self.quotes(s, s.CHANNELS)
        self.tick()
        self.assertEqual(order['phase'], 'active')
        self.assertTrue(order['protection_verified'])
        self.tick()
        self.assertEqual(len(h.api.opening_posts()), 1)
        RESULTS.append(dict(rule=key, scenario=scenario, workers=4,
            phase=order['phase'], protection_verified=True, opening_requests=1,
            initial_execution_quotes=0, signal_preserved=True,
            transport='simulated socket frames through production receive/feed',
            exchange='simulated account, quotes, order ACK, fill and SL'))


for key in FIXTURES:
    for scenario in ('first_subscription', 'monitor_disconnect', 'execution_recovery', 'cold_start'):
        def test(self, key=key, scenario=scenario):
            self.exercise(key, scenario)
        setattr(DynamicEntry, 'test_'+key+'_'+scenario, test)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DynamicEntry)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = dict(version='1.6.4', tests_run=result.testsRun,
        failures=len(result.failures), errors=len(result.errors),
        actual_phone_tested=False, actual_exchange_order_requests=0,
        network_attempts=NETWORK_ATTEMPTS, positive_results=RESULTS,
        runtime_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HOST.iterdir()) if p.is_file()},
        failure_details=[(str(t), v) for t, v in result.failures+result.errors])
    (D/'dynamic_entry_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    raise SystemExit(not result.wasSuccessful())
