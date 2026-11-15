from pathlib import Path
import ast,hashlib,json
REPO=Path(__file__).resolve().parents[2];ROOT=REPO.parent/'fixture121';OUT=Path(__file__).parent
PRIOR=REPO/'android/phone_1_3_1_setup.py'
assert hashlib.sha256(PRIOR.read_bytes()).hexdigest()=='5430a129db3445145bfc997cb92e8363019b0a28ea05ab47146163696515c09b'
old={p.name:p.read_bytes() for p in (ROOT/'host-v29').iterdir() if p.is_file()};files=dict(old)
payload=next(ast.literal_eval(n.value) for n in ast.parse(PRIOR.read_text()).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='PAYLOAD')
assert old=={n:s.encode() for n,s in payload.items()}
def replace(name,a,b):
 s=files[name].decode();assert s.count(a)==1,(name,a,s.count(a));files[name]=s.replace(a,b,1).encode()
for n in ('phone_mobile.py','phone_update.py','phone_button_upgrade.py','phone_runtime_health.py'):files[n]=files[n].replace(b'1.3.1',b'1.3.2')
replace('phone_update.py','CURRENT = 29','CURRENT = 30')
replace('phone_service.py',"VERSION = 'phone-service-29'","VERSION = 'phone-service-30'")
replace('phone_service.py',"MARKER = '# OKX phone service v29 managed boot hook'","MARKER = '# OKX phone service v30 managed boot hook'")
replace('phone_service.py','LEGACY_MARKERS = (',"LEGACY_MARKERS = ('# OKX phone service v29 managed boot hook', ")
replace('phone_button_upgrade.py',"('host-v24', 'host-v25', 'host-v26', 'host-v27', 'host-v28')","('host-v24', 'host-v25', 'host-v26', 'host-v27', 'host-v28', 'host-v29')")
pins={h:{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/h).iterdir() if p.is_file()} for h in ('host-v24','host-v25','host-v26','host-v27','host-v28','host-v29')}
p=json.loads(files['phone_button_old_sources.json']);p.update(pins);files['phone_button_old_sources.json']=(json.dumps(p,ensure_ascii=False,indent=2)+'\n').encode()
for n in ('phone_market_alerts.py','phone_market_ui.js','phone_sections.css'):files[n]=(OUT/n).read_bytes()
replace('phone_host.py','    market = MarketFeed(settings, events)', '''    from phone_market_alerts import AlertFeed
    mobile.market_alerts = AlertFeed(root, engine.universe if engine else None)
    mobile.market_alerts.start()
    market = MarketFeed(settings, events)''')
replace('phone_host.py','        market.stop()','        mobile.market_alerts.stop()\n        market.stop()')
replace('phone_mobile.py',"                self.snapshot['phone_host'] = True", """                self.snapshot['phone_host'] = True
                if hasattr(self, 'market_alerts'):
                    self.snapshot['market_alerts'] = self.market_alerts.snapshot()""")
replace('phone_mobile.py',"        if name == 'style.css':\n            data += '\\n.phone-host-notice", "        if name == 'style.css':\n            data += '\\n' + Path(__file__).with_name('phone_sections.css').read_text()\n            data += '\\n.phone-host-notice")
replace('phone_mobile.py',"            data += '\\n' + Path(__file__).with_name('phone_update_ui.js').read_text()", "            data += '\\n' + Path(__file__).with_name('phone_update_ui.js').read_text()\n            data += '\\n' + Path(__file__).with_name('phone_market_ui.js').read_text()")
replace('phone_mobile.py',"            data = data.replace('<main>',", """            data = data.replace('<section id="marketPanel">', '<section id="phoneMovesPanel"><h2>급등 · 급락 알림</h2><p class="muted">확정 15분봉 시가 → 종가 ±10% · 최근 24시간, 최대 100건</p><p class="muted">봇 수신봉 기준 · 카드를 누르면 차트와 수동 롱/숏 진입</p><p id="phoneMoveStatus" class="muted">수신봉 검사 대기</p><div id="phoneMoveRows"></div></section><section id="marketPanel">', 1)
            data = data.replace('<main>',""")
ui=files['phone_update_ui.js'].decode()
start=ui.index('// Read-only verification summary;');end=ui.index('// Calculation mode:',start)
ui=ui[:start]+(OUT/'health_ui.js').read_text()+'\n'+ui[end:]
ui=ui.replace("el=document.createElement('p');el.id='phonePerfSummary'", "el=document.createElement('p');el.id='phonePerfSummary'")
ui=ui.replace("const rows=['최근 '","const rows=['계산 성능','최근 '")
ui=ui.replace("(r.mean_s??'측정 중')", "(Number.isFinite(r.mean_s)?r.mean_s.toFixed(3):'측정 중')")
ui=ui.replace("(r.p95_s??'측정 중')", "(Number.isFinite(r.p95_s)?r.p95_s.toFixed(3):'측정 중')")
files['phone_update_ui.js']=ui.encode()
prior=PRIOR.read_text();head=prior[:prior.index('PINNED_BY_HOST =')]
tail=prior[prior.index('\ndef digest('):].replace('host-v29','host-v30').replace("('host-v28','host-v27','host-v26','host-v25','host-v24')","('host-v29','host-v28','host-v27','host-v26','host-v25','host-v24')")
tail=tail.replace('1.3.1','1.3.2').replace('1.2.9/1.3.0','1.2.9/1.3.0/1.3.1')
text=head+'PINNED_BY_HOST = '+repr(pins)+"\nHOST_NEW = 'host-v30'\nPAYLOAD = "+repr({n:b.decode() for n,b in files.items()})+'\n'+tail
p=REPO/'android/phone_1_3_2_setup.py';p.write_text(text)
dest=ROOT/'host-v30';dest.mkdir(exist_ok=True)
for n,b in files.items():(dest/n).write_bytes(b)
audit=dict(version='1.3.2',from_versions=[24,25,26,27,28,29],changed=[n for n,b in files.items() if old.get(n)!=b],sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,live_orders=False)
(OUT/'build_audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit,indent=2))
