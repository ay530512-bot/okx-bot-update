"""New OR route through actual coordinator/engine; all exchange I/O simulated."""
import copy
import json
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
from execution_harness import Harness,NETWORK_ATTEMPTS,trend,BotError,dec
import phone_ema_support as support

T=int(datetime(2026,11,17,8,15,tzinfo=timezone.utc).timestamp()*1000)
SYMBOL='SUPPORT-USDT-SWAP'


def fixture(live=False,t=T):
    b=[]
    for i in range(80):
        close=100+i*.1
        b.append([t-(80-i)*trend.STEP,close-.05,close+.15,close-.15,close,100.])
    if not live:
        ema=support.context(b[:-1])['ema20']
        b[-1][1:]=[ema-.1,ema+.6,ema-.2,ema+.4,120.]
    h=[]
    hour=t//trend.HOUR*trend.HOUR
    for i in range(80):
        price=125-i*.2
        h.append([hour-(80-i)*trend.HOUR,price+.1,price+.3,price-.2,price,100.])
    # Deliberately a falling 1H trend and no new 20-bar breakout.
    row=dict(symbol=SYMBOL,live_frames={'15m':b,'1H':h,'4H':[]},rank_base=90.)
    return dict(rows=[row],now=t+(120000 if live else 2000))


class Tests(unittest.TestCase):
    def setUp(self):self.h=None
    def tearDown(self):
        if self.h:self.h.close()
        self.assertEqual(NETWORK_ATTEMPTS,[])
    def harness(self,live=False):
        self.h=Harness(fixture(live));return self.h
    def live_touch(self,h):
        level=support.context(h.api.rows[SYMBOL]['live_frames']['15m'])['ema20']
        h.api.live_prices[SYMBOL]=level-.02;h.ready()
        self.assertIsNone(support.scan(h.e));self.assertTrue(h.e.journal.data[support.STATE]['touch'])
        h.api.now+=1000;h.api.live_prices[SYMBOL]=level+.05;h.ready()
        return support.scan(h.e)
    def test_closed_support_without_breakout_or_hourly_trend_fills_and_protects(self):
        h=self.harness();b=h.api.rows[SYMBOL]['live_frames']['15m'];hours=h.api.rows[SYMBOL]['live_frames']['1H']
        self.assertFalse(trend.uptrend(hours));self.assertFalse(trend.breakout(b,hours));self.assertIsNone(trend.scan(h.e))
        s=h.candidate();self.assertEqual(s['pattern'],support.ROUTE)
        self.assertEqual(h.e.phone_entry_diagnostic['selected_symbol'],SYMBOL)
        o=h.submit(s);self.assertEqual(o['phase'],'submitted');self.assertFalse(o.get('protection_verified'))
        h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o));self.assertEqual(o['phase'],'active')
        h.e.entry(s);self.assertEqual(len(h.api.opening_posts()),1)
        self.assertTrue(trend.is_owned(o));self.assertTrue(o['protection_verified'])
        from phone_position_details import describe
        self.assertEqual(describe(o)['rule'],'상승1위 EMA20 지지 반등')
    def test_live_touch_then_recovery_enters_without_waiting_for_close(self):
        h=self.harness(True);s=self.live_touch(h)
        self.assertIsNotNone(s);self.assertEqual(s['decision_record']['volume_wick_proof']['mode'],'live')
        self.assertEqual(s['valid_from_ms'],h.api.now);self.assertLess(h.api.now,T+trend.STEP)
        # Full coordinator and original final checks, not only pure signal test.
        candidate=h.candidate()
        self.assertEqual(candidate['signal_id'],s['signal_id'])
        from phone_similar_candidates import FIELD
        self.assertEqual(candidate[FIELD]['candle_ms'],T)
        o=h.submit(s);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
        self.assertEqual(len(h.api.opening_posts()),1)
    def test_touch_alone_is_not_recovery_and_rally_without_touch_does_not_enter(self):
        h=self.harness(True);self.assertIsNone(support.scan(h.e))
        level=support.context(h.api.rows[SYMBOL]['live_frames']['15m'])['ema20']
        for p in (level-.1,level-.2,level):
            h.api.live_prices[SYMBOL]=p;h.api.now+=1000;h.ready()
            self.assertIsNone(support.scan(h.e))
        self.assertEqual(h.api.opening_posts(),[])
    def test_falling_ema_does_not_trigger(self):
        f=fixture();b=f['rows'][0]['live_frames']['15m']
        for i,r in enumerate(b):r[1:]=[110-i*.1,111-i*.1,109-i*.1,110-i*.1,100]
        self.h=Harness(f);self.assertIsNone(support.scan(self.h.e))
    def test_same_timestamp_cannot_invent_touch_then_recovery(self):
        h=self.harness(True);b=h.api.rows[SYMBOL]['live_frames']['15m'];state={};level=support.context(b)['ema20']
        support.observed_proof(state,b,dict(last=level-.1,ts=h.api.now),h.api.now)
        p,_=support.observed_proof(state,b,dict(last=level+.1,ts=h.api.now),h.api.now)
        self.assertIsNone(p)
    def test_expiry_never_renews_on_rescan_or_reload(self):
        h=self.harness();s=support.scan(h.e);h.api.now=s['expires_ms']+1;h.ready()
        for _ in range(3):self.assertIsNone(support.scan(h.e))
        h.e.journal.data=json.loads(h.e.journal.path.read_text())
        self.assertIsNone(support.scan(h.e));self.assertEqual(h.api.opening_posts(),[])
    def test_closed_signal_first_seen_late_cannot_be_revived(self):
        h=self.harness();h.api.now=T+TTL+1;h.ready()
        self.assertIsNone(support.scan(h.e));self.assertEqual(h.api.opening_posts(),[])
    def test_rank_change_invalidates_pending_and_rest_revalidates_leader(self):
        h=self.harness();s=support.scan(h.e)
        row=copy.deepcopy(h.api.rows[SYMBOL]);row['symbol']='OTHER-USDT-SWAP';row['rank_base']=80
        h.feed([h.api.rows[SYMBOL],row],h.api.now+1001)
        with self.assertRaisesRegex(BotError,'1위 변경'):h.submit(s)
        new=support.scan(h.e);self.assertEqual(new['symbol'],'OTHER-USDT-SWAP')
        self.assertEqual(h.api.opening_posts(),[])
    def test_changed_candles_and_lost_support_rejected(self):
        h=self.harness();s=support.scan(h.e);h.api.changed=True
        with self.assertRaisesRegex(BotError,'원래 확정봉'):h.submit(s)
        h.api.changed=False
        h.api.live_prices[SYMBOL]=s['decision_record']['volume_wick_proof']['ema20']-.01;h.ready()
        with self.assertRaisesRegex(BotError,'회복 이탈'):h.submit(s)
        self.assertEqual(h.api.opening_posts(),[])
    def test_freshness_spread_expiry_and_reserved_slot_guards(self):
        h=self.harness();s=support.scan(h.e)
        h.e.stream.data.pop((SYMBOL,'books5'))
        with self.assertRaises(BotError):h.submit(s)
        h.ready();h.api.spread=dec('.002');h.ready()
        with self.assertRaisesRegex(BotError,'스프레드'):h.submit(s)
        h.api.spread=dec('.0002');h.ready()
        reserved=dict(symbol='HELD-USDT-SWAP',direction='long',v4_signal={'trend130':True})
        with patch.object(h.e,'records',return_value=[reserved]):
            with self.assertRaisesRegex(BotError,'자리 배분'):support.validate_entry(h.e,s,s['entry_reference'])
        h.api.now=s['expires_ms']+1;h.ready()
        with self.assertRaisesRegex(BotError,'만료'):support.validate_entry(h.e,s,s['entry_reference'])
        self.assertEqual(h.api.opening_posts(),[])
    def test_three_common_slots_leave_one_reserved_for_support(self):
        h=self.harness();s=support.scan(h.e)
        common=[dict(symbol=f'C{i}-USDT-SWAP',direction='long',v4_signal={}) for i in range(3)]
        with patch.object(h.e,'records',return_value=common):trend.require_slot(h.e,s)
        with patch.object(h.e,'records',return_value=common+[dict(symbol='X',direction='long',v4_signal={})]):
            with self.assertRaisesRegex(BotError,'자리 배분'):trend.require_slot(h.e,s)
    def test_cutoff_does_not_create_signal(self):
        h=self.harness(True);h.api.now=T//trend.DAY*trend.DAY+17*trend.HOUR;h.ready()
        self.assertIsNone(support.scan(h.e));self.assertEqual(h.api.opening_posts(),[])
    def test_missing_or_future_quote_never_creates_live_touch(self):
        h=self.harness(True);b=h.api.rows[SYMBOL]['live_frames']['15m'];c=support.context(b)
        for q in (None,dict(last=c['ema20'],ts=h.api.now+1),dict(last=c['ema20'],ts=h.api.now-15001),dict(last='nan',ts=h.api.now)):
            state={};p,_=support.observed_proof(state,b,q,h.api.now)
            self.assertIsNone(p);self.assertFalse(state.get('touch'))
    def test_original_candidate_failure_does_not_block_valid_support_or_branch(self):
        import okx_channel701 as ch
        h=self.harness();good=support.scan(h.e);bad=copy.deepcopy(good);bad['pattern']=trend.ROUTE;bad['signal_id']='tr130-bad'
        with patch.object(trend,'scan',return_value=bad):
            s=h.candidate()
        self.assertEqual(s['pattern'],support.ROUTE)
        self.assertEqual(h.api.opening_posts(),[])
    def test_no_new_rest_requests_from_scan(self):
        h=self.harness(True);before=list(h.api.calls)
        for _ in range(40):support.scan(h.e)
        self.assertEqual(h.api.calls,before)
    def test_four_positions_after_manual_partial_releases_required_margin(self):
        from execution_harness import D
        fx=copy.deepcopy(json.loads((D/'fixtures.json').read_text())['fixtures']['trend_pullback_LONG'])
        base=fx['rows'][0]
        fx['rows']=[dict(copy.deepcopy(base),symbol=s+'-USDT-SWAP') for s in ('AAA','BBB','CCC')]
        h=self.h=Harness(fx)
        from test_manual_reduction import Ledger
        ledger=Ledger(h)
        for n in range(3):
            o=ledger.enter();self.assertFalse(trend.is_owned(o))
            h.e.executing_signal=None;h.ready()
        self.assertEqual(trend.slot_counts(h.e),(3,0,3))
        more=fixture(t=h.api.now//trend.STEP*trend.STEP)
        h.api.rank_bases[SYMBOL]=80
        h.feed(fx['rows']+more['rows'],h.api.now+1001)
        s=h.candidate();self.assertEqual(s['pattern'],support.ROUTE)
        # Full quarter sizing also reserves fees: do not bypass that gate.
        with self.assertRaisesRegex(BotError,'증거금·수수료 부족'):h.submit(s)
        first=h.e.records()[0];ledger.reduce(first,'.1')
        self.assertEqual(ledger.drive(first),'active')
        h.ready();o=h.submit(s);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
        h.e.executing_signal=None;h.ready()
        self.assertEqual(trend.slot_counts(h.e),(4,1,3))
        self.assertIsNone(h.candidate())
        self.assertEqual(len(h.api.opening_posts()),4);self.assertEqual(len(h.api.algos),4)
        self.assertTrue(all(o['protection_verified'] for o in h.e.records()))

    def test_rank_churn_and_restart_cannot_refresh_live_expiry(self):
        h=self.harness(True);s=self.live_touch(h);original_expiry=s['expires_ms']
        row=copy.deepcopy(h.api.rows[SYMBOL]);row['symbol']='OTHER-USDT-SWAP';row['rank_base']=80
        h.feed([h.api.rows[SYMBOL],row],h.api.now+1001);support.scan(h.e)
        h.api.rank_bases[SYMBOL]=70;h.api.now+=1001;h.ready()
        h.e.journal.data=json.loads(h.e.journal.path.read_text())
        h.api.now=original_expiry+1;h.ready()
        self.assertIsNone(self.live_touch(h))
        self.assertEqual(h.e.journal.data[support.STATE]['observed_signals'][s['signal_id']]['expires_ms'],original_expiry)
        self.assertEqual(h.api.opening_posts(),[])

    def test_support_diagnostics_exported_without_account_data(self):
        from phone_diagnostic_export import safe
        x=safe(dict(support_status='대기',support_detail=dict(ema20=100,rising=True),entry=dict(selected_symbol=SYMBOL,selected_route=support.ROUTE),secret='hidden'))
        self.assertEqual(x['support_detail']['ema20'],100);self.assertNotIn('secret',x)

TTL=support.TTL
if __name__=='__main__':unittest.main(verbosity=2)
