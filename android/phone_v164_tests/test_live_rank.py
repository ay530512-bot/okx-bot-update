"""Live-leader changes and entry boundaries, using offline exchange fixtures."""
import copy
import json
import queue
import threading
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from execution_harness import Harness, NETWORK_ATTEMPTS, BotError, D, trend
from test_inputs import engine as original_engine, T, A, B
from test_morning import fixture, stamp
import phone_live_rank as live
import phone_morning_short as morning


def engine():
    e = original_engine(); e.clock = T+2000; e.api.now_ms = lambda:e.clock
    m = e.universe.full_market
    m.quotes = {s:dict(ts=str(e.clock), last=str(p), sodUtc0='1') for s,p in ((A,1.3),(B,1.2))}
    m.market = lambda:dict(instruments=copy.deepcopy(m.instruments), quotes=copy.deepcopy(m.quotes))
    e.stream = NS(read=lambda *a:None, monitor=Mock())
    e.journal.data[trend.STATE]['leader_key'] = (T//live.DAY*live.DAY, A)
    return e


def refresh(e):
    e.clock += 1001
    for q in e.universe.full_market.quotes.values(): q['ts'] = str(e.clock)


class RankTests(unittest.TestCase):
    def test_live_leader_changes_inside_same_quarter_and_hour(self):
        e=engine(); self.assertEqual(live.selected(e)['symbol'],A)
        e.universe.full_market.quotes[B]['last']='1.4';refresh(e)
        self.assertEqual(live.selected(e)['symbol'],B)
        self.assertEqual(e.clock//trend.STEP,T//trend.STEP)
        self.assertEqual(e.clock//trend.HOUR,T//trend.HOUR)

    def test_fresh_ws_wins_but_older_ws_cannot_roll_back_rest(self):
        e=engine(); q=dict(ts=str(e.clock),last='1.5',sodUtc0='1')
        e.stream.read=lambda s,*args:q if s==B else None
        self.assertEqual(live.selected(e)['symbol'],B)
        q['ts']=str(e.clock-1)
        self.assertEqual(live.selected(e,True)['symbol'],A)

    def test_partial_scan_and_missing_unrelated_candles_do_not_block(self):
        e=engine();e.universe.result=None;e.universe.search_paused.set()
        e.universe.full_market.band_cache.pop((B,'1H'))
        self.assertEqual(live.selected(e)['symbol'],A)
        self.assertIsNotNone(trend.scan(e))

    def test_missing_selected_candles_do_not_promote_second_place(self):
        e=engine();e.universe.full_market.band_cache.pop((A,'15m'))
        self.assertIsNone(trend.scan(e));self.assertIsNone(e.journal.data[trend.STATE]['pending'])
        self.assertEqual(live.selected(e)['symbol'],A)

    def test_missing_or_stale_quote_blocks_partial_ranking(self):
        for mode in ('missing','old','future','nan','zero'):
            e=engine();q=e.universe.full_market.quotes[B]
            if mode=='missing':q.pop('sodUtc0')
            if mode=='old':q['ts']=str(e.clock-60001)
            if mode=='future':q['ts']=str(e.clock+1)
            if mode=='nan':q['last']='NaN'
            if mode=='zero':q['sodUtc0']='0'
            with self.subTest(mode=mode),self.assertRaises(ValueError):live.selected(e)
            self.assertIsNone(live.snapshot(e)['leader'])

    def test_old_session_baseline_never_transplanted_to_new_ws_price(self):
        e=engine();e.clock=e.clock//live.DAY*live.DAY+live.DAY+1000
        e.stream.read=lambda s,*args:dict(ts=str(e.clock),last='2')
        with self.assertRaises(ValueError):live.selected(e)
        e.stream.read=lambda s,*args:dict(ts=str(e.clock),last='2',sodUtc0='1')
        self.assertEqual(live.selected(e,True)['day'],e.clock//live.DAY*live.DAY)

    def test_verified_new_listing_excluded_then_rejoins_next09(self):
        e=engine();m=e.universe.full_market
        m.instruments[B].update(instType='SWAP',listTime=str(e.clock-1000))
        m.quotes.pop(B)
        r=live.snapshot(e);self.assertTrue(r['ready']);self.assertEqual(r['leader']['symbol'],A)
        self.assertEqual(r['baseline_ineligible_count'],1)
        e.clock=e.clock//live.DAY*live.DAY+live.DAY+1000;refresh(e)
        with self.assertRaises(ValueError):live.selected(e)

    def test_unknown_listing_metadata_cannot_hide_missing_quote(self):
        e=engine();e.universe.full_market.quotes.pop(B)
        e.universe.full_market.instruments[B]['listTime']='unknown'
        with self.assertRaises(ValueError):live.selected(e)

    def test_excluded_assets_never_win_and_ties_stable(self):
        e=engine();m=e.universe.full_market
        m.instruments['BTC-USDT-SWAP']=dict(m.instruments[A],instId='BTC-USDT-SWAP',ctValCcy='BTC')
        m.quotes['BTC-USDT-SWAP']=dict(m.quotes[A],last='100')
        m.quotes[B]['last']='1.3'
        self.assertEqual(live.selected(e)['symbol'],A)
        self.assertEqual(live.snapshot(e)['eligible'],2)

    def test_no_positive_return_no_leader(self):
        e=engine()
        for q in e.universe.full_market.quotes.values():q['last']='.9'
        self.assertIsNone(live.selected(e));self.assertTrue(live.snapshot(e)['ready'])

    def test_new_leader_clears_old_arm_and_pending_even_if_new_bars_missing(self):
        e=engine();self.assertIsNotNone(trend.scan(e))
        e.universe.full_market.quotes[B]['last']='1.5'
        e.universe.full_market.band_cache.pop((B,'15m'));refresh(e)
        self.assertIsNone(trend.scan(e));state=e.journal.data[trend.STATE]
        self.assertEqual(state['rank']['symbol'],B);self.assertIsNone(state['arm']);self.assertIsNone(state['pending'])

    def test_outside_windows_tracks_new_short_target_without_entry(self):
        e=engine();e.clock=stamp('2026-11-17T02:05:00');refresh(e)
        e.journal.data['held']='unchanged'
        self.assertIsNone(trend.scan(e));self.assertIsNone(morning.scan(e))
        self.assertEqual(live.snapshot(e)['phase'],'wait_short')
        e.universe.full_market.quotes[B]['last']='1.5';refresh(e)
        self.assertIsNone(morning.scan(e));self.assertEqual(e.journal.data[morning.STATE]['rank']['symbol'],B)
        self.assertEqual(live.prewarm(e,e.clock),{B});self.assertEqual(e.journal.data['held'],'unchanged')
        self.assertIsNone(e.journal.data[trend.STATE]['pending'])
        self.assertIsNone(e.journal.data[morning.STATE]['pending'])

    def test_publisher_and_inspection_share_exact_snapshot(self):
        e=engine();p=live.Publisher(e,queue.Queue());r=p.payload()
        self.assertEqual(r['live_rank']['leader'],live.selected(e))
        self.assertEqual(r['rows'][0]['symbol'],live.selected(e)['symbol'])
        e.universe.full_market.quotes[B]['last']='1.5';refresh(e)
        self.assertEqual(p.payload()['live_rank']['leader']['symbol'],B)

    def test_publisher_runs_when_entry_paused_and_holds_exist(self):
        e=engine();e.enabled=False;e.user_paused=True;e.records=lambda:[{'symbol':'HELD'}]
        q=queue.Queue();p=live.Publisher(e,q)
        try:
            p.start();kind,payload=q.get(timeout=2)
            self.assertEqual(kind,'futures_market');self.assertEqual(payload['live_rank']['leader']['symbol'],A)
        finally:p.stop()
        self.assertFalse(p.thread.is_alive())

    def test_290_symbols_cached_without_rest_requests(self):
        e=engine();m=e.universe.full_market
        for i in range(288):
            s=f'COIN{i:03d}-USDT-SWAP';m.instruments[s]=dict(m.instruments[A],instId=s,ctValCcy=s.split('-')[0])
            m.quotes[s]=dict(m.quotes[A],last='1.01')
        started=time.perf_counter()
        for _ in range(100):live.snapshot(e,True)
        elapsed=time.perf_counter()-started
        self.assertEqual(live.snapshot(e)['eligible'],290)
        with patch.object(m,'market',side_effect=AssertionError('cached read collected again')):
            for _ in range(100):self.assertEqual(live.selected(e)['symbol'],A)
        (D/'rank_benchmark.json').write_text(json.dumps(dict(symbols=290,refreshes=100,
            elapsed_s=elapsed,mean_ms=elapsed*10,rest_requests=0,phone_hardware=False),indent=2)+'\n')

    def test_export_keeps_live_rank_source_and_coverage(self):
        from phone_diagnostic_export import safe
        r=live.snapshot(engine());d=safe({'live_rank':{k:v for k,v in r.items() if k!='rows'}})['live_rank']
        self.assertEqual(d['basis'],'kst09_live');self.assertEqual(d['leader']['symbol'],A)
        self.assertEqual(d['quotes_ready'],2)


class EntryTests(unittest.TestCase):
    def setUp(self):self.h=None
    def tearDown(self):
        if self.h:self.h.close()
        self.assertEqual(NETWORK_ATTEMPTS,[])

    def harness(self,t=None,workers=0):
        f=fixture(t=t or stamp('2026-11-17T05:15:00'),symbol=A)
        second=copy.deepcopy(f['rows'][0]);second['symbol']=B;f['rows'].append(second)
        self.h=Harness(f,workers);return self.h

    def flip(self,h):
        h.api.live_prices[B]=102.5;h.api.now+=1001;h.ready()

    def test_changed_leader_same_bar_new_short_orders_fills_and_protects(self):
        h=self.harness(workers=4);old=morning.scan(h.e);self.assertEqual(old['symbol'],A)
        self.flip(h);new=morning.scan(h.e);self.assertEqual(new['symbol'],B)
        self.assertEqual(new['valid_from_ms'],old['valid_from_ms'])
        self.assertEqual(new['expires_ms'],old['expires_ms'])
        with self.assertRaises(BotError):h.submit(old)
        self.assertEqual(h.api.opening_posts(),[])
        o=h.submit(new);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
        self.assertTrue(o['protection_verified']);self.assertEqual(o['symbol'],B)
        h.e.entry(new);self.assertEqual(len(h.api.opening_posts()),1)

    def test_change_during_candle_request_blocks_before_any_order(self):
        h=self.harness();s=morning.scan(h.e);original=h.api.public
        def public(path,**kw):
            result=original(path,**kw)
            if path.endswith('/candles'):self.flip(h)
            return result
        with patch.object(h.api,'public',side_effect=public):
            with self.assertRaisesRegex(BotError,'1위 변경'):h.submit(s)
        self.assertEqual(h.api.opening_posts(),[])

    def test_force_read_ignores_one_second_rank_cache_before_order(self):
        h=self.harness();s=morning.scan(h.e)
        h.api.live_prices[B]=102.5;h.ready() # No clock advance/cache invalidation.
        with self.assertRaisesRegex(BotError,'1위 변경'):h.submit(s)
        self.assertEqual(h.api.opening_posts(),[])

    def test_last_submit_guard_rechecks_after_risk_calculation(self):
        import okx_risk732 as risk
        h=self.harness();s=morning.scan(h.e);original=risk.cap_plan
        def cap(*args,**kwargs):
            result=original(*args,**kwargs)
            if any(x[0]=='post /api/v5/account/set-leverage' for x in h.api.calls):
                self.flip(h)
            return result
        with patch.object(risk,'cap_plan',side_effect=cap):
            with self.assertRaisesRegex(BotError,'1위 변경'):h.submit(s)
        self.assertEqual(h.api.opening_posts(),[])

    def test_after02_wait_tracks_b_then05_checks_b(self):
        h=self.harness(t=stamp('2026-11-17T02:15:00'))
        self.assertIsNone(morning.scan(h.e));self.flip(h)
        self.assertIsNone(morning.scan(h.e));self.assertEqual(live.selected(h.e)['symbol'],B)
        self.assertEqual(h.api.opening_posts(),[])
        f=fixture(t=stamp('2026-11-17T05:00:00'),symbol=A);r=copy.deepcopy(f['rows'][0]);r['symbol']=B
        h.feed(f['rows']+[r],f['now']);s=morning.scan(h.e)
        self.assertEqual(s['symbol'],B);self.assertEqual(s['valid_from_ms'],stamp('2026-11-17T05:00:00'))
        o=h.submit(s);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))

    def test_rank_change_never_renews_90_second_expiry(self):
        h=self.harness();s=morning.scan(h.e);h.api.now=s['expires_ms']+1;self.flip(h)
        self.assertIsNone(morning.scan(h.e));self.assertEqual(h.api.opening_posts(),[])

    def test_first_selected_after_close_can_replay_valid_long_setup(self):
        f=copy.deepcopy(json.loads((D/'fixtures.json').read_text())['fixtures']['top1_15kst_dip130_LONG'])
        h=self.h=Harness(f,4)
        leader=trend.rank_rows(f['arming_rows'],f['arming_now'])['symbol']
        h.feed(f['rows'],f['now']) # New leader: no saved arm from earlier scan.
        s=trend.scan(h.e);self.assertIsNotNone(s);self.assertEqual(s['symbol'],leader)
        self.assertEqual(s['decision_record']['rank130']['basis'],'kst09_live')
        self.assertEqual(s['expires_ms'],s['valid_from_ms']+90000)
        o=h.submit(s);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))

    def test_new_long_leader_replay_cannot_revive_old_confirmation(self):
        f=copy.deepcopy(json.loads((D/'fixtures.json').read_text())['fixtures']['top1_15kst_dip130_LONG'])
        h=self.h=Harness(f);h.feed(f['rows'],f['now']+90001)
        self.assertIsNone(trend.scan(h.e));self.assertEqual(h.api.opening_posts(),[])

    def test_new_leader_waits_for_candles_then_evaluates_same_close(self):
        f=copy.deepcopy(json.loads((D/'fixtures.json').read_text())['fixtures']['top1_15kst_dip130_LONG'])
        h=self.h=Harness(f);h.feed(f['rows'],f['now'])
        symbol=live.selected(h.e)['symbol'];cache=h.e.universe.full_market.band_cache
        bars=cache.pop((symbol,'15m'))
        self.assertIsNone(trend.scan(h.e))
        cache[(symbol,'15m')]=bars;h.api.now+=1001;h.ready()
        s=trend.scan(h.e);self.assertEqual(s['symbol'],symbol)
        self.assertEqual(s['expires_ms'],f['now']//trend.STEP*trend.STEP+90000)

    def test_brief_rank_data_gap_does_not_lose_unexpired_long_setup(self):
        f=copy.deepcopy(json.loads((D/'fixtures.json').read_text())['fixtures']['top1_15kst_dip130_LONG'])
        h=self.h=Harness(f);old=h.signal();m=h.e.universe.full_market
        saved=m.quotes;oldread=h.e.stream.read;m.quotes={};h.e.stream.read=lambda *args:None
        h.api.now+=1001;self.assertIsNone(trend.scan(h.e))
        m.quotes=saved;h.e.stream.read=oldread;h.api.now+=1001;h.ready()
        new=trend.scan(h.e);self.assertEqual(new['signal_id'],old['signal_id'])
        self.assertEqual(new['expires_ms'],old['expires_ms'])


if __name__=='__main__':unittest.main(verbosity=2)
