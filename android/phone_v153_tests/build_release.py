"""Deterministic cumulative 1.5.3 bundle; never starts a service or an API."""
import ast
import hashlib
import json
from pathlib import Path

D = Path(__file__).resolve().parents[1]
HOST = D/'phone_v153'
prior = D/'phone_1_5_2_setup.py'
assert hashlib.sha256(prior.read_bytes()).hexdigest() == 'ed2923ad30e0f823d1e7b5d19a5d30f8e052b1e460b58fc39d67edae4c109ce3'
source = prior.read_text()
tree = ast.parse(source)
values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
pins = values['PINNED_BY_HOST']
pins['host-v42'] = {n: hashlib.sha256(s.encode()).hexdigest() for n, s in values['PAYLOAD'].items()}
(HOST/'phone_button_old_sources.json').write_text(json.dumps(pins, ensure_ascii=False, indent=2)+'\n')
payload = {p.name:p.read_text() for p in sorted(HOST.iterdir()) if p.is_file()}
for name, text in payload.items():
    if name.endswith('.py'): compile(text, name, 'exec')
changed = sorted(n for n, text in payload.items() if text != values['PAYLOAD'].get(n))
# Preserve transport, signal predicates, sizing, account, protection and
# handover. Only baseline eligibility, diagnostics and version wiring differ.
expected = sorted(('phone_button_old_sources.json', 'phone_button_upgrade.py',
    'phone_mobile.py', 'phone_restore_previous.py', 'phone_runtime_health.py',
    'phone_service.py', 'phone_update.py', 'phone_trend_inputs.py',
    'phone_diagnostic_export.py', 'phone_update_ui.js'))
assert changed == expected, changed
lines = source.splitlines(keepends=True)
for n in reversed(tree.body):
    if isinstance(n, ast.Assign):
        key = n.targets[0].id
        lines[n.lineno-1:n.end_lineno] = [key+' = '+repr(dict(
            PINNED_BY_HOST=pins, HOST_NEW='host-v43', PAYLOAD=payload)[key])+'\n']
out = ''.join(lines)
node = next(n for n in ast.parse(out).body if isinstance(n, ast.Assign) and n.targets[0].id == 'PAYLOAD')
lines = out.splitlines(keepends=True)
tail = ''.join(lines[node.end_lineno:]).replace('host-v42', 'host-v43').replace('1.5.2', '1.5.3')
tail = tail.replace("for host in ('host-v41'", "for host in ('host-v42','host-v41'")
tail = tail.replace('시세 수신 부하 개선 및 진입·보유 연결 분리', '신규상장 기준봉 부재로 인한 전체 추세 순위 대기 수정')
out = ''.join(lines[:node.end_lineno])+tail
out = out.replace('Phone host-v42: strict fast decoding and isolated execution/monitor sockets.',
                  'Phone host-v43: exclude verified post-baseline listings from KST09 ranking.')
dest = D/'phone_1_5_3_setup.py'
dest.write_text(out)
meta = dict(display_version='1.5.3', version=43, host='host-v43', from_versions=list(range(24,43)),
    sha256=hashlib.sha256(dest.read_bytes()).hexdigest(), bytes=dest.stat().st_size,
    changed_files=changed, unchanged_files=len(payload)-len(changed),
    files={n:hashlib.sha256(s.encode()).hexdigest() for n,s in payload.items()})
Path(__file__).with_name('release.json').write_text(json.dumps(meta, indent=2)+'\n')
print(json.dumps({k:v for k,v in meta.items() if k not in ('files','changed_files')}))
