import tempfile
import unittest
from pathlib import Path
from test_pc280 import P
from pc_frame_reversal import FrameJournal, FrameWatch, confirmation, MINUTE, QUARTER

class FrameTests(unittest.TestCase):
    def test_contrary_hour_requires_five_minute_break(self):
        for side in (-1,1):
            levels=[100,101,102,103,104,101,102,103,104,105]
            rows=[(i*MINUTE,side*(v-.25),max(side*(v+.25),side*(v-.5)),min(side*(v+.25),side*(v-.5)),side*v) for i,v in enumerate(levels)]
            s=dict(side=side,hour_agrees=False)
            self.assertIsNone(confirmation(s,rows[:5],.01))
            self.assertIsNotNone(confirmation(s,rows,.01))

    def test_history_dedup_recovery_and_missing_outcome(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'records.db'; j=FrameJournal(path)
            h=dict(side=1,anchor_ms=0,ts=100,price=100)
            self.assertTrue(j.add('X',h));self.assertFalse(j.add('X',h))
            j.db.close();j=FrameJournal(path)
            self.assertAlmostEqual(j.finish('X',100+QUARTER,101)[0][2],.8)
            self.assertFalse(j.finish('X',200+QUARTER,102))
            self.assertTrue(j.add('Y',h))
            self.assertFalse(j.finish('Y',QUARTER+18000,None))
            self.assertEqual(j.db.execute("select status from signals where symbol='Y'").fetchone()[0],'missing')
            j.db.close()
