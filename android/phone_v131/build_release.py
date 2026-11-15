from pathlib import Path
import ast,hashlib,json
REPO=Path(__file__).resolve().parents[2];ROOT=REPO.parent/'fixture121';OUT=Path(__file__).parent
PRIOR=REPO/'android/phone_1_3_0_setup.py'
assert hashlib.sha256(PRIOR.read_bytes()).hexdigest()=='d7f80a1d156ccda65a5bfd1b69c0aa25f3d7b2417101916bad1bd83611916d34'
old={p.name:p.read_bytes() for p in (ROOT/'host-v28').iterdir() if p.is_file()};files=dict(old)
payload=next(ast.literal_eval(n.value) for n in ast.parse(PRIOR.read_text()).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='PAYLOAD')
assert old=={n:s.encode() for n,s in payload.items()}
def replace(name,a,b):
 s=files[name].decode();assert s.count(a)==1,(name,a,s.count(a));files[name]=s.replace(a,b,1).encode()
for n in ('phone_mobile.py','phone_update.py','phone_button_upgrade.py'):files[n]=files[n].replace(b'1.3.0',b'1.3.1')
replace('phone_update.py','CURRENT = 28','CURRENT = 29')
replace('phone_service.py',"VERSION = 'phone-service-28'","VERSION = 'phone-service-29'")
replace('phone_service.py',"MARKER = '# OKX phone service v28 managed boot hook'","MARKER = '# OKX phone service v29 managed boot hook'")
replace('phone_service.py','LEGACY_MARKERS = (',"LEGACY_MARKERS = ('# OKX phone service v28 managed boot hook', ")
replace('phone_button_upgrade.py',"('host-v24', 'host-v25', 'host-v26', 'host-v27')","('host-v24', 'host-v25', 'host-v26', 'host-v27', 'host-v28')")
pins={h:{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/h).iterdir() if p.is_file()} for h in ('host-v24','host-v25','host-v26','host-v27','host-v28')}
p=json.loads(files['phone_button_old_sources.json']);p.update(pins);files['phone_button_old_sources.json']=(json.dumps(p,ensure_ascii=False,indent=2)+'\n').encode()
files['phone_entry_diagnostics.py']=(OUT/'phone_entry_diagnostics.py').read_bytes()
name='phone_candidate_fast.py'
replace(name,'    original_select = inspect.unwrap(patterns.select)','    from phone_entry_diagnostics import make_selector, accumulate\n    original_select = make_selector(pins)')
replace(name,'    channel._phone_entry_gate = gate','''    def pattern_stats(p, symbol):
        d = getattr(state, 'diagnostic', None)
        if d is not None: accumulate(d, p, symbol)
    def pattern_wait(p):
        detail = p.get('entry_diagnostic', {})
        gate('기존·두꼬리 방향 충돌' if p.get('or_status') == 'conflict' else
             '자료 대기: '+detail['data_issue'] if detail.get('data_issue') else '확정봉 규칙 조건 미충족')
    channel._phone_entry_stats = pattern_stats
    channel._phone_entry_pattern_wait = pattern_wait
    channel._phone_entry_gate = gate''')
# Edit the generated packet source, not its original predicates.
replace(name,'    fast = compiled(src, \'packet\', original_packet.__defaults__)', '''    src = replace_once(src, "v, or_status = _phone_select_validated", "v, or_status, detail = _phone_select_validated")
    src = replace_once(src, "return dict(entry_setups=[], or_status=or_status)", "return dict(entry_setups=[], or_status=or_status, entry_diagnostic=detail)")
    src = replace_once(src, "return dict(symbol=row['symbol'],", "return dict(entry_diagnostic=detail, symbol=row['symbol'],")
    fast = compiled(src, 'packet', original_packet.__defaults__)''')
replace(name,'    fixed_candidate = compiled(src, \'candidate\')', '''    src = replace_once(src, "p = packet(row, e.cfg, now)", "p = packet(row, e.cfg, now)\\n            _phone_entry_stats(p, symbol)")
    src = replace_once(src, "_phone_entry_gate('패턴 조건 미충족')", "_phone_entry_pattern_wait(p)")
    fixed_candidate = compiled(src, 'candidate')''')
