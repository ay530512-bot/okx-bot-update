"""Closed-candle context, authenticated settings and trade-level confirmation."""
from queue import Queue
from types import SimpleNamespace
from urllib.parse import urlsplit
import os
import threading
import time
import unittest
from playwright.sync_api import expect, sync_playwright

from test_pc280 import OfflineEngine, P, STEP, SYMBOL, candles
from test_pc2100 import print_trade
from pc_wick_alert import HISTORY
from pc_wick_chart import caption_note, render, snapshot
from pc_wick_context import context, describe, adverse_momentum, rsi_pair, visible_spans
from pc_wick_entries import WickEntries
from phone_dashboard_live import Dashboard
from phone_host import route_control
from phone_mobile import mobile_module


def sample_values(values,side=1):
    rows=[]
    for i,c in enumerate(values):
        p=c if side==1 else 200-c
        rows.append((i*STEP,p,p+.05,p-.05,p,100))
    return rows


def reaction(rows,side=1,price=None):
    p=rows[-1][4] if price is None else price
    return dict(ts=rows[-1][0]+STEP+10,price=p,side=side,anchor_atr=1.,
                anchor_ms=rows[-1][0],first=p-.06*side,second=p-.01*side,trade_id=2,bars=1)


def pattern_points(points, length=48):
    result=[]
    for j in range(len(points)-1):
        start,p=points[j]
        end,q=points[j+1]
        result.extend(p+(q-p)*(t-start)/(end-start) for t in range(start,end))
    result.append(points[-1][1])
    assert len(result)==length
    return result


def live_context_signal(e,side=1):
    """Keep the genuine wick fixture, with a longer declining/ascending history for the cloud."""
    e.signal(side)
    template,=e.wick_entries.pending.values()
    hit,tick=template.hit,template.tick
    e.wick_entries=WickEntries(e)
    e.feed.entries=e.wick_entries
    e.notifier.reset_mock()
    rows=list(template.bars)
    # A gentle but long trend before the anchor makes the latest RSI extreme.
    earlier=[]
    for k in range(70,0,-1):
        t=rows[0][0]-k*STEP; px=100+side*(k*.03)
        earlier.append((t,px,px+.08,px-.08,px,90))
    # The supplied flat patch has a neutral last cloud; give its first 33 bars a
    # consistent slope to distinguish both lines without changing the anchor bars.
    for i,r in enumerate(rows[:33]):
        change=side*(33-i)*.012
        rows[i]=(r[0],*(p+change for p in r[1:5]),r[5])
    e.wick_entries.offer(SYMBOL,hit,tick,tuple(earlier+rows))
    return next(iter(e.wick_entries.pending.values()))


