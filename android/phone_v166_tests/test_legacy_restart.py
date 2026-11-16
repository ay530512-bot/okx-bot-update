"""Linux process tests: frozen-checkpoint restart, thaw and installer death.

Only disposable child PIDs and temp directories. Fake GET-only account.
"""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import phone_legacy_restart as r
import phone_button_upgrade as u
import phone_handover as h
from phone_account import save_json
from phone_migrate import child_pids,process_token
from test_handover import fixtures,ReadAPI

HOST_SCRIPT='''
import fcntl,json,os,signal,sys,time
from pathlib import Path
from phone_account import save_json
root=Path(sys.argv[1]);fd=(root/'phone_host.lock').open('a');fcntl.flock(fd,fcntl.LOCK_EX)
def pause(*_):
 p=root/'runtime-q2x/bot_state.json';j=json.loads(p.read_text());c=j['entry_continuity732']
 for reason in ('사용자가 신규 진입 중지',):
  c.update(requested=False,event='operator_stop',reason=reason,ms=int(time.time()*1000));c['history'].append(dict(event=c['event'],reason=reason,ms=c['ms']))
 save_json(p,j)
signal.signal(signal.SIGTERM,pause)
while True:
 p=root/'protection-heartbeat.tmp';p.write_text(str(time.monotonic()));p.replace(root/'protection-heartbeat');time.sleep(.03)
'''
SUPERVISOR='''
import fcntl,json,os,signal,subprocess,sys,time
from pathlib import Path
from phone_account import save_json
root=Path(sys.argv[1]);fd=(root/'phone_service.lock').open('a');fcntl.flock(fd,fcntl.LOCK_EX)
p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('phone_host.py')),str(root)])
stop=False
def done(*_):
 global stop
 stop=True
signal.signal(signal.SIGTERM,done)
save_json(root/'phone_service_status.json',dict(pid=os.getpid(),host_pid=p.pid,host_process_running=True,service_version='phone-service-43'))
while not(stop and p.poll() is not None):time.sleep(.03)
'''


