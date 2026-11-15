from pathlib import Path
import ast, hashlib, json, importlib.util

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO.parent/'fixture121'
OUT = Path(__file__).parent
PRIOR = REPO/'android/phone_1_2_9_setup.py'
assert hashlib.sha256(PRIOR.read_bytes()).hexdigest() == '8e525987cd075ee13457af4700d580abc9b8b29f1bc1661e594df267235edd21'
old = {p.name:p.read_bytes() for p in (ROOT/'host-v27').iterdir() if p.is_file()}
tree = ast.parse(PRIOR.read_text())
payload = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='PAYLOAD')
assert old == {n:s.encode() for n,s in payload.items()}
files = dict(old)
def replace(name, before, after):
    s=files[name].decode()
    assert s.count(before)==1, (name,before,s.count(before))
    files[name]=s.replace(before,after,1).encode()
for name in ('phone_mobile.py','phone_update.py','phone_button_upgrade.py'):
    files[name]=files[name].replace(b'1.2.9',b'1.3.0')
replace('phone_update.py','CURRENT = 27','CURRENT = 28')
replace('phone_service.py',"VERSION = 'phone-service-27'","VERSION = 'phone-service-28'")
replace('phone_service.py',"MARKER = '# OKX phone service v27 managed boot hook'","MARKER = '# OKX phone service v28 managed boot hook'")
replace('phone_service.py','LEGACY_MARKERS = (',"LEGACY_MARKERS = ('# OKX phone service v27 managed boot hook', ")
replace('phone_button_upgrade.py',"('host-v24', 'host-v25', 'host-v26')","('host-v24', 'host-v25', 'host-v26', 'host-v27')")
replace('phone_button_upgrade.py',"                service.start(root, enable=True)",
        "                atomic_private(root/'phone_trend_activation_hold', b'1.3.0 readiness pending\\n')\n                service.start(root, enable=True)")
replace('phone_button_upgrade.py',"                wait_ready(root)",
        "                wait_ready(root)\n                (root/'phone_trend_activation_hold').unlink(missing_ok=True)")
replace('phone_button_upgrade.py',"                    rollback(root, old, boot, boot_before)",
        "                    rollback(root, old, boot, boot_before)\n                    (root/'phone_trend_activation_hold').unlink(missing_ok=True)")
replace('phone_button_upgrade.py',"새 추세 눌림목 롱 주문 크기 1/4", "기존 공용3자리 + 추세5배 전용1자리")
pins={h:{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/h).iterdir() if p.is_file()} for h in ('host-v24','host-v25','host-v26','host-v27')}
p=json.loads(files['phone_button_old_sources.json']);p.update(pins)
files['phone_button_old_sources.json']=(json.dumps(p,ensure_ascii=False,indent=2)+'\n').encode()
files['phone_trend_slot.py']=(OUT/'phone_trend_slot.py').read_bytes()
replace('phone_host.py','        engine = RuleEngine(runtime, settings, events)',
        '        from phone_trend_slot import install as install_trend, attach as attach_trend\n'
        '        install_trend(source)\n'
        '        engine = RuleEngine(runtime, settings, events)\n'
        '        attach_trend(engine)')
replace('phone_host.py',"['진입 경로', '기존15m OR 두꼬리']", "['진입 경로', '기존3규칙 공용3자리 + 상승1위 추세5배 전용1자리']")
replace('phone_mobile.py',"<main><p class=\"phone-host-notice\">OKX Ai trade - 1.3.0</p>",
        '<main><p class="phone-host-notice">OKX Ai trade - 1.3.0<br>기존3규칙 공용3자리 · 추세5배 전용1자리<br>추세: 15시 이후 상승1위 · 돌파 후 눌림 종가 확인 · 절반익절 없이 전량 추적 · 조건 없으면 빈자리</p>')
prior=PRIOR.read_text();head=prior[:prior.index('PINNED_BY_HOST =')]
tail=prior[prior.index('\ndef digest('):].replace("('host-v26','host-v25','host-v24')", "('host-v27','host-v26','host-v25','host-v24')")
tail=tail.replace('host-v27','host-v28').replace("('host-v28','host-v26','host-v25','host-v24')","('host-v27','host-v26','host-v25','host-v24')")
tail=tail.replace('1.2.6/1.2.7/1.2.8','1.2.6/1.2.7/1.2.8/1.2.9').replace('1.2.9 파일','1.3.0 파일').replace('1.2.9,','1.3.0,')
tail=tail.replace('1.2.9 눌림목 복원 · 기존 OR 두꼬리 · 기본 1/4','1.3.0 기존3자리 + 추세5배 전용1자리 · 눌림 진입·전량 추적')
text=head+'PINNED_BY_HOST = '+repr(pins)+"\nHOST_NEW = 'host-v28'\nPAYLOAD = "+repr({n:b.decode() for n,b in files.items()})+'\n'+tail
target=REPO/'android/phone_1_3_0_setup.py';target.write_text(text)
dest=ROOT/'host-v28';dest.mkdir(exist_ok=True)
for n,b in files.items():(dest/n).write_bytes(b)
audit=dict(display_version='1.3.0',host=28,changed=[n for n,b in files.items() if old.get(n)!=b],
           sha256=hashlib.sha256(target.read_bytes()).hexdigest(),bytes=target.stat().st_size,
           from_versions=[24,25,26,27],live_orders_tested=False)
(OUT/'build_audit.json').write_text(json.dumps(audit,indent=2))
print(json.dumps(audit,indent=2))
