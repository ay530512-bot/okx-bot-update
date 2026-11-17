"""Actual Linux button ancestry, regression reproduction and stale recovery.

All processes are disposable fixtures. Exchange reads are fake, no credentials.
"""
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import phone_legacy_restart as r
import phone_handover as h
from phone_account import save_json
from phone_migrate import process_token,child_pids
import test_legacy_restart as base

DRIVER='''
import importlib.util,json,os,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[4])
import phone_legacy_restart as r,phone_button_upgrade as u,phone_handover as h
from phone_migrate import process_token,child_pids
from test_handover import fixtures,ReadAPI
root=Path(sys.argv[1]);old=root/'host-v43';target=root/'host-v44'
if sys.argv[2]=='broken':
 spec=importlib.util.spec_from_file_location('broken_restart',sys.argv[3]);r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
j,s,a=fixtures();api=ReadAPI(s,a)
state=h.load(root/'phone_service_status.json');pid=state['pid']
tokens={p:process_token(p) for p in [pid,*child_pids(pid)]}
(root/'driver-pid').write_text(str(os.getpid()))
def inspect(api,root,pins):return h.validate_protected(h.load(root/'runtime-q2x/bot_state.json'),api.snapshot(),api.pending_algos(full=True))
with patch.object(Path,'home',return_value=root),patch.object(u,'inspect_account',side_effect=inspect),patch.object(u,'transport_released',return_value=True):
 ack=r.checkpoint_restart(root,old,target,tokens,api,{})
 r.complete(ack)
 (root/'driver-result').write_text(json.dumps(ack))
'''
OUTER='''
import json,os,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);(root/'outer-pid').write_text(str(os.getpid()))
p=subprocess.Popen([sys.executable,'-B',str(root/'driver.py'),str(root),*sys.argv[2:]])
(root/'driver-code').write_text(str(p.wait()))
'''


def idle_worker(pipe):
    pipe.send(os.getpid())
    while True:time.sleep(.1)


