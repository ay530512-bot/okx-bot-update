"""Offline mutable-input, producer, signal and full public-feed differential tests."""
import copy
import importlib.util
import json
import os
import pickle
import queue
import random
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path[:0] = [os.environ['OKX_TEST_HOST'], os.environ['OKX_TEST_CORE']]
import okx_band_flow as band
import okx_channel701 as channel
import okx_pattern15 as trend
import okx_stream
import okx_two_wick732 as patterns
from phone_frozen_bars import FrozenBars, freeze, install as install_frozen
from phone_feed_fast import install as install_feed
from phone_performance import Timing
from phone_signal_cache import install

PINS = json.loads((Path(os.environ['OKX_TEST_HOST'])/'phone_sources.json').read_text())
FIXTURE = json.loads((Path(__file__).parents[1]/'phone_v118/test_signal_fixture.json').read_text())


class ImmutableInputs(unittest.TestCase):
    def test_detached_readonly_rows_and_editable_deepcopy(self):
        original = [[900000, 1., 2., .5, 1.5, 3.]]
        frozen = freeze(original)
        original[0][4] = 9
        self.assertEqual(frozen[0][4], 1.5)
        with self.assertRaises(TypeError): frozen[0][4] = 8
        with self.assertRaises(TypeError): frozen._encoded = b'bad'
        thawed = copy.deepcopy(frozen);thawed[0][4] = 7
        self.assertEqual(frozen[0][4], 1.5)
        self.assertEqual(pickle.loads(frozen._encoded), [[900000,1.,2.,.5,1.5,3.]])

    def test_types_signed_zero_and_unusual_data_are_not_collapsed(self):
        self.assertNotEqual(freeze([[0, 1]])._encoded, freeze([[0, 1.]])._encoded)
        self.assertNotEqual(freeze([[0, 0.]])._encoded, freeze([[0, -0.]])._encoded)
        for rows in ([[0, float('nan')]], [[0, {}]], [[0, float('inf')]]):
            self.assertIs(freeze(rows), rows)

    def test_full_and_incremental_producer_preserve_corrections(self):
        install_frozen(band, PINS)
        original = band.merge_completed.__wrapped__
        raw = [[i*900000,1.,2.,.5,1.5,3.] for i in range(299)]
        frozen = band.merge_completed(None, raw, '15m', 299*900000, 300)
        self.assertIs(type(frozen), FrozenBars)
        fresh = [[298*900000,1.,2.,.5,1.6,4.], [299*900000,1.,2.,.5,1.5,3.]]
        got = band.merge_completed((0,frozen),fresh,'15m',300*900000,3)
        expected = original((0,raw),fresh,'15m',300*900000,3)
        self.assertEqual(got.thaw(),expected)
        self.assertEqual(got[-2][4],1.6)
        self.assertEqual(frozen[-1][4],1.5)
        self.assertNotEqual(got._encoded,frozen._encoded)

    def test_scanner_publishes_frozen_frames_and_reuses_without_requests(self):
        install_frozen(band,PINS)
        now=900000*500
        calls=[]
        class API:
            session=NS(close=lambda:None)
            def __init__(self,settings):pass
            def now_ms(self):return now
            def public(self,path,**kwargs):
                calls.append(kwargs)
                step=band.STEPS[kwargs['bar']];end=now//step*step
                return [[str(end-i*step),'1','2','.5','1.5','3','3','3','1'] for i in range(1,300)]
        owner=NS(cfg={'execution':{'rule_channel701':True},'signals':{}},settings={'TRADING_EXCHANGE':'okx'},
                 lock=threading.RLock(),stop_event=threading.Event(),search_paused=threading.Event(),
                 search_generation=0,throttle=lambda **kw:None)
        market=NS(owner=owner,market=lambda:{'instruments':{'X':{'instId':'X'}},'quotes':{}})
        with patch('okx_core.OKX',API):
            result=band.scan(market);second=band.scan(market)
        self.assertEqual(len(calls),3)
        for name, bars in result['rows'][0]['live_frames'].items():
            self.assertIs(type(bars),FrozenBars)
            self.assertIs(bars,second['rows'][0]['live_frames'][name])


