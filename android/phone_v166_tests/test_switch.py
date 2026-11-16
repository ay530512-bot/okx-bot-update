import copy
import json
import unittest
from unittest.mock import patch
from execution_harness import D, Harness, dec, BotError, UnknownOutcome, trend, NETWORK_ATTEMPTS
from test_morning import fixture
import phone_morning_short as m

LONG = json.loads((D/'fixtures.json').read_text())['fixtures']['top1_15kst_dip130_LONG']

class SwitchTests(unittest.TestCase):
    def setUp(self):self.h=None
    def tearDown(self):
        if self.h:self.h.close()
        self.assertEqual(NETWORK_ATTEMPTS,[])
    def held_long(self, same_symbol=False):
        h=Harness(copy.deepcopy(LONG));self.h=h
        s=h.signal();o=h.submit(s);h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o))
        t=h.api.now//m.DAY*m.DAY+20*m.HOUR+m.STEP
        data=fixture(t,o['symbol'] if same_symbol else 'MORNING-USDT-SWAP')
        if not same_symbol:
            data['rows'][0]['rank_base']=70  # Synthetic live return now exceeds the held long's return.
            price=float(h.api.positions[0]['avgPx'])
            r=fixture(t,o['symbol'])['rows'][0]
            for f,bs in r['live_frames'].items():
                for b in bs:b[1:5]=[price,price*1.01,price*.99,price]
            data['rows'].append(r)
        h.feed(data['rows'],data['now']);h.e.journal.roll_day(h.api.now,dec(300),initialize=True)
        h.e.journal.save();h.e.raw_snapshot=h.api.snapshot()
        orig_post=h.api.post;orig_get=h.api.get
        def post(path,body):
            if path=='/api/v5/trade/cancel-algos':
                h.api.calls.append(('post '+path,copy.deepcopy(body)))
                ids={v['algoId'] for v in body};h.api.algos=[a for a in h.api.algos if a['algoId'] not in ids]
                return [dict(sCode='0')]
            return orig_post(path,body)
        def get(path,**kw):
            if path=='/api/v5/account/positions-history':return []
            return orig_get(path,**kw)
        h.api.post=post;h.api.get=get
        return h,o
    def close_requests(self,h):
        return [b for path,b in h.api.calls if path=='post /api/v5/trade/order' and not b.get('attachAlgoOrds')]
    def request_switch(self,h,o):
        with h.e.selected(0):
            self.assertTrue(m.maybe_switch(h.e,h.e.snapshot(),h.api.positions[0],o))
        self.assertEqual(o['phase'],'closing');self.assertEqual(len(self.close_requests(h)),1)
        self.assertEqual(len(h.api.opening_posts()),1)
        return copy.deepcopy(h.e.journal.data[m.STATE]['pending'])
    def fill_close(self,h,o,fraction=1):
        order=h.api.orders[o['close_id']];qty=dec(o['quantity'])*dec(fraction)
        order.update(state='filled' if fraction==1 else 'partially_filled',accFillSz=str(qty),avgPx='1')
        if fraction==1:h.api.positions=[]
        else:h.api.positions[0]['pos']=str(dec(o['quantity'])-qty)
    def test_full_tick_switch_long_close_then_short_fill_and_sl(self):
        h,o=self.held_long();h.compute()
        for _ in range(3):
            h.ready();h.e.tick()
            if o['phase']=='closing':break
        self.assertEqual(o['phase'],'closing');self.assertEqual(len(self.close_requests(h)),1)
        s=h.e.journal.data[m.STATE]['pending'];self.assertTrue(m.is_signal(s))
        h.e.tick();self.assertEqual(len(h.api.opening_posts()),1);self.assertEqual(len(self.close_requests(h)),1)
        self.fill_close(h,o);h.api.now+=2000;h.ready();h.e.tick()
        # Completed close + current shared rank + selected completed candles
        # allow the short without waiting for unrelated whole-universe scans.
        self.assertEqual(len(h.api.opening_posts()),2)
        h.feed(list(h.api.rows.values()),h.api.now+1000);h.compute();h.e.tick()
        self.assertEqual(len(h.api.opening_posts()),2,dict(status=getattr(h.e,'phone_morning_status',None),diagnostic=getattr(h.e,'phone_entry_diagnostic',None),log=(h.e.root/'bot_log.txt').read_text()[-3000:]))
        short=h.e.records()[0];self.assertEqual(short['direction'],'short');self.assertEqual(short['phase'],'submitted')
        h.api.fill(short['client_id']);h.ready();h.e.tick()
        self.assertEqual(short['phase'],'active');self.assertTrue(short['protection_verified'])
        self.assertTrue(h.e.journal.data[m.STATE]['switch']['confirmed_ms'])
    def test_same_symbol_does_not_overlap_positions(self):
        h,o=self.held_long(True);s=self.request_switch(h,o)
        self.assertIs(h.submit(s),o);self.assertEqual(len(h.api.opening_posts()),1)
        self.fill_close(h,o);h.api.now+=2000;h.ready()
        with h.e.selected(0):h.e.reconcile(h.e.snapshot())
        short=h.submit(s);self.assertEqual(short['direction'],'short')
        self.assertEqual(len(h.api.opening_posts()),2)
    def test_partial_close_no_short(self):
        h,o=self.held_long();s=self.request_switch(h,o);self.fill_close(h,o,.5)
        with h.e.selected(0):h.e.reconcile(h.e.snapshot())
        with self.assertRaisesRegex(BotError,'자리 배분|청산 완료'):m.validate_entry(h.e,s,s['entry_reference'])
        self.assertEqual(len(h.api.opening_posts()),1)
    def test_missing_close_ack_no_duplicate_close(self):
        h,o=self.held_long();h.api.unknown=True
        with self.assertRaises(UnknownOutcome):m.maybe_switch(h.e,h.e.snapshot(),h.api.positions[0],o)
        state=json.loads(h.e.journal.path.read_text())[m.STATE]
        self.assertEqual(state['switch']['close_id'],o['close_id'])
        h.api.unknown=False
        self.assertFalse(m.maybe_switch(h.e,h.e.snapshot(),h.api.positions[0],o))
        self.assertEqual(len(self.close_requests(h)),1);self.assertEqual(len(h.api.opening_posts()),1)
    def test_restart_intent_flat_ack_or_unfinished_cleanup_blocks(self):
        h,o=self.held_long();s=self.request_switch(h,o)
        h.e.journal.data[m.STATE]=json.loads(h.e.journal.path.read_text())[m.STATE]
        with patch.object(h.e,'records',return_value=[]):
            with self.assertRaisesRegex(BotError,'잔량'):m.verify_switch_flat(h.e,s)
            h.api.positions=[]
            with self.assertRaisesRegex(BotError,'미체결'):m.verify_switch_flat(h.e,s)
            order=h.api.orders[o['close_id']];order.update(state='canceled')
            with self.assertRaisesRegex(BotError,'체결 확인'):m.verify_switch_flat(h.e,s)
            order.update(state='filled',accFillSz=o['quantity'])
            with self.assertRaisesRegex(BotError,'보호주문'):m.verify_switch_flat(h.e,s)
    def test_expired_after_close_no_forced_short(self):
        h,o=self.held_long();s=self.request_switch(h,o);self.fill_close(h,o)
        h.api.now=s['expires_ms']+1;h.ready()
        with h.e.selected(0):h.e.reconcile(h.e.snapshot())
        self.assertIsNone(m.scan(h.e));self.assertEqual(len(h.api.opening_posts()),1)
    def test_user_pause_preview_connection_or_day_stop_preserves_long(self):
        for key in ('user_paused','preview','recovering','ended','entry_cancel'):
            h,o=self.held_long()
            if key=='ended':h.e.journal.data['day']['ended']=True
            elif key=='entry_cancel':h.e.entry_cancel.set()
            else:setattr(h.e,key,True)
            self.assertFalse(m.maybe_switch(h.e,h.e.snapshot(),h.api.positions[0],o),key)
            self.assertEqual(o['phase'],'active');self.assertFalse(self.close_requests(h));h.close();self.h=None
    def test_other_positions_and_manual_target_never_closed(self):
        h,o=self.held_long()
        with patch.object(h.e,'blocked_manual_symbols',return_value={'MORNING-USDT-SWAP'}):
            self.assertFalse(m.maybe_switch(h.e,h.e.snapshot(),h.api.positions[0],o))
        common=dict(o,v4_signal={},holding_rule={})
        with self.assertRaises(BotError):m.validate_switch_scope(h.e,{'symbol':'MORNING-USDT-SWAP'},common)
        self.assertFalse(self.close_requests(h))
    def test_full_capacity_still_collects_for_reversal_but_remains_full(self):
        import okx_search_capacity as cap
        h,o=self.held_long();others=[dict(symbol='O'+str(i),direction='short',client_id='o'+str(i),v4_signal={}) for i in range(3)]
        with patch.object(h.e,'records',return_value=[o]+others):
            self.assertTrue(cap.sync(h.e));self.assertFalse(h.e.universe.search_paused.is_set())
            self.assertFalse(h.e.can_open_position())
            h.api.now=h.api.now//m.DAY*m.DAY+23*m.HOUR
            self.assertTrue(cap.sync(h.e));self.assertTrue(h.e.universe.search_paused.is_set())

if __name__=='__main__':unittest.main(verbosity=2)
