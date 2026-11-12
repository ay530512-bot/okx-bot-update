import sys,unittest,tempfile,json,time
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import Mock,patch
sys.path.insert(0,'chart_update')
from okx_core import OKX,UnknownOutcome,Journal,BotError
class TransportError(Exception):pass
class Tests(unittest.TestCase):
 def test_write_timeout_not_retried(self):
  api=object.__new__(OKX);api.requests=S(RequestException=TransportError);api.session=S(request=Mock(side_effect=TransportError()));api.synced=time.monotonic();api.key='fake';api.secret='fake';api.passphrase='fake';api.now_ms=lambda:0
  with self.assertRaises(UnknownOutcome):api.request('POST','/api/v5/trade/order',body={'test':'no network'})
  api.session.request.assert_called_once()
 def test_atomic_state_failure_preserves_old(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'bot_state.json';j=Journal(p);j.save();old=p.read_bytes();j.data['account']='new'
   with patch('okx_core.os.replace',side_effect=OSError('disk failure')):
    with self.assertRaises(OSError):j.save()
   self.assertEqual(p.read_bytes(),old);self.assertEqual(list(Path(folder).glob('*.tmp')),[])
 def test_corrupt_state_blocks_start(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'bot_state.json';p.write_text('{broken')
   with self.assertRaises(BotError):Journal(p)
if __name__=='__main__':unittest.main()
