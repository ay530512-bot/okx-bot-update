"""Offline acceptance for the PC 2.6.1 manual two-wick Telegram signal."""
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

PACKAGE=Path(__file__).resolve().parent/'OKX_PC_PACKAGE'
if not PACKAGE.is_dir(): PACKAGE=Path.cwd()/'OKX_PC_PACKAGE'
sys.path[:0]=[str(PACKAGE/'runtime'),str(PACKAGE/'core'),str(PACKAGE)]
from pc_wick_alert import STEP,MarketWicks,alert_text
from pc_wick_feed import SymbolWatch,PublicWickFeed,CANDLE,TRADES
from okx_notify import Notifier,WICK_EVENT

BASE=1_790_000_000_000//STEP*STEP
SYMBOL='TEST-USDT-SWAP'


def candles(side=1):
    out=[]
    previous=100.
    for i in range(50):
        close=100. if i<44 else 100-(i-43)*.35
        op=100.04 if i<44 else previous
        low=close-(1.4 if i==49 else .28 if i>=44 else .15)
        row=(BASE+i*STEP,op,max(op,close)+.06,low,close,250. if i==49 else 90.)
        out.append(reflect(row) if side<0 else row)
        previous=close
    return out


def reflect(row):
    t,o,h,l,c,v=row
    return (t,200-o,200-l,200-h,200-c,v)


def raw(row,done=True):
    return [*[str(x) for x in row],'0','0','1' if done else '0']


def print_series(watch,side,start,prices):
    events=[]
    for index,price in enumerate(prices):
        events.extend(watch.trade(start+index,index+1,price if side==1 else 200-price,True))
    return events


