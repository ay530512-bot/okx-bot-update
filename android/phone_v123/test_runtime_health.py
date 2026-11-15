import json,unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import phone_runtime_health as health
from phone_performance import Timing

class HealthTests(unittest.TestCase):
 def test_summary_exposes_faults_and_wait_reason_without_mutation(self):
  e=NS(phone_entry_diagnostic={'observed_at':1,'reasons':{'실시간 자료 대기':1},'waiting':[]})
  t=Timing('/tmp')
  data={'public':{'connected':True,'transport':{'disconnect_count':2,'last_disconnect':{'observed_at':100,'cause':'read_eof'}}},'account':{'connected':True,'fresh_at_observation':True,'last_equity_receive_age_s':3},'engine':{'recovering':False,'entry_enabled':True,'entry_cancelled':False,'user_paused':False}}
  health.attach(e,t)
  with patch.object(health,'snapshot',return_value=data):
   report=t.report();summary=t.make_summary(report)
  h=summary['runtime_health'];self.assertEqual(h['disconnect_count'],2);self.assertEqual(h['entry']['reasons']['실시간 자료 대기'],1)
  self.assertTrue(h['entry_enabled']);json.dumps(report)
 def test_lock_busy_does_not_claim_public_connected(self):
  e=NS();t=Timing('/tmp');health.attach(e,t)
  with patch.object(health,'snapshot',return_value={'public':{'lock_busy':True},'account':{},'engine':{}}):
   self.assertIsNone(t.report()['runtime_health']['public_connected'])
 def test_snapshot_failure_is_explicit_not_healthy(self):
  e=NS();t=Timing('/tmp');health.attach(e,t)
  with patch.object(health,'snapshot',side_effect=RuntimeError()):self.assertTrue(t.report()['runtime_health']['unavailable'])

if __name__=='__main__':unittest.main()
