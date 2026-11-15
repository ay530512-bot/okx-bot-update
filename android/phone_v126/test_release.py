"""Actual v23 updater -> v24 installer compatibility; downloads mocked, no install."""
import hashlib, importlib.util, json, os, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, os.environ['OKX_TEST_HOST'])
import phone_button_upgrade as upgrade

BASE=Path(__file__).resolve().parents[2]
ROOT=BASE.parent/'fixture121'
INSTALLER=BASE/'android/phone_1_2_6_setup.py'

class Release(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('old_updater126',ROOT/'host-v23/phone_update.py')
        self.old=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.old)
        raw=INSTALLER.read_bytes();self.raw=raw
        self.manifest=dict(format='okx-phone-release-1',version=24,display_version='1.2.6',from_versions=[23],
            installer='android/phone_1_2_6_setup.py',sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),commit='a'*40,notes='test')
        self.command=dict(request_id='fixture',owner='fixture',issued_at=time.monotonic())
        self.updater=self.old.PhoneUpdater('/tmp',NS(complete_control=lambda _:None))

    def test_old_button_accepts_new_release_and_verifies_installer(self):
        with patch.object(self.old,'download',side_effect=[json.dumps(self.manifest).encode(),self.raw]):
            self.updater.check(self.command)
        self.assertEqual(self.updater.state['target_version'],'1.2.6')
        self.assertEqual(self.updater.candidate['raw'],self.raw)
        self.assertFalse(self.updater.installing)

    def test_modified_download_is_rejected_before_execution(self):
        with patch.object(self.old,'download',side_effect=[json.dumps(self.manifest).encode(),self.raw+b'\n']):
            with self.assertRaisesRegex(ValueError,'설치 파일 검증 실패'):
                self.updater.check(self.command)
        self.assertIsNone(self.updater.candidate)

    def test_actual_predecessor_files_and_boot_registration_match(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);boot=home/'.termux/boot/40-okx-home';boot.parent.mkdir(parents=True)
            boot.write_text(str(ROOT/'host-v23/phone_service.py'))
            with patch.object(Path,'home',return_value=home):
                self.assertEqual(upgrade.verify_old(ROOT),ROOT/'host-v23')

if __name__=='__main__':unittest.main(verbosity=2)
