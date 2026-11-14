"""Presentation/resource checks; no exchange connection, orders or device changes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import phone_performance as perf


class FoldRuntime(unittest.TestCase):
    def mobile(self, root):
        core=Path(os.environ['OKX_TEST_CORE'])
        sys.path.insert(0,str(core))
        from phone_mobile import mobile_module
        from phone_host import View
        module=mobile_module(core)
        service=module.PhoneMobile(root,{'OKX_SECRET_KEY':'fixture-sensitive-secret'},
            dict(module.credential('fixture-password'),https_host='',controls_enabled=True),
            feed_factory=lambda *a:Mock(),port=0)
        service.updater=Mock()
        service.updater.snapshot.return_value={'message':'first'}
        return module,service,View({},False)

    def test_unchanged_presentation_reused_but_age_and_update_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            module,s,v=self.mobile(Path(temp))
            try:
                v.data_seen=100
                v.receive('futures_market',{'rows':[dict(symbol='TEST-USDT-SWAP',last=1,change=.1,ts=1)],'observed_ms':1,'stale':False})
                with patch('time.monotonic',return_value=101):s.capture(v)
                rows=s.snapshot['futures']['rows']
                self.assertEqual(s.capture_rebuilds,1)
                s.updater.snapshot.return_value={'message':'fixture-sensitive-secret','progress':float('nan')}
                s.config['controls_enabled']=False
                with patch('time.monotonic',return_value=105):s.capture(v)
                self.assertIs(rows,s.snapshot['futures']['rows'])
                self.assertEqual(s.snapshot['account_age_seconds'],5)
                self.assertFalse(s.snapshot['controls_enabled'])
                self.assertEqual(s.capture_reuses,1)
                self.assertNotIn('fixture-sensitive-secret',json.dumps(s.snapshot))
                self.assertIsNone(s.snapshot['program_update']['progress'])
            finally:s.server.server_close()

    def test_new_market_status_and_log_visible_next_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            module,s,v=self.mobile(Path(temp))
            try:
                s.capture(v)
                v.receive('futures_market',{'rows':[dict(symbol='TEST-USDT-SWAP',last=9,change=.1,ts=1)],'observed_ms':1,'stale':False})
                v.receive('status',dict(live=True,market_connected=True,account_connected=True,recovering=False))
                v.add('new activity')
                s.capture(v)
                self.assertEqual(s.snapshot['futures']['rows'][0]['last'],9)
                self.assertTrue(s.snapshot['state']['live'])
                self.assertEqual(s.snapshot['status'],'폰 실거래 가동 중')
                self.assertEqual(s.snapshot['activities'][0]['text'],'new activity')
                self.assertEqual(s.capture_rebuilds,2)
                v.receive('futures_market_error',None);s.capture(v)
                self.assertTrue(s.snapshot['futures']['stale'])
            finally:s.server.server_close()

    def test_live_position_event_reaches_authenticated_api_immediately(self):
        import time
        import urllib.request
        with tempfile.TemporaryDirectory() as temp:
            module,s,v=self.mobile(Path(temp));s.start()
            try:
                v.receive('dashboard',{'positions':[dict(symbol='TEST-USDT-SWAP',direction='long',quantity='2',entry='10',mark='10',roe='0',pnl='0',reason='fixture-sensitive-secret')]})
                s.capture(v)
                now=int(time.time()*1000)
                v.receive('position_live',dict(received_ms=now,row=dict(instId='TEST-USDT-SWAP',posSide='long',pos='2',avgPx='10',markPx='11',uplRatio='.1',upl='2')))
                s.capture(v)
                s.sessions['fixture-session']=time.monotonic()+60
                req=urllib.request.Request('http://127.0.0.1:'+str(s.port)+'/api/snapshot',headers={'Cookie':'mobile_session=fixture-session'})
                with urllib.request.urlopen(req,timeout=2) as response:body=response.read()
                data=json.loads(body)
                self.assertEqual(data['positions'][0]['mark'],'11')
                self.assertEqual(data['positions'][0]['pnl'],'2')
                self.assertNotIn(b'fixture-sensitive-secret',body)
                self.assertEqual(s.capture_rebuilds,2)
            finally:s.stop()

    def test_elapsed_ignores_wall_clock_jump(self):
        t=perf.Timing('/tmp');t.started_mono=100
        with patch.object(perf.time,'monotonic',return_value=125),patch.object(perf.time,'time',return_value=t.started+100000):
            self.assertEqual(t.report()['elapsed_s'],25)

    def test_checkpoints_are_bounded_with_explicit_actual_elapsed(self):
        t=perf.Timing('/tmp');t.started_mono=100
        stop=Mock();stop.is_set.side_effect=[False,False,True]
        holder={}
        def thread(**kwargs):holder['run']=kwargs['target'];return Mock()
        import phone_account
        with patch.object(perf.threading,'Thread',side_effect=thread), \
             patch.object(perf.time,'monotonic',return_value=3705), \
             patch.object(phone_account,'save_json') as save:
            t.start_writer(stop);holder['run']()
        snapshots=[c for c in save.call_args_list if 'min.json' in str(c.args[0])]
        self.assertEqual(len(snapshots),3)
        for c in snapshots:
            self.assertEqual(c.args[1]['checkpoint']['actual_elapsed_s'],3605)
            self.assertTrue(c.args[1]['checkpoint']['includes_paused_time'])
        self.assertEqual(t.checkpoints,{10,30,60})

    def test_asset_cache_returns_identical_bytes_with_bounded_slots(self):
        with tempfile.TemporaryDirectory() as temp:
            module,s,v=self.mobile(Path(temp))
            try:
                first=module.asset('index.html');second=module.asset('index.html')
                self.assertIs(first,second)
                self.assertIn(b'1.1.7',first)
                self.assertLessEqual(module.asset.cache_info().currsize,3)
            finally:s.server.server_close()

    def test_resource_denial_is_nonfatal_and_cpu_is_interval_measurement(self):
        t=perf.Timing('/tmp')
        with patch.object(perf.Path,'read_text',side_effect=PermissionError()), \
             patch.object(perf.time,'monotonic',side_effect=[100,105]), \
             patch.object(perf.time,'process_time',side_effect=[2,3]):
            first=t.sample_resources();second=t.sample_resources()
        self.assertNotIn('cpu_one_core_pct',first)
        self.assertEqual(second['cpu_one_core_pct'],20)
        self.assertNotIn('rss_mib',second)
        self.assertGreaterEqual(second['threads'],1)

    def test_empty_proc_fields_do_not_prevent_rss_observation(self):
        t=perf.Timing('/tmp')
        with patch.object(perf.Path,'read_text',return_value='Name:\tpython\nGroups:\t\nVmRSS:\t2048 kB\nVmHWM:\t4096 kB\n'):
            r=t.sample_resources()
        self.assertEqual(r['rss_mib'],2.)
        self.assertEqual(r['peak_rss_mib'],4.)
        with patch.object(perf.Path,'read_text',return_value='VmRSS:\nVmHWM:\n'):
            r=t.sample_resources()
        self.assertNotIn('rss_mib',r)

    def test_summary_distinguishes_recent_ticks_and_keeps_admission_record(self):
        t=perf.Timing('/tmp')
        report=t.report()
        report['recent_ticks']=[dict(mode='optimized',seconds=n) for n in range(1,21)]+[dict(mode='baseline',seconds=100)]
        report['signal_cache']=dict(hits=90,misses=10,key_bytes=1048576,evictions=3)
        report['metrics']=[dict(group='optimized',label='engine.tick',calls=4,total_s=8,max_s=5)]
        report['recent_admission_exceptions']=[dict(category='risk_limit')]
        s=t.make_summary(report)
        self.assertEqual(s['recent'],dict(count=20,mean_s=10.5,p95_s=19))
        self.assertEqual(s['ticks']['optimized']['mean_s'],2)
        self.assertEqual(s['cache'],dict(hit_pct=90.,input_mib=1.,evictions=3))
        self.assertEqual(s['last_admission'],[dict(category='risk_limit')])


if __name__=='__main__':unittest.main()
