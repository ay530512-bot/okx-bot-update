import sys,tempfile,unittest,json,threading,time
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'fixture121/host-v30'),str(ROOT/'core121')]
from phone_market_alerts import AlertFeed,candle_event,STEP,DAY,LIMIT

NOW=1800000000000;T=NOW-STEP
def bar(c=110,t=T):return [t,100,max(100,c),min(100,c),c,10]
class Alerts(unittest.TestCase):
 def test_thresholds(self):
  for c in (110,90,140,60):self.assertIsNotNone(candle_event('ALT-USDT-SWAP',bar(c),NOW))
  for c in (109.999999,90.000001,100):self.assertIsNone(candle_event('ALT-USDT-SWAP',bar(c),NOW))
 def test_confirmed_time_and_price(self):
  for b in (bar(t=NOW),bar(t=T+1),bar(t=NOW-DAY-2*STEP),[T,0,1,0,1], [T,100,101,99,110],bar(float('nan'))):
   self.assertIsNone(candle_event('ALT-USDT-SWAP',b,NOW))
  self.assertIsNone(candle_event('<img>-USDT-SWAP',bar(),NOW))
 def test_dedup_expiry_and_restart(self):
  with tempfile.TemporaryDirectory() as tmp:
   f=AlertFeed(tmp,clock=lambda:NOW);bars=tuple(map(tuple,[bar(),bar(t=NOW)]))
   f.observe([('ALT-USDT-SWAP',bars)],2,NOW);f.observe([('ALT-USDT-SWAP',bars)],2,NOW)
   self.assertEqual(len(f.snapshot()['items']),1);self.assertEqual(f.snapshot()['coverage_fresh'],1)
   g=AlertFeed(tmp,clock=lambda:NOW);g.observe([],2,NOW)
   self.assertEqual(len(g.snapshot()['items']),1)
   # Previously forming row only becomes visible once a NEW confirmed snapshot arrives.
   f.observe([('ALT-USDT-SWAP',tuple(tuple(r) for r in [bar(),bar(t=NOW)]))],1,NOW+STEP)
   self.assertEqual(len(f.snapshot()['items']),2)
   f.observe([],2,NOW+DAY+STEP+1);self.assertEqual(f.snapshot()['items'],[])
 def test_bounded(self):
  with tempfile.TemporaryDirectory() as tmp:
   f=AlertFeed(tmp);f.observe([(f'A{i}-USDT-SWAP',[bar()]) for i in range(140)],140,NOW)
   self.assertEqual(len(f.snapshot()['items']),LIMIT)
   self.assertLess(f.path.stat().st_size,262144)
 def test_cache_read_only_and_universe_filter(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=tuple(map(tuple,[bar()]));u=NS(lock=threading.Lock(),full_market=NS(instruments={'ALT-USDT-SWAP':{}},band_cache={('ALT-USDT-SWAP','15m'):(1,b),('OTHER-USDT-SWAP','15m'):(1,b)}))
   f=AlertFeed(tmp,u,clock=lambda:NOW);f.poll()
   self.assertIs(u.full_market.band_cache[('ALT-USDT-SWAP','15m')][1],b)
   self.assertEqual([x['symbol'] for x in f.snapshot()['items']],['ALT-USDT-SWAP'])
   s=f.snapshot();s['items'][0]['symbol']='bad';self.assertEqual(f.snapshot()['items'][0]['symbol'],'ALT-USDT-SWAP')
 def test_missing_and_bad_persistence(self):
  with tempfile.TemporaryDirectory() as tmp:
   (Path(tmp)/'phone_market_alerts.json').write_text('invalid')
   f=AlertFeed(tmp);self.assertEqual(f.errors,1);f.poll()
   self.assertIsNone(f.snapshot()['checked_at_ms'])
   f.observe([],289,NOW);self.assertEqual(f.snapshot()['coverage_fresh'],0)
 def test_write_failure_isolated(self):
  with tempfile.TemporaryDirectory() as tmp:
   f=AlertFeed(Path(tmp)/'missing');f.observe([('ALT-USDT-SWAP',[bar()])],1,NOW)
   self.assertEqual(f.snapshot()['save_errors'],1);self.assertEqual(len(f.snapshot()['items']),1)
 def test_immutable_strategy_and_order_modules(self):
  old=ROOT/'fixture121/host-v29';new=ROOT/'fixture121/host-v30'
  for n in ('phone_trend_slot.py','phone_pullback_size.py','phone_entry_diagnostics.py','phone_candidate_fast.py','phone_parallel.py','phone_handover.py','phone_public_ws.py','phone_performance.py'):
   self.assertEqual((old/n).read_bytes(),(new/n).read_bytes(),n)
 def test_mobile_snapshot_and_packaged_assets(self):
  from unittest.mock import Mock,patch
  from phone_mobile import mobile_module
  m=mobile_module(ROOT/'core121')
  with tempfile.TemporaryDirectory() as tmp:
   server=Mock(server_address=('127.0.0.1',8768))
   with patch.object(m,'ThreadingHTTPServer',return_value=server):
    mobile=m.PhoneMobile(Path(tmp)/'runtime-q2x',{},dict(m.credential('test-only-pass'),https_host='',controls_enabled=True),feed_factory=lambda *a:Mock())
   mobile.market_alerts=AlertFeed(tmp,clock=lambda:NOW)
   mobile.market_alerts.observe([('ALT-USDT-SWAP',[bar()])],1,NOW)
   view=NS(revision=1,data_seen=None)
   with patch.object(m.Mobile,'capture',side_effect=lambda v:setattr(mobile,'snapshot',{'captured_ms':NOW})):
    mobile.capture(view)
   self.assertEqual(len(mobile.snapshot['market_alerts']['items']),1)
   mobile.capture(view)
   self.assertEqual(len(mobile.snapshot['market_alerts']['items']),1)
   self.assertTrue(mobile.control_commands.empty())
   self.assertIn(b'phoneMovesPanel',m.asset('index.html'))
   self.assertIn(b'phone-diagnostic-section',m.asset('style.css'))
   self.assertIn(b'function phoneOpenMove',m.asset('app.js'))

if __name__=='__main__':unittest.main(verbosity=2)
