"""Deterministic cumulative phone update; never starts an API or service."""
import ast
import hashlib
import json
from pathlib import Path

D=Path(__file__).resolve().parents[1];HOST=D/'phone_v1610'
prior=D/'phone_1_6_9_setup.py'
assert hashlib.sha256(prior.read_bytes()).hexdigest()=='b6ef9c876b6dad8e5531b5c6eca864b0198c7c38f6e13aa5c970326272f48553'
source=prior.read_text();tree=ast.parse(source)
values={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)}
pins=values['PINNED_BY_HOST'];pins['host-v56']={n:hashlib.sha256(s.encode()).hexdigest() for n,s in values['PAYLOAD'].items()}
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
    'phone_home_assets.py','phone_dashboard_live.py','phone_dashboard_ui.js'}
assert set(changed)<=allowed,changed
assert set(values['PAYLOAD'])<=set(payload)
lines=source.splitlines(keepends=True)
for n in reversed(tree.body):
    if isinstance(n,ast.Assign):
        key=n.targets[0].id
        lines[n.lineno-1:n.end_lineno]=[key+' = '+repr(dict(PINNED_BY_HOST=pins,HOST_NEW='host-v57',PAYLOAD=payload)[key])+'\n']
out=''.join(lines);node=next(n for n in ast.parse(out).body if isinstance(n,ast.Assign) and n.targets[0].id=='PAYLOAD')
lines=out.splitlines(keepends=True)
tail=''.join(lines[node.end_lineno:]).replace('host-v56','host-v57').replace('1.6.9','1.6.10')
tail=tail.replace("for host in ('host-v55'","for host in ('host-v56','host-v55'")
out=''.join(lines[:node.end_lineno])+tail
dest=D/'phone_1_6_10_setup.py';dest.write_text(out)
meta=dict(display_version='1.6.10',version=57,host='host-v57',from_versions=list(range(24,57)),
    sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),bytes=dest.stat().st_size,
    changed_files=changed,unchanged_files=len(payload)-len(changed),
    files={n:hashlib.sha256(s.encode()).hexdigest() for n,s in payload.items()})
Path(__file__).with_name('release.json').write_text(json.dumps(meta,indent=2)+'\n')
print(json.dumps({k:v for k,v in meta.items() if k not in ('files','changed_files')}))
