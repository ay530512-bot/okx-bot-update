import http.client,json,os,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
sys.path[:0]=[os.environ['OKX_TEST_HOST'],os.environ['OKX_TEST_CORE']]
from phone_mobile import mobile_module
from phone_parallel import preference

class Controls(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);(self.root/'runtime-q2x').mkdir()
  module=mobile_module(Path(os.environ['OKX_TEST_CORE']))
  self.mobile=module.PhoneMobile(self.root/'runtime-q2x',{},dict(https_host='',salt='a'*32,password_hash='b'*128,controls_enabled=True),feed_factory=lambda *a:NS(start=lambda:None,stop=lambda:None,select=lambda *a:None),port=0)
  self.mobile.sessions['fixture']=time.monotonic()+60;self.mobile.start()
 def tearDown(self):self.mobile.stop();self.temp.cleanup()
 def request(self,key,ident='request_fixture_001',cookie=True,origin=None):
  c=http.client.HTTPConnection('127.0.0.1',self.mobile.port,timeout=3)
  headers={'Origin':origin or 'http://127.0.0.1:'+str(self.mobile.port),'Content-Type':'application/json'}
  if cookie:headers['Cookie']='mobile_session=fixture'
  c.request('POST','/api/control/calculation',json.dumps(dict(key=key,client_id=ident)),headers)
  r=c.getresponse();data=json.loads(r.read());c.close();return r.status,data
 def test_auth_and_origin_required(self):
  self.assertEqual(self.request('serial',cookie=False)[0],401)
  self.assertEqual(self.request('serial',origin='https://wrong.example')[0],403)
  self.assertFalse((self.root/'phone_calculation.json').exists())
 def test_change_restore_and_replay_idempotent(self):
  self.assertEqual(self.request('parallel4')[0],202);self.assertEqual(preference(self.root)['workers'],4)
  self.assertEqual(self.request('serial','request_fixture_002')[0],202);self.assertEqual(preference(self.root)['workers'],0)
  self.assertEqual(self.request('parallel4')[0],202);self.assertEqual(preference(self.root)['workers'],0)
  self.assertTrue(self.mobile.control_commands.empty())
 def test_readonly_installing_and_bad_mode_rejected(self):
  self.assertEqual(self.request('eight')[0],400)
  self.assertEqual(self.request('serial','bad')[0],400)
  self.mobile.config['controls_enabled']=False;self.assertEqual(self.request('serial')[0],403)
  self.mobile.config['controls_enabled']=True;self.mobile.updater.installing=True;self.assertEqual(self.request('serial')[0],400)
  self.assertFalse((self.root/'phone_calculation.json').exists())
if __name__=='__main__':unittest.main(verbosity=2)
