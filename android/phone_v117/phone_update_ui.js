// Phone release controls. Reuse authenticated same-origin control endpoint.
const phoneOriginalRender = render;
render = function(d) {
 phoneOriginalRender(d);
 const u=d.program_update||{};
 $('mobileUpdateButton').textContent=u.ticket?'확인한 새 버전 설치':'폰 새 버전 확인';
 $('mobileUpdateStatus').textContent=(u.message||'1.1.7')+(u.notes?'\n'+u.notes:'');
 $('mobileUpdateStatus').style.whiteSpace='pre-wrap';
};
$('mobileUpdateButton').onclick=async()=>{
 const u=state.data?.program_update||{};
 const body={client_id:'phone_update_'+crypto.randomUUID().replaceAll('-','')};
 if(u.ticket){
  if(!confirm('폰 버전 '+u.target_version+' 설치\n'+u.notes+'\n\n신규 진입을 중지하고 보유·미체결·조건주문이 모두 0이어야 합니다. 설치 중 잠시 연결이 끊기며 완료 후 실거래 시작은 직접 확인합니다. 설치할까요?'))return;
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
