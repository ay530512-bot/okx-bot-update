"""Deterministic cumulative phone update; never starts an API or service."""
import ast
import hashlib
import json
from pathlib import Path

D=Path(__file__).resolve().parents[1];HOST=D/'phone_v171'
prior=D/'phone_1_7_0_setup.py'
assert hashlib.sha256(prior.read_bytes()).hexdigest()=='0f9c28f5401c6a246d72e57e578f0fc8fdaa41db48d3b5d7aafee033fa4cf654'
source=prior.read_text();tree=ast.parse(source)
values={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)}
pins=values['PINNED_BY_HOST'];pins['host-v59']={n:hashlib.sha256(s.encode()).hexdigest() for n,s in values['PAYLOAD'].items()}
(HOST/'phone_button_old_sources.json').write_text(json.dumps(pins,ensure_ascii=False,indent=2)+'\n')
payload={p.name:p.read_text() for p in sorted(HOST.iterdir()) if p.is_file()}
for name,text in payload.items():
    if name.endswith('.py'):compile(text,name,'exec')
changed=sorted(n for n,text in payload.items() if text!=values['PAYLOAD'].get(n))
allowed={'phone_button_old_sources.json','phone_button_upgrade.py','phone_update.py',
    'phone_service.py','phone_restore_previous.py','phone_runtime_health.py','phone_mobile.py',
    'phone_update_ui.js','phone_sections.css','phone_analysis_ui.js',
    'phone_manual_reduction.py','phone_host.py','phone_account.py','phone_handover.py','phone_position_details.py','phone_risk_lifecycle.py','phone_similar_candidates.py',
    'phone_signal_cache.py','phone_mobile_entry.py','phone_diagnostic_export.py','phone_legacy_restart.py','phone_performance.py',
    'phone_home_assets.py','phone_dashboard_live.py','phone_dashboard_ui.js','phone_ema_support.py','phone_trend_slot.py','phone_entry_journey.py','phone_public_ws.py','phone_ws_handover.py','phone_connection_trace.py'}
assert set(changed)<=allowed,changed
assert set(values['PAYLOAD'])<=set(payload)
lines=source.splitlines(keepends=True)
for n in reversed(tree.body):
    if isinstance(n,ast.Assign):
        key=n.targets[0].id
        lines[n.lineno-1:n.end_lineno]=[key+' = '+repr(dict(PINNED_BY_HOST=pins,HOST_NEW='host-v60',PAYLOAD=payload)[key])+'\n']
out=''.join(lines);node=next(n for n in ast.parse(out).body if isinstance(n,ast.Assign) and n.targets[0].id=='PAYLOAD')
lines=out.splitlines(keepends=True)
tail=''.join(lines[node.end_lineno:]).replace('host-v59','host-v60').replace('1.7.0','1.7.1')
tail=tail.replace("for host in ('host-v58'","for host in ('host-v59','host-v58'")
out=''.join(lines[:node.end_lineno])+tail
dest=D/'phone_1_7_1_setup.py';dest.write_text(out)
meta=dict(display_version='1.7.1',version=60,host='host-v60',from_versions=list(range(24,60)),
    sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),bytes=dest.stat().st_size,
    changed_files=changed,unchanged_files=len(payload)-len(changed),
    files={n:hashlib.sha256(s.encode()).hexdigest() for n,s in payload.items()})
Path(__file__).with_name('release.json').write_text(json.dumps(meta,indent=2)+'\n')
print(json.dumps({k:v for k,v in meta.items() if k not in ('files','changed_files')}))
