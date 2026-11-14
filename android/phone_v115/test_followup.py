import sys,os,unittest,tempfile,json,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import phone_performance as perf
from phone_signal_cache import SignalCache

class Followup(unittest.TestCase):
 def test_inputs_shared_only_inside_packet(self):
  t=perf.Timing('/tmp');t.local.group='optimized';c=SignalCache(t)
  a=[1,2];fn=Mock(side_effect=lambda x:sum(x));f=c.wrap(fn,'first');g=c.wrap(fn,'second')
  with c.packet_scope():self.assertEqual(f(a),3);self.assertEqual(g(a),3)
  self.assertEqual(c.serializations,1);self.assertEqual(c.shared_inputs,1)
  a[0]=3
  with c.packet_scope():self.assertEqual(f(a),5)
  self.assertEqual(fn.call_count,3)
 def test_bytes_limit(self):
  t=perf.Timing('/tmp');t.local.group='optimized';c=SignalCache(t,max_bytes=64)
  f=c.wrap(lambda x:len(x),'test')
  for i in range(12):
   with c.packet_scope():f([i]*10)
  self.assertLessEqual(c.key_bytes,64)
  with c.packet_scope():f(list(range(100)))
  self.assertLessEqual(c.key_bytes,64)
 def test_exception_rethrows_and_no_secret_text(self):
  t=perf.Timing('/tmp')
  try:
   with t.scope('entry.admission_and_order'):raise ValueError('시장가 실제 체결가 기준 포지션 예상 손실 한도 초과 SECRET-123')
  except ValueError:pass
  else:self.fail('exception swallowed')
  report=t.report();self.assertEqual(report['recent_exceptions'][0]['category'],'postfill_risk_limit')
  self.assertNotIn('SECRET-123',json.dumps(report));self.assertEqual(report['recent_exceptions'][0]['stage'],'entry.admission_and_order')
 def test_expired_update_clears_ticket(self):
  sys.path.insert(0,os.environ['OKX_TEST_CORE'])
  from phone_update import PhoneUpdater
  u=PhoneUpdater(Path('/tmp'),Mock())
  u.candidate={'owner':'one','expires':time.monotonic()-1,'ticket':'x'}
  u.state['ticket']='x'
  with self.assertRaises(ValueError):u.install({'owner':'one','ticket':'x'})
  self.assertIsNone(u.candidate);self.assertNotIn('ticket',u.snapshot())

if __name__=='__main__':unittest.main()
