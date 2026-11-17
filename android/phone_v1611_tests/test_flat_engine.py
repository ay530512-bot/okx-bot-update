"""Real serial engine quit: orphan risk flag vs actual owned position."""
import copy
import json
import unittest
from execution_harness import D,Harness,NETWORK_ATTEMPTS,BotError

FIXTURE=json.loads((D/'fixtures.json').read_text())['fixtures']['trend_pullback_LONG']


class QuitTests(unittest.TestCase):
    def setUp(self):self.h=Harness(copy.deepcopy(FIXTURE),0)
    def tearDown(self):self.h.close();self.assertEqual(NETWORK_ATTEMPTS,[])
    def test_paused_flat_serial_quit_succeeds_despite_old_risk_flag(self):
        e=self.h.e;e.queued_risks.add('already-closed')
        e.handle('pause',{});e.handle('quit',{})
        self.assertTrue(e.stop_event.is_set());self.assertFalse(e.journal.data['entry_continuity732']['requested'])
        self.assertFalse(any(path.startswith('post ') for path,args in self.h.api.calls))
    def test_live_position_refuses_quit_and_keeps_protection(self):
        o=self.h.submit(self.h.signal());self.h.api.fill(o['client_id']);self.assertTrue(self.h.reconcile(o))
        e=self.h.e;algos=copy.deepcopy(self.h.api.algos);n=len(self.h.api.calls)
        e.handle('pause',{})
        with self.assertRaises(BotError):e.handle('quit',{})
        self.assertFalse(e.stop_event.is_set());self.assertEqual(self.h.api.algos,algos)
        self.assertFalse(any(path.startswith('post ') for path,args in self.h.api.calls[n:]))


if __name__=='__main__':unittest.main(verbosity=2)
