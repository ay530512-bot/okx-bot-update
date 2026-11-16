"""Deterministic cumulative 1.5.4 bundle; never starts a service or an API."""
import ast
import hashlib
import json
from pathlib import Path

D = Path(__file__).resolve().parents[1]
HOST = D/'phone_v154'
prior = D/'phone_1_5_3_setup.py'
assert hashlib.sha256(prior.read_bytes()).hexdigest() == '31da7ee14c7473b417c73381d3c210127628405d555f469ae31491fe695d7a40'
source = prior.read_text()
tree = ast.parse(source)
values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
pins = values['PINNED_BY_HOST']
pins['host-v43'] = {n: hashlib.sha256(s.encode()).hexdigest() for n, s in values['PAYLOAD'].items()}
(HOST/'phone_button_old_sources.json').write_text(json.dumps(pins, ensure_ascii=False, indent=2)+'\n')
payload = {p.name:p.read_text() for p in sorted(HOST.iterdir()) if p.is_file()}
for name, text in payload.items():
    if name.endswith('.py'): compile(text, name, 'exec')
changed = sorted(n for n, text in payload.items() if text != values['PAYLOAD'].get(n))
# Preserve all trading predicates, data paths, sizing and protection code.
for name in ('phone_sources.json','phone_public_ws.py','phone_public_lanes.py',
             'phone_mobile_entry.py','phone_mobile_compute.py','phone_pullback_size.py',
             'phone_trend_inputs.py','phone_trend_slot.py','phone_morning_short.py'):
    assert payload[name] == values['PAYLOAD'][name], name
lines = source.splitlines(keepends=True)
for n in reversed(tree.body):
    if isinstance(n, ast.Assign):
        key = n.targets[0].id
        lines[n.lineno-1:n.end_lineno] = [key+' = '+repr(dict(
            PINNED_BY_HOST=pins, HOST_NEW='host-v44', PAYLOAD=payload)[key])+'\n']
out = ''.join(lines)
node = next(n for n in ast.parse(out).body if isinstance(n, ast.Assign) and n.targets[0].id == 'PAYLOAD')
lines = out.splitlines(keepends=True)
tail = ''.join(lines[node.end_lineno:]).replace('host-v43', 'host-v44').replace('1.5.3', '1.5.4')
tail = tail.replace("for host in ('host-v42'", "for host in ('host-v43','host-v42'")
tail = tail.replace('신규상장 기준봉 부재로 인한 전체 추세 순위 대기 수정', '보유 포지션 업데이트 및 진입 근거 화면 개선')
out = ''.join(lines[:node.end_lineno])+tail
out = out.replace('Phone host-v43: exclude verified post-baseline listings from KST09 ranking.',
                  'Phone host-v44: protected-position update and compact entry-evidence UI.')
dest = D/'phone_1_5_4_setup.py'
dest.write_text(out)
meta = dict(display_version='1.5.4', version=44, host='host-v44', from_versions=list(range(24,44)),
    sha256=hashlib.sha256(dest.read_bytes()).hexdigest(), bytes=dest.stat().st_size,
    changed_files=changed, unchanged_files=len(payload)-len(changed),
    files={n:hashlib.sha256(s.encode()).hexdigest() for n,s in payload.items()})
Path(__file__).with_name('release.json').write_text(json.dumps(meta, indent=2)+'\n')
print(json.dumps({k:v for k,v in meta.items() if k not in ('files','changed_files')}))
