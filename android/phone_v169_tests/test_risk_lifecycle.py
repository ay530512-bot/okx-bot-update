"""Real confirmed-close cleanup and recovery; fake exchange, no network."""
import json
import threading
import unittest
from unittest.mock import patch
from execution_harness import Harness, D, NETWORK_ATTEMPTS
from test_manual_reduction import Ledger
from okx_engine import Engine
import phone_risk_lifecycle as risk

FIXTURE = json.loads((D/'fixtures.json').read_text())['fixtures']['trend_pullback_LONG']


class Tests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(FIXTURE)
        self.ledger = Ledger(self.h)
        self.s = self.h.signal()
        self.o = self.h.submit(self.s)
        self.h.api.fill(self.o['client_id'])
        self.assertTrue(self.h.reconcile(self.o))
        self.cid = self.o['client_id']

    def tearDown(self):
        self.h.close()
        self.assertEqual(NETWORK_ATTEMPTS, [])

    def finish(self):
        self.h.api.positions = []
        with self.h.e.selected(0):
            self.h.e.finish_position()

    def test_late_closed_guard_no_longer_creates_orphan(self):
        self.finish()
        e = self.h.e
        e.entry_cancel.clear()
        e.queue_risk(self.cid, 'late guard')
        self.assertEqual(e.queued_risks, set())
        self.assertTrue(e.risk_queue.empty())
        self.assertFalse(e.entry_cancel.is_set())
        self.assertEqual(risk.diagnostics(e)['retired_callbacks'], 1)

    def test_callback_between_original_discard_and_cleanup_is_retired(self):
        e = self.h.e
        e.queue_risk(self.cid, 'original close')
        original = Engine.finish_position
        def racing(engine):
            worker = threading.Thread(target=engine.queue_risk, args=(self.cid, 'late during cleanup'))
            worker.start(); worker.join(2)
            self.assertFalse(worker.is_alive(), 'network cleanup must not hold risk_lock')
            return original(engine)
        with patch.object(Engine, 'finish_position', racing):
            self.finish()
        self.assertNotIn(self.cid, e.queued_risks)
        self.assertTrue(e.risk_queue.empty())
        # Retirement itself must not override the normal recovery/operator gate.
        self.assertTrue(e.entry_cancel.is_set())

    def test_other_pending_risk_preserved_and_deduplicated(self):
        e = self.h.e
        e.queue_risk(self.cid, 'closed')
        e.queue_risk('another-live-position', 'protect other')
        e.queue_risk('another-live-position', 'duplicate')
        self.finish()
        self.assertEqual(e.queued_risks, {'another-live-position'})
        self.assertEqual(e.risk_queue.get_nowait(), ('another-live-position', 'protect other'))
        self.assertTrue(e.risk_queue.empty())
        self.assertTrue(e.entry_cancel.is_set())

    def test_failed_cleanup_not_retired_and_entry_stays_blocked(self):
        e = self.h.e
        e.queue_risk(self.cid, 'protect')
        with patch.object(Engine, 'finish_position', side_effect=TimeoutError('SL cancel uncertain')):
            with self.assertRaises(TimeoutError):
                self.finish()
        self.assertIn(self.cid, e.queued_risks)
        self.assertNotIn(self.cid, getattr(e, '_retired_risks169', ()))
        self.assertTrue(e.entry_cancel.is_set())

    def test_real_tick_resumes_scanning_only_after_healthy_recovery(self):
        e = self.h.e
        e.queue_risk(self.cid, 'close')
        self.finish()
        e.queue_risk(self.cid, 'stale callback')
        e.recovering = True; e.good_snapshots = 0
        e.executing_signal = None
        with patch.object(e, 'refresh_day'), patch.object(e, 'latch_day', return_value=False), \
                patch.object(e, 'settle'), patch.object(e, 'publish_portfolio'), \
                patch.object(e, 'candidate_decision', return_value=None) as scan:
            e.tick(); self.assertEqual(scan.call_count, 0)
            e.tick(); self.assertEqual(scan.call_count, 0)
            e.tick(); self.assertEqual(scan.call_count, 1)
        self.assertFalse(e.entry_cancel.is_set())

    def test_operator_pause_still_blocks_after_retirement(self):
        e = self.h.e
        e.queue_risk(self.cid, 'close'); self.finish()
        e.user_paused = True; e.enabled = False; e.run_requested = False; e.resume_pending = False
        with patch.object(e, 'refresh_day'), patch.object(e, 'latch_day', return_value=False), \
                patch.object(e, 'settle'), patch.object(e, 'publish_portfolio'), \
                patch.object(e, 'candidate_decision', return_value=None) as scan:
            for _ in range(4): e.tick()
        self.assertEqual(scan.call_count, 0)
        self.assertTrue(e.entry_cancel.is_set())


if __name__ == '__main__':
    unittest.main(verbosity=2)
