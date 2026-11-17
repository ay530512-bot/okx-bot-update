"""Similarity is evidence/prioritization, never an independent trading rule."""
import copy
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from execution_harness import Harness, D, NETWORK_ATTEMPTS, configured
import okx_channel701 as channel
import phone_similar_candidates as sim
import phone_trend_slot as trend

FIXTURES = json.loads((D/'fixtures.json').read_text())['fixtures']


class Tests(unittest.TestCase):
    def test_all_eight_automatic_paths_capture_confirmation_features(self):
        from test_morning import fixture
        fixtures=dict(FIXTURES,morning_SHORT=fixture())
        for name,fx in fixtures.items():
            with self.subTest(route=name):
                h=Harness(fx)
                try:
                    s=h.signal()
                    self.assertIn(sim.FIELD,s)
                    self.assertEqual(s[sim.FIELD]['candle_ms'],s['valid_from_ms'])
                    saved=copy.deepcopy(s[sim.FIELD]);s.pop(sim.FIELD)
                    sim.capture_selected(s,fx['rows'])
                    self.assertEqual(s[sim.FIELD],saved)
                finally:h.close()

    def feature(self):
        fx = FIXTURES['trend_pullback_LONG']; values = fx['rows'][0]['live_frames']
        return sim.features(values['15m'], values['1H'], fx['now'])

    def test_scale_invariant_chart_and_self_relative_volume(self):
        fx = copy.deepcopy(FIXTURES['trend_pullback_LONG'])
        a = self.feature(); self.assertIsNotNone(a)
        values = fx['rows'][0]['live_frames']
        for rows in values.values():
            for r in rows:
                r[1:5] = [v*200 for v in r[1:5]]; r[5] *= 500
        b = sim.features(values['15m'], values['1H'], fx['now'])
        self.assertEqual(sim.compare(a, b)['score'], 100)
        self.assertEqual(a['relative_volume'], b['relative_volume'])

    def test_unfinished_candles_do_not_change_features(self):
        fx = copy.deepcopy(FIXTURES['trend_pullback_LONG']); values = fx['rows'][0]['live_frames']
        a = self.feature()
        for frame,step in [('15m',sim.STEP),('1H',sim.HOUR)]:
            values[frame].append([fx['now']//step*step,100,200,1,5,999999])
        self.assertEqual(a, sim.features(values['15m'], values['1H'], fx['now']))

    def test_missing_or_corrected_data_recomputes_without_signal_override(self):
        fx=copy.deepcopy(FIXTURES['trend_pullback_LONG']); values=fx['rows'][0]['live_frames']
        self.assertIsNone(sim.features(values['15m'][:-2], values['1H'], fx['now']))
        values['15m'][-1][5] *= 20
        changed=sim.features(values['15m'], values['1H'], fx['now'])
        self.assertLess(sim.compare(self.feature(),changed)['volume'],100)

    def test_only_confirmed_auto_record_can_anchor_and_entry_snapshot_frozen(self):
        h=Harness(FIXTURES['trend_pullback_LONG'])
        try:
            s=h.signal(); original=copy.deepcopy(s[sim.FIELD]); o=h.submit(s)
            self.assertIsNone(sim.anchor(h.e)[0])  # request ACK is not a fill
            h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
            ref,_=sim.anchor(h.e);self.assertEqual(ref['features'],original)
            h.api.rows[s['symbol']]['live_frames']['15m'][-1][5]*=100
            self.assertEqual(sim.anchor(h.e)[0]['features'],original)
            o['v4_signal']['click716']=True;self.assertIsNone(sim.anchor(h.e)[0])
            o['v4_signal'].pop('click716');o['v4_signal'].pop(sim.FIELD)
            self.assertIsNone(sim.anchor(h.e)[0])
            self.assertIn('진입 당시',sim.anchor(h.e)[1])
        finally:h.close()

    def test_priority_only_reorders_valid_same_direction_and_same_expiry(self):
        f=self.feature(); bad=copy.deepcopy(f);bad['chart']=[x+4 for x in bad['chart']]
        def signal(action,feature,score=0,start=100):
            return dict(action=action,valid_from_ms=start,decision_record={'evidence704':{'score':score}},**{sim.FIELD:feature})
        items=[('A',signal('LONG',bad,20)),('B',signal('LONG',f,1)),('C',signal('SHORT',f,30)),('D',signal('LONG',f,0,90))]
        ref=dict(action='LONG',features=f)
        result=sim.ordered(items,ref,channel.rank_item)
        self.assertEqual([s for s,_ in result],['D','B','C','A'])
        self.assertEqual(set(s for s,_ in result),set(s for s,_ in items))
        self.assertEqual(sim.ordered(items,None,channel.rank_item),sorted(items,key=channel.rank_item))

    def test_three_common_positions_enter_fill_and_verify_stops_then_reserved_slot_remains(self):
        fx=copy.deepcopy(FIXTURES['trend_pullback_LONG']); base=fx['rows'][0]
        fx['rows']=[dict(copy.deepcopy(base),symbol=s+'-USDT-SWAP') for s in ('AAA','BBB','CCC','DDD')]
        h=Harness(fx)
        try:
            cfg=copy.deepcopy(h.e.cfg)
            for n in range(3):
                h.ready(); s=h.candidate();self.assertIsNotNone(s)
                o=h.submit(s);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
                h.e.executing_signal=None
                self.assertEqual(len(h.e.records()),n+1)
            h.ready();self.assertIsNone(h.candidate())
            self.assertEqual(trend.slot_counts(h.e),(3,0,3))
            self.assertEqual(len(h.api.opening_posts()),3)
            self.assertEqual(len(h.api.algos),3)
            self.assertEqual(h.e.cfg,cfg)
            report=h.e.phone_entry_diagnostic['similarity']
            self.assertEqual(report['reference_symbol'],'AAA-USDT-SWAP')
            self.assertLessEqual(len(report['candidates']),3)
        finally:h.close()
        self.assertEqual(NETWORK_ATTEMPTS,[])

    def test_similar_but_no_original_signal_never_returns_entry(self):
        h=Harness(FIXTURES['trend_pullback_LONG'])
        try:
            s=h.signal();o=h.submit(s);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
            row=copy.deepcopy(h.fixture['rows'][0]);row['symbol']='SIMILAR-USDT-SWAP'
            h.feed([*h.fixture['rows'],row],h.api.now)
            h.e.channel_pending={}
            p={'entry_setups':[],sim.FIELD:copy.deepcopy(s[sim.FIELD])}
            with patch.object(h.manager,'lookup',return_value=p):
                self.assertIsNone(channel.candidate(h.e))
            report=h.e.phone_entry_diagnostic['similarity']
            self.assertEqual(report['candidates'][0]['score'],100)
            self.assertFalse(report['candidates'][0]['passed'])
            self.assertEqual(len(h.api.opening_posts()),1)
        finally:h.close()

    def test_similarity_cannot_bypass_original_preflight_rejection(self):
        fx=copy.deepcopy(FIXTURES['trend_pullback_LONG']);base=fx['rows'][0]
        fx['rows']=[base,dict(copy.deepcopy(base),symbol='ZZZ-USDT-SWAP')]
        h=Harness(fx)
        try:
            s=h.signal();o=h.submit(s);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
            h.ready();h.compute()
            from okx_core import BotError
            with patch.object(channel,'check_entry',side_effect=BotError('봉 연속성 오류')) as check:
                self.assertIsNone(channel.candidate(h.e));self.assertGreater(check.call_count,0)
            self.assertEqual(len(h.api.opening_posts()),1)
        finally:h.close()


if __name__=='__main__':unittest.main(verbosity=2)
