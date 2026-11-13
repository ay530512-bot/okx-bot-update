import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import phone_update as update

RAW=b"print('fixture only')\n"
def manifest(**kw):
    return dict(format='okx-phone-release-1',version=9,notes='fixture',commit='a'*40,
                installer='android/release9.py',sha256=hashlib.sha256(RAW).hexdigest(),
                bytes=len(RAW),from_versions=[8],**kw)

class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.mobile=Mock()
        self.manager=update.PhoneUpdater(self.root,self.mobile)
        self.cmd=dict(request_id='request',owner='owner',issued_at=time.monotonic())
    def tearDown(self): self.temp.cleanup()
    def check(self,m=None,raw=RAW):
        with patch.object(update,'download',side_effect=[json.dumps(m or manifest()).encode(),raw]) as fetch:
            self.manager.check(self.cmd)
            return fetch.call_count
    def test_current_version_only_checks_manifest(self):
        m=manifest();m['version']=8
        self.assertEqual(self.check(m),1)
        self.assertIsNone(self.manager.candidate)
    def test_valid_download_and_ticket(self):
        self.assertEqual(self.check(),2)
        self.assertEqual(self.manager.candidate['raw'],RAW)
        self.assertTrue(self.manager.snapshot()['ticket'])
    def test_hash_or_length_mismatch_rejected(self):
        for raw in (b'wrong',RAW+b'x'):
            with self.assertRaises(ValueError):self.check(raw=raw)
    def test_manifest_fail_closed(self):
        for key,val in [('version',7),('version',True),('format','pc'),('commit','main'),
                        ('installer','https://bad/file.py'),('installer','android/../file.py'),
                        ('sha256','bad'),('bytes',2_000_001),('from_versions',[7])]:
            m=manifest();m[key]=val
            with self.subTest(key=key),self.assertRaises(ValueError):update.validate_manifest(m)
    def test_wrong_owner_expired_ticket_do_not_launch(self):
        self.check()
        ticket=self.manager.snapshot()['ticket']
        with patch.object(update.subprocess,'Popen') as process:
            for cmd in (dict(self.cmd,ticket='wrong'),dict(self.cmd,ticket=ticket,owner='other')):
                with self.assertRaises(ValueError):self.manager.install(cmd)
            self.manager.candidate['expires']=0
            with self.assertRaises(ValueError):self.manager.install(dict(self.cmd,ticket=ticket))
            process.assert_not_called()
    def test_active_entry_blocks_install_without_launch(self):
        self.check(); ticket=self.manager.snapshot()['ticket']
        (self.root/'runtime-q2x').mkdir()
        (self.root/'runtime-q2x/bot_state.json').write_text(json.dumps(dict(version=1,owned=None,
            entry_continuity732=dict(schema=1,requested=True))))
        with patch.object(update.subprocess,'Popen') as process:
            with self.assertRaises(ValueError):self.manager.install(dict(self.cmd,ticket=ticket))
            process.assert_not_called()
    def test_detached_installer_and_single_use_ticket(self):
        self.check(); ticket=self.manager.snapshot()['ticket']
        child=Mock();child.wait.return_value=0
        with patch('phone_button_upgrade.require_paused_flat_journal'),patch.object(update.subprocess,'Popen',return_value=child) as process:
            self.manager.install(dict(self.cmd,ticket=ticket))
            self.assertTrue(process.call_args.kwargs['start_new_session'])
            self.assertEqual(Path(process.call_args.args[0][-1]).read_bytes(),RAW)
            with self.assertRaises(ValueError):self.manager.install(dict(self.cmd,ticket=ticket))
            self.assertEqual(process.call_count,1)
    def test_busy_or_stale_does_not_start_thread(self):
        with patch.object(update.threading,'Thread') as thread:
            self.manager.request(dict(self.cmd,issued_at=time.monotonic()-31))
            self.manager.state['busy']=True;self.manager.request(self.cmd)
            thread.assert_not_called()
    def test_no_redirect(self):
        with self.assertRaises(ValueError):update.NoRedirect().redirect_request(None)

if __name__=='__main__':unittest.main()
