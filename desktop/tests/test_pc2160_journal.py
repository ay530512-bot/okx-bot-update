import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path.cwd() / 'OKX_PC_PACKAGE' / 'runtime'))
from pc_flow_journal import FAST_HORIZON_MS, FlowJournal, GRACE_MS, HORIZON_MS


class JournalTest(unittest.TestCase):
    ts = 1_800_000_000_000

    def setUp(self):
        assets = tempfile.TemporaryDirectory()
        self.addCleanup(assets.cleanup)
        self.path = Path(assets.name) / 'symbol_flow.db'
        self.journal = self.open_db()
        self.hit = dict(ts=self.ts, anchor_ms=self.ts-900_000, side=1, price=100.)
        self.flow = dict(side=-1, regime='continuation', route='normal15')

    def open_db(self):
        journal = FlowJournal(self.path)
        self.addCleanup(journal.close)
        return journal

    def row(self, source):
        return dict(self.journal.db.execute('SELECT * FROM observations WHERE source=?', (source,)).fetchone())

    def test_first_observed_print_on_or_after_each_horizon(self):
        j = self.journal
        self.assertTrue(j.add('H', 'classic', self.hit, self.flow))
        self.assertTrue(j.add('H', 'fast5', self.hit, dict(self.flow, side=0)))
        self.assertEqual(j.pending, {'H': self.ts+FAST_HORIZON_MS})
        self.assertFalse(j.finish('H', self.ts+FAST_HORIZON_MS-1, 80))
        self.assertFalse(j.finish('H', self.ts+FAST_HORIZON_MS, float('nan')))
        self.assertEqual(j.expire(self.ts+FAST_HORIZON_MS+GRACE_MS), 0)
        done = j.finish('H', self.ts+FAST_HORIZON_MS+GRACE_MS, 95)
        self.assertEqual(len(done), 1)
        self.assertAlmostEqual(done[0]['chosen_net_pct'], 0)
        self.assertAlmostEqual(done[0]['original_net_pct'], -5.2)
        self.assertEqual(self.row('fast5')['horizon_ms'], FAST_HORIZON_MS)
        self.assertEqual(j.pending, {'H': self.ts+HORIZON_MS})
        done = j.finish('H', self.ts+HORIZON_MS, 92)
        self.assertAlmostEqual(done[0]['chosen_net_pct'], 7.8)
        self.assertAlmostEqual(done[0]['original_net_pct'], -8.2)
        self.assertEqual(json.loads(self.row('classic')['flow_json'])['route'], 'normal15')
        self.assertEqual(self.row('classic')['end_price'], 92)
        self.assertFalse(j.finish('H', self.ts+HORIZON_MS+1, 90))
        self.assertNotIn('H', j.pending)

    def test_duplicate_setup_and_restarts(self):
        j = self.journal
        self.assertTrue(j.add('H', 'swing', self.hit, self.flow))
        again = self.open_db()
        self.assertEqual(again.pending, j.pending)
        self.assertFalse(again.add('H','swing', dict(self.hit, ts=self.ts+9), dict(self.flow, side=1)))
        self.assertEqual(again.finish('H',self.ts+HORIZON_MS,103)[0]['chosen_side'],-1)
        self.assertEqual(j.finish('H',self.ts+HORIZON_MS+1,104), [])
        self.assertEqual(self.row('swing')['end_price'], 103)
        self.assertFalse(j.add('H', 'swing', self.hit, self.flow))
        self.assertNotIn('H', j.pending)
        self.assertTrue(j.add('H', 'swing', dict(self.hit,last_pivot_ms=self.ts-3), self.flow))
        self.assertTrue(j.add('H', 'fast5', self.hit, self.flow))
        self.assertTrue(j.add('H', 'fast5', dict(self.hit,ts=self.ts+100), self.flow))
        self.assertFalse(j.add('H', 'fast5', dict(self.hit,ts=self.ts+100), self.flow))

    def test_no_trade_expiry_survives_restart_and_keeps_later_observations(self):
        j = self.journal
        j.add('H','classic',self.hit,dict(self.flow,horizon_ms=FAST_HORIZON_MS))
        j.add('H','swing',self.hit,self.flow)
        j.add('X','fast5',self.hit,dict(self.flow,horizon_ms=HORIZON_MS))
        again = self.open_db()
        deadline = self.ts+FAST_HORIZON_MS+GRACE_MS+1
        self.assertEqual(again.expire(deadline), 1)
        self.assertEqual(again.expire(deadline), 0)
        self.assertEqual(again.pending, {'H':self.ts+HORIZON_MS,'X':self.ts+HORIZON_MS})
        self.assertIsNone(self.row('classic')['original_net_pct'])
        self.assertIsNone(self.row('classic')['chosen_net_pct'])
        self.assertIsNone(self.row('classic')['end_price'])
        self.assertEqual(self.row('classic')['status'], 'missing')
        self.assertFalse(again.finish('X',self.ts+HORIZON_MS+GRACE_MS+1,102))
        self.assertEqual(self.row('fast5')['status'], 'missing')
        self.assertTrue(again.finish('H',self.ts+HORIZON_MS+1,101))
        self.assertEqual(self.open_db().pending, {})

    def test_rollback_preserves_open_in_memory(self):
        j=self.journal
        j.add('H','classic',self.hit,self.flow)
        with j.db:
            j.db.execute("""CREATE TRIGGER fail_update BEFORE UPDATE ON observations
                BEGIN SELECT RAISE(ABORT,'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            j.finish('H',self.ts+HORIZON_MS,103)
        self.assertIn('H',j.pending)
        self.assertEqual(self.row('classic')['status'],'open')
        with j.db:
            j.db.execute('DROP TRIGGER fail_update')
        self.assertTrue(j.finish('H',self.ts+HORIZON_MS+1,104))

if __name__ == '__main__':
    unittest.main()
