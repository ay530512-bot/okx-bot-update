"""Withdraw new EMA entry; keep the original strategy and live position care."""
import ast,copy,json,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from execution_harness import Harness,NETWORK_ATTEMPTS,trend,BotError,D,HOST
import phone_ema_support as support
import okx_channel701 as ch

class Tests(unittest.TestCase):
 def test_scan_cannot_revive_saved_support_signal(self):
  e=NS(journal=NS(data={support.STATE:{'signal':{'pattern':support.ROUTE},'touch':{'low':1}}}))
  for _ in range(3):self.assertIsNone(support.scan(e))
 def test_direct_saved_signal_is_also_rejected(self):
  with self.assertRaisesRegex(BotError,'제거된 EMA20'):support.validate_entry(None,{'pattern':support.ROUTE},10)
 def test_coordinator_never_scans_support_and_discards_old_pending(self):
  fx=json.loads((D/'fixtures.json').read_text())['fixtures']['trend_pullback_LONG'];h=Harness(copy.deepcopy(fx))
  try:
   symbol=fx['rows'][0]['symbol']
   h.e.channel_pending={symbol:dict(pattern=support.ROUTE,symbol=symbol,signal_id='old-support',expires_ms=h.api.now+90000)}
   with patch.object(support,'scan',side_effect=AssertionError('removed scanner was called')):
    candidate=h.candidate()
   self.assertFalse(candidate and support.is_signal(candidate))
   self.assertFalse(any(support.is_signal(s) for s in h.e.channel_pending.values()))
   self.assertEqual(h.api.opening_posts(),[])
  finally:h.close()
  self.assertEqual(NETWORK_ATTEMPTS,[])
 def test_legacy_support_remains_reserved_owned_and_managed(self):
  fx=json.loads((D/'fixtures.json').read_text())['fixtures']['trend_pullback_LONG'];h=Harness(copy.deepcopy(fx))
  try:
   o=dict(symbol='X-USDT-SWAP',direction='long',v4_signal=dict(pattern=support.ROUTE,trend130=True))
   self.assertTrue(trend.is_owned(o));self.assertTrue(trend.reserved_owned(o))
   import phone_morning_short as morning
   with patch.object(morning,'maybe_switch',return_value=False) as switch,patch.object(trend,'manage',return_value='kept') as manage:
    self.assertEqual(ch.management(h.e,{}, {},o),'kept');switch.assert_called_once();manage.assert_called_once()
  finally:h.close()
 def test_actual_previous_runtime_record_survives_handover_and_manual_half(self):
  from test_manual_reduction import Ledger
  import phone_handover
  from execution_harness import dec
  f=json.loads((D/'legacy_support_fixture.json').read_text());h=Harness(f['fixture'])
  try:
   h.e.journal.data=copy.deepcopy(f['journal']);h.e.journal.save()
   h.api.positions=copy.deepcopy(f['positions']);h.api.algos=copy.deepcopy(f['algos']);h.api.orders=copy.deepcopy(f['orders'])
   h.api.levers={(s,d):v for s,d,v in f['levers']};h.api.now=f['now'];h.ready()
   o=h.e.records()[0];before=copy.deepcopy(o)
   self.assertEqual(o['v4_signal']['pattern'],support.ROUTE)
   self.assertTrue(h.reconcile(o));self.assertTrue(trend.is_owned(o))
   self.assertIsInstance(phone_handover.validate_protected(h.e.journal.data,h.e.snapshot(),h.api.pending_algos(full=True)),str)
   ledger=Ledger(h);ledger.append(o,o['quantity'],True);position=ledger.reduce(o)
   self.assertEqual(ledger.drive(o),'active');self.assertEqual(dec(o['quantity']),dec(before['quantity'])/2)
   self.assertEqual(o['v4_signal'],before['v4_signal']);self.assertTrue(h.e.verify_protection(h.e.snapshot(),position,o))
   self.assertEqual(h.api.opening_posts(),[])
  finally:h.close()
 def test_existing_long_and_morning_short_sources_are_identical(self):
  prior=HOST.parent/'phone_v170'
  for name in ('phone_trend_slot.py','phone_morning_short.py','phone_pullback_size.py','phone_mobile_policy.py','phone_risk_lifecycle.py','phone_manual_reduction.py'):
   self.assertEqual((HOST/name).read_bytes(),(prior/name).read_bytes(),name)
 def test_new_home_and_diagnostics_no_longer_advertise_removed_entry(self):
  self.assertNotIn('OR EMA20',(HOST/'phone_mobile.py').read_text())
  self.assertNotIn("trendLines.push('기존 돌파 눌림 OR",(HOST/'phone_update_ui.js').read_text())

if __name__=='__main__':unittest.main(verbosity=2)
