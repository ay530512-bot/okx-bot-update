"""Capture a synthetic 1.7.0 filled/SL-confirmed EMA record before withdrawal.

Run in its own interpreter so the previous runtime is never mixed into 1.7.1.
The prior harness prohibits network I/O; only its fake exchange is used.
"""
import copy,hashlib,json,sys
from pathlib import Path
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parent/'phone_v170_tests'))
from execution_harness import Harness,NETWORK_ATTEMPTS
from test_ema_support import fixture
f=fixture();h=Harness(copy.deepcopy(f))
try:
 o=h.submit(h.signal());h.api.fill(o['client_id']);assert h.reconcile(o)
 p=h.api.positions[0];p.update(cTime=str(o['entry_ms']),uTime=str(h.api.now))
 for a in h.api.algos:a.update(tdMode='isolated',side='sell')
 data=dict(fixture=f,journal=h.e.journal.data,positions=h.api.positions,algos=h.api.algos,orders=h.api.orders,
           levers=[[s,d,l] for (s,d),l in h.api.levers.items()],now=h.api.now,
           provenance='1.7.0 engine + simulated exchange; no actual orders')
 assert not NETWORK_ATTEMPTS
 (D/'legacy_support_fixture.json').write_text(json.dumps(data,indent=2,default=str)+'\n')
 print('Captured previous-runtime active EMA record with verified protection')
finally:h.close()
