"""Synthetic inputs isolate collection ordering; no live fills or profit claims."""
import copy,importlib.util,json,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
D=Path(__file__).resolve().parents[1];HOST=D/'phone_v165';CORE=D.parent.parent/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
import phone_trend_slot as new
spec=importlib.util.spec_from_file_location('rank_old141',D.parent.parent/'regression_hosts/phone_v141/phone_trend_slot.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
T=1794829500000 # 2026-11-16 20:45 KST
A,B='TESTA-USDT-SWAP','TESTB-USDT-SWAP'
def bars(step,slope,n=70):
 end=T//step*step
 return [[end-(n-i)*step,1+i*slope,1+i*slope+.01,1+i*slope-.01,1+i*slope+.002,100] for i in range(n)]
def engine():
 rows=[]
 for s,slope in [(A,.005),(B,.001)]:
  b=bars(900000,.002);b[-1][4]=b[-1][1]-.005
  rows.append(dict(symbol=s,instrument=dict(instId=s,state='live',settleCcy='USDT',ctType='linear',ctValCcy=s.split('-')[0],instCategory='1',lever='100'),
      live_frames={'15m':b,'1H':bars(3600000,slope),'4H':[]},observed_ms=T+1000))
 result=dict(rows=rows,whole_market=True,universe=2,ms=T+1000,filter_counts={'data_error':0})
 cache={(r['symbol'],f):(time.monotonic(),tuple(tuple(b) for b in bs)) for r in rows for f,bs in r['live_frames'].items()}
 u=NS(lock=threading.RLock(),result=result,full_market=NS(instruments={r['symbol']:r['instrument'] for r in rows},band_cache=cache),search_paused=threading.Event())
 u.read=lambda:(u.result,None)
 e=NS(universe=u,cfg={'selection':{}},api=NS(now_ms=lambda:T+2000),journal=NS(data={},save=lambda:None),root='/tmp/no_live/runtime')
 e.journal.data[new.STATE]={'last':T-900000,'arm':{'t':T-900000,'symbol':A,'level':rows[0]['live_frames']['15m'][-1][4]+.01},'pending':None}
 return e
