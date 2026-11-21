"""No-network end-to-end regressions for PC 2.8.0. Exchange writes are recorded in memory."""
import copy
from pathlib import Path
from queue import Queue
import sys
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace as NS
import time
import unittest
from unittest.mock import Mock, patch

P=(Path.cwd()/'OKX_PC_PACKAGE').resolve()
sys.path[:0]=[str(P),str(P/'runtime'),str(P/'core')]
from okx_core import BotError, Rejected, UnknownOutcome, dec
from okx_engine import day_key
from okx_v5 import RuleEngine
from okx_notify import Notifier
from pc_sizing import configure
from pc_wick_alert import STEP
from pc_wick_entries import WickEntries
from pc_wick_feed import PublicWickFeed, SymbolWatch, CANDLE, TRADES
from test_wick_alert import candles, raw, SYMBOL


class Exchange:
    def __init__(self):
        self.now=candles()[-1][0]+STEP+100
        self.bid=96.57
        self.ask=96.58
        self.writes=[]
        self.error=None
        self.before_book=None
        self.manual_bars=None

    def now_ms(self):
        return self.now

    def public(self,path,**arg):
        if path.endswith('/instruments'):
            sym=arg['instId']
            return [dict(instId=sym,instCategory='1',ctValCcy=sym.split('-')[0],state='live',settleCcy='USDT',
                         ctType='linear',lever='20',tickSz='.01',lotSz='.001',ctVal='1',minSz='.001',maxMktSz='100000')]
        if path.endswith('/ticker'):
            return [dict(bidPx=str(self.bid),askPx=str(self.ask),last=str(self.bid),ts=str(self.now))]
        if path.endswith('/candles'):
            return [raw(row) for row in reversed(self.manual_bars or candles())]
        if path.endswith('/books'):
            if self.before_book:
                self.before_book()
            return [dict(bids=[[str(self.bid),'50000']],asks=[[str(self.ask),'50000']],ts=str(self.now))]
        raise AssertionError(path)

    def get(self,path,**arg):
        if path.endswith('/max-size'):
            return [dict(maxBuy='100000',maxSell='100000')]
        if path.endswith('/leverage-info'):
            return [dict(self.writes[-1][1])]
        raise AssertionError(path)

    def post(self,path,body):
        if path not in ('/api/v5/account/set-leverage','/api/v5/trade/order'):
            raise AssertionError(path)
        self.writes.append((path,copy.deepcopy(body)))
        if path.endswith('/order') and self.error:
            raise self.error
        return [{'ordId':'MOCK'}]

    def taker_fee(self,i):
        return dec('.0005')

    def orders(self):
        return [v for path,v in self.writes if path.endswith('/order')]


