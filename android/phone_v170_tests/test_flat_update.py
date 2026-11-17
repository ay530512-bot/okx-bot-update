"""Paused/empty upgrade, actual disposable process exit, GET-only exchange.

The transport socket is stubbed because AF_UNIX is unavailable in the runner.
PID identity, locks, signals and child process exits are real OS operations.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

import phone_flat_update as f
import phone_button_upgrade as u
import phone_handover as h
import phone_legacy_restart as recovery
from phone_account import save_json
from phone_migrate import child_pids, process_token
from test_handover import fixtures, ReadAPI, HandoverTests

HOST = '''
import fcntl,signal,sys,time,json,queue,threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from phone_account import save_json
import phone_handover as old
root=Path(sys.argv[1]);fd=(root/'phone_host.lock').open('a');fcntl.flock(fd,fcntl.LOCK_EX)
commands=queue.Queue()
e=SimpleNamespace(journal=SimpleNamespace(data=json.loads((root/'runtime-q2x/bot_state.json').read_text())),
 api=Mock(),handle=Mock(),send=lambda action,**kwargs:commands.put((action,kwargs)),commands=commands,events=queue.Queue(),
 risk_queue=queue.Queue(),queued_risks={'already-closed-position'},entry_cancel=threading.Event(),stop_event=threading.Event(),
 command_wake=threading.Event(),enabled=False,preview=False,user_paused=True,run_requested=False,resume_pending=False,invalidate=Mock())
def log(message):
 with (root/'handover-messages').open('a') as out:out.write(message+'\\n')
e.log=log;adapter=old.install(e,root)
stop=False
def graceful(*_):
 global stop
 p=root/'runtime-q2x/bot_state.json';j=json.loads(p.read_text())
 j['entry_continuity732']['requested']=False;save_json(p,j)
 (root/'normal-stop-observed').touch()
 if not any([j.get('owned'),j.get('extra_owned'),*j.get('additional_owned',[])]) and not (root/'refuse-quit').exists():stop=True
signal.signal(signal.SIGTERM,graceful)
(root/'host-ready').touch()
while not stop:
 adapter.poll()
 while not commands.empty():
  action,kwargs=commands.get();e.handle(action,kwargs)
 time.sleep(.02)
'''
SUPERVISOR = '''
import fcntl,os,sys,subprocess,time
from pathlib import Path
from phone_account import save_json
root=Path(sys.argv[1]);fd=(root/'phone_service.lock').open('a');fcntl.flock(fd,fcntl.LOCK_EX)
p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('phone_host.py')),str(root)])
while p.poll() is None:
 save_json(root/'phone_service_status.json',dict(pid=os.getpid(),host_pid=p.pid,state='running',host_process_running=True,remote_process_running=True,service_version='phone-service-53',observed_at=time.time()))
 time.sleep(.03)
'''


class FlatProcesses(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.old=self.root/'host-v53';self.old.mkdir();self.target=self.root/'host-v55';self.target.mkdir()
        (self.old/'phone_host.py').write_text(HOST);(self.old/'phone_service.py').write_text(SUPERVISOR)
        original=Path(__file__).resolve().parents[1]/'phone_v166/phone_handover.py'
        (self.old/'phone_handover.py').write_bytes(original.read_bytes())
        (self.root/'runtime-q2x').mkdir()
        self.j,self.snap,self.algos=fixtures(False)
        self.j['owned']=None;self.snap['positions']=[];self.algos=[]
        self.path=self.root/'runtime-q2x/bot_state.json';save_json(self.path,self.j)
        self.api=ReadAPI(self.snap,self.algos)
        self.p=subprocess.Popen([sys.executable,'-B',str(self.old/'phone_service.py'),str(self.root)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.wait(lambda:(self.root/'host-ready').exists())
        self.host=h.load(self.root/'phone_service_status.json')['host_pid']
        self.tokens={pid:process_token(pid) for pid in (self.p.pid,*child_pids(self.p.pid))}
        self.patches=[patch.object(f,'start_watchdog'),patch.object(u,'verify_owner'),
                      patch.object(f,'transport_released',return_value=True),patch.object(u,'transport_released',return_value=True)]
        for p in self.patches:p.start()
        self.boot=('exec '+str(self.old/'phone_service.py')).encode()
    def wait(self,fn):
        end=time.monotonic()+4
        while time.monotonic()<end:
            if fn():return
            time.sleep(.02)
        self.fail('process timeout')
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        # Test cleanup only. Production flat update never uses SIGKILL.
        for pid,token in self.tokens.items():
            if process_token(pid)==token:os.kill(pid,signal.SIGKILL)
        self.p.wait(timeout=3);self.p.stderr.close();self.temp.cleanup()
    def transition(self):return f.transition(self.root,self.old,self.target,self.tokens,self.api,{},self.boot)
    def unchanged(self):
        self.assertIsNone(self.p.poll());self.assertFalse((self.root/'normal-stop-observed').exists())
    def test_flat_paused_stale_work_can_exit_normally_and_preserves_pause(self):
        original=copy.deepcopy(self.j)
        with patch.object(f.os,'kill',wraps=os.kill) as signals:
            ack=self.transition();f.complete(ack)
            self.assertEqual(signals.call_args_list[0].args,(self.host,signal.SIGTERM))
            self.assertEqual(signals.call_count,1)
        self.assertIsNone(process_token(self.host));self.assertIsNotNone(self.p.poll())
        self.assertTrue((self.root/'normal-stop-observed').exists())
        self.assertEqual(h.load(self.path),original);self.assertFalse(ack['requested'])
        self.assertEqual(self.api.calls,['GET snapshot','GET algos']*3)
    def test_installed166_busy_reply_to168_fallback_over_real_request_files(self):
        ack=f.handover_or_flat(self.root,self.old,self.target,self.tokens,self.api,{},self.boot)
        f.complete(ack)
        messages=(self.root/'handover-messages').read_text().splitlines()
        self.assertEqual(messages,['처리 중인 명령/보호 작업이 있어 설치 보류']*2)
        self.assertFalse(ack['requested']);self.assertIsNone(process_token(self.host))
        self.assertEqual(self.api.calls,['GET snapshot','GET algos']*3)
        self.assertFalse((self.root/h.REQUEST).exists())
    def test_nonzero_position_blocks_without_stopping(self):
        self.snap['positions']=[dict(pos='1')]
        with self.assertRaisesRegex(ValueError,'보유·미체결'):self.transition()
        self.unchanged()
    def test_live_order_blocks_without_stopping(self):
        self.snap['orders']=[dict(ordId='pending')]
        with self.assertRaisesRegex(ValueError,'보유·미체결'):self.transition()
        self.unchanged()
    def test_conditional_order_blocks_without_cancelling(self):
        self.algos.append(dict(algoId='unowned'))
        with self.assertRaisesRegex(ValueError,'보유·미체결'):self.transition()
        self.unchanged();self.assertEqual(len(self.algos),1)
    def test_unpaused_intent_never_implicitly_pauses(self):
        self.j['entry_continuity732']['requested']=True;save_json(self.path,self.j)
        with self.assertRaisesRegex(ValueError,'신규 진입 중지'):self.transition()
        self.unchanged();self.assertTrue(h.load(self.path)['entry_continuity732']['requested'])
    def test_pending_local_record_blocks_even_if_exchange_looks_flat(self):
        for field,value in [('owned',{'phase':'submitted'}),('extra_owned',{'phase':'closing'}),
                            ('additional_owned',[{'phase':'active'}]),('manual_closes716',[{'id':'unknown'}])]:
            with self.subTest(field=field):
                j=copy.deepcopy(self.j);j[field]=value;save_json(self.path,j)
                with self.assertRaisesRegex(ValueError,'처리 중인 기록'):self.transition()
                self.unchanged()
    def test_position_arriving_on_second_read_keeps_original_running(self):
        original=self.api.snapshot;count=0
        def snapshot():
            nonlocal count
            count+=1
            if count==2:self.snap['positions']=[dict(pos='1')]
            return original()
        self.api.snapshot=snapshot
        with self.assertRaises(ValueError):self.transition()
        self.unchanged()
    def test_wrong_pid_token_is_never_signalled(self):
        self.tokens[self.host]='incorrect'
        with self.assertRaisesRegex(ValueError,'프로세스'):self.transition()
        self.tokens[self.host]=process_token(self.host);self.unchanged()
    def test_query_failure_before_stop_leaves_original_running(self):
        self.api.callback=Mock(side_effect=OSError('unavailable'))
        with self.assertRaises(OSError):self.transition()
        self.unchanged()
    def test_post_stop_query_failure_restores_original(self):
        original=self.api.snapshot;count=0
        def snapshot():
            nonlocal count
            count+=1
            if count==3:raise OSError('post-stop unavailable')
            return original()
        self.api.snapshot=snapshot
        with patch.object(recovery,'restore_old') as restore,patch.object(recovery,'wait_old_ready') as ready:
            with self.assertRaisesRegex(OSError,'post-stop'):self.transition()
            restore.assert_called_once();ready.assert_called_once_with(self.root,self.old)
        self.assertIsNone(process_token(self.host));self.assertFalse(h.load(self.path)['entry_continuity732']['requested'])
        self.assertEqual(h.load(next(self.root.glob('phone-flat-update-*.json')))['phase'],'complete')
    def test_refused_normal_quit_never_escalates_or_starts_another_owner(self):
        (self.root/'refuse-quit').touch()
        def refused(*_):
            self.wait(lambda:(self.root/'normal-stop-observed').exists())
            raise ValueError('normal quit refused')
        with patch.object(u,'wait_released',side_effect=refused),patch.object(f.os,'kill',wraps=os.kill) as signals,patch.object(recovery,'restore_old') as restore:
            with self.assertRaisesRegex(ValueError,'refused'):self.transition()
            self.assertEqual(signals.call_count,1);self.assertEqual(signals.call_args.args,(self.host,signal.SIGTERM))
            restore.assert_not_called();self.assertIsNone(self.p.poll())
    def test_dead_installer_watchdog_restores_after_all_owners_exit(self):
        ack=self.transition();path=Path(ack['flat_path']);row=h.load(path);row['installer']=[99999999,'missing'];save_json(path,row)
        with patch.object(recovery,'restore_old') as restore,patch.object(recovery,'wait_old_ready'):
            f.recover(path);restore.assert_called_once()
        self.assertEqual(h.load(path)['phase'],'complete')
    def test_watchdog_does_not_replace_live_new_owner(self):
        ack=self.transition();path=Path(ack['flat_path']);row=h.load(path);row['installer']=[99999999,'missing'];save_json(path,row)
        save_json(self.root/'phone_service_status.json',dict(host_pid=12345,state='running',host_process_running=True,remote_process_running=True,observed_at=time.time()))
        with patch.object(f.service,'running',return_value=True),patch.object(recovery,'restore_old') as restore:
            f.recover(path);restore.assert_not_called()


class RetryTests(unittest.TestCase):
    def test_transient_busy_is_retried_before_flat_fallback(self):
        ack={'phase':'released'}
        with patch.object(u,'request_handover',side_effect=[u.HandoverBusy('busy'),ack]) as request,patch.object(f.time,'sleep'),patch.object(f,'transition') as flat:
            self.assertEqual(f.handover_or_flat(*([None]*7)),ack);flat.assert_not_called();self.assertEqual(request.call_count,2)
    def test_repeated_known_busy_uses_flat_checks(self):
        with patch.object(u,'request_handover',side_effect=u.HandoverBusy('busy')),patch.object(f.time,'sleep'),patch.object(f,'transition',return_value={'requested':False}) as flat:
            self.assertFalse(f.handover_or_flat(*([None]*7))['requested']);flat.assert_called_once()
    def test_unrelated_handover_error_never_uses_fallback(self):
        with patch.object(u,'request_handover',side_effect=ValueError('SL mismatch')),patch.object(f,'transition') as flat:
            with self.assertRaisesRegex(ValueError,'SL mismatch'):f.handover_or_flat(*([None]*7))
            flat.assert_not_called()


class BusyEvidence(unittest.TestCase):
    def test_old166_flat_risk_flag_reproduces_generic_block_without_account_read(self):
        case=HandoverTests();case.setUp()
        try:
            path=Path(__file__).resolve().parents[1]/'phone_v166/phone_handover.py'
            spec=importlib.util.spec_from_file_location('old166_handover',path);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
            case.e.handle=Mock();case.e.send=Mock();old.install(case.e,case.root)
            case.e.run_requested=False;case.j['entry_continuity732']['requested']=False;case.j['owned']=None
            case.snap['positions']=[];case.api.algos=[];case.e.queued_risks.add('already-closed-position')
            ack=case.run_handover()
            self.assertEqual(ack['message'],'처리 중인 명령/보호 작업이 있어 설치 보류')
            self.assertEqual(case.api.calls,[]);self.assertFalse(case.e.stop_event.is_set())
        finally:case.doCleanups();case.tearDown()
    def test_new_handover_reports_each_waiting_component(self):
        case=HandoverTests();case.setUp()
        try:
            case.e.queued_risks.add('already-closed-position');case.e.commands.put(('pause',{}))
            ack=case.run_handover()
            self.assertEqual(ack['code'],'busy');self.assertEqual(ack['blockers'],{'대기 명령':1,'위험 감시 표시':1})
            self.assertIn('위험 감시 표시 1',ack['message']);self.assertFalse(case.e.stop_event.is_set())
        finally:case.doCleanups();case.tearDown()


if __name__=='__main__':
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (FlatProcesses,RetryTests,BusyEvidence))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
