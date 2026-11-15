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

// Read-only verification summary; elapsed run and faults remain explicit.
const healthRender123 = render;
render = function(d){
 healthRender123(d);
 let el=document.getElementById('phoneHealthSummary');
 if(!el){el=document.createElement('p');el.id='phoneHealthSummary';el.className='muted';document.getElementById('programUpdate').appendChild(el);}
 const h=d.performance?.runtime_health, rows=[];
 if(!h||h.unavailable){el.textContent='연결·진입 진단 수집 중';return;}
 const fresh=Math.max(0,Date.now()/1000-h.observed_at);
 rows.push('연결·진입 진단 '+Math.round(fresh)+'초 전 · 이번 실행 '+Math.floor((h.elapsed_s||0)/60)+'분');
 rows.push('시세 '+(h.public_connected===true?'연결':h.public_connected===false?'끊김':'확인 대기')+' / 계좌 '+(h.account_connected&&h.account_fresh?'최신 자료 수신':'연결·자료 확인 중'));
 const allowed=h.entry_enabled&&!h.user_paused&&!h.entry_cancelled&&!h.recovering&&h.public_connected&&h.account_fresh;
 rows.push('신규 진입 상태: '+(fresh>10?'진단 자료 지연':allowed?'허용 · 조건·주문 검사 필요':'대기·차단'));
 rows.push('이번 실행 시세 끊김 '+(h.disconnect_count??'확인 중')+'회');
 if(h.last_disconnect_at)rows.push('마지막 끊김 '+new Date(h.last_disconnect_at*1000).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})+' KST');
 const causes={read_eof:'소켓 수신 종료(EOF)',socket_already_closed:'이미 닫힌 소켓',websocket_closed:'웹소켓 종료',tcp_reset:'TCP 연결 초기화',write_broken_pipe:'송신 연결 종료',idle_timeout:'수신 무응답',peer_close_frame:'상대 종료 프레임',other_transport_error:'기타 통신 오류'};
 if(h.last_disconnect_cause)rows.push('마지막 종료 유형: '+(causes[h.last_disconnect_cause]||'분류 확인 필요'));
 const e=h.entry||{};
 if(e.observed_at){
  rows.push('신호 검사 '+Math.round(Math.max(0,Date.now()/1000-e.observed_at))+'초 전 · '+e.duration_s+'초 소요 · 준비 '+e.pending+'개 · '+e.result);
  const reasons=Object.entries(e.reasons||{}).map(([k,v])=>k+' '+v+'건');
  if(reasons.length)rows.push('이번 검사 대기 이유: '+reasons.join(' / '));
  for(const w of e.waiting||[])rows.push(w.symbol+' · '+w.channels.join(', ')+' 대기 · 검사 당시 유효시간 '+w.remaining_s+'초 남음');
 }
 rows.push('연결 허용은 체결 확인이 아닙니다. 끊김 횟수는 재시작 시 초기화됩니다.');
 el.style.whiteSpace='pre-line';el.textContent=rows.join('\n');
};

// Calculation mode: authenticated controls, no order or trading-mode action.
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
 document.getElementById('parallelState126').textContent=lines.join('\n');
};
