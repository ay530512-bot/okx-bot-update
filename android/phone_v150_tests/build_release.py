"""Reproducible cumulative installer from the pinned1.4.2 payload."""
import ast
import hashlib
import json
from pathlib import Path

D = Path(__file__).resolve().parents[1]
HOST = D/'phone_v150'
prior = D/'phone_1_4_2_setup.py'
assert hashlib.sha256(prior.read_bytes()).hexdigest() == '24c4814b5d73044b1d3b87477cf9de8abc7d50d00f3ee58a299e87f9f3d2ca87'
s = prior.read_text()
tree = ast.parse(s)
values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)}
pins = values['PINNED_BY_HOST']
pins['host-v39'] = {n: hashlib.sha256(x.encode()).hexdigest() for n, x in values['PAYLOAD'].items()}
(HOST/'phone_button_old_sources.json').write_text(json.dumps(pins, ensure_ascii=False, indent=2)+'\n')
payload = {p.name: p.read_text() for p in sorted(HOST.iterdir()) if p.is_file()}
for name, text in payload.items():
    if name.endswith('.py'):
        compile(text, name, 'exec')
assert payload['phone_sources.json'] == values['PAYLOAD']['phone_sources.json']
lines = s.splitlines(keepends=True)
for n in reversed(tree.body):
    if isinstance(n, ast.Assign):
        k = n.targets[0].id
        lines[n.lineno-1:n.end_lineno] = [k+' = '+repr(dict(PINNED_BY_HOST=pins, HOST_NEW='host-v40', PAYLOAD=payload)[k])+'\n']
out = ''.join(lines)
node = next(n for n in ast.parse(out).body if isinstance(n, ast.Assign) and n.targets[0].id == 'PAYLOAD')
lines = out.splitlines(keepends=True)
tail = ''.join(lines[node.end_lineno:]).replace('host-v39', 'host-v40').replace('1.4.2', '1.5.0')
tail = tail.replace("for host in ('host-v38'", "for host in ('host-v39','host-v38'")
tail = tail.replace('기존3자리 + 추세5배 전용1자리 · 눌림 진입·전량 추적', '기존 롱 유지 + KST05~08 반등실패 숏·롱청산 확인 후 전환')
out = ''.join(lines[:node.end_lineno])+tail
out = out.replace('Verified phone host-v39: confirmed ranking inputs and retained diagnostics.',
                  'Phone host-v40: original long plus morning failed-rebound short and serialized reversal.')
dest = D/'phone_1_5_0_setup.py'
dest.write_text(out)
meta = dict(display_version='1.5.0', version=40, host='host-v40', from_versions=list(range(24,40)),
            sha256=hashlib.sha256(dest.read_bytes()).hexdigest(), bytes=dest.stat().st_size,
            files={n:hashlib.sha256(x.encode()).hexdigest() for n,x in payload.items()})
(Path(__file__).parent/'release.json').write_text(json.dumps(meta, indent=2)+'\n')
print(json.dumps({k:v for k,v in meta.items() if k!='files'}))
