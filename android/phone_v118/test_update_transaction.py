"""Transactional updater fault tests; exchange and process boundaries mocked."""
import contextlib
import base64
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import phone_button_upgrade as u
import phone_handover as h
from test_handover import fixtures


class Transactions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.root=self.home/'okx-phone';(self.root/'runtime-q2x').mkdir(parents=True)
        self.old=self.root/'host-v15';self.old.mkdir()
        self.new=self.root/'host-v16';self.new.mkdir()
        # Protocol-capable fixture (production predecessor v15 remains legacy).
        (self.old/'phone_handover.py').write_text('fixture')
        self.boot=self.home/'.termux/boot/40-okx-home';self.boot.parent.mkdir(parents=True)
        self.boot.write_text('old exact boot')
        self.j,self.snap,self.algos=fixtures()
        h.save_json(u.journal_path(self.root),self.j)
        h.save_json(self.root/'phone_service_status.json',{'service_version':'phone-service-15'})
        h.save_json(self.root/'phone_credentials.json',{})
        self.events=[]
    def tearDown(self):self.temp.cleanup()
    def run_update(self, fail=None, paused=False, current=False):
        if paused:
            self.j['entry_continuity732']['requested']=False
            h.save_json(u.journal_path(self.root),self.j)
        if current:h.save_json(self.root/'phone_service_status.json',{'service_version':u.service.VERSION})
        def step(name, result=None):
            def f(*args,**kw):
                self.events.append(name)
                if fail==name:raise ValueError('fixture failure '+name)
                return result
            return f
        ack=dict(phase='released',nonce='a'*32,journal_sha=h.digest(self.j),requested=not paused)
        mocks=[patch.object(Path,'home',return_value=self.home),patch.object(u,'HERE',self.new),
            patch.object(u,'verify_old',return_value=self.old),
            patch.object(u,'verified_installation',side_effect=step('verify',(None,{}))),
            patch.object(u,'running_tokens',return_value={123:'token'}),
            patch.object(u,'inspect_account',side_effect=step('inspect','same')),
            patch.object(u,'request_handover',side_effect=step('handover',ack)),
            patch.object(u,'wait_released',side_effect=step('released')),
            patch.object(u,'readonly_client',return_value=Mock()),
            patch.object(u,'validate_keys',return_value={}),
            patch.object(u.service,'running',return_value=True),
            patch.object(u.service,'config',return_value={'mode':'run','enabled':True}),
            patch.object(u.service,'boot_script',side_effect=step('boot')),
            patch.object(u.service,'start',side_effect=step('start')),
            patch.object(u,'wait_ready',side_effect=step('ready')),
            patch.object(u,'rollback',side_effect=step('rollback'))]
        error=None
        with contextlib.ExitStack() as st,contextlib.redirect_stdout(io.StringIO()):
            for m in mocks:st.enter_context(m)
            try:u.upgrade(self.root)
            except Exception as exc:error=exc
        return error
    def test_owned_positions_install_without_manual_pause_or_journal_change(self):
        before=u.journal_path(self.root).read_bytes()
        self.assertIsNone(self.run_update())
        self.assertEqual(self.events,['verify','inspect','handover','released','verify','boot','start','ready'])
        self.assertEqual(u.journal_path(self.root).read_bytes(),before)
        self.assertTrue(h.load(self.root/'phone_update_result.json')['resume_requested'])
    def test_paused_owned_positions_install_still_paused(self):
        self.assertIsNone(self.run_update(paused=True))
        self.assertFalse(h.load(self.root/'phone_update_result.json')['resume_requested'])
        self.assertEqual(h.load(u.journal_path(self.root))['owned'],self.j['owned'])
    def test_no_restart_if_preflight_or_handover_fails(self):
        for fail in ('inspect','handover','released'):
            self.events=[]
            self.assertIsInstance(self.run_update(fail),ValueError)
            self.assertNotIn('start',self.events)
            self.assertNotIn('boot',self.events)
            self.assertEqual(h.load(u.journal_path(self.root))['owned'],self.j['owned'])
    def test_new_start_failure_rolls_back_with_positions_intact(self):
        for fail in ('boot','start','ready'):
            self.events=[]
            self.assertIsInstance(self.run_update(fail),ValueError)
            self.assertEqual(self.events[-1],'rollback')
            self.assertEqual(h.load(u.journal_path(self.root)),self.j)
            self.assertEqual(h.load(self.root/'phone_update_result.json')['phase'],'rolled_back')
    def test_same_version_install_noop_while_active_with_positions(self):
        self.assertIsNone(self.run_update(current=True))
        self.assertEqual(self.events,[])
    def test_rollback_does_not_kill_new_manager_that_refuses_handover(self):
        h.save_json(self.root/'phone_service_status.json',{'service_version':u.service.VERSION})
        with patch.object(u.service,'running',return_value=True), \
             patch.object(u,'running_tokens',return_value={}), \
             patch.object(u,'request_handover',side_effect=ValueError('protecting')), \
             patch.object(u.subprocess,'run') as start:
            with self.assertRaises(ValueError):u.rollback(self.root,self.old,self.boot,b'old boot')
            start.assert_not_called()
            self.assertEqual(self.boot.read_text(),'old exact boot')
    def test_rollback_restores_exact_boot_after_new_process_exit(self):
        ack={'nonce':'x'}
        h.save_json(self.root/'phone_service_status.json',{'service_version':u.service.VERSION})
        with patch.object(u.service,'running',return_value=True), \
             patch.object(u,'running_tokens',return_value={}), \
             patch.object(u,'request_handover',return_value=ack), \
             patch.object(u,'wait_released') as released, \
             patch.object(u.subprocess,'run') as start:
            u.rollback(self.root,self.old,self.boot,b'original exact boot\n')
            released.assert_called_once()
            self.assertEqual(self.boot.read_bytes(),b'original exact boot\n')
            self.assertIn(str(self.old/'phone_service.py'),start.call_args.args[0])
            self.assertEqual(h.load(u.journal_path(self.root)),self.j)

    def test_orphaned_installer_recovers_previous_only_after_locks_release(self):
        # Simulated previous owner is the module folder; all broker/journal data
        # remains untouched. No network or signals in the recovery path.
        folder=Path(h.__file__).resolve().parent
        root=folder.parent
        r=dict(old=str(folder),target=str(folder.parent/'host-v17'),boot=str(self.boot),
               boot_before=base64.b64encode(b'original boot').decode(),nonce='a'*32,
               installer_pid=888,installer_token='old-installer',host_pid=999,host_token='old-host')
        ack=dict(nonce='a'*32,phase='released')
        self.boot.write_text(str(folder/'phone_service.py'))
        events=[]
        def fake_load(path):
            if path.name==h.ACK:return ack
            if path.name=='phone_service_status.json':return {}
            return r
        with (patch.object(h,'load',side_effect=fake_load), \
             patch.object(h.Path,'exists',return_value=True), \
             patch.object(h,'process_token',return_value=None), \
             patch.object(u.service,'running',return_value=False), \
             patch.object(u.service,'lock',return_value=contextlib.nullcontext()), \
             patch('phone_migrate.transport_released',return_value=True), \
             patch.object(u,'apply_late_stop',side_effect=lambda *a:events.append('stop-intent')),
             patch('phone_account.atomic_private',side_effect=lambda *a:events.append('restore-boot')),
             patch.object(u.service,'start',side_effect=lambda *a,**k:events.append('start')),
             patch.object(h,'save_json')):
            h.recover(root/'recovery-fixture.json')
        self.assertEqual(events,['stop-intent','restore-boot','start'])


if __name__=='__main__':unittest.main()