class Processes(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.old=self.root/'host-v43';self.old.mkdir();self.target=self.root/'host-v44';self.target.mkdir()
        (self.root/'runtime-q2x').mkdir();(self.old/'phone_host.py').write_text(HOST_SCRIPT);(self.old/'phone_service.py').write_text(SUPERVISOR)
        self.boot=self.root/'.termux/boot/40-okx-home';self.boot.parent.mkdir(parents=True);self.boot.write_text(str(self.old/'phone_service.py'))
        self.j,self.snap,self.algos=fixtures();self.j['owned']['fill_px']=self.j['owned'].pop('avg_px')
        save_json(self.root/'runtime-q2x/bot_state.json',self.j)
        self.api=ReadAPI(self.snap,self.algos)
        self.p=subprocess.Popen([sys.executable,'-B',str(self.old/'phone_service.py'),str(self.root)],env=os.environ.copy(),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.wait(lambda:(self.root/'protection-heartbeat').exists())
        s=h.load(self.root/'phone_service_status.json');self.host=s['host_pid'];self.tokens={pid:process_token(pid) for pid in (self.p.pid,*child_pids(self.p.pid))}
        self.home=patch.object(Path,'home',return_value=self.root);self.home.start()
        self.checks=0;self.change_on=None
        def inspect(api,root,pins):
            self.checks+=1
            if self.checks==self.change_on:api.algos[0]['slTriggerPx']='90'
            return h.validate_protected(h.load(root/'runtime-q2x/bot_state.json'),api.snapshot(),api.pending_algos(full=True))
        self.inspect=patch.object(u,'inspect_account',side_effect=inspect);self.inspect.start()
        # This fixture has no remote daemon/socket. The host sandbox prohibits
        # AF_UNIX; process/lock/heartbeat checks below remain real OS operations.
        self.transport=patch.object(u,'transport_released',return_value=True);self.transport.start()
    def wait(self,fn):
        end=time.monotonic()+5
        while time.monotonic()<end:
            if fn():return
            time.sleep(.03)
        self.fail('process wait timeout')
    def tearDown(self):
        self.home.stop();self.inspect.stop();self.transport.stop()
        for pid,token in self.tokens.items():
            if r.matches(pid,token):os.kill(pid,signal.SIGCONT);os.kill(pid,signal.SIGKILL)
        self.p.wait(timeout=3)
        for p in list(r.WATCHERS):
            try:p.wait(timeout=2);r.WATCHERS.remove(p)
            except subprocess.TimeoutExpired:pass
        self.p.stderr.close();self.temp.cleanup()
    def restart(self):return r.checkpoint_restart(self.root,self.old,self.target,self.tokens,self.api,{})
    def test_preserves_owned_stop_and_original_run_intent(self):
        ack=self.restart();r.complete(ack)
        self.assertIsNotNone(self.p.poll());self.assertIsNone(process_token(self.host))
        after=h.load(self.root/'runtime-q2x/bot_state.json')
        self.assertEqual(after['owned'],self.j['owned']);self.assertEqual(after['seen_signals'],self.j['seen_signals'])
        self.assertTrue(after['entry_continuity732']['requested']);self.assertTrue(ack['requested'])
        self.assertEqual(self.checks,3);self.assertTrue(all(x.startswith('GET ') for x in self.api.calls))
    def test_original_pause_is_preserved(self):
        self.j['entry_continuity732']['requested']=False;save_json(self.root/'runtime-q2x/bot_state.json',self.j)
        ack=self.restart();r.complete(ack)
        self.assertFalse(h.load(self.root/'runtime-q2x/bot_state.json')['entry_continuity732']['requested'])
    def test_changed_stop_thaws_original_manager_without_kill(self):
        self.change_on=3
        with self.assertRaisesRegex(ValueError,'손절'):self.restart()
        self.assertTrue(r.matches(self.host,self.tokens[self.host]));self.assertFalse(r.frozen(self.host,self.tokens[self.host]))
        before=float((self.root/'protection-heartbeat').read_text());self.wait(lambda:float((self.root/'protection-heartbeat').read_text())>before)
        self.assertEqual(h.load(self.root/'runtime-q2x/bot_state.json')['owned'],self.j['owned'])
    def test_missing_stop_blocks_before_pausing(self):
        self.api.algos=[]
        with self.assertRaises(ValueError):self.restart()
        self.assertEqual(h.load(self.root/'runtime-q2x/bot_state.json'),self.j)
        self.assertIsNone(self.p.poll())
    def test_dead_installer_watchdog_thaws_both_processes(self):
        row=dict(phase='prepared',installer=[99999999,'missing'],host=[self.host,self.tokens[self.host]],supervisor=[self.p.pid,self.tokens[self.p.pid]],deadline=time.monotonic()+60)
        path=self.root/'watchdog.json';save_json(path,row)
        for pid,token in (row['host'],row['supervisor']):r.signal_exact(pid,token,signal.SIGSTOP)
        self.wait(lambda:r.frozen(self.host,self.tokens[self.host]))
        r.recover(path)
        self.assertEqual(h.load(path)['phase'],'aborted');self.assertFalse(r.frozen(self.host,self.tokens[self.host]));self.assertIsNone(self.p.poll())
    def test_wrong_pid_token_never_signals(self):
        with self.assertRaises(ValueError):r.signal_exact(self.host,'not-the-start-token',signal.SIGKILL)
        self.assertIsNone(self.p.poll())
    def test_user_stop_during_preflight_wins_over_resume(self):
        def operator_stop():
            j=h.load(self.root/'runtime-q2x/bot_state.json');c=j['entry_continuity732'];c['requested']=False
            c['history'].append(dict(event='operator_stop',reason='사용자가 신규 진입 중지',ms=2))
            save_json(self.root/'runtime-q2x/bot_state.json',j)
        self.api.callback=operator_stop
        ack=self.restart();r.complete(ack)
        self.assertFalse(ack['requested'])
    def test_committed_installer_death_retires_old_then_recovers(self):
        row=dict(phase='committed',installer=[99999999,'missing'],host=[self.host,self.tokens[self.host]],
            supervisor=[self.p.pid,self.tokens[self.p.pid]],children=[],deadline=time.monotonic()+60,
            old=str(self.old),target=str(self.target),boot_hex=self.boot.read_bytes().hex())
        path=self.root/'committed.json';save_json(path,row)
        for pid,token in (row['host'],row['supervisor']):r.signal_exact(pid,token,signal.SIGSTOP)
        self.wait(lambda:r.frozen(self.host,self.tokens[self.host]))
        with patch.object(r,'transport_released',return_value=True),patch.object(r,'restore_old') as restore:
            r.recover(path)
            restore.assert_called_once()
        self.assertIsNone(process_token(self.host));self.assertEqual(h.load(path)['phase'],'complete')
    def test_expired_freeze_lease_thaws_even_with_live_installer(self):
        row=dict(phase='prepared',installer=[os.getpid(),process_token(os.getpid())],host=[self.host,self.tokens[self.host]],
            supervisor=[self.p.pid,self.tokens[self.p.pid]],deadline=time.monotonic()-1)
        path=self.root/'expired.json';save_json(path,row)
        for pid,token in (row['host'],row['supervisor']):r.signal_exact(pid,token,signal.SIGSTOP)
        self.wait(lambda:r.frozen(self.host,self.tokens[self.host]))
        r.recover(path)
        self.assertEqual(h.load(path)['phase'],'aborted');self.assertFalse(r.frozen(self.host,self.tokens[self.host]))

if __name__=='__main__':unittest.main()
