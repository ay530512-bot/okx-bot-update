"""Deterministic public feed simulation, never a live fill or speed benchmark."""
import bisect,copy,importlib.util,json,sys,threading,time,unittest
from collections import deque
from datetime import datetime,timezone,timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
D=Path(__file__).resolve().parents[1];HOST=D/'phone_v168';CORE=D.parent.parent/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
import phone_public_ws as new
import phone_trend_slot as trend
from phone_quote_registry import attach
from phone_entry_feed import quote_details
from phone_entry_journey import Journey
from phone_mobile_entry import Coordinator
from okx_stream import MarketStream
spec=importlib.util.spec_from_file_location('latency_old140',D.parent.parent/'regression_hosts/phone_v140/phone_public_ws.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
T=int(datetime(2026,11,16,19,45,tzinfo=timezone(timedelta(hours=9))).timestamp()*1000)
SYMBOL='CASHCAT-USDT-SWAP'
class Socket:
 def __init__(self):self.sent=[]
 def send(self,v):self.sent.append((time.monotonic(),json.loads(v)))
 def close(self):pass
def stream():
 s=MarketStream();s.connected=True;s.ws=Socket();s.generation=1
 return s
def signal():
 return dict(symbol=SYMBOL,action='LONG',valid_from_ms=T,expires_ms=T+90000,signal_id='offline',pattern=trend.ROUTE,trend130=True)
class Tests(unittest.TestCase):
 def test_late_candidate_old_expires_new_ready_with_same_time_and_freshness(self):
  def replay(transport):
   s=stream();s.symbols={SYMBOL};s.last_subscription=77.;s._phone_priority_symbols={SYMBOL}
   s._phone_subscription_times=deque([77.]);s._phone_watch_revision=1
   clock=[77.358];e=NS(api=NS(now_ms=lambda:T+round(clock[0]*1000)),stream=s,
       cfg={'liquidity':{'ws_max_age_seconds':15}},journal=NS(data={}))
   coordinator=Coordinator(None,None);checks={77.358,82.358,87.358,92.358};ready_at=None
   # Public messages arrive 3s after send; the engine polls every 5s.
   # Artificial scheduling chosen before the comparison, not measured phone performance.
   for i in range(61):
    at=77.358+i*.25;clock[0]=at
    with patch('time.monotonic',return_value=at):
     transport.flush_subscriptions(s)
     for sent,msg in s.ws.sent:
      if sent+3<=at:
       for a in msg['args']:
        pair=(a['instId'],a['channel'])
        s.data[pair]=({'ts':str(e.api.now_ms()),'last':'1'},at,1)
     if i%20==0:
      q=coordinator.market_ready(e,signal(),{'reasons':{},'waiting':[]})
      if q and ready_at is None:ready_at=round(at,3)
   return {'subscribe_at_s':s.ws.sent[0][0],'first_poll_ready_s':ready_at}
  a,b=replay(old),replay(new)
  self.assertIsNone(a['first_poll_ready_s']);self.assertEqual(b['first_poll_ready_s'],82.358)
  self.assertLess(b['subscribe_at_s'],a['subscribe_at_s'])
  (Path(__file__).parent/'latency_reproduction.json').write_text(json.dumps({
   'type':'offline synthetic timeline, not actual CASHCAT replay or fills',
   'input_first_seen_s':77.358,'valid_seconds':90,'engine_poll_seconds':5,
   'assumed_feed_response_seconds':3,'previous_subscription_at_s':77,
   'old140':a,'new141':b,'same_expiry_and_freshness':True},indent=2)+'\n')
 def test_all_candidate_channels_before_unrelated_tickers(self):
  s=stream();s.symbols={SYMBOL};s.monitor_symbols={f'A{i:05}-USDT-SWAP' for i in range(4000)}
  s._phone_priority_symbols={SYMBOL}
  with patch('time.monotonic',return_value=100):new.flush_subscriptions(s)
  args=s.ws.sent[0][1]['args']
  self.assertEqual({(a['instId'],a['channel']) for a in args[:4]},{(SYMBOL,c) for c in s.CHANNELS})
  self.assertLessEqual(len(json.dumps(s.ws.sent[0][1],separators=(',',':')).encode()),new.MAX_PAYLOAD_BYTES)
 def test_urgent_operation_hard_rolling_budget_and_one_second_minimum(self):
  s=stream();s.symbols={SYMBOL};s._phone_priority_symbols={SYMBOL}
  for n in range(7301):
   at=n/2
   with patch('time.monotonic',return_value=at):
    s.active_pairs=set();s._phone_subscription_settled=None
    new.flush_subscriptions(s)
  times=[at for at,_ in s.ws.sent]
  self.assertGreater(len(times),360)
  self.assertTrue(all(b-a>=1 for a,b in zip(times,times[1:])))
  for i,t in enumerate(times):self.assertLessEqual(i+1-bisect.bisect_right(times,t-3600),360)
  self.assertLessEqual(len(s._phone_subscription_times),360)
 def test_nonurgent_still_waits_ten_seconds(self):
  s=stream();s.symbols={SYMBOL};s.last_subscription=100
  with patch('time.monotonic',return_value=109.99):new.flush_subscriptions(s)
  self.assertFalse(s.ws.sent)
  with patch('time.monotonic',return_value=110):new.flush_subscriptions(s)
  self.assertEqual(len(s.ws.sent),1)
 def test_failed_send_never_claims_requested_or_spends_new_generation_budget(self):
  s=stream();s.symbols={SYMBOL};s._phone_priority_symbols={SYMBOL}
  def fail(v):raise BrokenPipeError()
  s.ws.send=fail
  with self.assertRaises(BrokenPipeError):new.flush_subscriptions(s)
  self.assertFalse(s.active_pairs);self.assertFalse(s._phone_subscription_times)
 def test_obsolete_generation_never_commits_send(self):
  s=stream();s.symbols={SYMBOL};s._phone_priority_symbols={SYMBOL}
  s.ws.send=lambda v:setattr(s,'generation',2)
  new.flush_subscriptions(s)
  self.assertFalse(s.active_pairs);self.assertFalse(getattr(s,'_phone_sent_at',{}))
 def engine(self,now=T):
  e=NS(api=NS(now_ms=lambda:now),stream=stream(),records=lambda:[],journal=NS(data={},save=lambda:None),
       cfg={'liquidity':{'ws_max_age_seconds':15}})
  attach(e);return e
 def test_current_leader_prewarms_without_creating_signal_or_order(self):
  e=self.engine();state={'arm':{'t':T-900000,'symbol':SYMBOL},'pending':None,'last':T-900000}
  e.journal.data[trend.STATE]=state;before=copy.deepcopy(e.journal.data)
  e._phone_live_rank=NS(value=dict(ready=True,leader={'symbol':SYMBOL},observed_ms=T))
  e.stream.watch(['OTHER-USDT-SWAP'])
  self.assertIn(SYMBOL,e.stream.symbols);self.assertIn(SYMBOL,e.stream._phone_priority_symbols)
  with patch('time.monotonic',return_value=100):new.flush_subscriptions(e.stream)
  self.assertTrue({(SYMBOL,c) for c in e.stream.CHANNELS}<=e.stream.active_pairs)
  self.assertEqual(e.journal.data,before);self.assertIsNone(state['pending'])
 def test_stale_arm_and_02_cutoff_are_not_prewarmed(self):
  e=self.engine();e.journal.data[trend.STATE]={'arm':{'t':T-1800000,'symbol':SYMBOL},'pending':None,'last':T-1800000}
  e.stream.watch([]);self.assertNotIn(SYMBOL,e.stream.symbols)
  cutoff=T+int(6.25*3600000);self.assertFalse(trend.in_window(cutoff))
  e.journal.data[trend.STATE]['last']=cutoff
  self.assertFalse(trend.prewarm_symbols(e,cutoff))
 def test_valid_pending_kept_and_prioritized_during_ui_watch(self):
  e=self.engine();e.channel_pending={SYMBOL:signal()}
  e.stream.watch(['CHART']);self.assertIn(SYMBOL,e.stream.symbols)
  self.assertIn(SYMBOL,e.stream._phone_priority_symbols)
  e.api.now_ms=lambda:T+90001;e.stream.watch(['CHART'])
  self.assertNotIn(SYMBOL,e.stream._phone_priority_symbols)
 def test_expired_trend_updates_text_and_clears_without_returning(self):
  e=self.engine(T+90001);e.journal.data[trend.STATE]={'last':T,'pending':signal(),'arm':None,'leader_key':(T//86400000*86400000,SYMBOL)}
  e.phone_trend_status='눌림 확인·주문 검사 대기'
  with patch.object(trend,'snapshot_ranks',return_value=([],{'symbol':SYMBOL,'day':T//86400000*86400000},None)):
   self.assertIsNone(trend.scan(e));self.assertIsNone(e.journal.data[trend.STATE]['pending'])
  self.assertIn('90초 만료',e.phone_trend_status)
 def test_seen_trend_cannot_still_claim_pending(self):
  e=self.engine(T+1000);e.journal.data={trend.STATE:{'last':T,'pending':signal(),'arm':None,'leader_key':(T//86400000*86400000,SYMBOL)},'seen_signals':{SYMBOL+':offline':1}}
  with patch.object(trend,'snapshot_ranks',return_value=([],{'symbol':SYMBOL,'day':T//86400000*86400000},None)):
   self.assertIsNone(trend.scan(e));self.assertIn('처리한 추세 신호',e.phone_trend_status)
 def test_last_rejection_survives_expiry(self):
  j=Journey();j.record(SYMBOL,T-900000,'LONG',T+77000,'market_wait')
  j.record(SYMBOL,T-900000,'LONG',T+80000,'market_ready')
  j.record(SYMBOL,T-900000,'LONG',T+81000,'validation_rejected',rejection='spread')
  r=j.report(T+91000)['rows'][0]
  self.assertEqual(r['stage'],'expired_rejected');self.assertEqual(r['rejection'],'spread')
  self.assertEqual(r['first_market_ready_ms'],T+80000)
 def test_requested_and_sent_are_distinct_and_generation_safe(self):
  e=self.engine();e.channel_pending={SYMBOL:signal()}
  with patch('time.monotonic',return_value=100):
   e.stream.watch([]);before=quote_details(e,SYMBOL)
   self.assertTrue(before['channels']['books5']['wanted']);self.assertFalse(before['channels']['books5']['subscribed'])
   new.flush_subscriptions(e.stream);after=quote_details(e,SYMBOL)
  self.assertTrue(after['channels']['books5']['subscribed'])
  self.assertEqual(after['channels']['books5']['request_sent_age_s'],0)
  self.assertEqual(after['observed_ms'],T)
  e.stream.generation+=1;e.stream.connected=False
  d=quote_details(e,SYMBOL)['channels']['books5']
  self.assertIsNone(d['request_sent_age_s']);self.assertFalse(d['subscribed'])
if __name__=='__main__':unittest.main(verbosity=2)
