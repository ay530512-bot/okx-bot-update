"""Activity and update regressions. Run from a release directory with OKX_PC_PACKAGE extracted.
For a legacy migration, run with OKX_PC_TEST_PACKAGE=<old extracted package> and
arguments --upgrade <new release ZIP>. All exchange data comes from ReadOnlyExchange.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
from queue import Queue
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

P = Path(os.getenv('OKX_PC_TEST_PACKAGE', 'OKX_PC_PACKAGE')).resolve()
sys.path[:0] = [str(P), str(P/'runtime'), str(P/'core')]
import okx_continuity732 as continuity
from okx_v5 import RuleEngine
import pc_update
from phone_host import View, route_control

UID = 'fixture-account'
ACCOUNT = hashlib.sha256(UID.encode()).hexdigest()
CFG = dict(version='fixture', execution=dict(rule_channel701=True, continuous_trading=True, recovery_snapshots=2),
           risk=dict(profit_review_roe=.2, daily_stop=-.21, daily_cap=2),
           notifications=dict(enabled=False, repeat_wait_seconds=60), selection={}, signals={}, indicators={})
HELD = dict(symbol='FIX-USDT-SWAP', direction='long', quantity='2', phase='active', fill_px='10',
            stop_px='9.8', posId='p1', algo_client_id='protected', client_id='opened', entry_ms=1)


class ReadOnlyExchange:
    def __init__(self):
        self.config = dict(uid=UID, acctLv='2', posMode='long_short_mode', perm='trade')
        self.positions = []
        self.algos = []
        self.orders = []
        self.reads = 0

    def now_ms(self):
        return int(time.time()*1000)

    def snapshot(self):
        self.reads += 1
        return dict(config=copy.deepcopy(self.config), positions=copy.deepcopy(self.positions),
                    orders=copy.deepcopy(self.orders), equity=150, available=100, ms=self.now_ms())

    def pending_algos(self, *, full):
        assert full
        return copy.deepcopy(self.algos)

    def holding(self):
        self.positions = [dict(instId=HELD['symbol'], posSide='long', posId='p1', mgnMode='isolated', pos='2', avgPx='10')]
        self.algos = [dict(instId=HELD['symbol'], posSide='long', algoClOrdId='protected', algoId='a1',
                           side='sell', tdMode='isolated', state='live', slTriggerPxType='mark',
                           slOrdPx='-1', slTriggerPx='9.8', sz='2')]


def boot(root, api, cfg=CFG):
    runtime = root/'trading/runtime-q2x'
    runtime.mkdir(parents=True, exist_ok=True)
    with patch('okx_v5.load_config', return_value=copy.deepcopy(cfg)):
        e = RuleEngine(runtime, {}, Queue(), exchange=api)
    u = pc_update.PCUpdater(root, SimpleNamespace(complete_control=Mock()))
    u.mobile.updater = u
    u.next_check = float('inf')
    u.bind(e)
    return e, u


def record_start(e):
    e.journal.data['account'] = ACCOUNT
    e.journal.save()
    continuity.started(e)


def stop_from_phone(e, u):
    route_control(e, dict(op='pause', issued_at=time.monotonic(), owner='phone', request_id='stop'), u.mobile)
    e.handle(*e.commands.get(timeout=2))
    results = [row for kind,row in list(e.events.queue) if kind == 'mobile_control_result']
    assert results[-1]['status'] == 'applied', results[-1]
    assert not e.enabled and not e.run_requested and e.journal.data[continuity.KEY]['requested'] is False


class UpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.api = ReadOnlyExchange()

    def test_restart_policy_is_equal_after_full_startup(self):
        e, _ = boot(self.root, self.api)
        record_start(e)
        restarted, _ = boot(self.root, self.api)
        self.assertTrue(restarted.run_requested and restarted.resume_pending)
        self.assertTrue(restarted.entry_cancel.is_set())
        self.assertFalse(restarted.enabled)
        self.assertEqual(continuity.policy_hash(restarted), restarted.journal.data[continuity.KEY]['policy_hash'])
        stop_from_phone(restarted, restarted.pc_updater)
        stopped, _ = boot(self.root, self.api)
        self.assertTrue(stopped.user_paused)
        self.assertFalse(stopped.run_requested or stopped.resume_pending or stopped.enabled)

    def test_changed_policy_and_account_require_persisted_confirmation(self):
        for change in ('policy', 'account', 'continuous'):
            with self.subTest(change=change), TemporaryDirectory() as name:
                root = Path(name)
                e, _ = boot(root, self.api)
                record_start(e)
                cfg = copy.deepcopy(CFG)
                if change == 'policy':
                    cfg['risk']['daily_stop'] = -.15
                elif change == 'continuous':
                    cfg['execution']['continuous_trading'] = False
                else:
                    e.journal.data[continuity.KEY]['account'] = 'different'
                    e.journal.save()
                restarted, _ = boot(root, self.api, cfg)
                row = json.loads((restarted.root/'bot_state.json').read_text())[continuity.KEY]
                self.assertFalse(row['requested'] or restarted.run_requested or restarted.resume_pending or restarted.enabled)
                self.assertEqual(row['event'], 'confirmation_required')
                self.assertTrue(restarted.entry_cancel.is_set())
                again, _ = boot(root, self.api, cfg)
                self.assertEqual(again.journal.data[continuity.KEY]['history'], row['history'])
                self.assertFalse(continuity.resume_if_ready(again))

    def test_change_during_reconciliation_cancels_requested_resume(self):
        e, _ = boot(self.root, self.api)
        record_start(e)
        e, _ = boot(self.root, self.api)
        e.stream.connected = True
        e.account_stream.fresh = lambda:True
        e.recovering, e.good_snapshots = False, 3
        e.cfg['risk']['daily_stop'] = -.16
        self.assertFalse(continuity.resume_if_ready(e))
        self.assertFalse(e.journal.data[continuity.KEY]['requested'] or e.resume_pending or e.enabled)
        self.assertEqual(self.api.reads, 0)

    def test_stopped_can_handover_but_protection_and_identity_are_required(self):
        e, u = boot(self.root, self.api)
        record_start(e)
        e, u = boot(self.root, self.api, {**CFG,'signals':{'changed':True}})
        self.api.holding()
        e.journal.data['owned'] = copy.deepcopy(HELD)
        e.journal.save()
        folder = 'r20999-'+'e'*16
        (self.root/'pc_versions'/folder).mkdir(parents=True)
        stored = copy.deepcopy(e.journal.data)
        for kind in ('missing SL', 'private order', 'account mismatch', 'pending command', 'changed between snapshots', 'opposite intent'):
            with self.subTest(kind=kind):
                self.api.holding()
                self.api.config['uid'] = UID
                self.api.orders = []
                if kind == 'missing SL':
                    self.api.algos.clear()
                if kind == 'private order':
                    self.api.orders.append({'ordId':'pending'})
                if kind == 'account mismatch':
                    self.api.config['uid'] = 'other'
                if kind == 'pending command':
                    e.commands.put(('pause',{}))
                if kind == 'opposite intent':
                    e.run_requested = True
                first = self.api.snapshot()
                second = copy.deepcopy(first)
                if kind == 'changed between snapshots':
                    second['positions'][0]['pos'] = '1'
                with patch.object(self.api,'snapshot',side_effect=[first,second]):
                    e.handle('pc_update_restart',dict(folder=folder))
                self.assertFalse(u.restart or e.stop_event.is_set())
                self.assertFalse((self.root/'pc_update_handoff.json').exists())
                self.assertEqual(stored, e.journal.data)
                if kind == 'pending command':
                    e.commands.get_nowait()
                e.run_requested = False
        self.api.holding()
        before = self.api.reads
        e.handle('pc_update_restart',dict(folder=folder))
        self.assertTrue(u.restart and e.stop_event.is_set())
        self.assertEqual(self.api.reads-before, 2)
        self.assertEqual(e.journal.data, stored)
        self.assertFalse(stored[continuity.KEY]['requested'])

    def test_activity_history_and_actual_status_transitions(self):
        e, _ = boot(self.root, self.api)
        e.execution_status.set('paused','사용자 중지')
        for now in (100.,163.,225.):
            with patch('time.monotonic', return_value=now):
                e.publish_portfolio()
        e.log('체결 확인')
        e.log('체결 확인')
        e.execution_status.set('signal_wait','두 꼬리 대기')
        e.publish_portfolio()
        e.execution_status.set('paused','사용자 중지')
        e.publish_portfolio()
        here = View({}, False)
        for kind, value in list(e.events.queue):
            if kind == 'log':
                here.receive(kind,value)
        texts = [item[1] for item in here.activities]
        self.assertEqual([t for t in texts if t.startswith('규칙 상태 · ')],
                         ['규칙 상태 · 신규 진입 정지 / 사용자 중지','규칙 상태 · 진입 신호 대기 / 두 꼬리 대기',
                          '규칙 상태 · 신규 진입 정지 / 사용자 중지'])
        self.assertEqual(texts.count('체결 확인'), 2)
        log = self.root/'prior.log'
        log.write_text('11-22 06:18:43  규칙 상태 · 중지\n11-22 06:19:00  체결 확인\n둘째 줄\n'
                       '11-22 06:19:46  규칙 상태 · 중지\n11-22 06:20:48  규칙 상태 · 중지\n'
                       '11-22 06:20:50  PC 업데이트 · 설치 요청\n', encoding='utf-8')
        view = View({},False)
        view.restore_activities(log)
        self.assertEqual(list(view.activities), [('11-22 06:20:50','PC 업데이트 · 설치 요청',None),
                        ('11-22 06:19:00','체결 확인\n둘째 줄',None),('11-22 06:18:43','규칙 상태 · 중지',None)])
        view.receive('log','11-22 06:21:50  규칙 상태 · 중지')
        self.assertEqual(len(view.activities), 3)
        view.receive('log','11-22 06:22:50  규칙 상태 · 가동')
        view.receive('log','11-22 06:23:50  규칙 상태 · 중지')
        self.assertEqual(view.activities[0][:2],('11-22 06:23:50','규칙 상태 · 중지'))

    def test_running_intent_waits_for_reconciliation_after_update(self):
        e, u = boot(self.root, self.api)
        record_start(e)
        e.enabled, e.user_paused = True, False
        self.api.holding()
        e.journal.data['owned'] = copy.deepcopy(HELD)
        e.journal.save()
        stage = 'r20999-'+'f'*16
        (self.root/'pc_versions'/stage).mkdir(parents=True)
        e.handle('pc_update_restart', {'folder':stage})
        self.assertTrue(u.restart)
        self.assertTrue(e.journal.data[continuity.KEY]['requested'])
        restarted, _ = boot(self.root, self.api)
        self.assertFalse(restarted.enabled)
        self.assertTrue(restarted.run_requested and restarted.resume_pending and restarted.entry_cancel.is_set())
        self.assertFalse(continuity.resume_if_ready(restarted))
        self.assertEqual(restarted.journal.data['owned']['stop_px'],HELD['stop_px'])

    def test_settings_stream_and_phone_update_button(self):
        from threading import RLock
        from urllib.parse import urlsplit
        from playwright.sync_api import expect, sync_playwright
        from phone_dashboard_live import Dashboard
        from phone_mobile import mobile_module

        app = mobile_module(P/'core')
        now = int(time.time()*1000)
        active = pc_update.package_manifest(P)['version']
        update = dict(display_version=active,target_version='2.8.2',target_revision=20802,available=True,
                      message='업데이트 확인',notes='테스트 변경 사항')
        data = dict(ui_version=app.UI_VERSION, display_ms=now,captured_ms=now,account_age_seconds=1,
                    controls_enabled=True,state={'account_connected':True},positions=[],activities=[],
                    futures={'rows':[]},performance={},program_update=update)
        mobile=SimpleNamespace(lock=RLock(),snapshot=data,display_basis={})
        projection=Dashboard(mobile)
        writes=[]
        errors=[]

        def route(request):
            path=urlsplit(request.request.url).path
            name=path.strip('/') or 'index.html'
            if name in ('index.html','app.js','style.css'):
                mime={'index.html':'text/html','app.js':'text/javascript','style.css':'text/css'}[name]
                request.fulfill(body=app.asset(name),content_type=mime+'; charset=utf-8')
            elif request.request.method=='POST':
                writes.append((path,request.request.post_data_json))
                request.fulfill(json=dict(status='queued',request_id='mock_update',message='PC 처리 대기'))
            elif path=='/api/control/result':
                request.fulfill(json=dict(status='failed',request_id='mock_update',message='테스트 설치 보류'))
            elif path in ('/api/snapshot','/api/phone/dashboard-live'):
                request.fulfill(json=data)
            else:
                request.fulfill(json={})

        with sync_playwright() as pw:
            options={}
            if os.getenv('PC_TEST_CHROME'):
                options=dict(executable_path=os.environ['PC_TEST_CHROME'],args=['--no-sandbox','--disable-gpu','--single-process'])
            browser=pw.chromium.launch(**options)
            page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            page.route('**/*',route)
            page.on('dialog', lambda dialog:dialog.accept())
            page.on('pageerror', lambda error:errors.append(str(error)))
            page.add_init_script('window.setInterval=()=>0;window.EventSource=undefined;')
            page.goto('http://pc.test/')
            page.locator('#nav-settings').click()
            status=page.locator('#mobileUpdateStatus')
            expect(status).to_contain_text('현재 PC '+active)
            expect(status).to_contain_text('설치 가능 PC 2.8.2')
            data['activities']=[dict(time='11-22 06:20:48',text='두 꼬리 롱 신호')]
            self.assertNotIn('activities',projection.snapshot(part='home'))
            delta=projection.snapshot(part='settings')
            self.assertEqual(delta['activities'],data['activities'])
            self.assertTrue(page.evaluate('d=>phoneDashboardAccept(d)',delta))
            expect(page.locator('#activities .activity p')).to_have_text('두 꼬리 롱 신호')
            expect(page.locator('#activities .activity time')).to_have_text('11-22 06:20:48 KST')
            page.locator('#mobileUpdateButton').click()
            expect(status).to_contain_text('테스트 설치 보류')
            self.assertEqual([p for p,_ in writes],['/api/control/update'])
            self.assertEqual(writes[0][1]['key'],'install_20802')
            self.assertEqual(errors,[])
            browser.close()

    def test_receipt_after_startup_is_shown_and_logged_once(self):
        path = self.root/'pc_update_result.json'
        pc_update.atomic_json(path,dict(message='2.7.0 설치 완료'))
        with patch.dict(os.environ, OKX_PC_SUPERVISOR='b'*32):
            e,u = boot(self.root,self.api)
            self.assertNotIn('2.7.0', u.snapshot()['message'])
            text = u.release['version']+' 설치 완료'
            pc_update.atomic_json(path,dict(message=text))
            u.next_receipt = 0.
            for _ in range(3):
                self.assertEqual(u.snapshot()['message'], text)
            self.assertEqual((e.root/'bot_log.txt').read_text(encoding='utf-8').count(text),1)


def migrate(asset):
    """Use the original supervisor, staged ZIP, journal, and phone controls end-to-end."""
    asset = Path(asset).resolve()
    from zipfile import ZipFile
    with ZipFile(asset) as z:
        target = json.loads(z.read('OKX_PC_PACKAGE/pc_release.json'))
    with TemporaryDirectory() as folder:
        root = Path(folder)
        fake = ReadOnlyExchange()
        first, _ = boot(root, fake)
        record_start(first)
        old, updater = boot(root, fake)
        assert not old.run_requested and old.journal.data[continuity.KEY]['requested']
        old.journal.data['owned'] = copy.deepcopy(HELD)
        old.journal.save()
        fake.holding()
        raw = asset.read_bytes()
        manifest = dict(format=1, revision=target['revision'], version=target['version'],
                        bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),commit='a'*40,notes='test')
        package = pc_update.verify_package(P)
        assert pc_update.verify_manifest(manifest,package['revision'])
        stage = pc_update.download_stage
        def fetch_staged(root, pkg, meta):
            return stage(root,pkg,meta,download=lambda url,limit:raw)
        def install():
            updater.available=manifest
            command = dict(op='update', key='install_'+str(manifest['revision']),
                           request_id='update', owner='phone',issued_at=time.monotonic())
            with patch.object(updater,'latest',return_value=manifest), patch.object(pc_update,'download_stage',fetch_staged):
                route_control(old,command,updater.mobile)
                old.handle(*old.commands.get(timeout=10))
        seen = []
        def launch(args, env):
            current = Path(args[4]).parent
            seen.append(current)
            if current == P:
                updater.token = env['OKX_PC_SUPERVISOR']
                install()
                assert '신규 진입 운용 상태 대조 실패' in updater.message, updater.message
                assert not old.stop_event.is_set()
                assert fake.reads == 0
                stop_from_phone(old,updater)
                install()
                assert updater.restart and fake.reads == 2
                assert old.journal.data['owned']==HELD
                return SimpleNamespace(wait=lambda timeout:pc_update.RESTART)
            assert pc_update.verify_package(current)['revision']==target['revision']
            env=dict(env,OKX_PC_TEST_PACKAGE=str(current))
            subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--boot',str(root)],
                           env=env,check=True,capture_output=True,text=True)
            return SimpleNamespace(wait=lambda timeout:0)
        assert pc_update.supervise(root,P,[],launch=launch)==0
        assert len(seen)==2 and pc_update.read_json(root/'pc_current.json')['folder']==seen[-1].name
        assert pc_update.read_json(root/'pc_update_result.json')['message']==target['version']+' 설치 완료'
        print(package['version'],'→',target['version'],'stopped, protected, installed and confirmed')


if __name__ == '__main__':
    if sys.argv[1:2]==['--upgrade']:
        migrate(sys.argv[2])
    elif sys.argv[1:2]==['--boot']:
        root=Path(sys.argv[2])
        fake=ReadOnlyExchange()
        fake.holding()
        e,u=boot(root,fake)
        assert not (e.run_requested or e.resume_pending or e.enabled)
        assert e.journal.data['owned']['stop_px']==HELD['stop_px']
        assert e.journal.data['owned']['quantity']==HELD['quantity']
        pc_update.position_handover(e.journal.data,fake.snapshot(),fake.pending_algos(full=True))
        from phone_mobile import mobile_module
        assert mobile_module(P/'core').UI_VERSION=='PC-'+pc_update.package_manifest(P)['version']
        pc_update.signal_ready(root)
    else:
        unittest.main()
