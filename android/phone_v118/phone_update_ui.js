// Phone release controls. Reuse authenticated same-origin control endpoint.
const phoneOriginalRender = render;
render = function(d) {
 phoneOriginalRender(d);
 const u=d.program_update||{};
 $('mobileUpdateButton').textContent=u.ticket?'확인한 새 버전 설치':'폰 새 버전 확인';
 $('mobileUpdateStatus').textContent=(u.message||'1.1.8')+(u.notes?'\n'+u.notes:'');
 $('mobileUpdateStatus').style.whiteSpace='pre-wrap';
};
$('mobileUpdateButton').onclick=async()=>{
 const u=state.data?.program_update||{};
 const body={client_id:'phone_update_'+crypto.randomUUID().replaceAll('-','')};
 if(u.ticket){
  if(!confirm('폰 버전 '+u.target_version+' 설치\n'+u.notes+'\n\n신규 진입만 자동으로 잠시 멈추고 보유분과 거래소 손절을 인계합니다. 완료 후 기존 운용 상태로 복구하며, 원래 중지 상태였다면 계속 중지합니다. 교체 중 로컬 추적 관리는 잠시 쉬고 거래소 손절은 유지됩니다. 설치할까요?'))return;
  body.ticket=u.ticket;
 }
 $('mobileUpdateButton').disabled=true;
 try{
  const r=await api('/api/control/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  $('mobileUpdateStatus').textContent=r.message;
 }catch(e){$('mobileUpdateStatus').textContent='응답 미확인 · 새로고침 후 설치 상태 확인: '+e.message;}
};

const perfRender113 = render;
render = function(d){
 perfRender113(d);
 let el=document.getElementById('phonePerfSummary');
 if(!el){el=document.createElement('p');el.id='phonePerfSummary';el.className='muted';document.getElementById('programUpdate').appendChild(el);}
 const p=d.performance||{}, r=p.recent||{}, c=p.cache||{}, m=p.resources||{};
 const rows=['최근 '+(r.count||0)+'회 검사 · 평균 '+(r.mean_s??'측정 중')+'초 · 95% 지점 '+(r.p95_s??'측정 중')+'초',
  '계산 재사용 '+(c.hit_pct??'측정 중')+'% · 입력 저장 '+(c.input_mib??0)+' MiB · 밀려난 계산 '+(c.evictions??0)+'개',
  '프로세스 메모리 '+(m.rss_mib??'측정 중')+' MiB · CPU '+(m.cpu_one_core_pct??'측정 중')+'% (1코어 기준)'];
 const last=p.last_admission?.[0];
 if(last)rows.push('최근 진입 확인 결과: '+last.category+' · '+last.type);
 rows.push('실측 참고값 · 새 시세와 주문 직전 조건은 매번 확인');
 el.style.whiteSpace='pre-line';el.textContent=rows.join('\n');
};
