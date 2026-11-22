"""Exercise the PC two-wick liquidity and timing changes with offline exchange data."""
from queue import Queue
from tempfile import TemporaryDirectory
import unittest

from test_pc280 import OfflineEngine, P, SYMBOL, STEP, candles, raw
from test_pc291 import CFG, SETTINGS
from okx_core import BotError, dec
from okx_notify import Notifier, WICK_EVENT, WICK_RESULT
from okx_v5 import RuleEngine
from pc_wick_entries import TTL_MS, Reaction
from pc_wick_feed import CANDLE, TRADES, SymbolWatch
import okx_risk732 as risk


def print_trade(e, timestamp, trade_id, px):
    e.feed.message(dict(arg=dict(channel=TRADES,instId=SYMBOL),
                        data=[dict(ts=timestamp,tradeId=trade_id,px=px)]),e.api.now)


def jumped(e, side=1, offset=0):
    rows = candles(side)
    start = rows[-1][0]+STEP
    t = start+offset
    state = e.feed.markets[SYMBOL] = SymbolWatch('.01')
    assert state.seed([raw(r) for r in rows],t)
    e.feed.message(dict(event='subscribe',arg=dict(channel=TRADES,instId=SYMBOL)),start-1)
    e.api.now = t+100
    for i,p in enumerate((96.74,96.51,96.55)):
        print_trade(e,t+i,i+1,p if side==1 else 200-p)
    return t


