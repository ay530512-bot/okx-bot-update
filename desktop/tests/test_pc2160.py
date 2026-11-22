import unittest
from test_pc280 import OfflineEngine,P,SYMBOL
from pc_wick_feed import SymbolWatch,FIVE_CHANNEL,TRADES
from pc_fast_setup import fast_setup
from pc_flow_watch import FIVE
from pc_symbol_flow import assess_market

def fixture(ts,side):
    rows=[]
    for i in range(180):
        op=82+i*.10; close=op+.10
        rows.append((ts+(i-180)*FIVE,op,close+.025,op-.025,close,100.))
    base=rows[-6][1]
    for i,(op,h,lo,c,v) in enumerate([(0,.14,-.02,.11,130),(.10,.16,-.05,.07,150),(.06,.25,.02,.22,210),(.23,.36,.05,.32,230),(.28,.32,.01,.07,250),(.05,.24,-.04,.18,270)]):
        rows[-6+i]=(rows[-6+i][0],base+op,base+h,base+lo,base+c,v)
    return rows if side==1 else [(t,200-o,200-l,200-h,200-c,v) for t,o,h,l,c,v in rows]

def msg(e,ch,data,now):e.feed.message(dict(arg=dict(instId=SYMBOL,channel=ch),data=data),now)
class FastRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from phone_trend_slot import install
        install(P/'core')

    def test_native_five_minute_to_protected_order(self):
        for side in (1,-1):
            for selected in (False,True):
                with self.subTest(side=side,selected=selected):
                    e=OfflineEngine();t=e.api.now//900000*900000+(FIVE if side==1 else 2*FIVE)
                    rows=fixture(t,side);hit=fast_setup(rows,.01);self.assertIsNotNone(hit)
                    flow=assess_market([],rows,None,t,side)
                    self.assertEqual((flow['pace'],flow['side']),('fast',side),flow)
                    s=e.feed.markets[SYMBOL]=SymbolWatch('.01');self.assertFalse(s.ready)
                    self.assertTrue(s.flow.seed(rows[:-1],t-FIVE+10));s.ack_at=t-60000
                    if selected:e.wick_entries.set_mode('symbol_flow')
                    last=rows[-1];msg(e,FIVE_CHANNEL,[[*last,0,0,'1']],t+100)
                    self.assertTrue(s.flow.pending)
                    price=last[4];e.api.now=t+250;e.api.bid=price-.01 if side==1 else price;e.api.ask=e.api.bid+.01
                    msg(e,TRADES,[dict(ts=t+200,tradeId=91,px=price)],e.api.now)
                    self.assertFalse(s.flow.pending)
                    if not selected:
                        self.assertFalse(e.wick_entries.pending);self.assertFalse(e.api.orders());self.assertIn('5분 우선',e.status());continue
                    self.assertEqual(len(e.wick_entries.pending),1,e.status())
                    self.assertTrue(e.wick_entries.poll(),e.status());self.assertEqual(len(e.api.orders()),1)
                    sig=e.durable['owned']['v4_signal'];self.assertEqual(sig['execution_frame'],'5m')
                    self.assertLess((sig['stop']-hit['first'])*side,0)
                    self.assertEqual(e.durable['owned']['wick_chart']['step_ms'],FIVE);self.assertEqual(sig['expires_ms'],t+15000)
                    self.assertEqual(sig['decision_record']['volume_wick_proof']['symbol_flow']['side'],side)
