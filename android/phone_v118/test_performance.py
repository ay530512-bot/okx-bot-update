import ast, hashlib, inspect, json, os, sys, tempfile, textwrap, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import phone_performance as perf

class PerfTests(unittest.TestCase):
 def test_exclusive_timing_and_exceptions(self):
  clock=[0.];t=perf.Timing('/tmp',clock=lambda:clock[0])
  with t.scope('outer'):
   clock[0]=1
   with t.scope('inner'):clock[0]=3
   clock[0]=5
  rows={r['label']:r for r in t.report()['metrics']}
  self.assertEqual(rows['outer']['total_s'],5)
  self.assertEqual(rows['outer']['self_s'],3)
  self.assertEqual(rows['inner']['total_s'],2)
  with self.assertRaises(ValueError):
   with t.scope('failure'):raise ValueError('private text must not be recorded')
  self.assertNotIn('private text',json.dumps(t.report()))
  self.assertEqual(next(r for r in t.report()['metrics'] if r['label']=='failure')['errors'],1)
 def engine(self,record=None):
  return SimpleNamespace(enabled=True,user_paused=False,recovering=False,journal=SimpleNamespace(data={'owned':record}),slot_count=lambda:4)
 def test_only_intermediate_empty_normal_slots_skipped(self):
  t=perf.Timing('/tmp');t.local.group='optimized';e=self.engine()
  self.assertEqual([t.skip_empty(e,s) for s in range(4)],[True,True,True,False])
  for record in ({'phase':'active'},{'phase':'protecting'},{'phase':'pending'}):
   e.journal.data['owned']=record
   self.assertFalse(any(t.skip_empty(e,s) for s in range(4)))
  e.journal.data['owned']=None
  for attr,val in (('recovering',True),('user_paused',True),('enabled',False)):
   e=self.engine();setattr(e,attr,val)
   self.assertFalse(any(t.skip_empty(e,s) for s in range(4)))
  t.local.group='baseline';self.assertFalse(t.skip_empty(self.engine(),0))
 def test_five_successful_baselines_before_optimization(self):
  t=perf.Timing('/tmp');t.optimization_enabled=True;e=self.engine();seen=[]
  for _ in range(6):t.tick(e,lambda:seen.append(t.local.group))
  self.assertEqual(seen,['baseline']*5+['optimized'])
  with self.assertRaises(RuntimeError):t.tick(e,lambda:(_ for _ in ()).throw(RuntimeError()))
  self.assertEqual(t.local.group,'background')
 def test_thread_local_samples(self):
  t=perf.Timing('/tmp')
  def one():
   for _ in range(100):
    with t.scope('worker'):pass
  threads=[threading.Thread(target=one) for _ in range(4)]
  for th in threads:th.start()
  for th in threads:th.join()
  self.assertEqual(t.report()['metrics'][0]['calls'],400)
 def test_actual_tick_ast_unchanged_except_guard(self):
  core=Path(os.environ['OKX_TEST_CORE']);sys.path.insert(0,str(core))
  from okx_v5 import RuleEngine
  original=RuleEngine.tick
  source=textwrap.dedent(inspect.getsource(original));tree=ast.parse(source)
  captured={}
  real_compile=compile
  def compile_capture(obj,*args,**kw):
   if isinstance(obj,ast.AST):captured['tree']=obj
   return real_compile(obj,*args,**kw)
  from unittest.mock import patch
  pins=json.loads(Path(perf.__file__).with_name('phone_sources.json').read_text())
  with patch('builtins.compile',side_effect=compile_capture):perf.patch_tick(RuleEngine,pins['files']['okx_v5.py'])
  changed=captured['tree'];removed=0
  for n in ast.walk(changed):
   if isinstance(n,ast.Try) and n.body and isinstance(n.body[0],ast.If) and '_phone_perf.skip_empty' in ast.unparse(n.body[0].test):
    n.body.pop(0);removed+=1
  self.assertEqual(removed,1)
  self.assertEqual(ast.dump(tree,include_attributes=False),ast.dump(changed,include_attributes=False))
  RuleEngine.tick=original
  with self.assertRaises(ValueError):perf.patch_tick(RuleEngine,'0'*64)
 def test_flat_snapshot_call_count(self):
  # Initial read + four slots. Last-slot and every occupied-slot read retained.
  t=perf.Timing('/tmp');e=self.engine()
  counts={}
  for mode in ('baseline','optimized'):
   t.local.group=mode;calls=1
   for slot in range(4):
    if t.skip_empty(e,slot):continue
    calls+=1
   counts[mode]=calls
  self.assertEqual(counts,{'baseline':5,'optimized':2})

if __name__=='__main__':unittest.main()