class WickTimingAndLiquidity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from phone_trend_slot import install
        import phone_entry_feed
        install(P/'core')
        phone_entry_feed.install()

    def test_exact_caps_are_inclusive_and_scoped(self):
        new_route = {'pc_wick280':True}
        risk.check_liquidity(dict(spread='.0008',slippage='.0007'),new_route)
        risk.check_liquidity(dict(spread='.0008',slippage='.05'),new_route)
        for spread, slippage, route in (('.000801','0',new_route),
                                       ('.000501','0',{}),('0','.000501',None)):
            with self.subTest(spread=spread,slippage=slippage,route=route):
                with self.assertRaises(BotError) as ctx:
                    risk.check_liquidity(dict(spread=spread,slippage=slippage),route)
                detail = ctx.exception.phone_admission_detail
                self.assertEqual(dec(detail['spread_limit_pct']),dec('.08' if route else '.05'))
                self.assertEqual(detail['slippage_limit_pct'],None if route else str(dec('.0005')*100))

    def test_real_orderbook_pass_and_fresh_pre_submit_rejection(self):
        for mode in ('pass','spread','slippage','risk'):
            with self.subTest(mode=mode):
                e = OfflineEngine()
                e.signal()
                # Best and average execution prices both stay inside the signal window.
                # Most of this ~1.5 contract order is one book level behind the touch.
                e.api.bid,e.api.ask = 96.49,96.56
                raw_public = e.api.public
                books = []
                def public(path,**kwargs):
                    result = raw_public(path,**kwargs)
                    if path.endswith('/books'):
                        book = result[0]
                        book['asks'] = [['96.56','.02'],['96.62','500']]
                        if books and mode=='spread':
                            book['bids'] = [['96.45','500']]
                        if mode=='slippage':
                            book['asks'][1][0] = '96.64'
                        books.append(book)
                    return result
                e.api.public = public
                if mode=='risk':
                    e.cfg['risk']['max_position_loss_fraction'] = .0001
                e.wick_entries.poll()
                if mode in ('pass','slippage'):
                    self.assertEqual(len(e.api.orders()),1,e.status())
                    owned = e.records()[0]
                    liq = owned['entry_liquidity']
                    self.assertGreater(liq['spread'],.0005)
                    self.assertGreater(liq['slippage'],.0007 if mode=='slippage' else .0005)
                    self.assertAlmostEqual(float(owned['cost_rate']),.002,places=9)
                    self.assertLessEqual(dec(owned['estimated_loss']),dec(owned['original_risk_budget']))
                else:
                    self.assertFalse(e.api.orders(),e.status())
                    self.assertIn('위험 한도' if mode=='risk' else '호가 한도',e.status())
                if mode!='risk':
                    self.assertEqual(len(books),2)

    def test_jump_boundary_is_strict_and_mirrored(self):
        for side in (1,-1):
            for gap,jump,wait in ((1,2,False),(1,3,True),(4,4,False),(4,5,True)):
                hit = dict(side=side,anchor_ms=0,ts=STEP,trade_id=3,first=100,
                           second=100+side*gap*.01,price=100+side*(gap+jump)*.01)
                self.assertEqual(Reaction(SYMBOL,hit,'.01',(),'').wait_retest,wait)

    def test_both_directions_wait_then_order_once_and_freeze_two_photos(self):
        for side in (1,-1):
            with self.subTest(side=side), TemporaryDirectory() as folder:
                e = OfflineEngine()
                e.feed.notifier = e.notifier = Notifier(folder,SETTINGS,CFG)
                e.notify = RuleEngine.notify.__get__(e)
                e.settings, e.events = {}, Queue()
                t = jumped(e,side)
                self.assertIn('재반응 대기',e.notifier.data['pending'][0]['text'])
                e.wick_entries.poll()
                self.assertFalse(e.api.writes)
                prices = (96.52,96.53) if side==1 else (103.48,103.47)
                # Distinct exchange trades may carry the same millisecond timestamp.
                for idx,px in enumerate(prices):
                    print_trade(e,t+99,idx+4,px)
                    if idx==0:
                        e.wick_entries.poll()
                        self.assertFalse(e.api.writes)
                e.api.bid,e.api.ask = (96.52,96.53) if side==1 else (103.47,103.48)
                self.assertTrue(e.wick_entries.poll(),e.notifier.data['pending'][-1]['text'])
                e.wick_entries.poll()
                self.assertEqual(len(e.api.orders()),1)
                owned = e.durable['owned']
                signal = owned['v4_signal']
                proof = signal['decision_record']['volume_wick_proof']
                self.assertEqual((proof['trade_id'],proof['first_reaction_ms'],signal['valid_from_ms'],
                                  signal['expires_ms']),(5,t+2,t+99,t+2+TTL_MS))
                self.assertTrue(proof['retest_confirmed'])
                e.notify('진입 체결','체결가 확인',state='offline',chart=owned['wick_chart'])
                outbox = Notifier(folder,SETTINGS,CFG).data['pending']
                self.assertEqual([row['event'] for row in outbox],[WICK_EVENT,WICK_RESULT,'진입 체결'])
                charts = [row['chart'] for row in outbox]
                self.assertEqual([c['ts'] for c in charts],[t+2,t+99,t+99])
                self.assertEqual([round(c['price'],2) for c in charts],[96.55 if side==1 else 103.45,*[prices[1]]*2])
                self.assertTrue(all(c['live'][-1]==c['price'] for c in charts))

    def test_only_ordered_trades_can_confirm_and_only_within_original_window(self):
        for fail in ('expire','duplicate','stale','candle_only','break','disconnect',
                     'late_order','new_candle','worse_ask','overflow'):
            with self.subTest(fail=fail):
                e = OfflineEngine()
                t = jumped(e,offset=STEP-400 if fail=='new_candle' else 0)
                if fail=='stale':
                    e.api.now = t+7000
                if fail=='candle_only':
                    bar = (t//STEP*STEP,96.74,96.80,96.51,96.52,200)
                    e.feed.message(dict(arg=dict(channel=CANDLE,instId=SYMBOL),data=[raw(bar,False)]),e.api.now)
                if fail not in ('candle_only','expire'):
                    print_trade(e,t+90,4,96.52)
                if fail=='break':
                    print_trade(e,t+91,5,96.50)
                if fail=='disconnect':
                    e.feed.message(dict(event='unsubscribe',arg=dict(channel=TRADES,instId=SYMBOL)),e.api.now)
                print_trade(e,t+99,4 if fail=='duplicate' else 6,
                            96.54 if fail=='overflow' else 96.53)
                e.api.bid,e.api.ask = (96.52,96.54 if fail=='worse_ask' else 96.53)
                if fail in ('late_order','new_candle'):
                    e.api.now = t+(405 if fail=='new_candle' else TTL_MS+3)
                e.wick_entries.poll()
                self.assertFalse(e.api.orders(),e.status())
                if e.wick_entries.pending:
                    e.api.now = t+TTL_MS+10
                    e.wick_entries.poll()
                self.assertIn('자동 미진입',e.status())
                self.assertFalse(e.wick_entries.pending)
                e.notifier.wick_alert.assert_called_once()
                e.notifier.wick_result.assert_called_once()


if __name__=='__main__':
    unittest.main()
