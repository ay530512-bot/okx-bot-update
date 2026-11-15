from pathlib import Path
import hashlib,importlib.util,json
repo=Path(__file__).resolve().parents[2];src=repo.parent/'fixture121/host-v23';out=repo/'android/phone_v126';files={p.name:p.read_bytes() for p in src.iterdir() if p.is_file()}
# Preserve the entire 1.2.5 serial function; only bracket it with pure preparation.
s=files['phone_candidate_fast.py'].decode()
s=s.replace("    fast = compiled(src, 'packet', original_packet.__defaults__)\n", "    fast = compiled(src, 'packet', original_packet.__defaults__)\n    channel._phone_worker_packet = fast\n")
s=s.replace("            result = fixed_candidate(e)\n", "            parallel = getattr(cache.timer, 'parallel', None)\n            if parallel is not None and getattr(cache.timer.local, 'group', None) == 'optimized':\n                if not parallel.prepare(e):\n                    gate('계산 전환·실시간 상태 재확인')\n                    return None\n            result = fixed_candidate(e)\n")
s=s.replace("            if enabled():\n                return fast(*args, **kwargs)", "            if enabled():\n                parallel = getattr(cache.timer, 'parallel', None)\n                if parallel is not None:\n                    row, cfg, now = args[:3]\n                    prepared = parallel.lookup(row, cfg, now)\n                    if prepared is not None:\n                        return prepared\n                return fast(*args, **kwargs)")
(out/'phone_candidate_fast.py').write_text(s)
s=files['phone_performance.py'].decode().replace("    install(timer,pins)\n", "    install(timer,pins)\n    from phone_parallel import install as install_parallel\n    install_parallel(timer,pins)\n")
s=s.replace('    timer.start_writer(engine.stop_event)', "    def stop_parallel():\n        engine.stop_event.wait()\n        timer.parallel.close()\n    threading.Thread(target=stop_parallel, name='packet-stop', daemon=True).start()\n    timer.start_writer(engine.stop_event)")
(out/'phone_performance.py').write_text(s)
s=files['phone_mobile.py'].decode().replace('1.2.5','1.2.6')
s=s.replace('    module = types.ModuleType', '    old_route = "\'/api/control/update\':\'update\'"\n    if text.count(old_route) != 1: raise ValueError("control route mismatch")\n    text = text.replace(old_route, old_route+",\'/api/control/calculation\':\'calculation\'")\n    module = types.ModuleType')
s=s.replace('            self._view_revision = None', '            self.calculation_root = Path(args[0]).parent\n            self._view_revision = None')
s=s.replace("            if op not in {'update',", "            if op == 'calculation':\n                if not self.config.get('controls_enabled', False) or self.updater.installing:\n                    raise ValueError('계산 방식 변경 대기')\n                choice = kwargs.get('key')\n                if choice not in ('serial', 'parallel4'):\n                    raise ValueError('계산 방식 오류')\n                owner, client_id = args[:2]\n                if not module.re.fullmatch(r'[A-Za-z0-9_-]{12,80}', client_id): raise ValueError('request id')\n                request_id = module.hashlib.sha256((owner+':'+client_id).encode()).hexdigest()[:32]\n                from phone_parallel import set_preference\n                with self.lock:\n                    if request_id in self.control_results: return dict(self.control_results[request_id]['public'])\n                    now = time.monotonic()\n                    self.control_results = {k:v for k,v in self.control_results.items() if now-v['at']<600}\n                    if len(self.control_results)>=128: raise ValueError('requests')\n                    set_preference(self.calculation_root, 0 if choice == 'serial' else 4)\n                    public = dict(request_id=request_id, status='done', message=('기존 1.2.5 계산 방식 복원 요청' if choice == 'serial' else '4개 분산 요청')+' · 다음 신호 검사부터 반영')\n                    self.control_results[request_id] = dict(owner=owner, at=now, public=public)\n                    return public\n            if op not in {'update',")
(out/'phone_mobile.py').write_text(s)
s=files['phone_update_ui.js'].decode()+'''\n// Calculation mode: authenticated controls, no order or trading-mode action.
const parallelRender126=render;
render=function(d){
 parallelRender126(d);
 let box=document.getElementById('parallel126');
 if(!box){
  box=document.createElement('div');box.id='parallel126';
  const text=document.createElement('p');text.id='parallelState126';text.className='muted';box.appendChild(text);
  for(const [key,label] of [['parallel4','4개 분산 사용'],['serial','기존 방식으로 복원']]){
   const b=document.createElement('button');b.textContent=label;b.type='button';
   b.onclick=async()=>{b.disabled=true;try{
    const r=await api('/api/control/calculation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({client_id:'calc_'+crypto.randomUUID().replaceAll('-',''),key})});
    document.getElementById('parallelState126').textContent=r.message;
   }catch(e){document.getElementById('parallelState126').textContent='변경 미확인: '+e.message;}finally{b.disabled=false;}};
   box.appendChild(b);
  }
  document.getElementById('programUpdate').appendChild(box);
 }
 const p=d.performance?.parallel||{};
 const lines=['계산 방식: '+(p.effective===4?'4개 분산':p.effective===0?'기존 1.2.5 방식':'확인 중'),
  '선택: '+(p.requested===4?'4개 분산':p.requested===0?'기존 방식':'확인 중')+' · 실행 작업자 '+(p.workers_alive??0)+'개'];
 if(p.last_error)lines.push('계산 오류로 기존 방식 자동 복원: '+p.last_error);
 if(p.aggregate_rss_mib!=null)lines.push('부모+작업자 RSS 합계 '+p.aggregate_rss_mib+' MiB · CPU '+(p.aggregate_cpu_one_core_pct??'측정 중')+'% (1코어 환산)');
 lines.push('변경은 다음 신호 검사부터 적용 · 재시작 후에도 선택 유지 · 포지션/매매 규칙 유지');
 document.getElementById('parallelState126').style.whiteSpace='pre-line';
 document.getElementById('parallelState126').textContent=lines.join('\\n');
};
'''
(out/'phone_update_ui.js').write_text(s)
# Build a standalone hash-pinned incremental installer with the existing safe handover.
s=(repo/'android/phone_1_2_5_setup.py').read_text()
head=s[:s.index('PINNED =')].replace('1.2.4 -> 1.2.5 CPU overhead reduction','1.2.5 -> 1.2.6 reversible four-worker calculation')
helpers=s[s.index('\ndef digest('):s.index('\ndef candidate(originals)')].replace('1.2.4','1.2.5').replace('host-v22','host-v23')
body=s[s.index('\ndef candidate(originals)'):s.index('\ndef stage(')]
# Mobile/UI and performance are supplied as already-patched modules, not overwritten by the old version-only block.
a=body.index("    mobile = originals['phone_mobile.py']")
b=body.index("    update = originals['phone_update.py']")
body=body[:a]+body[b:]
for a,b in [('1.2.5','1.2.6'),('1.2.4','1.2.5'),('phone-service-23','phone-service-24'),('phone-service-22','phone-service-23'),('v23 managed','v24 managed'),('v22 managed','v23 managed'),('CURRENT = 23','CURRENT = 24'),('CURRENT = 22','CURRENT = 23'),('host-v22','host-v23'),('host-v21','host-v22')]:body=body.replace(a,b)
tail=s[s.index('\ndef stage('):].replace('host-v23','host-v24').replace('1.2.5','1.2.6').replace('반복 봉 변환 및 시세 처리 부하 개선','4개 계산 분산 및 기존 방식 복원')
pins={n:hashlib.sha256(b).hexdigest() for n,b in files.items()}
mods={n:(out/n).read_text() for n in ['phone_parallel.py','phone_candidate_fast.py','phone_performance.py','phone_mobile.py','phone_update_ui.js']}
installer=head+'PINNED = '+repr(pins)+"\nHOST_OLD = 'host-v23'\nHOST_NEW = 'host-v24'\nMODULES = "+repr(mods)+'\n'+helpers+body+tail
p=repo/'android/phone_1_2_6_setup.py';p.write_text(installer)
spec=importlib.util.spec_from_file_location('installer126',p);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
new=mod.candidate(mod.read_pins(repo.parent/'fixture121'));mod.stage(repo.parent/'fixture121',new)
print('installer',len(p.read_bytes()),hashlib.sha256(p.read_bytes()).hexdigest())
