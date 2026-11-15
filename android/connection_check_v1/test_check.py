import importlib.util
import json
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('netcheck',Path(__file__).with_name('check.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)


class Tests(unittest.TestCase):
    def test_idle_and_periodic(self):
        self.assertFalse(c.due('idle',25,24,0))
        self.assertTrue(c.due('periodic',25,24,0))
        self.assertTrue(c.due('idle',25,0,0))
        self.assertFalse(c.due('periodic',26,24,25))

    def test_count_reset_and_stale(self):
        stats={'idle':dict(connections=0,market_frames=0,disconnects=0,connect_failures=0,pings=0,pongs=0)}
        rows=[dict(pid=1,age=0,count=2),dict(pid=1,age=0,count=5)]
        self.assertIn('봇 신규 끊김: 3',c.summarize(rows,stats,600))
        rows[-1]['pid']=2
        self.assertIn('봇 신규 끊김: 판정 불가',c.summarize(rows,stats,600))
        rows[-1]['pid']=1;rows[-1]['count']=0
        self.assertIn('봇 신규 끊김: 판정 불가',c.summarize(rows,stats,600))
        self.assertIn('봇 유효 표본: 0/1',c.summarize([dict(age=20,count=1)],stats,600))

    def test_bot_fields_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'phone_connection_trace.json').write_text(json.dumps(dict(observed_at=time.time(),secret='NO',latest={'public':{'transport':{'last_disconnect':{'cause':'read_eof','private':'NO'}}}})))
            sample=c.bot_sample(p)
            self.assertNotIn('NO',json.dumps(sample))
            self.assertEqual(sample['last']['cause'],'read_eof')

    def fake_run(self, fail):
        class Closed(Exception):pass
        class Raw:
            def settimeout(self,*a):pass
            def connect(self,*a):pass
            def close(self,*a,**k):pass
        class WS(Raw):
            def send(self,msg):
                if msg!='ping':
                    body=json.loads(msg)
                    assert body=={'op':'subscribe','args':[{'channel':'tickers','instId':'AAVE-USDT-SWAP'}]}
            def recv_data_frame(self,**k):
                time.sleep(.01)
                if fail:raise Closed()
                return 1,types.SimpleNamespace(data=b'{"data":[{"ts":"123"}]}')
        mod=types.SimpleNamespace(__version__='test',ABNF=types.SimpleNamespace(OPCODE_CLOSE=8,OPCODE_TEXT=1,OPCODE_BINARY=2),
            WebSocketTimeoutException=TimeoutError,create_connection=lambda *a,**k:WS())
        adapter=types.SimpleNamespace(public_socket_class=lambda w:WS,failure_kind=lambda e:'read_eof',PublicPeerClosed=Closed)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            with patch.object(c,'OUT',out),patch.object(c,'dependencies',return_value=(mod,adapter)),patch.object(c,'bot_sample',return_value=dict(pid=1,age=0,count=0)),patch.object(c.socket,'getaddrinfo',return_value=[(2,1,6,'',('test',443))]),patch.object(c.socket,'socket',return_value=Raw()),patch.object(c.ssl,'create_default_context',return_value=types.SimpleNamespace(wrap_socket=lambda raw,**k:raw)):
                c.run(1.1)
            result=json.loads((out/'result.json').read_text())
            self.assertFalse(result['worker_pending'])
            for value in result['stats'].values():
                self.assertEqual(value['connections'],1)
                self.assertEqual(value['disconnects'],int(fail))
                if not fail:self.assertGreater(value['market_frames'],0)

    def test_both_arms_receive_no_orders(self):self.fake_run(False)
    def test_both_arms_eof_recorded(self):self.fake_run(True)


if __name__=='__main__':unittest.main()
