import ast,importlib.util,json,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[2];D=ROOT/'android';sys.path[:0]=[str(D/'phone_v164'),str(ROOT.parent/'core121')]
import phone_trend_slot as t
from okx_core import BotError
KST=timezone(timedelta(hours=9))
def ms(s):return int(datetime.fromisoformat(s).replace(tzinfo=KST).timestamp()*1000)
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
class Tests(unittest.TestCase):
 def test_exact_boundaries_and_every_minute(self):
  for s,want in [('2026-11-16T14:59:59.999',False),('2026-11-16T15:00:00',True),('2026-11-17T01:59:59.999',True),('2026-11-17T02:00:00',False),('2026-11-17T08:59:59',False),('2026-11-17T14:59:59',False),('2026-11-17T15:00:00',True),('2027-01-01T01:59:59',True)]:self.assertEqual(t.in_window(ms(s)),want,s)
  start=datetime(2026,11,16,tzinfo=KST)
  for i in range(1440):
   d=start+timedelta(minutes=i);self.assertEqual(t.in_window(int(d.timestamp()*1000)),d.hour>=15 or d.hour<2)
 def test_cutoff_clears_pending_and_arm_without_touching_positions(self):
  saved=[];state={'arm':{'symbol':'X'},'pending':{'symbol':'X'},'last':0}
  e=NS(api=NS(now_ms=lambda:ms('2026-11-17T02:00:00')),journal=NS(data={t.STATE:state,'positions':['held']},save=lambda:saved.append(1)))
  self.assertIsNone(t.scan(e));self.assertIsNone(state['arm']);self.assertIsNone(state['pending']);self.assertEqual(e.journal.data['positions'],['held']);self.assertEqual(saved,[1])
 def test_final_admission_time_guard_trend_only(self):
  e=NS(api=NS(now_ms=lambda:ms('2026-11-17T02:00:00')),records=lambda:[],raw_snapshot={})
  with self.assertRaisesRegex(BotError,'진입 시간 종료'):t.require_slot(e,{'trend130':True,'symbol':'X'})
  t.require_slot(e,{'symbol':'X'})
  e.api.now_ms=lambda:ms('2026-11-17T01:59:59.999');t.require_slot(e,{'trend130':True,'symbol':'X'})
 def test_validate_rejects_at_cutoff_before_rest(self):
  e=NS(api=NS(now_ms=lambda:ms('2026-11-17T02:00:00')),root='/tmp/offline/runtime')
  with self.assertRaisesRegex(BotError,'진입 시간 종료'):t.validate_entry(e,{'trend130':True,'action':'LONG','leverage':5},1)
if __name__=='__main__':unittest.main()
