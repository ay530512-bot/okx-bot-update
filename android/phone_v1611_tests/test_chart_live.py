import copy
import io
import json
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

D=Path(__file__).resolve().parent;HOST=D.parent/'phone_v1611';CORE=D.parents[2]/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
from phone_chart_live import LiveChart,accept
from phone_chart_feed import factory
from phone_mobile import mobile_module
from okx_stream import MarketStream

S='TEST-USDT-SWAP';T=1794852000000;STEP=300000


def mobile():
    return NS(lock=threading.RLock(),snapshot=dict(positions=[{'symbol':S}]),
        chart_cache={(S,'5m'):dict(symbol=S,frame='5m',bars=[[T-STEP,100,102,99,101,10,True],[T,101,102,100,101,5,False]],observed_ms=T+1000)},
        touched=0,feed=NS(select=Mock()),closed=threading.Event())


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.mobile=mobile();self.stream=MarketStream();self.stream.connected=True;self.stream.generation=1
        self.now=T+2000;self.live=LiveChart(self.mobile,self.stream,lambda:self.now)
    def tick(self,p,stamp=None):
        self.stream.feed(json.dumps({'arg':{'instId':S,'channel':'tickers'},'data':[{'last':str(p),'ts':str(stamp or self.now)}]}))
    def test_live_price_and_all_tick_extremes_without_rest(self):
        before=copy.deepcopy(self.mobile.chart_cache)
        self.tick(104);self.tick(98);self.tick(103)
        p=self.live.packet(S,'5m');self.assertTrue(p['live'])
        self.assertEqual(p['bars'][-1],[T,101,104,98,103,5,False])
        self.assertEqual(self.mobile.chart_cache,before)
    def test_confirmed_bar_never_changes(self):
        self.mobile.chart_cache[(S,'5m')]['bars'][-1][6]=True;self.tick(110)
        p=self.live.packet(S,'5m');self.assertEqual(p['bars'][-1][4],101)
        self.assertEqual(p['quote']['last'],110)
    def test_rollover_shows_price_without_fabricating_new_candle(self):
        self.now=T+STEP+1;self.tick(105)
        p=self.live.packet(S,'5m');self.assertEqual(p['bars'][-1][0],T)
        self.assertEqual(p['bars'][-1][4],101);self.assertEqual(p['quote']['last'],105)
    def test_older_or_newer_frame_quote_never_rewrites_wrong_candle(self):
        self.tick(105,T-1);p=self.live.packet(S,'5m');self.assertEqual(p['bars'][-1][4],101)
    def test_disconnect_generation_and_stale_quote_mark_unavailable(self):
        for mode in ('disconnect','generation','stale'):
            self.setUp();self.tick(105)
            if mode=='disconnect':self.stream.connected=False
            if mode=='generation':self.stream.generation+=1
            if mode=='stale':self.now+=3001
            p=self.live.packet(S,'5m');self.assertFalse(p['live']);self.assertIsNone(p['quote'])
            self.assertEqual(p['bars'][-1][4],101)
    def test_nonfinite_or_negative_price_not_emitted(self):
        for value in ('NaN','inf','0','-1'):
            self.tick(value);p=self.live.packet(S,'5m');self.assertFalse(p['live']);self.assertIsNone(p['quote'])
    def test_one_minute_day_week_overlay_preserves_official_open_and_volume(self):
        for frame,step in [('1m',60000),('1D',86400000),('1W',604800000)]:
            offset=345600000 if frame=='1W' else 0;start=(self.now-offset)//step*step+offset
            self.mobile.chart_cache[(S,frame)]=dict(bars=[[start,101,102,100,101,55,False]],observed_ms=self.now)
            self.tick(103);p=self.live.packet(S,frame)
            self.assertEqual(p['bars'][-1],[start,101,103,100,103,55,False])
    def test_old_generation_high_not_imported_after_reconnection(self):
        self.tick(150);self.stream.generation+=1;self.tick(103)
        self.assertEqual(self.live.packet(S,'5m')['bars'][-1][2],103)
    def test_selection_only_adds_monitor_ticker(self):
        self.live.select(S,'5m');self.assertIn(S,self.stream.monitor_symbols)
        self.assertNotIn(S,self.stream.symbols);self.mobile.feed.select.assert_called_once_with(S,'5m')
        for s,f in [('UNKNOWN','5m'),(S,'bad')]:
            with self.assertRaises(ValueError):self.live.select(s,f)
    def test_rest_failure_retains_existing_chart_without_false_freshness(self):
        before=copy.deepcopy(self.mobile.chart_cache[(S,'5m')])
        accept(self.mobile,dict(symbol=S,frame='5m',bars=[],observed_ms=T+9000,error='timeout',stale=True))
        after=self.mobile.chart_cache[(S,'5m')]
        self.assertEqual(after['bars'],before['bars']);self.assertEqual(after['observed_ms'],before['observed_ms'])
        self.assertTrue(after['stale']);self.assertEqual(after['error'],'timeout')
    def test_sse_small_packet_flushed_and_slot_released(self):
        self.tick(103);chunks=[];headers=[]
        def write(data):chunks.append(data);self.mobile.closed.set()
        h=NS(reply=Mock(),authorized=lambda:True,send_response=Mock(),send_header=lambda k,v:headers.append((k,v)),end_headers=Mock(),wfile=NS(write=write,flush=Mock()))
        self.live.serve(h,S,'5m',True)
        self.assertLess(len(chunks[0]),1000);self.assertTrue(chunks[0].startswith(b'data: '));h.wfile.flush.assert_called_once()
        self.assertIn(('X-Accel-Buffering','no'),headers)
        self.assertEqual(self.live.slots._value,4)
    def test_sse_disconnect_and_connection_limit_do_not_leak_slots(self):
        h=NS(reply=Mock(),authorized=lambda:True,send_response=Mock(),send_header=Mock(),end_headers=Mock(),wfile=NS(write=Mock(side_effect=BrokenPipeError),flush=Mock()))
        self.live.serve(h,S,'5m',True);self.assertEqual(self.live.slots._value,4)
        for _ in range(4):self.live.slots.acquire()
        self.live.serve(h,S,'5m',True);self.assertEqual(h.reply.call_args.args[0],429)
        for _ in range(4):self.live.slots.release()
    def test_expired_session_stops_stream(self):
        h=NS(reply=Mock(),authorized=lambda:False,send_response=Mock(),send_header=Mock(),end_headers=Mock(),wfile=NS(write=Mock(),flush=Mock()))
        self.live.serve(h,S,'5m',True);h.wfile.write.assert_not_called()