class IndicatorTiming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from phone_trend_slot import install
        install(P/'core')

    def test_visible_cloud_uses_displaced_bars_and_no_future_data(self):
        rows=sample_values([110-i*.1 for i in range(120)])
        hit=reaction(rows,price=97.5)
        raw=context(rows,hit,.01)
        orig=120-26
        def mid(n):
            cut=rows[orig+1-n:orig+1]
            return (max(b[2] for b in cut)+min(b[3] for b in cut))/2
        expected=sorted(((mid(9)+mid(26))/2,mid(52)))
        self.assertEqual([raw['cloud']['bottom'],raw['cloud']['top']],expected)
        changed=rows.copy()
        for i in range(orig+1,len(rows)):
            t,o,h,l,c,v=changed[i]
            changed[i]=(t,o,h+15,l,c,v)
        self.assertEqual(visible_spans(rows),visible_spans(changed))
        future=(120*STEP,5,90,1,2,9999)
        self.assertEqual(context(rows+[future],hit,.01),raw)
        self.assertIsNone(context(rows[-76:],hit,.01)['cloud'])
        self.assertIsNone(context(rows[:65]+rows[66:],hit,.01)['cloud'])
        self.assertEqual(rsi_pair(sample_values([100.]*91))['latest'],50.)
        self.assertIsNotNone(visible_spans(rows[-77:]))
        self.assertGreaterEqual(HISTORY,111)
        frame=snapshot(SYMBOL,hit,'.01',rows)
        self.assertEqual(frame['cloud'][-1][0],120*STEP)
        self.assertEqual(sorted(frame['cloud'][-1][1:]),expected)
        self.assertEqual(frame['market_context'],raw)
        self.assertTrue(render(frame).startswith(b'\x89PNG'))
        self.assertIn('RSI',caption_note(frame))
        old={k:v for k,v in frame.items() if k not in ('cloud','market_context')}
        self.assertTrue(render(old).startswith(b'\x89PNG'))
        self.assertNotIn('RSI',caption_note(old))

    def test_only_confirmed_neckline_and_diamond_breaks_are_identified(self):
        shapes={
            'hs':[(0,92),(13,101),(18,97),(23,104),(28,97),(34,101),(39,98.2),(43,97.5),(44,96.7),(47,96.3)],
            'diamond':[(0,94),(12,100),(16,97),(21,104),(25,94),(31,102.2),(37,96.5),
                       (41,97.5),(43,97.8),(44,100.5),(47,101.)]}
        for kind,coordinates in shapes.items():
            for side in (1,-1):
                with self.subTest(kind=kind,side=side):
                    # Prefix supplies history while preserving the right-hand structure.
                    values=[92.]*72+pattern_points(coordinates)
                    rows=sample_values(values,side)
                    h=reaction(rows,side)
                    found=context(rows,h,.01)['patterns']
                    name=('hs' if side==1 else 'inverse_hs') if kind=='hs' else kind
                    signal_side=(-side if kind=='hs' else side)
                    matches=[p for p in found if (p['kind'],p['side'])==(name,signal_side)]
                    self.assertTrue(matches,found)
                    p=matches[0]
                    self.assertLessEqual(p['confirmed_ms'],h['ts'])
                    cut=p['confirmed_ms']//STEP-1
                    before=rows[:cut]
                    self.assertFalse(any(x['kind']==name and x['side']==signal_side
                                         for x in context(before,reaction(before,side),.01)['patterns']))

    def test_indicator_mode_waits_for_ordered_prints_and_fresh_quote(self):
        for side in (1,-1):
            for mode in ('standard','fill','expire','drift','broken','duplicate'):
                with self.subTest(side=side,mode=mode):
                    e=OfflineEngine()
                    if mode!='standard':e.wick_entries.set_mode('confirm')
                    r=live_context_signal(e,side)
                    self.assertTrue(adverse_momentum(r.chart['market_context'],side))
                    self.assertEqual(r.wait_follow,mode!='standard')
                    if mode=='standard':
                        self.assertTrue(e.wick_entries.poll(),e.status())
                        continue
                    self.assertIn('추가 체결 대기',e.notifier.wick_alert.call_args.args[-1])
                    e.wick_entries.poll()
                    self.assertFalse(e.api.writes)
                    source=r.hit['ts'];ref=r.hit['price']
                    if mode=='broken':
                        print_trade(e,source+20,4,ref-.04*side)
                    if mode=='expire':
                        e.api.now=source+15020
                    else:
                        print_trade(e,source+40,3 if mode=='duplicate' else 5,ref+.01*side)
                    bid=ref+.01*side
                    e.api.bid,e.api.ask=(bid-.01,bid) if side==1 else (bid,bid+.01)
                    if mode=='drift':
                        e.api.bid+=.03*side;e.api.ask+=.03*side
                    if mode=='duplicate':
                        self.assertFalse(r.confirmation)
                        e.api.now=source+15020
                    e.wick_entries.poll()
                    self.assertEqual(len(e.api.orders()),int(mode=='fill'),e.status())
                    if mode=='fill':
                        held=e.durable['owned']
                        proof=held['v4_signal']['decision_record']['volume_wick_proof']
                        self.assertTrue(proof['follow_confirmed'])
                        self.assertFalse(proof['retest_confirmed'])
                        self.assertEqual(held['wick_chart']['ts'],source+40)
                        self.assertEqual(held['v4_signal']['expires_ms'],source+15000)
                    else:self.assertIn('자동 미진입',e.status())

    def test_mobile_mode_persists_and_only_changes_new_signals(self):
        e=OfflineEngine()
        e.events=Queue()
        r=live_context_signal(e)
        app=mobile_module(P/'core')
        mobile=app.PhoneMobile.__new__(app.PhoneMobile)
        mobile.config={'controls_enabled':True}
        mobile.hidden=[]
        mobile.lock=threading.Lock();mobile.control_commands=Queue();mobile.control_results={}
        mobile.updater=SimpleNamespace(installing=False)
        e.send=lambda action,**kw:e.handle(action,kw)
        request=mobile.enqueue_control('wick_timing','owner-a','test-wick-123456',key='confirm')
        route_control(e,mobile.control_commands.get_nowait(),mobile)
        _,reply=e.events.get_nowait()
        mobile.complete_control(reply)
        self.assertEqual(mobile.control_result(request['request_id'],'owner-a')['status'],'done')
        self.assertFalse(r.wait_follow)
        self.assertEqual(WickEntries(e).mode,'confirm')
        self.assertFalse(e.api.writes)
        e.journal.save=lambda: (_ for _ in ()).throw(OSError('disk'))
        with self.assertRaises(OSError): e.wick_entries.set_mode('standard')
        self.assertEqual(e.journal.data['wick_indicator_mode'],'confirm')
        self.assertEqual(e.wick_entries.mode,'confirm')
        with self.assertRaises(ValueError):mobile.enqueue_control('wick_timing','owner-a','test-wick-456789',key='invalid')
        mobile.snapshot={'wick_indicator_mode':'confirm'}
        self.assertEqual(Dashboard(mobile).snapshot()['wick_indicator_mode'],'confirm')

    def test_phone_switch_waits_for_server_ack_and_displays_the_new_mode(self):
        app=mobile_module(P/'core')
        now=int(time.time()*1000)
        data=dict(ui_version=app.UI_VERSION,captured_ms=now,display_ms=now,account_age_seconds=1,
                  controls_enabled=True,state=dict(account_connected=True),positions=[],movers=[],
                  activities=[],wick_indicator_mode='standard',program_update={})
        posts=[]
        def route(req):
            path=urlsplit(req.request.url).path
            name=path.removeprefix('/') or 'index.html'
            mime={'index.html':'text/html','style.css':'text/css','app.js':'text/javascript'}
            if name in mime:req.fulfill(content_type=mime[name]+'; charset=utf-8',body=app.asset(name))
            elif path in ('/api/snapshot','/api/phone/dashboard-live'):req.fulfill(json=data)
            elif path=='/api/control/wick_timing' and req.request.method=='POST':
                posts.append(req.request.post_data_json['key'])
                req.fulfill(json=dict(status='queued',request_id='local'))
            elif path=='/api/control/result':
                data['wick_indicator_mode']=posts[-1]
                req.fulfill(json=dict(status='done',message='다음 신호부터 적용'))
            else:req.fulfill(json={})
        with sync_playwright() as pw:
            kwargs={}
            if os.environ.get('PC_TEST_CHROME'):
                kwargs=dict(executable_path=os.environ['PC_TEST_CHROME'],args=['--no-sandbox','--disable-gpu','--single-process'])
            browser=pw.chromium.launch(**kwargs)
            page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True)
            page.add_init_script('window.setInterval=()=>0;window.EventSource=undefined;')
            page.route('**/*',route);page.goto('http://pc.test/')
            switch=page.get_by_role('switch',name='일목·RSI 추가 확인')
            expect(switch).to_be_enabled()
            for checked in (True,False):
                switch.click()
                expect(switch).to_have_attribute('aria-checked',str(checked).lower())
                expect(switch).to_be_enabled()
            self.assertEqual(posts,['confirm','standard'])
            browser.close()

