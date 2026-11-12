import sys,unittest,queue,threading,copy
from types import SimpleNamespace as S
from unittest.mock import Mock,patch
sys.path.insert(0,'chart_update')
import okx_continuity732 as c
class Tests(unittest.TestCase):
 def engine(self):
  e=S(cfg={'execution':{'continuous_trading':True,'recovery_snapshots':2}},settings={'TRADING_EXCHANGE':'okx'},journal=S(data={'account':'test-account'},save=Mock()),events=queue.Queue(),log=Mock(),budget=1,entry_cancel=threading.Event(),enabled=False,user_paused=False,preview=False,commands=queue.Queue(),stop_event=threading.Event(),account_stream=S(fresh=lambda:True),stream=S(connected=True),recovering=False,good_snapshots=2,queued_risks=[],risk_queue=queue.Queue(),records=lambda:[],slot_count=lambda:0,snapshot=Mock(return_value={'orders':[],'equity':300}),activate=Mock())
  c.started(e);e.resume_pending=True;return e
 def test_recovery_gate(self):
  e=self.engine();self.assertTrue(c.resume_if_ready(e));e.activate.assert_called_once()
 def test_disconnected(self):
  e=self.engine();e.stream.connected=False;self.assertFalse(c.resume_if_ready(e));e.activate.assert_not_called()
 def test_operator_stop_persists(self):
  e=self.engine();c.stopped(e,'operator');c.initialize(e);self.assertFalse(e.run_requested);self.assertFalse(c.resume_if_ready(e))
 def test_changed_policy_requires_confirmation(self):
  e=self.engine();e.cfg['execution']['recovery_snapshots']=3;c.initialize(e);self.assertFalse(e.run_requested)
 def test_pending_order_blocks_resume(self):
  e=self.engine();e.snapshot.return_value['orders']=[{}];self.assertFalse(c.resume_if_ready(e));e.activate.assert_not_called()
 def test_uncertain_fill_blocks_resume(self):
  e=self.engine();e.records=lambda:[{'phase':'active','market_fill_check_pending':True}];self.assertFalse(c.resume_if_ready(e))
 def test_private_read_failure_never_activates(self):
  e=self.engine();e.snapshot.side_effect=TimeoutError
  with self.assertRaises(TimeoutError):c.resume_if_ready(e)
  e.activate.assert_not_called()
 def test_preflight_never_claims_live_ready(self):
  import preflight
  self.assertFalse(preflight.collect(False)['live_ready'])
if __name__=='__main__':unittest.main()