class Routes(unittest.TestCase):
    def test_live_route_requires_allowed_host_and_login(self):
        module=mobile_module(CORE);s=object.__new__(module.PhoneMobile)
        s.lock=threading.RLock();s.hosts={'localhost:8766'};s.sessions={'ok':time.monotonic()+30};s.live_chart=NS(serve=Mock())
        for host,cookie,want in [('wrong','mobile_session=ok',403),('localhost:8766','',401),('localhost:8766','mobile_session=ok',None)]:
            h=object.__new__(s.handler());h.path='/api/phone/chart-live?symbol='+S+'&frame=5m&stream=1'
            h.headers={'Host':host,'Cookie':cookie};h.reply=Mock();h.do_GET()
            if want:self.assertEqual(h.reply.call_args.args[0],want)
            else:s.live_chart.serve.assert_called_once_with(h,S,'5m',True)
    def test_final_mobile_asset_integrates_stream_and_canvas_without_changing_close_actions(self):
        module=mobile_module(CORE);script=module.asset('app.js').decode()
        self.assertIn('new EventSource(',script);self.assertIn('ctx.setTransform(ratio,0,0,ratio,0,0)',script)
        self.assertIn('phoneChartMarker(ctx,w,h)',script)
        self.assertIn("trade('close_one'",script)
        (D/'chart_asset.js').write_text(script)
    def test_compact_funding_and_original_trade_controls_precede_analysis_tables(self):
        from html.parser import HTMLParser
        class Tree(HTMLParser):
            def __init__(self):super().__init__();self.stack=[];self.ids={}
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if attrs.get('id'):
                    self.ids.setdefault(attrs['id'],[]).append((tuple(self.stack),attrs))
                if tag not in ('meta','link','input','br','hr'):self.stack.append(attrs.get('id') or tag)
            def handle_endtag(self,tag):
                if self.stack:self.stack.pop()
        module=mobile_module(CORE);html=module.asset('index.html').decode();tree=Tree();tree.feed(html)
        for ident in ('fundingPreview','chartTradeSymbol','chartLong','chartShort','chartTradeStatus'):
            self.assertEqual(len(tree.ids[ident]),1,ident)
            self.assertIn('phoneDirectionPanel',tree.ids[ident][0][0])
            self.assertLess(html.index('id="'+ident+'"'),html.index('id="directionAnalysis"'))
        for ident in ('chartLong','chartShort'):self.assertIn('disabled',tree.ids[ident][0][1])
        self.assertNotIn('class="direction-panel funding-panel"',html)
        self.assertIn('phone-funding-compact',html)


