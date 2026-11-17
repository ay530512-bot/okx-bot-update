"""Actual engine paths; synthetic exchange fills/protection, network disabled."""
import copy
import json
import unittest
from unittest.mock import patch

from execution_harness import Harness, D, CORE, NETWORK_ATTEMPTS, dec
from okx_core import BotError, Rejected, UnknownOutcome
from test_morning import fixture
import phone_manual_reduction as m
import phone_handover

FIXTURES = json.loads((D/'fixtures.json').read_text())['fixtures']
FIXTURES['morning_SHORT'] = fixture()


class Ledger:
    def __init__(self, h):
        self.h = h
        self.api = a = h.api
        self.rows = []
        self.posts = []
        self.unknown = self.reject = self.omit_stop = False
        self.fail_history = self.duplicate = False
        old_get, old_post = a.get, a.post
        def get(path, **params):
            if path == '/api/v5/trade/fills-history':
                a.calls.append(('get '+path, params))
                if self.fail_history:
                    raise TimeoutError('offline history unavailable')
                rows = [r for r in self.rows if r['instId']==params['instId']
                        and int(params['begin'])<=int(r['fillTime'])<=int(params['end'])]
                rows = sorted(rows,key=lambda r:int(r['billId']),reverse=True)
                if params.get('after'):
                    rows = [r for r in rows if int(r['billId'])<int(params['after'])]
                return copy.deepcopy((rows+rows if self.duplicate else rows)[:100])
            return old_get(path, **params)
        def post(path, body):
            if path in ('/api/v5/trade/order-algo','/api/v5/trade/cancel-algos','/api/v5/trade/amend-algos'):
                self.posts.append((path,copy.deepcopy(body)))
                a.calls.append(('post '+path,copy.deepcopy(body)))
                if path.endswith('/order-algo'):
                    if self.reject:
                        raise Rejected('offline protection rejection')
                    if not self.omit_stop:
                        a.algos.append(dict(body,algoId='algo-'+body['algoClOrdId'],state='live'))
                    # Inspect durable intent before the simulated venue ACK.
                    disk=json.loads(h.e.journal.path.read_text())
                    rec=next(r for r in m.records(disk) if r.get(m.STATE))
                    assert rec[m.STATE]['request_sent']
                    if self.unknown:
                        raise UnknownOutcome('offline lost protection ACK')
                elif path.endswith('/cancel-algos'):
                    for cancel in body:
                        a.algos[:]=[r for r in a.algos if r['algoId']!=cancel['algoId']]
                else:
                    for row in a.algos:
                        if row['algoId']==body['algoId']:
                            row['slTriggerPx']=body['newSlTriggerPx']
                return [dict(sCode='0')]
            return old_post(path,body)
        a.get, a.post = get, post

    def append(self, o, quantity, opening=False, client=None):
        side = 'buy' if (o['direction']=='long')==opening else 'sell'
        self.rows.append(dict(instId=o['symbol'],posSide=o['direction'],side=side,
            clOrdId=(o['client_id'] if opening else 'manual') if client is None else client,
            billId=str(len(self.rows)+1),fillTime=str(self.api.now),fillSz=str(quantity)))

    def enter(self):
        o=self.h.submit(self.h.signal())
        self.api.fill(o['client_id'])
        self.append(o,o['quantity'],True)
        p=next(p for p in self.api.positions if p['instId']==o['symbol'])
        p.update(cTime=str(o['entry_ms']),uTime=str(self.api.now))
        for a in self.api.algos:
            a.update(tdMode='isolated',side='sell' if o['direction']=='long' else 'buy')
        self.h.reconcile(o)
        return o

    def reduce(self,o,fraction='.5',client=None):
        self.api.now+=1000
        p=next(p for p in self.api.positions if p['instId']==o['symbol'])
        q=dec(p['pos']);removed=q*dec(fraction)
        self.append(o,removed,client=client)
        p.update(pos=str(q-removed),margin=str(dec(p['margin'])*(1-dec(fraction))),uTime=str(self.api.now))
        return p

    def drive(self,o):
        for _ in range(5):
            self.h.e.reconcile(self.h.e.snapshot())
            if o['phase']=='active':break
        return o['phase']


