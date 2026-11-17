"""Blocked old feeds and chart reconnects, with no real sockets or orders."""
import copy
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

D=Path(__file__).resolve().parent;HOST=D.parent/'phone_v169';CORE=D.parents[2]/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
from phone_chart_quotes import ChartQuotes, ticker_stream
from phone_chart_live import LiveChart
from phone_mobile import mobile_module
from phone_live_rank import Publisher
from phone_dashboard_live import Dashboard

S='HUMA-USDT-SWAP';T=1794855600000


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.now=100
        self.stream=ticker_stream()
        self.stream.start=Mock()
        self.feed=ChartQuotes(factory=lambda:self.stream,clock=lambda:self.now)
    def tearDown(self):self.feed.close()
    def tick(self,price=103,stamp=T+2000,symbol=S):
        self.stream.connected=True
        self.stream.feed(json.dumps(dict(arg=dict(channel='tickers',instId=symbol),data=[dict(last=str(price),ts=str(stamp))])))
    def test_lazy_single_ticker_watch_replaces_instead_of_accumulating(self):
        self.assertIsNone(self.feed.stream)
        self.feed.watch(S);self.tick();self.assertIsNotNone(self.feed.quote(S,T+2000))
        self.feed.watch('NEW-USDT-SWAP')
        self.assertEqual(self.stream.pairs(),{('NEW-USDT-SWAP','tickers')})
        self.assertEqual(self.stream.symbols,set());self.assertIsNone(self.feed.quote(S,T+2000))
        self.assertEqual(self.stream.band_prices,{})
        self.assertEqual(self.stream._phone_priority_symbols,{'NEW-USDT-SWAP'})
        self.stream.start.assert_called_once()
    def test_same_selection_does_not_reset_quote_or_subscription_revision(self):
        self.feed.watch(S);self.tick();revision=self.stream._phone_watch_revision
        for _ in range(20):self.feed.watch(S)
        self.assertEqual(self.stream._phone_watch_revision,revision)
        self.assertEqual(self.feed.quote(S,T+2000)['last'],'103')
    def test_idling_drops_socket_and_new_watch_can_reuse_reader(self):
        self.feed.watch(S);self.tick();generation=self.stream.generation
        self.now+=16;self.feed.expire()
        self.assertFalse(self.stream.connected);self.assertGreater(self.stream.generation,generation)
        self.assertEqual(self.stream.pairs(),set());self.assertIsNone(self.feed.quote(S,T+2000))
        self.feed.watch(S);self.assertIsNone(self.feed.quote(S,T+2000))
        self.tick(104);self.assertEqual(self.feed.quote(S,T+2000)['last'],'104')
        self.stream.start.assert_called_once()
    def test_chart_quote_does_not_wait_for_blocked_whole_market_reader(self):
        self.feed.watch(S);self.tick()
        old=NS(read=Mock(side_effect=AssertionError('whole-market feed must not be read')),monitor=Mock())
        mobile=NS(lock=threading.RLock(),snapshot=dict(positions=[dict(symbol=S)]),
            chart_cache={(S,'15m'):dict(bars=[[T,100,102,99,101,77,False]],observed_ms=T+2200)},
            feed=NS(select=Mock()),touched=0)
        live=LiveChart(mobile,old,clock=lambda:T+2300,quotes=self.feed)
        live.select(S,'15m');packet=live.packet(S,'15m')
        self.assertTrue(packet['live']);self.assertEqual(packet['quote']['last'],103)
        self.assertEqual(packet['bars'][0],[T,100,103,99,103,77,False])
        old.read.assert_not_called();old.monitor.assert_not_called()
    def test_reconnection_and_staleness_keep_existing_freshness_checks(self):
        self.feed.watch(S);self.tick()
        self.assertIsNone(self.feed.quote(S,T+5001))
        self.stream.generation+=1;self.assertIsNone(self.feed.quote(S,T+2000))
        self.tick(104);self.assertEqual(self.feed.quote(S,T+2000)['last'],'104')
        self.stream.connected=False;self.assertIsNone(self.feed.quote(S,T+2000))
    def test_close_stops_reader_and_idle_worker(self):
        self.feed.watch(S);self.feed.close()
        self.assertTrue(self.stream.stop_event.is_set());self.assertFalse(self.feed.worker.is_alive())
        revision=self.stream._phone_watch_revision;self.feed.watch('NO')
        self.assertEqual(self.stream._phone_watch_revision,revision)
    def test_display_diagnostic_reports_its_own_lane_only(self):
        self.feed.watch(S);self.tick()
        d=self.feed.diagnostic(T+2300)
        self.assertEqual(d['symbol'],S);self.assertAlmostEqual(d['exchange_age_s'],.3)
        self.assertTrue(d['connected']);self.assertNotIn('account',d)