class FeedTests(unittest.TestCase):
    def test_limit_two_for_warm_cache_full_reload_after_gap(self):
        F=factory(CORE);f=F({},queue.Queue(),api_factory=Mock())
        key=(S,'5m');self.assertEqual(f.candle_limit(key,T),'300')
        f.cache[key]=[[T,1,1,1,1,1,False]]
        self.assertEqual(f.candle_limit(key,T+1),'2')
        self.assertEqual(f.candle_limit(key,T+STEP),'2')
        self.assertEqual(f.candle_limit(key,T+2*STEP),'300')
    def test_slow_analysis_cannot_block_new_candle_refreshes(self):
        F=factory(CORE);events=queue.Queue();entered=threading.Event();release=threading.Event();calls=[]
        class API:
            def __init__(self,settings):self.session=NS(close=lambda:None)
            def now_ms(self):return T+2000
            def public(self,path,**kw):
                name=threading.current_thread().name;calls.append((name,path,dict(kw)))
                if name=='phone-chart-analysis' and path.endswith('/candles'):
                    entered.set();release.wait(5)
                if path.endswith('/candles'):
                    step={'5m':STEP,'15m':900000,'1H':3600000,'4H':14400000}[kw['bar']]
                    start=T//step*step;n=min(70,int(kw['limit']))
                    return [[str(start-i*step),'100','102','99','101','5','5','505','0' if i==0 else '1'] for i in range(n)]
                if path.endswith('/ticker'):return [{'last':'101','ts':str(self.now_ms())}]
                raise ValueError('offline optional feed unavailable')
        f=F({},events,api_factory=API)
        try:
            f.select(S,'5m');f.start();self.assertTrue(entered.wait(2))
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and len([x for x in calls if x[0]=='readonly-position-chart'])<2:time.sleep(.02)
            main=[x for x in calls if x[0]=='readonly-position-chart']
            self.assertGreaterEqual(len(main),2);self.assertEqual(main[0][2]['limit'],'300');self.assertEqual(main[1][2]['limit'],'2')
            self.assertFalse(release.is_set());self.assertEqual(len(f.cache[(S,'5m')]),70)
            self.assertTrue(all(x[1]=='/api/v5/market/candles' for x in main))
        finally:
            release.set();f.stop()
            for thread in (f.thread,f.analysis_thread):
                if thread:thread.join(timeout=3)
        self.assertFalse(f.thread.is_alive());self.assertFalse(f.analysis_thread.is_alive())
        charts=[]
        while not events.empty():
            kind,value=events.get_nowait()
            if kind=='position_chart':charts.append(value)
        main=[x for x in calls if x[0]=='readonly-position-chart']
        self.assertGreaterEqual(len(charts),2)
        self.assertLessEqual(len(charts),len(main))  # No duplicate whole-history event per fetch.
    def test_analysis_jobs_coalesce_and_old_selection_is_ignored(self):
        f=factory(CORE)({},queue.Queue(),api_factory=Mock());f.revision=5
        f.schedule_analysis(S,'5m',[],T,4);self.assertIsNone(f.analysis_job)
        f.schedule_analysis(S,'5m',[],T,5);job=f.analysis_job
        f.schedule_analysis(S,'5m',[[1]],T+1,5);self.assertEqual(f.analysis_job,job)
        f.revision=6;f.schedule_analysis('NEXT','15m',[],T,6);self.assertEqual(f.analysis_job[0],'NEXT')


if __name__=='__main__':unittest.main(verbosity=2)