replace(name, "            e.phone_entry_diagnostic = d  # Replace atomically; readers never mutate.", """            previous_totals = getattr(e, 'phone_entry_totals', {})
            totals = dict(scans=previous_totals.get('scans',0)+1,
                          candidate_returns=previous_totals.get('candidate_returns',0)+int(result is not None),
                          reasons=dict(previous_totals.get('reasons',{})))
            for label,count in d['reasons'].items():
                totals['reasons'][label]=totals['reasons'].get(label,0)+count
            e.phone_entry_totals = totals
            e.phone_entry_diagnostic = d  # Replace atomically; readers never mutate.""")
name='phone_runtime_health.py'
replace(name,'    report, summary = timer.report, timer.make_summary','    report, summary = timer.report, timer.make_summary\n    from phone_entry_diagnostics import History\n    history = History(timer.root)')
replace(name,"                entry=dict(getattr(engine,'phone_entry_diagnostic',{})))", """                entry=dict(getattr(engine,'phone_entry_diagnostic',{})),
                trend_status=getattr(engine,'phone_trend_status','추세 검사 대기'),
                entry_observation_totals=dict(getattr(engine,'phone_entry_totals',{})),
                program_version='1.3.1')
            history.observe(d['runtime_health'],d)
            d['runtime_health']['history_write_errors']=history.errors""")
# Display-only: avoid stale trend status outside its entry window.
replace('phone_trend_slot.py','    if not in_window(now):','    if not in_window(now):\n        e.phone_trend_status = \'신규 추세 진입 시간 대기: KST15시~다음09시\'')
name='phone_update_ui.js'
replace(name,"  if(reasons.length)rows.push('이번 검사 대기 이유: '+reasons.join(' / '));", """  if(reasons.length)rows.push('이번 검사 대기 이유: '+reasons.join(' / '));
  const names={trend_pullback:'눌림목',confirmed_reversal:'확정반전',double_wick:'두꼬리'};
  for(const [key,x] of Object.entries(e.routes||{})){
   rows.push((names[key]||key)+': 통과 '+x.pass_count+' · 조건대기 '+x.wait_count+' · 자료대기 '+x.data_wait_count+' · 상태별 비활성 '+x.inactive_count);
   const top=Object.entries(x.reasons||{}).sort((a,b)=>b[1]-a[1]).slice(0,2).map(([k,n])=>k+' '+n+'건');
   if(top.length)rows.push('  '+top.join(' / '));
  }
  if(e.routes)rows.push('눌림목·확정반전은 1시간 추세 상태에 따라 선택됩니다. 두꼬리는 별도 OR 검사입니다.');""")
replace(name," rows.push('연결 허용은 체결 확인이 아닙니다. 끊김 횟수는 재시작 시 초기화됩니다.');", """ if(h.entry_observation_totals)rows.push('이번 실행 검사 '+h.entry_observation_totals.scans+'회 · 주문 전 검사 전달 '+h.entry_observation_totals.candidate_returns+'회(체결 건수 아님)');
 if(h.trend_status)rows.push('추세 전용1자리: '+h.trend_status);
 rows.push('연결 허용은 체결 확인이 아닙니다. 끊김 횟수는 재시작 시 초기화됩니다.');
 if(h.program_version)rows.push('진입 진단 기록은 재시작 후에도 보존됩니다(최근 파일 최대 약4MiB).');
 if(h.history_write_errors)rows.push('진단 기록 저장 오류 '+h.history_write_errors+'회');""")
prior=PRIOR.read_text();head=prior[:prior.index('PINNED_BY_HOST =')]
tail=prior[prior.index('\ndef digest('):].replace('host-v28','host-v29').replace("('host-v27','host-v26','host-v25','host-v24')","('host-v28','host-v27','host-v26','host-v25','host-v24')")
tail=tail.replace('1.2.6/1.2.7/1.2.8/1.2.9','1.2.6/1.2.7/1.2.8/1.2.9/1.3.0').replace('1.3.0','1.3.1')
tail=tail.replace('1.2.9/1.3.1','1.2.9/1.3.0')
text=head+'PINNED_BY_HOST = '+repr(pins)+"\nHOST_NEW = 'host-v29'\nPAYLOAD = "+repr({n:b.decode() for n,b in files.items()})+'\n'+tail
p=REPO/'android/phone_1_3_1_setup.py';p.write_text(text)
dest=ROOT/'host-v29';dest.mkdir(exist_ok=True)
for n,b in files.items():(dest/n).write_bytes(b)
audit=dict(version='1.3.1',from_versions=[24,25,26,27,28],changed=[n for n,b in files.items() if old.get(n)!=b],sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,live_orders=False)
(OUT/'build_audit.json').write_text(json.dumps(audit,indent=2));print(json.dumps(audit,indent=2))
