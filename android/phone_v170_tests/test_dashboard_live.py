"""Private feed observations are simulated; no exchange connections or writes."""
import copy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch

D=Path(__file__).resolve().parent;HOST=D.parent/'phone_v170';CORE=D.parents[2]/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
from phone_dashboard_live import Dashboard,PrivateDisplay,install_projection
from phone_mobile import mobile_module
from okx_stream import AccountStream
from okx_core import day_key

T=1794852000000;S='TEST-USDT-SWAP'
def position():
    return dict(key='one',symbol=S,direction='long',quantity='2',entry='100',mark='101',pnl='2',roe='.02',
                margin='20',margin_basis='거래소 포지션 증거금',close_key='exact',stop='90',phase='active',protected=True)


class PrivateTests(unittest.TestCase):
    def setUp(self):
        self.now=T+2000;self.mono=100
        self.clock=patch('phone_dashboard_live.time.monotonic',lambda:self.mono);self.clock.start()
        self.callback=Mock();self.stream=AccountStream({},self.callback);self.stream.connected=True;self.stream.generation=1
        self.live=PrivateDisplay(self.stream,lambda:self.now)
        self.data=dict(state=dict(equity='100',available='80',day_profit='0',account_connected=True,daily_goal=dict(date=day_key(T),ai_cost='1')),
                       positions=[position()],account_age_seconds=31,controls_enabled=False)
        self.basis=dict(snapshot_ms=T,day=dict(date=day_key(T),base='100',start_equity='100',flow_status='확인'))
    def tearDown(self):self.clock.stop()
    def account(self,**extra):
        detail=dict(ccy='USDT',eq='104.50',availBal='82.50',uTime=str(self.now));detail.update(extra)
        self.stream.feed(json.dumps(dict(arg=dict(channel='account'),data=[dict(details=[detail])])))
    def pos(self,**extra):
        row=dict(instType='SWAP',instId=S,posSide='long',pos='2',avgPx='100',markPx='103',upl='6',uplRatio='.06',margin='21',uTime=str(self.now))
        row.update(extra);self.stream.feed(json.dumps(dict(arg=dict(channel='positions'),data=[row])))
    def project(self):
        out=copy.deepcopy(self.data);self.live.project(out,self.basis,self.now);return out
    def test_received_balance_and_daily_profit_do_not_wait_for_engine(self):
        self.account();out=self.project();s=out['state']
        self.assertEqual(s['equity'],'104.50');self.assertEqual(s['available'],'82.50');self.assertEqual(s['day_profit'],'4.50')
        self.assertEqual(s['daily_goal']['net_profit'],'3.50');self.assertEqual(s['daily_goal']['remaining'],'2.50')
        self.assertTrue(out['account_live']['account_live']);self.callback.assert_called_once()
        self.assertEqual(self.data['state']['equity'],'100');self.assertEqual(out['account_age_seconds'],31);self.assertFalse(out['controls_enabled'])
    def test_original_private_risk_callback_runs_before_display_observer(self):
        self.callback.side_effect=lambda *args:self.assertIsNone(self.live.account)
        self.account();self.assertIsNotNone(self.live.account)
    def test_original_feed_errors_are_not_swallowed(self):
        self.callback.side_effect=RuntimeError('original risk callback')
        with self.assertRaisesRegex(RuntimeError,'original risk'):self.account()
        self.assertIsNone(self.live.account)
    def test_actual_private_position_metrics_preserve_controls_and_evidence(self):
        self.pos();out=self.project();p=out['positions'][0]
        self.assertEqual((p['mark'],p['pnl'],p['roe'],p['margin']),('103','6','0.06','21'))
        for key in ('stop','close_key','phase','protected','quantity','entry'):self.assertEqual(p[key],self.data['positions'][0][key])
    def test_partial_or_full_close_does_not_apply_old_size_metrics(self):
        for qty in ('1','0'):
            self.pos(pos=qty);p=self.project()['positions'][0]
            self.assertEqual(p['quantity'],'2');self.assertEqual(p['pnl'],'2');self.assertIn('확인 중',p['live_note'])
    def test_other_side_or_entry_is_not_applied_to_holding(self):
        self.pos(posSide='short');self.assertEqual(self.project()['positions'][0]['pnl'],'2')
        self.pos(avgPx='99');self.assertEqual(self.project()['positions'][0]['pnl'],'2')
    def test_missing_margin_is_not_zeroed(self):
        self.pos(margin='',imr='999');self.assertEqual(self.project()['positions'][0]['margin'],'20')
    def test_disconnect_staleness_and_generation_never_grant_freshness(self):
        for mode in ('disconnect','generation','age'):
            self.stream.connected=True;self.mono=100;self.now=T+2000;self.account();self.pos()
            if mode=='disconnect':self.stream.connected=False
            if mode=='generation':self.stream.generation+=1
            if mode=='age':self.mono+=5.01;self.now+=5010
            out=self.project();self.assertEqual(out['state']['equity'],'100');self.assertEqual(out['positions'][0]['pnl'],'2');self.assertFalse(out['account_live']['account_live'])
    def test_old_event_cannot_replace_newer_rest_or_private_observation(self):
        self.account();self.pos();self.basis['snapshot_ms']=self.now+1
        self.assertEqual(self.project()['state']['equity'],'100');self.assertEqual(self.project()['positions'][0]['pnl'],'2')
        self.basis['snapshot_ms']=T;self.now+=1;self.account(eq='999',uTime=str(self.now-2));self.pos(upl='999',uTime=str(self.now-2))
        self.assertEqual(self.project()['state']['equity'],'104.50');self.assertEqual(self.project()['positions'][0]['pnl'],'6')
    def test_nan_invalid_and_missing_fields_do_not_invent_money(self):
        self.account(eq='NaN');self.assertEqual(self.project()['state']['equity'],'100')
        self.account(availBal='');self.assertEqual(self.project()['state']['available'],'80')
        self.pos(upl='NaN');self.assertEqual(self.project()['positions'][0]['pnl'],'2')
    def test_day_rollover_does_not_apply_previous_daily_base(self):
        self.now+=86400000;self.account();out=self.project()
        self.assertEqual(out['state']['equity'],'104.50');self.assertIsNone(out['state']['day_profit'])
    def test_sensitive_raw_fields_never_leave_observer(self):
        self.account(secret='NEVER_EXPORT');self.pos(apiKey='NEVER_EXPORT')
        self.assertNotIn('NEVER_EXPORT',json.dumps(self.project()))
    def test_cumulative_position_observer_is_bounded(self):
        for i in range(300):self.pos(instId=f'X{i}-USDT-SWAP')
        self.assertLessEqual(len(self.live.positions),256)
    def test_projection_captures_same_snapshot_equity_and_day_baseline(self):
        import okx_dashboard_data as module
        with patch.object(module,'dashboard_snapshot',Mock(return_value=dict(day_profit='4',positions=[]))) as old:
            old._phone_live_basis=False
            install_projection();fn=module.dashboard_snapshot;install_projection();self.assertIs(fn,module.dashboard_snapshot)
            out=fn(dict(equity='104',available='82',ms=T),[],dict(base='100',date=day_key(T)),True,True,False)
            self.assertEqual(out['equity'],'104');self.assertEqual(out['display_basis']['day']['base'],'100');self.assertNotIn('start_equity',out['display_basis']['day']);old.assert_called_once()


