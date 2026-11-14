import tempfile, unittest, shutil
from pathlib import Path
from unittest.mock import patch
import phone_button_upgrade as u
class Predecessors(unittest.TestCase):
 def test_both_exact_predecessors_and_tamper(self):
  base=Path(__file__).resolve().parent.parent
  for version,folder in ((13,'phone_v115'),(14,'phone_v116'),(15,'phone_v117')):
   with tempfile.TemporaryDirectory() as t:
    home=Path(t);root=home/'okx-phone';old=root/f'host-v{version}'
    old.mkdir(parents=True);boot=home/'.termux/boot/40-okx-home';boot.parent.mkdir(parents=True)
    pins=u.read_json(Path(u.HERE)/'phone_button_old_sources.json')[old.name]
    for n in pins:shutil.copyfile(base/folder/n,old/n)
    boot.write_text(str(old/'phone_service.py')+' --boot')
    with patch.object(Path,'home',return_value=home):
     self.assertEqual(u.verify_old(root),old)
     (old/'phone_mobile.py').write_text('changed')
     with self.assertRaises(ValueError):u.verify_old(root)
if __name__=='__main__':unittest.main()