class Signals(unittest.TestCase):
    def test_frozen_inputs_match_original_and_invalidate_on_correction(self):
        originals=(channel.packet,channel.candidate,channel.closed,patterns.select,band.view,trend.summary)
        row=copy.deepcopy(FIXTURE['row']);row['instrument']['lever']='100';now=int(FIXTURE['now'])
        for bars in row['live_frames'].values():
            for r in bars:r[0]=int(r[0])
        cfg={'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]}}
        def engine(row,at):
            return NS(api=NS(now_ms=lambda:at),can_open_position=lambda:True,
                universe=NS(read=lambda:({'rows':[row]},None)),records=lambda:[],blocked_manual_symbols=lambda:set(),
                cfg=cfg,journal=NS(data={}),stream=NS(watch=lambda _:None,ready=lambda *a:False),
                chat=NS(watch=lambda:[]),pipeline=lambda *a,**k:None,events=queue.Queue())
        timer=Timing('/tmp');timer.local.group='optimized';cache=install(timer,PINS)
        try:
            with patch.object(trend,'allowed',return_value=True):
                for offset, correction in [(0,0),(1000,0),(89999,0),(90001,0),(900000,0),(0,1),(0,2)]:
                    plain=copy.deepcopy(row)
                    if correction:plain['live_frames']['1H'][-2][5]+=correction
                    immutable=dict(plain,live_frames={k:freeze(v) for k,v in plain['live_frames'].items()})
                    # Original candidate calls the installed packet; force the original packet only for control.
                    with patch.object(channel,'packet',originals[0]),patch.object(channel,'closed',originals[2]),patch.object(patterns,'select',originals[3]):
                        expected=engine(plain,now+offset);originals[1](expected)
                    actual=engine(immutable,now+offset);channel.candidate(actual)
                    self.assertEqual(actual.channel_pending,expected.channel_pending)
                self.assertGreater(cache.report()['frozen_reuses'],0)
                # Repeat immutable input: no full-array serialization on a warm miss-free scan.
                before=cache.report();channel.candidate(engine(immutable,now));after=cache.report()
                self.assertEqual(after['misses'],before['misses'])
                self.assertGreater(after['frozen_reuses'],before['frozen_reuses'])
                # Public packet consumers preserve original list shape and current quote.
                for price in ('100','101'):
                    got=channel.packet(immutable,cfg,now,{'last':price})
                    with patch.object(channel,'closed',originals[2]),patch.object(patterns,'select',originals[3]):
                        expected=originals[0](plain,cfg,now,{'last':price})
                    self.assertEqual(got,expected)
        finally:
            channel.packet,channel.candidate,channel.closed,patterns.select,band.view,trend.summary=originals


class Feed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('original_feed125',Path(os.environ['OKX_TEST_CORE'])/'okx_stream.py')
        cls.reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.reference)
        install_feed(PINS)

    def test_each_frame_quotes_bars_callbacks_and_errors_match(self):
        a=self.reference.MarketStream();b=okx_stream.MarketStream();ca=[];cb=[]
        a.on_mark=ca.append;b.on_mark=cb.append
        rng=random.Random(125)
        cases=[]
        for i in range(1600):
            if i%127==0:
                cases.append(('generation',None))
            ts=(i//40)*300000+i%40
            channel_name=('tickers','tickers','mark-price','books5','trades')[i%5]
            value=100 if i%7 else 100+rng.randrange(-3,4)
            cases.append(('frame',json.dumps({'arg':{'instId':'X'+str(i%9),'channel':channel_name},
                'data':[{'ts':str(ts),'last':str(value),'markPx':str(value)}]})))
        cases += [('frame',x) for x in ('pong','{}','{"event":"error","code":"60014"}',
                    '{"arg":{"instId":"X0","channel":"tickers"},"data":[{"ts":"0","last":"1"}]}')]
        with patch('time.monotonic',return_value=123):
            for kind,message in cases:
                if kind=='generation':a.generation+=1;b.generation+=1;continue
                errors=[]
                for s in (a,b):
                    try:s.feed(message);errors.append(None)
                    except Exception as e:errors.append((type(e).__name__,str(e)))
                self.assertEqual(errors[0],errors[1])
                self.assertEqual(a.data,b.data)
                self.assertEqual(a.band_prices,b.band_prices)
                self.assertEqual(ca,cb)

    def test_duplicate_price_keeps_timestamp_and_book_freshness(self):
        s=okx_stream.MarketStream();s.connected=True;s.generation=1
        for stamp in (1000,2000):
            s.feed(json.dumps({'arg':{'instId':'X','channel':'tickers'},'data':[{'ts':str(stamp),'last':'100'}]}))
        self.assertEqual(s.read('X','tickers',15,2000)['ts'],'2000')
        self.assertIsNone(s.read('X','tickers',15,20000))
        s.generation+=1
        self.assertIsNone(s.read('X','tickers',15,2000))


sys.path.append(str(Path(__file__).parents[1]/'phone_v123'))
from test_entry_clock import ClockTests
class FrozenClock(ClockTests):
    def setUp(self):
        super().setUp()
        self.row['live_frames']={name:freeze(bars) for name,bars in self.row['live_frames'].items()}
    def test_bad_or_changed_candles_cannot_reuse_success(self):
        self.run_candidate(channel.candidate)
        self.row=copy.deepcopy(self.row)
        super().test_bad_or_changed_candles_cannot_reuse_success()
    def test_hourly_correction_invalidates_selection_cache(self):
        self.run_candidate(channel.candidate)
        before=self.cache.report()['misses']
        self.row=copy.deepcopy(self.row)
        self.row['live_frames']['1H'][-2][5]+=1
        self.row['live_frames']={name:freeze(bars) for name,bars in self.row['live_frames'].items()}
        self.run_candidate(channel.candidate)
        self.assertGreater(self.cache.report()['misses'],before)
del ClockTests

if __name__=='__main__':unittest.main(verbosity=2)