class StreamTests(unittest.TestCase):
    def mobile(self):
        return NS(lock=threading.RLock(),closed=threading.Event(),snapshot=dict(ui_version='7.32-Q2X',state=dict(equity='100'),positions=[position()],futures=dict(rows=[dict(symbol=f'X{i}',last=1) for i in range(290)]),performance=dict(large='x'*100000),captured_ms=T),display_basis={})
    def test_home_stream_excludes_whole_market_and_diagnostics(self):
        d=Dashboard(self.mobile());home=d.snapshot();market=d.snapshot(part='market');full=d.snapshot(full=True)
        self.assertNotIn('futures',home);self.assertNotIn('performance',home);self.assertEqual(len(market['futures']['rows']),290);self.assertIn('performance',full)
    def test_unchanged_values_are_not_repeated_and_stream_slot_is_released(self):
        m=self.mobile();d=Dashboard(m);raw=[];clock=iter([T,T+250]);d.clock=lambda:next(clock)
        def write(b):
            raw.append(b)
            if len(raw)==2:m.closed.set()
        h=NS(authorized=lambda:True,send_response=Mock(),send_header=Mock(),end_headers=Mock(),wfile=NS(write=write,flush=Mock()))
        d.serve(h,'home',True)
        self.assertIn(b'"positions"',raw[0]);self.assertNotIn(b'"positions"',raw[1]);self.assertLess(len(raw[1]),80)
        self.assertEqual(d.slots._value,4);self.assertIn(b'retry: 500',raw[0])
    def test_live_route_requires_host_and_session(self):
        import time
        module=mobile_module(CORE);s=object.__new__(module.PhoneMobile)
        s.lock=threading.RLock();s.hosts={'localhost:8766'};s.sessions={'ok':time.monotonic()+30};s.live_dashboard=NS(serve=Mock())
        for host,cookie,want in [('wrong','mobile_session=ok',403),('localhost:8766','',401),('localhost:8766','mobile_session=ok',None)]:
            h=object.__new__(s.handler());h.path='/api/phone/dashboard-live?part=home&stream=1';h.headers={'Host':host,'Cookie':cookie};h.reply=Mock();h.do_GET()
            if want:self.assertEqual(h.reply.call_args.args[0],want)
            else:s.live_dashboard.serve.assert_called_once_with(h,'home',True)
    def test_unknown_page_and_expired_session(self):
        d=Dashboard(self.mobile())
        with self.assertRaises(ValueError):d.snapshot(part='arbitrary')
        h=NS(authorized=lambda:False,send_response=Mock(),send_header=Mock(),end_headers=Mock(),wfile=NS(write=Mock(),flush=Mock()))
        d.serve(h,'chart',True);h.wfile.write.assert_not_called();self.assertEqual(d.slots._value,4)