class OfflineEngine(RuleEngine):
    def __init__(self):
        self.api=Exchange()
        self.cfg=dict(risk=dict(max_position_loss_fraction=.005,max_open_stop_loss_fraction=.02,
                                admission732={'enabled':True},profit_review_roe=.2),
                      liquidity={'max_book_age_ms':3000},selection={},indicators={'bb_period':20,'bb_multiplier':2,'ma_periods':[20,50]},
                      execution={'pattern15_only':True,'rule_channel701':True,'manual_coexist':True},
                      signals={'band_flow':{'enabled':True}})
        configure(self.cfg)
        self.durable={}
        self.journal=NS(data=dict(owned=None,extra_owned=None,additional_owned=[None],seen_signals={},
            day=dict(date=day_key(self.api.now),ended=False),api_total_spent=0),save=self.save)
        self.enabled=True
        self.recovering=self.preview=self.user_paused=False
        self.epoch=0
        self.stop_event=Event()
        self.entry_cancel=Event()
        self.command_wake=Event()
        self.queued_risks=set()
        self.quote_ready=True
        self.stream=NS(connected=True,ready=lambda *a:self.quote_ready,read=lambda *a:None,watch=Mock())
        self.account_stream=NS(fresh=lambda:True)
        self.raw_snapshot=dict(ms=self.api.now,equity=dec(150),available=dec(150),positions=[],orders=[],
                               manual_positions=[],manual_orders=[],config={'perm':'trade'})
        self.notifier=Mock()
        self.notifier.enabled=True
        self.notifier.data={}
        self.notify=self.pipeline=self.log=Mock()
        self.slot=0
        self.empty_runtime={k:None for k in self.SLOT_FIELDS}
        self.slot_runtime=[self.empty_runtime.copy() for _ in range(3)]
        for k in self.SLOT_FIELDS:
            setattr(self,k,None)
        self.wick_entries=WickEntries(self)
        self.feed=PublicWickFeed(None,self.notifier,self.cfg,self.api.now_ms,self.wick_entries)

    def save(self):
        self.durable=copy.deepcopy(self.journal.data)

    def snapshot(self):
        return dict(self.raw_snapshot)

    def risk_snapshot(self,s):
        if self.entry_cancel.is_set():
            raise BotError('중지')

    def within_session(self):
        return True

    def algos(self,full=False):
        return [],[]

    def is_allowed_instrument(self,i):
        return True

    def signal(self,side=1,symbol=SYMBOL):
        rows=candles(side)
        start=rows[-1][0]+STEP
        state=self.feed.markets[symbol]=SymbolWatch('.01')
        assert state.seed([raw(r) for r in rows],self.api.now)
        self.feed.message({'event':'subscribe','arg':dict(channel=TRADES,instId=symbol)},start-1)
        for i,p in enumerate((96.74,96.56,96.57)):
            price=p if side==1 else 200-p
            self.feed.message(dict(arg=dict(instId=symbol,channel=TRADES),
                 data=[dict(instId=symbol,ts=str(start+i),tradeId=str(i+1),px=str(price))]),self.api.now)
        if side==-1:
            self.api.bid,self.api.ask=103.42,103.43

    def status(self):
        return ' '.join(str(c.args[0]) for c in self.notifier.wick_result.call_args_list)