class CaptureTests(unittest.TestCase):
    def mobile(self):
        module=mobile_module(CORE);m=object.__new__(module.PhoneMobile)
        m.lock=threading.RLock();m.snapshot=dict(state={},positions=[],captured_ms=T)
        m.updater=NS(snapshot=lambda:{});m._view_revision=1;m.capture_rebuilds=0;m.capture_reuses=0
        m.hidden=();m.config={};m.display_basis={};m.closed=threading.Event()
        return m,NS(revision=1,data_seen=time.monotonic(),state={})
    def test_blocked_rank_collection_never_stalls_chart_or_private_display(self):
        m,v=self.mobile();entered=threading.Event();release=threading.Event()
        publisher=Publisher(NS(),None);m.live_market=publisher
        old=dict(rows=[dict(symbol=S,last=101)],observed_ms=T,stale=False)
        publisher.published=old
        def slow(*args):
            entered.set();release.wait(3)
            return dict(rows=[],observed_ms=T+1000,ready=False)
        with patch('phone_live_rank.snapshot',slow):
            thread=threading.Thread(target=publisher.payload);thread.start()
            try:
                self.assertTrue(entered.wait(1))
                start=time.monotonic();m.capture(v);value=Dashboard(m).snapshot()
                elapsed=time.monotonic()-start
                self.assertLess(elapsed,.2);self.assertEqual(m.snapshot['futures']['observed_ms'],T)
                self.assertEqual(value['positions'],[])
                # Display age remains the original observation, never fabricated.
                self.assertFalse(release.is_set())
            finally:release.set();thread.join(2)
        self.assertEqual(publisher.cached()['observed_ms'],T+1000)
    def test_fallback_payload_is_also_outside_display_lock(self):
        m,v=self.mobile();entered=threading.Event();release=threading.Event()
        def slow():entered.set();release.wait(2);return dict(rows=[],observed_ms=T,stale=True)
        m.live_market=NS(payload=slow)
        worker=threading.Thread(target=m.capture,args=(v,));worker.start()
        try:
            self.assertTrue(entered.wait(1));self.assertTrue(m.lock.acquire(timeout=.1));m.lock.release()
        finally:release.set();worker.join(2)
    def test_rank_cleaning_reuses_same_observation_without_mutating_publisher(self):
        m,v=self.mobile();p=Publisher(NS(),None)
        data=dict(rows=[dict(symbol=S,last=101)],observed_ms=T,stale=False)
        p.published=data;m.live_market=p
        m.capture(v);one=m.snapshot['futures'];m.capture(v);self.assertIs(m.snapshot['futures'],one)
        self.assertIsNot(one,data);self.assertEqual(data,one)
        p.published=dict(rows=[dict(symbol=S,last=104)],observed_ms=T+1,stale=False)
        m.capture(v);self.assertEqual(m.snapshot['futures']['rows'][0]['last'],104)
        self.assertEqual(data['rows'][0]['last'],101)


if __name__=='__main__':unittest.main(verbosity=2)
