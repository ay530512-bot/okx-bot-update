import copy,hashlib,json,time,unittest
from pathlib import Path
from execution_harness import D,CORE,HOST,Harness,NETWORK_ATTEMPTS,BotError,Rejected,UnknownOutcome,dec,trend
FIXTURES=json.loads((D/'fixtures.json').read_text())['fixtures']
RESULTS=[]
class EntryTests(unittest.TestCase):
 def setUp(self):self.h=None
 def tearDown(self):
  if self.h:self.h.close()
  self.assertEqual(NETWORK_ATTEMPTS,[])
 def harness(self,key='trend_pullback_LONG',workers=0):
  self.h=Harness(copy.deepcopy(FIXTURES[key]),workers);return self.h
 def positive(self,key,workers):
  h=self.harness(key,workers);s=h.signal()
  expected=key.rsplit('_',1);v=s['decision_record']['volume_wick_proof']
  self.assertEqual(v['route721'],expected[0]);self.assertEqual(s['action'],expected[1])
  self.assertEqual(s['leverage'],5 if s.get('trend130') else 10)
  o=h.submit(s);self.assertEqual(o['phase'],'submitted');self.assertFalse(o.get('protection_verified'))
  self.assertEqual(len(h.api.opening_posts()),1)
  # An ACK alone is not a filled entry or a verified protective SL.
  snap=h.e.snapshot();self.assertIsNone(h.e.reconcile(snap));self.assertEqual(o['phase'],'submitted')
  h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o));self.assertEqual(o['phase'],'active')
  self.assertTrue(o['protection_verified']);self.assertFalse(o['market_fill_check_pending'])
  self.assertEqual(dec(o['initial_margin_target']),dec('74.25'))
  self.assertLessEqual(abs(dec(o['committed_margin'])-dec('74.25')),dec('74.25')*dec('.03'))
  posts=len(h.api.opening_posts());h.e.entry(s);self.assertEqual(len(h.api.opening_posts()),posts)
  self.assertIn(s['symbol']+':'+s['signal_id'],h.e.journal.data['seen_signals'])
  c=h.e.execution_status.counts
  self.assertEqual(c['orders'],1);self.assertEqual(c['fills'],1);self.assertEqual(c['protected'],1)
  RESULTS.append(dict(rule=key,workers=workers,symbol=s['symbol'],confirmation_close_ms=s['valid_from_ms'],
   leverage=o['leverage'],quantity=o['quantity'],margin=o['committed_margin'],fill_px=o['fill_px'],
   stop_px=o['stop_px'],phase=o['phase'],protection_verified=o['protection_verified'],opening_requests=posts,
   api_reads=len([x for x in h.api.calls if not x[0].startswith('post ')]),
   assumption='Historical candle signal; synthetic tight quotes, contract metadata, account and exchange fills.'))
 def test_expired_before_candidate_blocks(self):
  h=self.harness();h.api.now+=90001;h.ready();self.assertIsNone(h.candidate());self.assertEqual(h.api.opening_posts(),[])
 def test_missing_quotes_block_then_same_valid_signal_recovers(self):
  h=self.harness();h.e.stream.data.clear();self.assertIsNone(h.candidate());self.assertEqual(h.api.opening_posts(),[])
  h.ready();s=h.candidate();self.assertIsNotNone(s);o=h.submit(s);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
 def test_stale_quotes_after_candidate_blocks(self):
  h=self.harness();s=h.signal();h.api.now+=61000
  with self.assertRaisesRegex(BotError,'실시간 시세'):h.submit(s)
  self.assertEqual(h.api.opening_posts(),[])
 def test_wide_spread_blocks(self):
  h=self.harness();s=h.signal();h.api.spread=dec('.002');h.ready()
  with self.assertRaisesRegex(BotError,'스프레드'):h.submit(s)
  self.assertEqual(h.api.opening_posts(),[])
 def test_changed_confirmation_at_final_read_blocks(self):
  h=self.harness();s=h.signal();h.api.changed=True
  with self.assertRaisesRegex(BotError,'원래 완료봉|신호 변경'):h.submit(s)
  self.assertEqual(h.api.opening_posts(),[])
 def test_initial_stop_touch_while_waiting_blocks(self):
  h=self.harness();s=h.signal();h.api.stop_touch=True
  with self.assertRaisesRegex(BotError,'초기SL'):h.submit(s)
  self.assertEqual(h.api.opening_posts(),[])
 def test_expiry_during_admission_blocks(self):
  h=self.harness();s=h.signal();h.api.now=s['expires_ms']+1;h.ready()
  with self.assertRaisesRegex(BotError,'만료'):h.submit(s)
  self.assertEqual(h.api.opening_posts(),[])
 def test_unknown_post_outcome_reconciles_without_resend(self):
  h=self.harness();s=h.signal();h.api.unknown=True
  with self.assertRaises(UnknownOutcome):h.submit(s)
  o=h.e.records()[0];self.assertEqual(o['phase'],'submitted');self.assertEqual(len(h.api.opening_posts()),1)
  h.e.entry(s);self.assertEqual(len(h.api.opening_posts()),1)
  h.api.unknown=False;h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
  self.assertEqual(len(h.api.opening_posts()),1)
 def test_exchange_rejection_is_not_a_fill(self):
  h=self.harness();s=h.signal();h.api.reject=True
  with self.assertRaises(Rejected):h.submit(s)
  self.assertFalse(h.e.records());self.assertNotIn('fills',h.e.execution_status.counts)
 def test_missing_protection_pauses_and_requests_close(self):
  h=self.harness();s=h.signal();o=h.submit(s);h.api.fill(o['client_id'],protect=False)
  h.api.now+=16000
  self.assertFalse(h.reconcile(o));self.assertFalse(o.get('protection_verified'));self.assertEqual(o['phase'],'closing')
  self.assertFalse(h.e.enabled)
  self.assertEqual(len(h.api.opening_posts()),1)
  closes=[b for p,b in h.api.calls if p=='post /api/v5/trade/order' and not b.get('attachAlgoOrds')]
  self.assertEqual(len(closes),1);self.assertEqual(closes[0]['side'],'sell')
 def test_insufficient_funds_blocks_no_tiny_substitution(self):
  h=self.harness();s=h.signal();h.api.available=dec(3)
  self.assertIsNone(h.submit(s))
  self.assertEqual(h.e.execution_status.phase,'preflight_rejected')
  self.assertEqual(h.api.opening_posts(),[])
 def test_manual_reserved_capital_uses_remaining_seed_quarter(self):
  h=self.harness();s=h.signal();h.api.available=dec(60);o=h.submit(s)
  self.assertEqual(dec(o['initial_margin_target']),dec('14.25'))
  self.assertEqual(dec(o['entry_seed']),dec(57))
 def test_trend_at02_is_not_new_entry(self):
  h=self.harness('top1_15kst_dip130_LONG');s=h.signal();h.api.now=h.api.now//86400000*86400000+17*3600000;h.ready()
  self.assertIsNone(h.submit(s))
  with self.assertRaisesRegex(BotError,'시간 종료'):trend.validate_entry(h.e,s,s['entry_reference'])
  self.assertEqual(h.api.opening_posts(),[])
 def tick_positive(self,key):
  h=self.harness(key,4)
  if 'arming_rows' in h.fixture:
   h.candidate();self.assertTrue(h.e.journal.data[trend.STATE]['arm'])
   h.feed(h.fixture['rows'],h.fixture['now'])
  h.compute()
  for i in range(3):
   h.ready();h.e.tick()
   if h.e.records():break
  self.assertEqual(len(h.e.records()),1,getattr(h.e,'phone_entry_diagnostic',None))
  o=h.e.records()[0];self.assertEqual(o['v4_signal']['decision_record']['volume_wick_proof']['route721'],key.rsplit('_',1)[0])
  self.assertEqual(o['phase'],'submitted');h.api.fill(o['client_id'])
  h.ready();h.e.tick()
  self.assertEqual(o['phase'],'active');self.assertTrue(o['protection_verified'])
  self.assertEqual(len(h.api.opening_posts()),1)
  RESULTS.append(dict(rule=key,workers=4,full_engine_tick=True,symbol=o['symbol'],phase=o['phase'],
   protection_verified=o['protection_verified'],opening_requests=1,condition_to_fill_via_tick=True))
 def test_first_observed77s_quotes80s_still_enters(self):
  h=self.harness();t=h.api.now//900000*900000;h.api.now=t+77358
  h.e.stream.data.clear();h.compute();h.e.tick();self.assertFalse(h.e.records())
  h.api.now=t+80000;h.ready();h.e.tick()
  self.assertEqual(len(h.e.records()),1)
  o=h.e.records()[0];h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
 def test_first_observed77s_quotes91s_blocks(self):
  h=self.harness();t=h.api.now//900000*900000;h.api.now=t+77358
  h.e.stream.data.clear();h.compute();h.e.tick();self.assertFalse(h.e.records())
  h.api.now=t+91000;h.ready();h.e.tick();self.assertFalse(h.e.records());self.assertEqual(h.api.opening_posts(),[])
 def test_missing_one_channel_blocks_every_rule(self):
  for key in FIXTURES:
   h=self.harness(key);s=h.signal()
   h.e.stream.data.pop((s['symbol'],'books5'))
   with self.assertRaisesRegex(BotError,'실시간 시세'):h.submit(s)
   self.assertEqual(h.api.opening_posts(),[]);h.close();self.h=None
 def test_reserved_slot_rules(self):
  from unittest.mock import patch
  h=self.harness();common=h.signal();tr=dict(common,trend130=True,pattern=trend.ROUTE,leverage=5)
  h.api.now=h.api.now//86400000*86400000+12*3600000
  common_records=[dict(symbol='O'+str(i)+'-USDT-SWAP',direction='long',v4_signal={}) for i in range(3)]
  trend_record=dict(symbol='T-USDT-SWAP',direction='long',v4_signal={'trend130':True})
  with patch.object(h.e,'records',return_value=common_records):
   with self.assertRaisesRegex(BotError,'자리 배분'):trend.require_slot(h.e,common)
   trend.require_slot(h.e,tr)
  with patch.object(h.e,'records',return_value=[trend_record]):
   with self.assertRaisesRegex(BotError,'자리 배분'):trend.require_slot(h.e,tr)
   trend.require_slot(h.e,common)
  with patch.object(h.e,'records',return_value=common_records+[trend_record]):
   for s in (tr,common):
    with self.assertRaisesRegex(BotError,'자리 배분'):trend.require_slot(h.e,s)

for key in FIXTURES:
 def tick_positive(self,key=key):return self.tick_positive(key)
 setattr(EntryTests,'test_tick_'+key,tick_positive)
 for workers in (0,4):
  def positive(self,key=key,workers=workers):return self.positive(key,workers)
  setattr(EntryTests,'test_positive_'+key+'_workers'+str(workers),positive)

if __name__=='__main__':
 frozen=dict(created_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
  files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in D.iterdir() if p.suffix in ('.py','.json') and p.name not in ('results.json','runner_frozen.json')})
 (D/'runner_frozen.json').write_text(json.dumps(frozen,indent=2)+'\n')
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(EntryTests)
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 out=dict(version='1.5.3',tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),
  network_attempts=NETWORK_ATTEMPTS,live_orders=0,positive_results=RESULTS,
  failure_details=[(str(t),v) for t,v in result.failures+result.errors])
 (D/'results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 raise SystemExit(not result.wasSuccessful())