class LiveWicks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import phone_trend_slot
        phone_trend_slot.install(P/'core')

    def test_reaction_to_protected_market_order_both_directions(self):
        from phone_position_details import describe
        from pc_held_positions import manage
        for side in (1,-1):
            with self.subTest(side=side):
                e=OfflineEngine()
                e.signal(side)
                e.notifier.wick_alert.assert_called_once()
                self.assertIn('자동 주문 조건 확인 중',e.notifier.wick_alert.call_args.args[-1])
                self.assertFalse(e.api.writes)
                self.assertTrue(e.wick_entries.poll(),e.status())
                self.assertEqual(len(e.api.orders()),1)
                order=e.api.orders()[0]
                held=e.records()[0]
                s=held['v4_signal']
                self.assertEqual((order['ordType'],order['posSide'],order['tdMode']),
                                 ('market','long' if side==1 else 'short','isolated'))
                self.assertEqual(held['initial_margin_target'],'49')
                self.assertIn(s['leverage'],(3,4,5))
                self.assertFalse(s.get('click716'))
                self.assertFalse(s.get('monthly208'))
                self.assertEqual(s['decision_record']['volume_wick_proof']['trade_id'],3)
                stop=float(order['attachAlgoOrds'][0]['slTriggerPx'])
                anchor=s['decision_record']['volume_wick_proof']['first_wick']
                self.assertGreaterEqual((anchor-stop)*side+1e-10,max(.02,.15*s['atr']))
                self.assertAlmostEqual(stop,s['stop'])
                self.assertIn('자동 주문 접수',e.status())
                desc=describe(held)
                self.assertIn('자동',desc['summary'])
                self.assertIn('두 번째 꼬리',[row['label'] for row in desc['evidence']])
                e.trail=Mock()
                avg=s['entry_reference']
                risk=(avg-stop)*side
                p={'avgPx':avg,'markPx':avg+2.2*risk*side}
                self.assertTrue(manage(e,{},p,held))
                self.assertAlmostEqual(e.trail.call_args.args[-1],avg+1.2*risk*side)
                self.assertIsNone(e.executing_signal)
                self.assertFalse(e.wick_entries.quote_symbols())

    def test_stopped_or_full_still_alert_and_no_old_trade_after_resume(self):
        for mode in ('off','mobile_pause','preview','recovering','update','full','external_pending'):
            with self.subTest(mode=mode):
                e=OfflineEngine()
                if mode=='off':e.enabled=False
                if mode=='mobile_pause':e.mobile_entry_pause=True
                if mode=='preview':e.preview=True
                if mode=='recovering':e.recovering=True
                if mode=='update':e.pc_updater=NS(installing=True)
                if mode=='full':
                    e.raw_snapshot['manual_positions']=[dict(instId=str(n),posSide='long',pos='1') for n in range(3)]
                if mode=='external_pending':
                    e.raw_snapshot['manual_orders']=[dict(instId=SYMBOL,side='sell',posSide='short')]
                e.signal()
                e.enabled=True
                e.mobile_entry_pause=e.preview=e.recovering=False
                e.pc_updater=NS(installing=False)
                e.wick_entries.poll()
                e.notifier.wick_alert.assert_called_once()
                self.assertIn('자동 미진입',e.notifier.wick_alert.call_args.args[-1]+e.status())
                self.assertFalse(e.api.writes)
                self.assertIn('pc_wick280_seen',e.durable)

    def test_reconnect_expiry_crossed_second_or_price_chase(self):
        for side in (1,-1):
            for mode in ('disconnect','retest_broken','expired','jump','risk','manual_first'):
                with self.subTest(side=side,mode=mode):
                    e=OfflineEngine()
                    e.quote_ready=False
                    e.signal(side)
                    e.wick_entries.poll()
                    self.assertEqual(e.wick_entries.quote_symbols(),{SYMBOL})
                    if mode=='expired':e.api.now+=16000
                    if mode=='disconnect':e.wick_entries.invalidate()
                    if mode=='retest_broken':
                        e.feed.message(dict(arg=dict(instId=SYMBOL,channel=TRADES),data=[dict(
                            ts=e.api.now,tradeId=9,px=96.55 if side==1 else 103.45)]),e.api.now)
                    if mode=='jump':e.api.bid+=2;e.api.ask+=2
                    if mode=='risk':e.cfg['risk']['max_position_loss_fraction']=.00001
                    if mode=='manual_first':
                        e.raw_snapshot['manual_positions']=[dict(instId=SYMBOL,posSide='long',pos='.1')]
                    e.quote_ready=True
                    e.wick_entries.poll()
                    self.assertFalse(e.api.orders())
                    self.assertIn('자동 미진입',e.status())
                    self.assertFalse(e.wick_entries.quote_symbols())

    def test_repeated_feed_after_restart_and_uncertain_submission(self):
        for error in (None,Rejected('거래소 거절'),UnknownOutcome('응답 없음')):
            with self.subTest(error=error):
                e=OfflineEngine()
                e.api.error=error
                e.signal()
                if isinstance(error,UnknownOutcome):
                    with self.assertRaises(UnknownOutcome):e.wick_entries.poll()
                    self.assertIn('결과 미확인',e.status())
                    self.assertEqual(e.durable['owned']['phase'],'submitted')
                else:
                    e.wick_entries.poll()
                e.signal()
                e.wick_entries.poll()
                self.assertEqual(len(e.api.orders()),1)
                e.journal.data=copy.deepcopy(e.durable)
                e.wick_entries=WickEntries(e)
                e.feed.entries=e.wick_entries
                e.signal()
                e.wick_entries.poll()
                self.assertEqual(len(e.api.orders()),1)
                self.assertEqual(e.notifier.wick_alert.call_count,1)

    def test_persist_before_any_write_and_revalidate_before_order(self):
        e=OfflineEngine()
        e.signal()
        with patch.object(e.journal,'save',side_effect=OSError('test disk')):
            with self.assertRaises(OSError):e.wick_entries.poll()
        self.assertFalse(e.api.writes)
        e.api.before_book=lambda:e.wick_entries.invalidate()
        e.wick_entries.poll()
        self.assertFalse(e.api.orders())
        self.assertIn('자동 미진입',e.status())

    def test_three_slots_and_next_distinct_signal_after_manual_entry(self):
        e=OfflineEngine()
        for symbol in ('ALPHA-USDT-SWAP','BETA-USDT-SWAP','GAMMA-USDT-SWAP','DELTA-USDT-SWAP'):
            e.signal(symbol=symbol)
            e.wick_entries.poll()
        self.assertEqual(len(e.api.orders()),3,e.status())
        self.assertEqual(e.notifier.wick_alert.call_count,4)
        self.assertIn('포지션 한도',e.status())
        self.assertEqual({o['instId'] for o in e.api.orders()},{'ALPHA-USDT-SWAP','BETA-USDT-SWAP','GAMMA-USDT-SWAP'})

    def test_manual_button_and_auto_share_the_same_slots(self):
        from okx_click716 import accept
        e=OfflineEngine()
        e.events=Queue()
        e.chat=NS(watch=lambda:[])
        e.signal()
        e.api.manual_bars=[(r[0],96.57,96.60,96.54,96.57,100) for r in candles()]
        accept(e,dict(issued_at=time.monotonic(),op='entry',request_id='TEST-manual-01',
                      symbol=SYMBOL,direction='LONG'))
        self.assertEqual(len(e.api.orders()),1)
        self.assertTrue(e.records()[0]['v4_signal']['click716'])
        self.assertEqual(e.records()[0]['leverage'],5)
        e.wick_entries.poll()
        self.assertEqual(len(e.api.orders()),1)
        self.assertIn('같은 종목',e.status())
        e.signal(symbol='ALT-USDT-SWAP')
        self.assertTrue(e.wick_entries.poll(),e.status())
        self.assertEqual(len(e.api.orders()),2)
        self.assertTrue(e.records()[1]['v4_signal']['pc_wick280'])

    def test_real_engine_tick_consumes_feed_after_protection(self):
        e=OfflineEngine()
        e.signal()
        e.refresh_day=Mock()
        e.latch_day=lambda snap:False
        e.cfg['execution']['recovery_snapshots']=2
        e.stream.generation=e.account_stream.generation=1
        e.connection_key=(1,1)
        e.risk_queue=Queue()
        e.good_snapshots=3
        e.chat=NS(watch=lambda:[],poll_selected=Mock())
        e.settle=Mock()
        e.publish_portfolio=Mock()
        with patch('okx_search_capacity.sync'),patch('okx_continuity732.resume_if_ready'):
            e.tick()
        self.assertEqual(len(e.api.orders()),1,e.status())
        e.settle.assert_called_once()
        e.publish_portfolio.assert_called_once()

    def test_signal_and_separate_order_status_survive_outbox_restart(self):
        cfg={'notifications':{'enabled':True,'repeat_wait_seconds':1}}
        credentials={'TELEGRAM_BOT_TOKEN':'offline','TELEGRAM_CHAT_ID':'offline'}
        with TemporaryDirectory() as root:
            e=OfflineEngine()
            e.notifier=Notifier(root,credentials,cfg)
            e.signal(-1)
            e.wick_entries.poll()
            reopened=Notifier(root,credentials,cfg)
            msgs=[m['text'] for m in reopened.data['pending']]
            self.assertEqual(len(msgs),2)
            self.assertIn('두 꼬리 숏 신호',msgs[0])
            self.assertIn('자동 주문 조건 확인 중',msgs[0])
            self.assertIn('자동 주문 접수',msgs[1])
            self.assertNotIn('체결 완료',msgs[1])

    def test_untrusted_direct_signal_is_rejected(self):
        e=OfflineEngine()
        for s in (dict(pc_wick280=True),dict(monthly208='two_wick',pc_wick280=True),
                  dict(pc_wick280=True,click716=True,signal_id='x')):
            e.click_authorized_signal716='x'
            with self.assertRaises(BotError):e.entry(s)
        self.assertFalse(e.api.writes)

    def test_order_continues_if_notification_delivery_is_unavailable(self):
        e=OfflineEngine()
        e.notifier.enabled=False
        e.notifier.wick_alert.side_effect=OSError('offline test')
        with self.assertLogs(level='ERROR'):
            e.signal()
        self.assertTrue(e.wick_entries.poll())
        self.assertEqual(len(e.api.orders()),1)


if __name__=='__main__':
    unittest.main()
