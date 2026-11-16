"""Build real mobile assets and a simulated position, without network access."""
import copy,json,sys
from pathlib import Path
from execution_harness import Harness,D,HOST,CORE
from phone_position_details import install
from phone_mobile import mobile_module
from okx_dashboard_data import dashboard_snapshot

out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
m=mobile_module(CORE)
for name in ('index.html','app.js','style.css'):(out/name).write_bytes(m.asset(name))
f=json.loads((D/'fixtures.json').read_text())['fixtures']['double_wick_SHORT'];e=Harness(copy.deepcopy(f),0)
try:
 o=e.submit(e.signal());e.api.fill(o['client_id']);e.reconcile(o);install()
 import okx_dashboard_data
 row=okx_dashboard_data.dashboard_snapshot(e.e.snapshot(),[o],None,True,True,False)['positions'][0]
 (out/'position.json').write_text(json.dumps(row,ensure_ascii=False))
finally:e.close()
