import copy,importlib.util,json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
REPO=Path(__file__).resolve().parents[2];WORK=REPO.parent
HOST=REPO/'android/phone_v162';CORE=WORK/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
import phone_public_ws as fix
import okx_stream
from phone_entry_journey import Journey

class Socket:
 def __init__(self):self.sent=[]
 def send(self,v):self.sent.append(v)
 def close(self):pass

def stream():
 s=okx_stream.MarketStream();s.ws=Socket();s.connected=True;s.generation=1
 s.symbols={'H-USDT-SWAP'};s.watch_changed=0
 return s

class Paths(unittest.TestCase):
 def test_subscribe_not_starved_by_watch_changes_and_pacing(self):
  spec=importlib.util.spec_from_file_location('old136',REPO.parent/'regression_hosts/phone_v136/phone_public_ws.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
  a,b=stream(),stream()
  for t in range(100,200):
   a.watch_changed=b.watch_changed=t-.1
   # A changing unrelated chart watch must not prevent candidate subscription.
   a.symbols.add('TEMP'+str(t)+'-USDT-SWAP');b.symbols.add('TEMP'+str(t)+'-USDT-SWAP')
   a._phone_watch_revision=b._phone_watch_revision=t
   with patch('time.monotonic',return_value=t):
    old.flush_subscriptions(a);fix.flush_subscriptions(b)
  self.assertFalse(a.ws.sent)
  self.assertEqual(len(b.ws.sent),10) # at most one operation per ten seconds
  self.assertIn(('H-USDT-SWAP','books5'),b.active_pairs)
 def test_unsubscribe_debounced_and_old_generation_not_committed(self):
  s=stream();s.active_pairs=s.pairs()|{('OLD','books5')};s.watch_changed=99
  with patch('time.monotonic',return_value=100):fix.flush_subscriptions(s)
  self.assertFalse(s.ws.sent)
  with patch('time.monotonic',return_value=101):fix.flush_subscriptions(s)
  self.assertEqual(json.loads(s.ws.sent[-1])['op'],'unsubscribe')
  s=stream()
  def send(v):s.generation+=1
  s.ws.send=send;fix.flush_subscriptions(s);self.assertFalse(s.active_pairs)
 def test_server_notice_observed_without_forced_disconnect_or_raw_text(self):
  import websocket
  s=stream();msg=json.dumps(dict(event='notice',code='64008',connId='SECRET',msg='RAW'))
  ws=NS(recv_data_frame=lambda **k:(websocket.ABNF.OPCODE_TEXT,NS(data=msg)))
  self.assertEqual(fix.receive(ws,websocket,s),msg)
  self.assertEqual(s._public_transport['server_notice']['code'],'64008')
  self.assertNotIn('SECRET',json.dumps(s._public_transport));self.assertTrue(s.connected)
  fix.disconnect(s,s.ws,s.generation,websocket.WebSocketConnectionClosedException('Connection to remote host was lost.'))
  self.assertFalse(s.connected);self.assertEqual(s._public_transport['last_disconnect']['cause'],'read_eof')
  self.assertEqual(s._public_transport['last_disconnect']['server_notice']['code'],'64008')
  for i in range(12):fix.disconnect(s,None,1,OSError('SECRET'))
  self.assertEqual(len(s._public_transport['disconnect_history']),8)
  self.assertNotIn('SECRET',json.dumps(s._public_transport))
 def test_journey_unique_late_and_waiting_are_distinguished(self):
  j=Journey();c=1800000;start=c+900000
  for _ in range(300):j.record('A','1800000','LONG',start+150000,'pattern')
  d=j.report(start+180000);self.assertEqual(d['unique_observed'],1);self.assertEqual(d['first_seen_expired'],1)
  self.assertEqual(d['rows'][0]['stage'],'first_seen_expired')
  j.record('B',c,'SHORT',start+2000,'valid')
  j.record('B',c,'SHORT',start+6000,'market_wait',last_market={'channels':{'books5':{'ready':False}}})
  d=j.report(start+91000);self.assertEqual(d['rows'][0]['stage'],'expired_wait')
  self.assertEqual(d['rows'][0]['first_delay_s'],2)
  j.record('C',c,'SHORT',start+80000,'admission')
  self.assertEqual(j.report(start+100000)['rows'][0]['stage'],'admission')
  for i in range(1030):j.record('X'+str(i),c,'LONG',start+1,'pattern')
  self.assertEqual(j.report(start+2)['retained'],1024)

if __name__=='__main__':unittest.main()
