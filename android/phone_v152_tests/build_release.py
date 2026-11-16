"""Deterministic cumulative 1.5.2 bundle; never starts a service or an API."""
import ast
import hashlib
import json
from pathlib import Path

D = Path(__file__).resolve().parents[1]
HOST = D/'phone_v152'
prior = D/'phone_1_5_1_setup.py'
assert hashlib.sha256(prior.read_bytes()).hexdigest() == 'a8c2d246f623eef9ae059c6dd5e1c508975e50cb142b16f596ffffb52cda43fb'
source = prior.read_text()
tree = ast.parse(source)
values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
pins = values['PINNED_BY_HOST']
pins['host-v41'] = {n: hashlib.sha256(s.encode()).hexdigest() for n, s in values['PAYLOAD'].items()}
(HOST/'phone_button_old_sources.json').write_text(json.dumps(pins, ensure_ascii=False, indent=2)+'\n')
payload = {p.name:p.read_text() for p in sorted(HOST.iterdir()) if p.is_file()}
for name, text in payload.items():
    if name.endswith('.py'): compile(text, name, 'exec')
changed = sorted(n for n, text in payload.items() if text != values['PAYLOAD'].get(n))
# Explicit preservation of every policy, account, clock, protection and handover
# module. Only transport, its diagnostics, install wiring/version may differ.
expected = sorted(('phone_button_old_sources.json', 'phone_button_upgrade.py',
    'phone_mobile.py', 'phone_restore_previous.py', 'phone_runtime_health.py',
    'phone_service.py', 'phone_update.py', 'phone_host.py', 'phone_public_ws.py',
    'phone_public_lanes.py', 'phone_connection_trace.py', 'phone_entry_feed.py',
    'phone_diagnostic_export.py', 'phone_update_ui.js'))
assert changed == expected, changed
lines = source.splitlines(keepends=True)
for n in reversed(tree.body):
    if isinstance(n, ast.Assign):
        key = n.targets[0].id
        lines[n.lineno-1:n.end_lineno] = [key+' = '+repr(dict(
            PINNED_BY_HOST=pins, HOST_NEW='host-v42', PAYLOAD=payload)[key])+'\n']
out = ''.join(lines)
node = next(n for n in ast.parse(out).body if isinstance(n, ast.Assign) and n.targets[0].id == 'PAYLOAD')
lines = out.splitlines(keepends=True)
tail = ''.join(lines[node.end_lineno:]).replace('host-v41', 'host-v42').replace('1.5.1', '1.5.2')
tail = tail.replace("for host in ('host-v40'", "for host in ('host-v41','host-v40'")
tail = tail.replace('설명 글씨·구분 및 업데이트 버튼 테두리 개선', '시세 수신 부하 개선 및 진입·보유 연결 분리')
out = ''.join(lines[:node.end_lineno])+tail
out = out.replace('Phone host-v41: compact explanations and visible update button; trading unchanged.',
                  'Phone host-v42: strict fast decoding and isolated execution/monitor sockets.')
dest = D/'phone_1_5_2_setup.py'
dest.write_text(out)
meta = dict(display_version='1.5.2', version=42, host='host-v42', from_versions=list(range(24,42)),
    sha256=hashlib.sha256(dest.read_bytes()).hexdigest(), bytes=dest.stat().st_size,
    changed_files=changed, unchanged_files=len(payload)-len(changed),
    files={n:hashlib.sha256(s.encode()).hexdigest() for n,s in payload.items()})
Path(__file__).with_name('release.json').write_text(json.dumps(meta, indent=2)+'\n')
print(json.dumps({k:v for k,v in meta.items() if k not in ('files','changed_files')}))