class Pattern(unittest.TestCase):
    def test_both_sides_intrabar_once_and_precision(self):
        for side in (1,-1):
            with self.subTest(side=side):
                rows=candles(side);w=MarketWicks(.01);w.seed(rows)
                t=rows[-1][0]+STEP
                ev=print_series(w,side,t,[96.74,96.60,96.56,96.56,96.57,96.61])
                self.assertEqual(len(ev),1)
                h=ev[0]
                self.assertEqual(h['side'],side)
                self.assertEqual(h['ts'],t+4)
                self.assertEqual(h['bars'],1)
                self.assertAlmostEqual(h['first'],96.50 if side==1 else 103.50)
                self.assertAlmostEqual(h['second'],96.56 if side==1 else 103.44)
                m=alert_text(SYMBOL,h,'0.01')
                self.assertIn('수동 '+('롱' if side==1 else '숏')+' 관찰',m)
                self.assertIn('15분봉',m)
                self.assertIn('KST',m)
                self.assertIn('음봉 아랫꼬리' if side==1 else '양봉 윗꼬리',m)
                self.assertIn('96.56' if side==1 else '103.44',m)

    def test_break_equal_far_or_unobserved(self):
        for side in (1,-1):
            for prices in ([96.75,96.5,96.56,96.58],[96.75,96.49,96.56,96.58],
                           [96.75,96.68,96.71],[96.75,96.60,96.58]):
                rows=candles(side);w=MarketWicks(.01);w.seed(rows)
                self.assertFalse(print_series(w,side,rows[-1][0]+STEP,prices))
            rows=candles(side);w=MarketWicks(.01);w.seed(rows);t=rows[-1][0]+STEP
            bar=(t,96.74,96.80,96.55,96.70,10)
            w.forming(bar if side==1 else reflect(bar))
            self.assertFalse(print_series(w,side,t,[96.70,96.71]))
            w.forming((t,96.74,96.8,96.50,96.68,11) if side==1 else reflect((t,96.74,96.8,96.50,96.68,11)))
            self.assertFalse(print_series(w,side,t+3,[96.6,96.58,96.59]))

    def test_rebound_then_retest_required(self):
        w=MarketWicks(.01);rows=candles();w.seed(rows);w.long.anchor.away=False
        t=rows[-1][0]+STEP
        ev=print_series(w,1,t,[96.62,96.56,96.57,96.69,96.58,96.56,96.57])
        self.assertEqual([e['ts'] for e in ev],[t+6])

    def test_range_color_volume(self):
        for side in (1,-1):
            for mode in ('range','color','volume'):
                rows=candles()
                if mode=='range':
                    rows=[(t,100.1,100.2,99.9,100,90) for t,*_ in rows[:-1]]+[rows[-1]]
                if mode=='color':
                    t,o,h,l,c,v=rows[-1];rows[-1]=(t,c-.02,h,l,c,v)
                if mode=='volume':
                    rows[-1]=(*rows[-1][:-1],70)
                w=MarketWicks(.01);w.seed(rows if side==1 else [reflect(r) for r in rows])
                self.assertIsNone((w.long if side==1 else w.short).anchor)

    def test_30_bar_window_and_gap(self):
        for side in (1,-1):
            for number in (30,31):
                rows=candles(side);w=MarketWicks(.01);w.seed(rows);anchor=rows[-1][0]
                for k in range(1,number):
                    row=(anchor+k*STEP,96.78,96.82,96.74,96.78,70)
                    w.closed(row if side==1 else reflect(row))
                ev=print_series(w,side,anchor+number*STEP,[96.74,96.55,96.56])
                self.assertEqual(len(ev),int(number==30))
            w=MarketWicks(.01);w.seed(rows)
            w.closed((anchor+2*STEP,96.8,96.9,96.7,96.8,8))
            self.assertFalse(w.wants_trades())

    def test_missing_history_duplicate_trades_and_partial_reconnect(self):
        rows=candles();w=MarketWicks(.01);w.seed(rows);t=rows[-1][0]+STEP
        self.assertFalse(w.trade(t,20,96.74,True))
        self.assertFalse(w.trade(t+1,21,96.55,True))
        self.assertFalse(w.trade(t+2,21,96.61,True))
        self.assertFalse(w.trade(t,22,96.61,True))
        self.assertTrue(w.trade(t+3,24,96.56,True))
        w.seed(rows+[(t,96.74,96.8,96.54,96.70,20)])
        self.assertIsNone(w.long.anchor)
        w.seed(rows);w.reset_trade_feed()
        self.assertFalse(w.trade(t+100,25,96.56,False))

    def test_close_then_next_ticks_out_of_order_between_channels(self):
        for side in (1,-1):
            sent=[]
            target=types.SimpleNamespace(enabled=True,wick_alert=lambda *a:sent.append(a))
            feed=PublicWickFeed(None,target,{},now=lambda:0)
            state=feed.markets[SYMBOL]=SymbolWatch('0.01');rows=candles(side)
            t=rows[-1][0]+STEP
            self.assertTrue(state.seed([raw(r) for r in rows[:-1]],t-1))
            self.assertTrue(state.rule.wants_trades())
            def frame(channel,data,**other):
                return dict(arg=dict(channel=channel,instId=SYMBOL),data=data,**other)
            feed.message(frame(TRADES,[],event='subscribe'),t-100)
            for ix,price in enumerate([96.74,96.56,96.57]):
                px=price if side==1 else 200-price
                feed.message(frame(TRADES,[dict(instId=SYMBOL,ts=str(t+ix),tradeId=str(ix+1),px=str(px))]),t+ix)
            self.assertFalse(sent)
            feed.message(frame(CANDLE,[raw(rows[-1])]),t+6)
            self.assertEqual(len(sent),1)
            self.assertEqual(sent[0][1],side)
            self.assertEqual(sent[0][3],t+2)
            # A restart only uses a current session's fresh events.
            fresh=SymbolWatch('0.01')
            self.assertFalse(fresh.seed([raw(r) for r in rows],t+2*STEP))
            self.assertFalse(fresh.print(t,150,96.61,t+10000))

    def test_partial_subscription_needs_fresh_whole_candle(self):
        rows=candles();t=rows[-1][0]+STEP
        watch=SymbolWatch('0.01')
        self.assertTrue(watch.seed([raw(r) for r in rows],t+100))
        forming=(t,96.74,96.80,96.60,96.70,9)
        watch.ws_bar(forming,False)
        watch.ack_at=t+500
        self.assertFalse(watch.print(t+501,100,96.56,t+502))
        self.assertFalse(watch.print(t+502,101,96.57,t+502))
        broken=(t,96.74,96.80,96.48,96.60,10)
        watch.ws_bar(broken,False)
        self.assertIsNone(watch.rule.long.anchor)
        self.assertFalse(watch.print(t+504,102,96.59,t+504))

    def test_universe_has_no_trading_permission_dependency(self):
        from types import SimpleNamespace as Obj
        def instrument(name,category='1'):
            return dict(instId=name+'-USDT-SWAP',instCategory=category,ctValCcy=name,ctType='linear',state='live',settleCcy='USDT',tickSz='.001')
        values=[instrument('TEST'),instrument('BTC'),instrument('ETH'),instrument('SOL'),instrument('SHARE','3')]
        u=Obj(full_market=Obj(instruments={v['instId']:v for v in values}),lock=threading.Lock())
        n=Obj(enabled=False)
        f=PublicWickFeed(u,n,{'selection':{}})
        self.assertEqual(f.instruments(),{SYMBOL:'.001'})
        f.start()
        self.assertFalse(f.threads)

    def test_outbox_dedup_restart_and_expiration(self):
        cfg={'notifications':{'enabled':True,'repeat_wait_seconds':1}}
        settings={'TELEGRAM_BOT_TOKEN':'test-only','TELEGRAM_CHAT_ID':'test-only'}
        with tempfile.TemporaryDirectory() as folder:
            first=Notifier(folder,settings,cfg)
            stamp=int(time.time()*1000)
            first.wick_alert('A',1,stamp-STEP,stamp,'[수동 롱 관찰] A')
            first.wick_alert('B',-1,stamp-STEP,stamp,'[수동 숏 관찰] B')
            first.wick_alert('A',1,stamp-STEP,stamp,'duplicate')
            second=Notifier(folder,settings,cfg)
            second.wick_alert('A',1,stamp-STEP,stamp,'duplicate across restart')
            second.wick_alert('A',-1,stamp-STEP,stamp,'[수동 숏 관찰] A')
            self.assertEqual([p['text'] for p in second.data['pending']],['[수동 롱 관찰] A','[수동 숏 관찰] B','[수동 숏 관찰] A'])
            second.data['pending'][0]['expires']=time.time()-1
            delivered=[]
            def send(session,token,method,**args):
                delivered.append(args['text'])
                self.assertEqual(method,'sendMessage')
                second.stop_event.set()
            with patch('okx_notify.telegram',send):
                second.run()
            self.assertEqual(delivered,['[수동 숏 관찰] B'])
            self.assertEqual(len(second.data['pending']),1)
            self.assertEqual(second.data['pending'][0]['event'],WICK_EVENT)


if __name__=='__main__':
    unittest.main()
