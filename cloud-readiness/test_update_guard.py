import sys,unittest
from types import SimpleNamespace as S
from unittest.mock import Mock
sys.path.insert(0,'chart_update')
from okx_update732 import flat_checkpoint
class Check(unittest.TestCase):
 def engine(self):return S(records=lambda:[],executing_signal=None,approval=None,prepared_signal={'old':'signal'},api=S(snapshot=Mock(return_value={'orders':[],'positions':[]}),pending_algos=Mock(return_value=[])))
 def test_cached_signal_flat_allowed(self):
  e=self.engine();self.assertTrue(flat_checkpoint(e)[0]);self.assertEqual(e.prepared_signal,{'old':'signal'});e.api.pending_algos.assert_called_once_with(full=True)
 def test_real_blockers(self):
  for what in ['records','executing','approval','orders','position','algos']:
   e=self.engine()
   if what=='records':e.records=lambda:[{}]
   elif what=='executing':e.executing_signal={'x':1}
   elif what=='approval':e.approval=object()
   elif what=='orders':e.api.snapshot.return_value['orders']=[{}]
   elif what=='position':e.api.snapshot.return_value['positions']=[{'pos':'1'}]
   else:e.api.pending_algos.return_value=[{}]
   self.assertFalse(flat_checkpoint(e)[0],what)
 def test_network_fail_closed(self):
  e=self.engine();e.api.snapshot.side_effect=RuntimeError('offline')
  with self.assertRaises(RuntimeError):flat_checkpoint(e)
 def test_zero_position_allowed(self):
  e=self.engine();e.api.snapshot.return_value['positions']=[{'pos':'0'}];self.assertTrue(flat_checkpoint(e)[0])
unittest.main()
