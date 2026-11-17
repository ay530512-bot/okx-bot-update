"""Simulate exchange maintenance, failed warm sockets and generation races."""
import json
from pathlib import Path
import sys, threading, time, unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
D=Path(__file__).resolve().parent
sys.path[:0]=[str(D.parent/'phone_v171'),str(D.parents[2]/'core121')]
import websocket
import phone_public_ws as wire
import phone_public_lanes as lanes
import phone_ws_handover as hand
from okx_stream import MarketStream

class Tests(unittest.TestCase):
 def setUp(self):
  wire.install();lanes.install()
  self.s=MarketStream();self.s.symbols={'X'};self.s._phone_monitor_only=False
  wire.activate(self.s,Mock());self.s._public_transport['server_notice']={'code':'64008','observed_at':time.time()}
  self.old=self.s.ws
 def tearDown(self):hand.abandon(self.s)
 def pending(self):
  p=hand.Pending(self.s);wire.activate(p.shadow,Mock());p.shadow.active_pairs=set(p.wanted)
  p.shadow._phone_acknowledged=set(p.wanted)
  p.shadow._phone_sent_at={k:(1,time.monotonic()) for k in p.wanted}
  for symbol,ch in p.wanted:
   if ch!='trades':p.shadow.feed(json.dumps({'arg':{'instId':symbol,'channel':ch},'data':[{'ts':str(int(time.time()*1000)),'last':'10','markPx':'10'}]}))
  p.ready=True;p.ready_at=time.monotonic();p.done.set();self.s._phone_upgrade_pending=p
  return p
 def test_only_notice_creates_one_warm_worker_without_blocking_old_reader(self):
  self.s._public_transport['server_notice']=None
  with patch.object(hand.threading,'Thread') as factory:
   self.assertFalse(hand.poll(self.s));factory.assert_not_called()
   self.s._public_transport['server_notice']={'code':'64008'}
   self.assertFalse(hand.poll(self.s));self.assertFalse(hand.poll(self.s));self.assertEqual(factory.call_count,1)
   self.assertIs(self.s.ws,self.old);self.assertTrue(self.s.connected)
 def test_warm_adoption_keeps_fresh_timestamps_new_generation_no_old_quotes(self):
  p=self.pending();now=time.monotonic();self.s.data[('OLD','tickers')]=({'ts':'1'},now,self.s.generation)
  before={k:v[1] for k,v in p.shadow.data.items()};new=p.shadow.ws
  self.assertTrue(hand.poll(self.s));self.assertIs(self.s.ws,new);self.assertTrue(self.s.connected)
  self.assertEqual(self.s.generation,2);self.assertNotIn(('OLD','tickers'),self.s.data)
  self.assertEqual(self.s._public_transport.get('disconnect_count'),0)
  self.assertEqual(self.s._public_transport['upgrade_count'],1)
  self.assertEqual({k:v[1] for k,v in self.s.data.items()},before)
  self.assertTrue(all(v[2]==2 for v in self.s.data.values()))
  self.assertTrue(all(v[4]==2 for v in self.s.band_prices.values()))
  self.assertIsNone(self.s.read('X','trades'));self.assertFalse(self.s.ready('X',{'liquidity':{'ws_max_age_seconds':5}},int(time.time()*1000)))
  self.assertTrue(p.taken)
 def test_stale_replacement_is_rejected_without_disconnecting_current(self):
  p=self.pending();p.shadow.data[('X','tickers')]=(p.shadow.data[('X','tickers')][0],time.monotonic()-10,1)
  self.assertFalse(hand.poll(self.s));self.assertIs(self.s.ws,self.old);self.assertTrue(self.s.connected)
  self.assertEqual(self.s._public_transport['upgrade_failures'],1)
 def test_missing_subscription_ack_cannot_handover(self):
  p=self.pending();p.shadow._phone_acknowledged.remove(('X','books5'))
  self.assertFalse(hand.poll(self.s));self.assertIs(self.s.ws,self.old)
 def test_changed_watch_cannot_adopt_wrong_subscriptions(self):
  self.pending();self.s.symbols.add('Y');self.assertFalse(hand.poll(self.s));self.assertIs(self.s.ws,self.old)
 def test_manual_generation_change_cannot_adopt_late_worker(self):
  p=self.pending();self.s.generation+=1;self.assertFalse(hand.poll(self.s));self.assertTrue(p.cancel.is_set());self.assertIs(self.s.ws,self.old)
 def test_stopped_owner_discards_ready_worker(self):
  p=self.pending();self.s.stop_event.set();self.assertFalse(hand.poll(self.s));self.assertTrue(p.cancel.is_set());self.assertFalse(p.taken)
 def test_warm_failure_keeps_current_and_rate_limits_retries(self):
  p=self.pending();p.ready=False;p.error='WebSocketBadStatusException'
  self.assertFalse(hand.poll(self.s));self.assertIs(self.s.ws,self.old)
  with patch.object(hand.threading,'Thread') as start:self.assertFalse(hand.poll(self.s));start.assert_not_called()
 def test_replacement_receiving_own_upgrade_notice_is_not_adopted(self):
  p=self.pending();p.shadow._public_transport['server_notice']={'code':'64008'}
  self.assertFalse(hand.poll(self.s));self.assertIs(self.s.ws,self.old)
 def test_monitor_rollover_does_not_touch_execution_owner(self):
  execution=self.s;monitor=execution._phone_monitor_stream;monitor.monitor_symbols={'X'}
  self.s=monitor;wire.activate(monitor,Mock());self.old=monitor.ws
  p=self.pending();self.assertTrue(hand.poll(monitor));self.assertEqual(execution.generation,1);self.assertEqual(monitor.generation,2)
  self.assertTrue(execution.connected);self.assertEqual(monitor.active_pairs,{('X','tickers')})
 def test_warm_worker_has_no_risk_callback_and_uses_real_subscription_acks(self):
  self.s.on_mark=Mock();p=hand.Pending(self.s)
  messages=[]
  for s,ch in sorted(p.wanted):
   messages.append(json.dumps({'event':'subscribe','arg':{'instId':s,'channel':ch}}))
   messages.append(json.dumps({'arg':{'instId':s,'channel':ch},'data':[{'ts':str(int(time.time()*1000)),'last':'10','markPx':'10'}]}))
  ws=Mock();ws.recv_data_frame.side_effect=[(1,NS(data=x.encode())) for x in messages]
  with patch.object(wire,'connect',return_value=(ws,Mock())):hand.warm(p)
  self.assertTrue(p.done.is_set());self.assertTrue(p.ready);self.s.on_mark.assert_not_called()
  self.assertIs(self.s.ws,self.old);self.assertTrue(p.wanted<=p.shadow._phone_acknowledged)
  p.close()
 def test_failed_warm_handshake_closes_raw_and_retains_original(self):
  p=hand.Pending(self.s)
  with patch.object(wire,'connect',side_effect=ConnectionError('failure')):hand.warm(p)
  self.assertTrue(p.done.is_set());self.assertFalse(p.ready);self.assertIs(self.s.ws,self.old)
 def test_cancelled_registration_closes_late_socket(self):
  p=hand.Pending(self.s);p.close();late=Mock()
  with self.assertRaises(ConnectionAbortedError):hand.register(p,late)
  late.close.assert_called_once()
 def test_disconnect_http_status_is_numeric_without_raw_headers(self):
  err=websocket.WebSocketBadStatusException('private server text',status_code=429)
  wire.disconnect(self.s,self.s.ws,1,err)
  d=self.s._public_transport['last_disconnect'];self.assertEqual(d['http_status'],429)
  self.assertNotIn('private server text',json.dumps(d))
 def test_eof_after_healthy_stream_uses_fast_retry_early_failure_backs_off(self):
  for uptime,expect in [(120,.25),(5,2)]:
   s=MarketStream();s.symbols={'X'};s.stop_event=Mock();s.stop_event.is_set.return_value=False
   def wait(delay):s.stop_event.is_set.return_value=True
   s.stop_event.wait.side_effect=wait
   def failed(*args):
    wire.diagnostics(s).update(connected_at=time.monotonic()-uptime,frame_at=time.monotonic())
    raise websocket.WebSocketConnectionClosedException('Connection to remote host was lost.')
   with patch.object(wire,'connect',return_value=(Mock(),Mock())),patch.object(wire,'receive',side_effect=failed):wire.run(s)
   s.stop_event.wait.assert_called_once_with(expect);self.assertFalse(s.connected)
 def test_original_lock_remains_available_during_blocked_retired_close(self):
  p=self.pending();gate=threading.Event();entered=threading.Event()
  def blocked(**kwargs):entered.set();gate.wait(2)
  self.old.close.side_effect=blocked
  try:
   self.assertTrue(hand.poll(self.s));self.assertTrue(entered.wait(1))
   self.assertTrue(self.s.lock.acquire(timeout=.2));self.s.lock.release()
   self.assertIsNotNone(self.s.read('X','tickers'))
  finally:gate.set()

if __name__=='__main__':unittest.main(verbosity=2)