class HomeAssetTests(unittest.TestCase):
    def test_home_snapshot_uses_same_total_for_ratio_and_goal(self):
        m=StreamTests().mobile()
        today=day_key(T)
        m.snapshot['state'].update(available='80',day_profit='8',daily_goal=dict(
            date=today, status='tracking', rate='0.06', net_profit='7',
            target_profit='6', target_equity='107'))
        m.home_assets=NS(snapshot=Mock(return_value=dict(total='200',observed_ms=T,stale=False)))
        dashboard=Dashboard(m);dashboard.clock=lambda:T
        for full in (False,True):
            out=dashboard.snapshot(full=full)
            self.assertEqual(out['profit_basis']['percent'],'4.00')
            goal=out['state']['daily_goal']
            self.assertEqual((goal['target_profit'],goal['remaining']),('12.00','5.00'))
            self.assertEqual(out['state']['available'],'80')
        self.assertEqual(m.snapshot['state']['daily_goal']['target_profit'],'6')

    def test_changed_stale_missing_total_and_previous_day(self):
        from phone_home_assets import project_total_basis
        today=day_key(T)
        state=dict(day_profit='8', daily_goal=dict(date=today,status='tracking',
                                                   rate='0.06',net_profit='7'))
        ratio=project_total_basis(state,dict(total='100',stale=True),today)
        self.assertEqual(ratio['percent'],'8.00')
        self.assertEqual(state['daily_goal']['status'],'reached')
        self.assertTrue(state['daily_goal']['assets_stale'])
        for total in (None,'0','-1','NaN'):
            snapshot=dict(state)
            ratio=project_total_basis(snapshot,dict(total=total),today)
            self.assertIsNone(ratio['percent'])
            self.assertEqual(snapshot['daily_goal']['status'],'unavailable')
        self.assertIsNone(project_total_basis(state,dict(total='100'),day_key(T+86400000))['percent'])

    def test_valuation_is_one_read_no_double_count_and_retains_on_failure(self):
        from phone_home_assets import HomeAssets
        now=[100];feed=HomeAssets({},threading.Event(),clock=lambda:now[0])
        api=NS(request=Mock(return_value=[dict(ts=str(T),totalBal='350.25',details=dict(funding='50.25',trading='200',earn='100'))]),now_ms=lambda:T)
        feed.poll(api);v=feed.snapshot()
        self.assertEqual((v['funding'],v['total'],v['stale']),('50.25','350.25',False))
        api.request.assert_called_once_with('GET','/api/v5/asset/asset-valuation',params={'ccy':'USDT'})
        for invalid in ([],[dict(ts=str(T),totalBal='NaN',details=dict(funding='0'))],
                        [dict(ts=str(T-90001),totalBal='350',details=dict(funding='0'))]):
            api.request.return_value=invalid
            with self.assertRaises(ValueError):feed.poll(api)
            self.assertEqual(feed.snapshot()['total'],'350.25')
        now[0]+=91;self.assertTrue(feed.snapshot()['stale'])

    def test_display_reads_do_not_block_snapshots_and_failures_back_off(self):
        from phone_home_assets import HomeAssets
        closed=NS(is_set=lambda:False,wait=Mock(side_effect=[False,False,True]))
        api=NS(request=Mock(side_effect=TimeoutError('PRIVATE SECRET MUST NOT ESCAPE')),session=NS(close=Mock()))
        feed=HomeAssets({},closed,factory=lambda _:api)
        feed.run()
        self.assertEqual([c.args[0] for c in closed.wait.call_args_list],[15,30,60])
        api.session.close.assert_called_once()
        self.assertIsNone(feed.snapshot()['total']);self.assertTrue(feed.snapshot()['stale'])
        m=StreamTests().mobile();m.home_assets=feed
        d=Dashboard(m).snapshot();self.assertIsNone(d['home_assets']['total'])
        self.assertNotIn('SECRET',json.dumps(d))

    def test_readonly_valuation_client_refuses_writes(self):
        from phone_home_assets import valuation_client
        from okx_core import OKX
        keys=dict(OKX_API_KEY='test',OKX_SECRET_KEY='secret',OKX_PASSPHRASE='pass')
        def init(api, settings):
            api.session=Mock();api.requests=NS(RequestException=OSError)
            api.server_ms=api.anchor=api.synced=0
        with patch.object(OKX,'__init__',init):api=valuation_client(keys)
        try:
            with self.assertRaises(PermissionError):api.request('POST','/api/v5/asset/transfer',body={})
            with self.assertRaises(PermissionError):api.request('GET','/arbitrary')
            with patch.object(api.session,'request',side_effect=AssertionError('offline only')) as request:
                with self.assertRaises(AssertionError):api.request('GET','/api/v5/asset/asset-valuation',params={'ccy':'USDT'})
                self.assertEqual(request.call_args.args[0],'GET')
        finally:api.session.close()


if __name__=='__main__':unittest.main(verbosity=2)
