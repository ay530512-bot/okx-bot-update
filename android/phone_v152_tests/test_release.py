import ast,hashlib,importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
D=Path(__file__).resolve().parents[1];HOST=D/'phone_v152';CORE=D.parent.parent/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class Tests(unittest.TestCase):
 def test_complete_bundle_preserves_policy_hashes_stages_once(self):
  old=load('old140',D/'phone_1_4_2_setup.py');new=load('new150',D/'phone_1_5_2_setup.py')
  previous={n:v.encode() for n,v in old.PAYLOAD.items()};files=new.candidate(previous)
  self.assertEqual(new.PINNED_BY_HOST['host-v39'],{n:hashlib.sha256(v).hexdigest() for n,v in previous.items()})
  self.assertEqual(files,{p.name:p.read_bytes() for p in HOST.iterdir() if p.is_file()})
  for n in ('phone_sources.json','phone_pullback_size.py','phone_mobile_policy.py','phone_exit_details.py','phone_handover.py','phone_market_alerts.py'):
   self.assertEqual(files[n],previous[n],n)
  self.assertNotIn('phone_candidate_fast.py',files)
  for n in ('phone_mobile_entry.py','phone_mobile_policy.py','phone_mobile_compute.py','phone_quote_registry.py'):
   tree=ast.parse(files[n]);self.assertFalse(any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id in ('exec','eval') for x in ast.walk(tree)))
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);folder=root/'host-v39';folder.mkdir()
   for n,v in previous.items():(folder/n).write_bytes(v)
   self.assertEqual(new.read_pins(root),previous)
   dest=new.stage(root,files);self.assertEqual(dest.name,'host-v42');self.assertEqual(new.stage(root,files),dest)
   (folder/'phone_host.py').write_text('modified')
   with self.assertRaises(ValueError):new.read_pins(root)
  self.assertIn("'host-v39', 'host-v40', 'host-v41')",files['phone_button_upgrade.py'].decode())
  self.assertIn('CURRENT = 42',files['phone_update.py'].decode())
 def test_direct_151_upgrade_and_all_unrelated_files_are_identical(self):
  old=load('direct151',D/'phone_1_5_1_setup.py');new=load('direct152',D/'phone_1_5_2_setup.py')
  previous={n:v.encode() for n,v in old.PAYLOAD.items()};files=new.candidate(previous)
  allowed={'phone_button_old_sources.json','phone_button_upgrade.py','phone_mobile.py','phone_restore_previous.py','phone_runtime_health.py','phone_service.py','phone_update.py','phone_host.py','phone_public_ws.py','phone_public_lanes.py','phone_connection_trace.py','phone_entry_feed.py','phone_diagnostic_export.py','phone_update_ui.js'}
  self.assertEqual(set(files)-set(previous),{'phone_public_lanes.py'})
  for name in set(previous)-allowed:self.assertEqual(files[name],previous[name],name)
  self.assertEqual(new.PINNED_BY_HOST['host-v41'],{n:hashlib.sha256(v).hexdigest() for n,v in previous.items()})
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);prev=root/'host-v41';prev.mkdir()
   for n,v in previous.items():(prev/n).write_bytes(v)
   self.assertEqual(new.read_pins(root),previous)
   self.assertEqual(new.stage(root,new.candidate(new.read_pins(root))).name,'host-v42')
 def test_trend_predicates_quantity_and_management_unchanged(self):
  def funcs(path):return {n.name:ast.dump(n) for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef)}
  old=funcs(D.parent.parent/'regression_hosts/phone_v142/phone_trend_slot.py');new=funcs(HOST/'phone_trend_slot.py')
  for n in old:
   if n not in ('scan','snapshot_ranks','slot_counts','require_slot','install'):self.assertEqual(old[n],new[n],n)
 def test_restore_verifies_full_previous_payload(self):
  import phone_restore_previous as r
  old=load('restore140',D/'phone_1_4_2_setup.py')
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);prev=root/'host-v39';prev.mkdir()
   for n,v in old.PAYLOAD.items():(prev/n).write_text(v)
   boot=('exec '+str(prev/'phone_service.py')+' --boot\n').encode()
   data=dict(host='host-v39',boot_hex=boot.hex(),boot_sha256=hashlib.sha256(boot).hexdigest())
   (root/'phone_mobile152_previous.json').write_text(json.dumps(data))
   self.assertEqual(r.verify(root),(prev,boot))
   (prev/'phone_host.py').write_text('bad')
   with self.assertRaisesRegex(ValueError,'원본이 변경'):r.verify(root)
 def test_production_install_order_uses_one_coordinator(self):
  import phone_pullback_size,phone_public_ws,phone_performance,phone_trend_slot,phone_exit_details,phone_entry_feed
  import okx_channel701 as ch
  from phone_mobile_entry import Coordinator
  from phone_mobile_compute import Manager
  pins=json.loads((HOST/'phone_sources.json').read_text())
  for n,h in pins['files'].items():self.assertEqual(hashlib.sha256((CORE/n).read_bytes()).hexdigest(),h)
  with tempfile.TemporaryDirectory() as td:
   phone_pullback_size.install(CORE);phone_public_ws.install();__import__('phone_public_lanes').install()
   timer=phone_performance.install_before_engine(Path(td));owner=ch.candidate
   phone_trend_slot.install(CORE);phone_exit_details.install(CORE);phone_entry_feed.install()
   self.assertIs(ch.candidate,owner);self.assertIsInstance(owner,Coordinator);self.assertIsInstance(timer.parallel,Manager)
   timer.parallel.close()
if __name__=='__main__':unittest.main(verbosity=2)