class Reductions(unittest.TestCase):
    def setUp(self):self.h=None
    def tearDown(self):
        if self.h:self.h.close()
        self.assertEqual(NETWORK_ATTEMPTS,[])
    def setup(self,key='trend_pullback_LONG'):
        self.h=Harness(copy.deepcopy(FIXTURES[key]),0)
        ledger=Ledger(self.h);o=ledger.enter()
        return ledger,o
    def assert_retained(self,before,o):
        for key in ('client_id','entry_ms','posId','fill_px','v4_signal','leverage','market_fill_stats','profit_guard714'):
            self.assertEqual(before.get(key),o.get(key),key)
    def test_all_automatic_rules_manual_half_preserves_rule_and_management(self):
        for key in FIXTURES:
            with self.subTest(rule=key):
                ledger,o=self.setup(key);before=copy.deepcopy(o)
                p=ledger.reduce(o)
                self.assertEqual(ledger.drive(o),'active')
                self.assertEqual(dec(o['quantity']),dec(p['pos']))
                self.assertEqual(dec(o['committed_margin']),dec(before['committed_margin'])/2)
                self.assertTrue(o['partial_used']);self.assertTrue(o['protection_verified'])
                self.assert_retained(before,o)
                self.assertTrue(self.h.e.verify_protection(self.h.e.snapshot(),p,o))
                self.assertEqual(len(self.h.api.opening_posts()),1)
                self.assertEqual(len(self.h.api.algos),1)
                # The normal guard/trailing API still acts on this exact record.
                target=(dec(o['stop_px'])+dec(p['markPx']))/2
                self.h.e.trail(self.h.e.snapshot(),p,o,target)
                for _ in range(4):self.h.e.reconcile(self.h.e.snapshot())
                self.assertEqual(o['phase'],'active')
                self.assertTrue(self.h.e.verify_protection(self.h.e.snapshot(),p,o))
                self.h.close();self.h=None
    def test_repeat_reductions_before_and_after_stop_ack(self):
        l,o=self.setup();initial=dec(o['quantity'])
        l.reduce(o);self.h.e.snapshot()
        self.assertFalse(o[m.STATE]['request_sent'])
        l.reduce(o);self.assertEqual(l.drive(o),'active')
        self.assertEqual(dec(o['quantity']),initial/4)
        l.reduce(o);self.assertEqual(l.drive(o),'active')
        self.assertEqual(dec(o['quantity']),initial/8)
        self.assertEqual(len(o['manual_reductions167']),3)
        self.assertEqual(len(self.h.api.algos),1)
    def test_restart_uses_saved_intent_without_duplicate_protection_post(self):
        l,o=self.setup();l.reduce(o);self.h.e.snapshot();l.unknown=True
        with self.assertRaises(UnknownOutcome):self.h.e.reconcile(self.h.e.snapshot())
        persisted=json.loads(self.h.e.journal.path.read_text())
        self.h.e.journal.data=persisted;o=persisted['owned']
        self.assertEqual(l.drive(o),'active')
        self.assertEqual(sum(p.endswith('/order-algo') for p,b in l.posts),1)
    def test_unacknowledged_protection_keeps_old_stop_and_never_resends(self):
        l,o=self.setup();old=copy.deepcopy(self.h.api.algos);l.reduce(o);l.unknown=True;l.omit_stop=True
        with self.assertRaises(UnknownOutcome):self.h.e.reconcile(self.h.e.snapshot())
        self.assertEqual(self.h.api.algos,old)
        self.h.e.reconcile(self.h.e.snapshot())
        self.assertEqual(sum(p.endswith('/order-algo') for p,b in l.posts),1)
        self.assertFalse(any(p.endswith('/cancel-algos') for p,b in l.posts))
        self.h.api.now+=16000
        self.h.e.reconcile(self.h.e.snapshot())
        self.assertEqual(o['phase'],'closing')
        close=[b for p,b in self.h.api.calls if p=='post /api/v5/trade/order' and not b.get('attachAlgoOrds')]
        self.assertEqual(dec(close[-1]['sz']),dec(o['quantity']))
    def test_new_stop_verified_before_old_stop_cancel(self):
        l,o=self.setup();l.reduce(o);self.h.e.reconcile(self.h.e.snapshot())
        self.assertEqual([p.rsplit('/',1)[-1] for p,b in l.posts],['order-algo','cancel-algos'])
        self.assertEqual(l.drive(o),'active')
    def test_protection_rejection_closes_remainder_not_original_size(self):
        l,o=self.setup();l.reduce(o);l.reject=True
        self.h.e.reconcile(self.h.e.snapshot())
        self.assertEqual(o['phase'],'closing')
        close=[b for p,b in self.h.api.calls if p=='post /api/v5/trade/order' and not b.get('attachAlgoOrds')]
        self.assertEqual(dec(close[-1]['sz']),dec(o['quantity']))
        self.assertFalse(any(p.endswith('/cancel-algos') for p,b in l.posts))
    def test_inflight_tighter_stop_not_widened(self):
        l,o=self.setup();old=dec(o['stop_px']);p=self.h.api.positions[0]
        target=(old+dec(p['markPx']))/2
        self.h.e.trail(self.h.e.snapshot(),p,o,target)
        pending=dec(o['target_stop_px']);l.reduce(o)
        self.assertEqual(l.drive(o),'active');self.assertEqual(dec(o['stop_px']),pending)
    def test_user_or_guard_full_close_during_resize_does_not_stall(self):
        l,o=self.setup();p=l.reduce(o);self.h.e.snapshot()
        self.h.e.close(self.h.e.snapshot(),'user requested close')
        self.assertEqual(o['phase'],'closing')
        close=[b for path,b in self.h.api.calls if path=='post /api/v5/trade/order' and not b.get('attachAlgoOrds')]
        self.assertEqual(dec(close[-1]['sz']),dec(p['pos']))
        self.h.e.close(self.h.e.snapshot(),'repeated user close')
        self.assertEqual(len([b for path,b in self.h.api.calls if path=='post /api/v5/trade/order' and not b.get('attachAlgoOrds')]),1)
    def test_stop_already_crossed_closes_remainder_without_new_stop(self):
        l,o=self.setup();p=l.reduce(o);p['markPx']=str(dec(o['stop_px'])-1)
        self.h.e.reconcile(self.h.e.snapshot())
        self.assertEqual(o['phase'],'closing')
        self.assertFalse(any(path.endswith('/order-algo') for path,b in l.posts))
    def test_boot_after_old_quantity_error_replays_saved_entry_proof(self):
        l,o=self.setup();l.reduce(o)
        saved=json.loads(self.h.e.journal.path.read_text())
        self.h.e.journal.data=saved;o=saved['owned']
        self.assertEqual(l.drive(o),'active')
        self.assertEqual(len(o['manual_reductions167']),1)
    def test_stale_larger_snapshot_never_restores_closed_quantity(self):
        l,o=self.setup();initial=dec(o['quantity']);p=l.reduce(o);l.drive(o)
        old=copy.deepcopy(o);p['pos']=str(initial)
        with self.assertRaises(BotError):self.h.e.snapshot()
        self.assertEqual(o,old)
    def test_unrelated_manual_position_is_not_adopted_or_cancelled(self):
        l,o=self.setup();p=copy.deepcopy(self.h.api.positions[0]);p.update(instId='MANUAL-USDT-SWAP',posId='manual')
        self.h.api.positions.append(p)
        a=copy.deepcopy(self.h.api.algos[0]);a.update(instId=p['instId'],algoId='manual-stop',algoClOrdId='manual-stop')
        self.h.api.algos.append(a)
        l.reduce(o);self.assertEqual(l.drive(o),'active')
        self.assertIn(p,self.h.api.positions);self.assertIn(a,self.h.api.algos)
        self.assertFalse(any(b.get('instId')==p['instId'] for path,b in l.posts if isinstance(b,dict)))
    def test_tick_continues_existing_management_while_entries_paused(self):
        l,o=self.setup();l.reduce(o);self.h.e.user_paused=True;self.h.e.enabled=False
        # The real management loop still runs; unrelated background work is isolated.
        e=self.h.e
        with patch.object(e,'refresh_day'),patch.object(e,'latch_day',return_value=False),patch.object(e,'settle'),patch.object(e,'publish_portfolio'),patch('okx_channel701.management') as manage:
            for _ in range(3):e.tick()
            self.assertEqual(o['phase'],'active');self.assertTrue(manage.called)
            self.assertEqual(manage.call_args.args[3]['client_id'],o['client_id'])
            self.assertEqual(dec(manage.call_args.args[2]['pos']),dec(o['quantity']))
    def test_manual_reduction_does_not_invent_profit_target_or_widen_existing_floor(self):
        from okx_profit_guard714 import observe, effective_stop
        for key in ('trend_pullback_LONG','trend_pullback_SHORT'):
            with self.subTest(rule=key):
                l,o=self.setup(key);p=l.reduce(o);old=dec(o['stop_px'])
                self.assertEqual(l.drive(o),'active')
                observe(self.h.e,self.h.e.snapshot(),p,o)
                self.assertEqual(dec(str(effective_stop(o))),old)
                self.assertFalse(o['profit_state714'].get('partial_latched'))
                # The original +20% observed-profit latch still enables its floor.
                sign=1 if o['direction']=='long' else -1
                p['markPx']=str(dec(p['avgPx'])*(1+sign*dec('.25')/dec(o['leverage'])))
                observe(self.h.e,self.h.e.snapshot(),p,o)
                floor=effective_stop(o)
                self.assertTrue(o['profit_state714']['partial_latched'])
                self.assertGreater((floor-float(p['avgPx']))*sign,0)
                l.reduce(o);self.assertEqual(l.drive(o),'active')
                self.assertGreaterEqual((effective_stop(o)-floor)*sign,-1e-12)
                self.h.close();self.h=None
    def test_no_duplicate_automatic_half_after_manual_reduction(self):
        l,o=self.setup();p=l.reduce(o);l.drive(o);before=len(self.h.api.calls)
        self.h.e.partial_close(self.h.e.snapshot(),'automatic half')
        self.assertFalse(any(path=='post /api/v5/trade/order' for path,b in self.h.api.calls[before:]))
    def test_full_close_retains_two_observation_confirmation(self):
        l,o=self.setup();p=l.reduce(o,'1')
        self.assertIsNone(self.h.e.reconcile(self.h.e.snapshot()))
        self.assertIs(self.h.e.journal.data['owned'],o)
        self.h.api.now+=1001
        self.h.e.reconcile(self.h.e.snapshot())
        self.assertIsNone(self.h.e.journal.data['owned'])
    def test_reopen_same_posid_and_average_is_not_adopted(self):
        l,o=self.setup();original=copy.deepcopy(o);p=l.reduce(o,'1')
        self.h.api.now+=1;l.append(o,dec(o['quantity'])/2,True,client='different-opening')
        p['pos']=str(dec(o['quantity'])/2)
        self.h.e.snapshot()
        self.assertEqual(o,original)
        self.assertIn(o['client_id'],self.h.e._manual_reduction_errors167)
        self.assertEqual(l.posts,[])
    def test_increased_quantity_and_other_position_id_not_adopted(self):
        l,o=self.setup();original=copy.deepcopy(o);p=self.h.api.positions[0]
        p['pos']=str(dec(p['pos'])*2)
        with self.assertRaises(BotError):self.h.e.snapshot()
        self.assertEqual(o,original)
        p['pos']=str(dec(o['quantity'])/2);p['posId']='different'
        self.h.e.snapshot();self.assertEqual(o,original);self.assertEqual(l.posts,[])
    def test_missing_history_waits_without_fabricated_quantity(self):
        l,o=self.setup();old=copy.deepcopy(o);l.reduce(o);l.fail_history=True
        self.h.e.snapshot();self.assertEqual(o,old)
        with self.assertRaisesRegex(BotError,'잔량 대조'):self.h.e.entry({})
        self.assertEqual(l.posts,[])
        l.fail_history=False;self.h.e._external_reduction_waits167={}
        self.assertEqual(l.drive(o),'active')
    def test_duplicate_fill_rows_count_once(self):
        l,o=self.setup();l.reduce(o);l.duplicate=True
        self.assertEqual(l.drive(o),'active')
    def test_unchanged_quantity_does_not_fetch_fill_history(self):
        l,o=self.setup();self.h.api.calls.clear()
        for _ in range(5):self.h.e.snapshot()
        self.assertFalse(any('fills-history' in path for path,b in self.h.api.calls))
    def test_manual_reduction_racing_bot_partial_terminal_fill(self):
        l,o=self.setup();q=dec(o['quantity']);cid='OP_TEST'
        o.update(phase='partial_closing',partial=dict(client_id=cid,before=str(q),quantity=str(q/2),started_ms=self.h.api.now))
        self.h.api.orders[cid]=dict(state='filled',accFillSz=str(q/2),avgPx=o['fill_px'])
        l.reduce(o,'.5',client=cid);l.reduce(o,'.5')
        self.assertEqual(l.drive(o),'active');self.assertEqual(dec(o['quantity']),q/4)
    def test_update_preflight_is_readonly_accepts_covered_proven_reduction(self):
        l,o=self.setup();l.reduce(o);journal=copy.deepcopy(self.h.e.journal.data)
        snap=self.h.api.snapshot();algos=self.h.api.pending_algos(True)
        with self.assertRaises(ValueError):phone_handover.validate_protected(journal,snap,algos)
        proofs=m.reduction_proofs(self.h.api,journal,snap)
        self.assertTrue(phone_handover.validate_protected(journal,snap,algos,proofs))
        self.assertEqual(journal,self.h.e.journal.data);self.assertEqual(l.posts,[])
        algos[0]['sz']=str(dec(snap['positions'][0]['pos'])/2)
        with self.assertRaises(ValueError):phone_handover.validate_protected(journal,snap,algos,proofs)
    def test_four_slots_reconcile_and_one_pending_does_not_block_other_slots(self):
        l,o=self.setup();base=copy.deepcopy(o);basep=copy.deepcopy(self.h.api.positions[0]);basea=copy.deepcopy(self.h.api.algos[0])
        others=[]
        for i in range(1,4):
            r=copy.deepcopy(base);r.update(symbol=f'FIX{i}-USDT-SWAP',client_id='entry'+str(i),posId='pos'+str(i),algo_client_id='stop'+str(i))
            r.pop('legs',None)
            p=copy.deepcopy(basep);p.update(instId=r['symbol'],posId=r['posId'])
            a=copy.deepcopy(basea);a.update(instId=r['symbol'],algoClOrdId=r['algo_client_id'],algoId='algo'+str(i))
            self.h.api.positions.append(p);self.h.api.algos.append(a);l.append(r,r['quantity'],True);others.append(r)
        self.h.e.journal.data.update(extra_owned=others[0],additional_owned=others[1:]);self.h.e.journal.save()
        for r in [o]+others:l.reduce(r)
        # Keep one slot unproved, while all three other records acquire protection.
        missing=[x for x in l.rows if x['instId']==o['symbol'] and x['side']=='sell']
        l.rows=[x for x in l.rows if x not in missing]
        self.h.e.snapshot()
        self.assertIn(o['client_id'],self.h.e._manual_reduction_errors167)
        for slot,r in enumerate(others,1):
            with self.h.e.selected(slot):
                self.assertEqual(l.drive(r),'active')
                self.assertTrue(r['protection_verified'])
        self.assertEqual(dec(o['quantity']),dec(base['quantity']))


if __name__=='__main__':unittest.main(verbosity=2)
