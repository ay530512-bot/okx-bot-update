"""A missing pre-listing baseline is not a missing existing-market candle."""
import copy
import importlib.util
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from test_inputs import engine, T, A, B, HOST, D
import phone_trend_inputs as inputs
import phone_trend_slot as trend

spec=importlib.util.spec_from_file_location('baseline152', D/'phone_v152/phone_trend_inputs.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)


def add_new_listing(e):
    market=e.universe.full_market
    listing=T//3600000*3600000-2*3600000
    instrument=market.instruments[B]
    instrument.update(instType='SWAP',listTime=str(listing))
    at,bars=market.band_cache[(B,'1H')]
    market.band_cache[(B,'1H')]=(at,[r for r in bars if r[0]>=listing])
    return listing


class Baseline(unittest.TestCase):
    def test_old_blocks_all_and_new_ranks_same_preexisting_market(self):
        e=engine();add_new_listing(e)
        with self.assertRaisesRegex(ValueError,'완료1시간봉 대기'):
            old.ranked_rows(e,e.universe.result,T)
        got=inputs.ranked_rows(e,e.universe.result,T)
        self.assertEqual([r['symbol'] for r in got],[A])
        self.assertEqual(trend.rank_rows(got,T)['symbol'],A)
        self.assertTrue(e.phone_trend_inputs['ready'])
        self.assertEqual(e.phone_trend_inputs['baseline_ineligible_count'],1)
        self.assertEqual(e.phone_trend_inputs['hourly_ready'],1)
        self.assertEqual(e.phone_trend_inputs['missing_hourly'],[])
        self.assertEqual(len(e.universe.full_market.instruments),2)

    def test_missing_old_instrument_still_blocks(self):
        e=engine();add_new_listing(e)
        e.universe.full_market.instruments[B]['listTime']=str(T//86400000*86400000-3600000)
        with self.assertRaisesRegex(ValueError,'완료1시간봉 대기'):
            inputs.ranked_rows(e,e.universe.result,T)

    def test_unknown_malformed_and_future_metadata_never_skip(self):
        for value in (None,'','bad','1794800000','-1794800000000',1794800000000,
                      '１７９４８００００００００',str(T+999999)):
            e=engine();add_new_listing(e)
            e.universe.full_market.instruments[B]['listTime']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                inputs.ranked_rows(e,e.universe.result,T)

    def test_wrong_market_or_identity_never_skips(self):
        for field,value in [('instType','SPOT'),('instType',''),('instId',A)]:
            e=engine();add_new_listing(e)
            i=e.universe.full_market.instruments[B];i[field]=value
            with self.subTest(field=field,value=value):
                self.assertFalse(inputs.listed_after_reference(B,i,T//86400000*86400000,T))
                if field=='instId':
                    # The incumbent instrument validator already excludes a
                    # mismatched instrument ID. It is not a listing exception.
                    inputs.ranked_rows(e,e.universe.result,T)
                    self.assertEqual(e.phone_trend_inputs['baseline_ineligible_count'],0)
                else:
                    with self.assertRaises(ValueError):inputs.ranked_rows(e,e.universe.result,T)

    def test_exact09_listing_remains_eligible(self):
        e=engine();i=e.universe.full_market.instruments[B]
        i.update(instType='SWAP',listTime=str(T//86400000*86400000))
        self.assertEqual(len(inputs.ranked_rows(e,e.universe.result,T)),2)

    def test_next09_rejoins_and_requires_its_actual_baseline(self):
        e=engine();add_new_listing(e)
        day=T//86400000*86400000
        i=e.universe.full_market.instruments[B]
        self.assertTrue(inputs.listed_after_reference(B,i,day,T))
        self.assertFalse(inputs.listed_after_reference(B,i,day+86400000,T+86400000))
        with self.assertRaises(ValueError):
            inputs.ranked_rows(e,e.universe.result,T+86400000)

    def test_missing_other_existing_symbol_still_blocks(self):
        e=engine();add_new_listing(e);e.universe.full_market.band_cache.pop((A,'1H'))
        with self.assertRaises(ValueError):inputs.ranked_rows(e,e.universe.result,T)
        self.assertEqual(e.phone_trend_inputs['missing_hourly'],[A])

    def test_all_new_listings_never_produce_a_fake_leader(self):
        e=engine();listing=add_new_listing(e)
        e.universe.full_market.instruments[A].update(instType='SWAP',listTime=str(listing))
        with self.assertRaises(ValueError):inputs.ranked_rows(e,e.universe.result,T)
        self.assertFalse(e.phone_trend_inputs['ready'])
        self.assertEqual(e.phone_trend_inputs['eligible'],0)

    def test_export_preserves_exclusion_reason(self):
        from phone_diagnostic_export import safe
        e=engine();add_new_listing(e);inputs.ranked_rows(e,e.universe.result,T)
        d=safe({'trend_inputs':e.phone_trend_inputs})['trend_inputs']
        self.assertEqual(d['baseline_ineligible_count'],1)
        self.assertEqual(d['baseline_ineligible'][0]['symbol'],B)
        self.assertIn('listing_ms',d['baseline_ineligible'][0])


class FullEntry(unittest.TestCase):
    def exercise(self, morning=False):
        from execution_harness import Harness, instrument, NETWORK_ATTEMPTS
        from test_morning import fixture as morning_fixture
        from execution_harness import D as tests
        f=morning_fixture() if morning else copy.deepcopy(json.loads((tests/'fixtures.json').read_text())['fixtures']['top1_15kst_dip130_LONG'])
        symbol='NEWLIST-USDT-SWAP'
        listing=f['now']//3600000*3600000-3*3600000
        for name in ('rows','arming_rows'):
            if name not in f:continue
            r=copy.deepcopy(f[name][0]);r['symbol']=symbol
            r['live_frames']={frame:[b for b in bars if b[0]>=listing]
                              for frame,bars in r['live_frames'].items()}
            f[name].append(r)
        def metadata(s):
            i=instrument(s)
            if s==symbol:i.update(instType='SWAP',listTime=str(listing))
            return i
        h=None
        try:
            with patch('execution_harness.instrument',side_effect=metadata):
                h=Harness(f,4)
                with self.assertRaises(ValueError):
                    old.ranked_rows(h.e,h.e.universe.result,h.api.now//900000*900000)
                if 'arming_rows' in f:
                    h.candidate();self.assertTrue(h.e.journal.data[trend.STATE]['arm'])
                    h.feed(f['rows'],f['now'])
                h.compute()
                for _ in range(3):
                    h.ready();h.e.tick()
                    if h.e.records():break
                self.assertEqual(len(h.api.opening_posts()),1)
                order=h.e.records()[0]
                self.assertNotEqual(order['symbol'],symbol)
                self.assertEqual(bool(order['v4_signal'].get('morning150')),morning)
                h.api.fill(order['client_id']);h.ready();h.e.tick()
                self.assertEqual(order['phase'],'active')
                self.assertTrue(order['protection_verified'])
                h.e.tick();self.assertEqual(len(h.api.opening_posts()),1)
                self.assertEqual(__import__('phone_live_rank').snapshot(h.e)['baseline_ineligible_count'],1)
                self.assertEqual(NETWORK_ATTEMPTS,[])
        finally:
            if h:h.close()

    def test_trend_leader_enters_with_verified_post09_listing(self):self.exercise()
    def test_morning_leader_enters_with_verified_post09_listing(self):self.exercise(True)


if __name__=='__main__':unittest.main(verbosity=2)
