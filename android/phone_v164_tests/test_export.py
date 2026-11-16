import copy,http.client,importlib.util,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from http.server import ThreadingHTTPServer
D=Path(__file__).resolve().parents[1];HOST=D/'phone_v164';CORE=D.parent.parent/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
from phone_diagnostic_export import export
class Tests(unittest.TestCase):
 def test_prior_run_journey_retained_without_restoring_pending(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);health={'program_version':'1.4.0','signal_journey':{'rows':[{'symbol':'TEST-USDT-SWAP','action':'LONG','confirmation_ms':1,'first_delay_s':77.358,'stage':'market_wait'}]}}
   row={'version':'phone-entry-history-1','run_id':'old','observed_at':1,'health':health}
   (root/'phone_entry_history.previous.jsonl').write_text(json.dumps(row)+'\n')
   (root/'phone_entry_history.jsonl').write_text('{unfinished')
   summary={'runtime_health':{'program_version':'1.4.2','signal_journey':None},'orders':[{'secret':'HIDDEN'}]}
   before=copy.deepcopy(summary);out=export(root,summary)
   self.assertEqual(out['historical_signals'][0]['first_delay_s'],77.358)
   self.assertIsNone(out['runtime_health']['signal_journey']);self.assertEqual(summary,before)
   self.assertEqual(out['history_rows'],1);self.assertNotIn('HIDDEN',json.dumps(out))
 def test_full_metrics_and_transport_survive_allowlist(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   (root/'phone_performance.json').write_text(json.dumps({'metrics':[{'label':'scan.universe','group':'background','max_s':77.0}],'exception_counts':{'a':{'count':2}},'api_key':'SECRET'}))
   (root/'phone_connection_trace.json').write_text(json.dumps({'latest':{'public':{'transport':{'text_pings':5,'text_pongs':4,'pending_ping_age_s':2}}},'settings':'SECRET'}))
   health={'morning_rank':{'symbol':'TEST-USDT-SWAP','gain':.27},'morning_rank_checked_ms':100,
           'trend_inputs':{'missing_hourly_details':[{'symbol':'JCT-USDT-SWAP','reason':'09시 기준봉 대기','completed1h_count':12}]}}
   out=export(root,{'runtime_health':health});self.assertEqual(out['runtime_health'],health)
   self.assertEqual(out['metrics'][0]['max_s'],77)
   self.assertEqual(out['connection_trace']['latest']['public']['transport']['text_pings'],5)
   self.assertNotIn('SECRET',json.dumps(out))
 def test_export_is_bounded_and_skips_links(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);secret=root/'secret';secret.write_text('SECRET');(root/'phone_connection_trace.json').symlink_to(secret)
   (root/'phone_entry_history.jsonl').write_text(''.join(json.dumps({'version':'phone-entry-history-1','observed_at':i,'health':{}})+'\n' for i in range(501)))
   out=export(root,{});self.assertEqual(out['history_rows'],240);self.assertNotIn('SECRET',json.dumps(out))
   self.assertTrue(out['export_errors'])
 def test_endpoint_requires_valid_host_and_session(self):
  from phone_mobile import mobile_module
  module=mobile_module(CORE);calls=[]
  service=NS(hosts=set(),config={'https_host':''},lock=threading.Lock(),sessions={'test':time.monotonic()+60},diagnostic_export=lambda:calls.append(1) or {'format':'test'})
  server=ThreadingHTTPServer(('127.0.0.1',0),module.Mobile.handler(service));port=server.server_address[1];service.hosts={f'127.0.0.1:{port}'}
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   for headers,status in [({},401),({'Cookie':'mobile_session=test','Host':'evil'},403),({'Cookie':'mobile_session=test'},200)]:
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=3);conn.request('GET','/api/phone/diagnostic',headers=headers);res=conn.getresponse();self.assertEqual(res.status,status);res.read();conn.close()
   self.assertEqual(calls,[1])
  finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main(verbosity=2)