class Ancestry(unittest.TestCase):
    wait=base.Processes.wait
    def setUp(self):
        original=base.HOST_SCRIPT
        base.HOST_SCRIPT=original.replace('import fcntl,json,os,signal,sys,time','import fcntl,json,os,signal,sys,time,subprocess').replace(
            'while True:\n', '''while True:
 if (root/'button.json').exists():
  cmd=json.loads((root/'button.json').read_text());(root/'button.json').unlink()
  subprocess.Popen(cmd,start_new_session=True)
''')
        try:base.Processes.setUp(self)
        finally:base.HOST_SCRIPT=original
        (self.root/'driver.py').write_text(DRIVER);(self.root/'outer.py').write_text(OUTER)
        self.pids=[]
    def tearDown(self):
        for name in ('outer-pid','driver-pid'):
            path=self.root/name
            if path.exists():
                pid=int(path.read_text());token=process_token(pid)
                if token:self.pids.append((pid,token))
        for pid,token in self.pids:
            if r.matches(pid,token):os.kill(pid,signal.SIGKILL)
        base.Processes.tearDown(self)
    def button(self,version):
        old=Path(__file__).resolve().parents[1]/'phone_v154/phone_legacy_restart.py'
        save_json(self.root/'button.json',[sys.executable,'-B',str(self.root/'outer.py'),str(self.root),version,str(old),str(Path(__file__).resolve().parent)])
        if version=='broken':
            self.wait(lambda:(self.root/'driver-pid').exists())
            self.wait(lambda:process_token(int((self.root/'driver-pid').read_text())) is None)
            return None
        self.wait(lambda:(self.root/'driver-code').exists())
        return int((self.root/'driver-code').read_text())
    def test_fixed_button_descendant_survives_and_restores_intent(self):
        self.assertEqual(self.button('fixed'),0)
        ack=h.load(self.root/'driver-result');self.assertTrue(ack['requested'])
        row=h.load(Path(ack['checkpoint_path']))
        self.assertEqual(row['phase'],'complete');self.assertEqual(row['children'],[])
        self.assertIsNone(process_token(self.host));self.assertIsNone(process_token(self.p.pid))
        self.assertTrue(h.load(self.root/'runtime-q2x/bot_state.json')['entry_continuity732']['requested'])
    def test_reproduces_154_self_termination_then_repairs_frozen_supervisor(self):
        self.button('broken')
        self.assertFalse((self.root/'driver-result').exists())
        self.wait(lambda:process_token(self.host) is None)
        self.assertTrue(r.frozen(self.p.pid,self.tokens[self.p.pid]))
        path=next(self.root.glob('phone-legacy-restart-*.json'));row=h.load(path)
        self.assertEqual(row['phase'],'committed')
        original=self.p
        # Real process/lock restart, but no production service or exchange API.
        def restore(root,row):
            self.assertIsNone(process_token(self.host))
            original.wait(timeout=3);original.stderr.close()
            script=(self.old/'phone_service.py').read_text().replace("service_version='phone-service-43'", "service_version='phone-service-43',state='running',remote_process_running=True,observed_at=time.time()")
            (self.old/'phone_service.py').write_text(script)
            self.p=subprocess.Popen([sys.executable,'-B',str(self.old/'phone_service.py'),str(root)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        # Stale service status is deliberately retained: ordinary upgrade would
        # reject it, so repair must precede running_tokens/freshness checks.
        with patch.object(r,'restore_old',side_effect=restore):r.repair_stalled(self.root,self.old)
        s=h.load(self.root/'phone_service_status.json');self.host=s['host_pid']
        self.tokens={p:process_token(p) for p in [self.p.pid,*child_pids(self.p.pid)]}
        self.assertEqual(h.load(path)['phase'],'complete')
        self.assertFalse(h.load(self.root/'runtime-q2x/bot_state.json')['entry_continuity732']['requested'])
        self.assertFalse(r.frozen(self.p.pid,self.tokens[self.p.pid]))
        before=float((self.root/'protection-heartbeat').read_text())
        self.wait(lambda:float((self.root/'protection-heartbeat').read_text())>before)
        # Recovery is repeatable; it must not signal this replacement manager.
        r.repair_stalled(self.root,self.old);self.assertIsNone(self.p.poll())
        # Simulate death after the old manager restarted but before final marker.
        seen=h.load(path);seen['phase']='committed';seen['installer']=[99999999,'gone'];save_json(path,seen)
        r.repair_stalled(self.root,self.old)
        self.assertEqual(h.load(path)['phase'],'complete');self.assertIsNone(self.p.poll())
    def test_unsafe_154_children_never_include_installer_or_watchdog(self):
        pairs=[[os.getpid(),process_token(os.getpid())],[self.p.pid,self.tokens[self.p.pid]],[self.host,self.tokens[self.host]]]
        self.assertEqual(r.calculation_workers(pairs),[])
    def test_pid_reuse_cannot_retire_other_process(self):
        self.assertEqual(r.calculation_workers([[self.host,'wrong-start-token']]),[])
    def test_real_spawn_workers_with_inherited_B_flag_are_retired(self):
        ctx=mp.get_context('spawn');workers=[];pairs=[]
        try:
            for i in range(4):
                a,b=ctx.Pipe();p=ctx.Process(target=idle_worker,args=(b,));p.start();b.close()
                workers.append((p,a));self.assertTrue(a.poll(10));self.assertEqual(a.recv(),p.pid)
                pairs.append([p.pid,process_token(p.pid)])
            self.assertEqual(r.calculation_workers(pairs),pairs)
            row=dict(host=[99999998,'gone'],supervisor=[99999999,'gone'],
                     children=[*pairs,[os.getpid(),process_token(os.getpid())]])
            r.retire(row)
            for p,a in workers:p.join(timeout=3);self.assertFalse(p.is_alive())
        finally:
            for p,a in workers:
                if p.is_alive():p.kill()
                p.join(timeout=3);a.close()


if __name__=='__main__':unittest.main(verbosity=2)
