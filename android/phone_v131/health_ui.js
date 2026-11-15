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
  const names={trend_pullback:'눌림목',confirmed_reversal:'확정반전',double_wick:'두꼬리'};
  for(const [key,x] of Object.entries(e.routes||{})){
   rows.push((names[key]||key)+': 통과 '+x.pass_count+' · 조건대기 '+x.wait_count+' · 자료대기 '+x.data_wait_count+' · 상태별 비활성 '+x.inactive_count);
   const top=Object.entries(x.reasons||{}).sort((a,b)=>b[1]-a[1]).slice(0,2).map(([k,n])=>k+' '+n+'건');
   if(top.length)rows.push('  '+top.join(' / '));
  }
  if(e.routes)rows.push('눌림목·확정반전은 1시간 추세 상태에 따라 선택됩니다. 두꼬리는 별도 OR 검사입니다.');
  for(const w of e.waiting||[])rows.push(w.symbol+' · '+w.channels.join(', ')+' 대기 · 검사 당시 유효시간 '+w.remaining_s+'초 남음');
 }
 if(h.entry_observation_totals)rows.push('이번 실행 검사 '+h.entry_observation_totals.scans+'회 · 주문 전 검사 전달 '+h.entry_observation_totals.candidate_returns+'회(체결 건수 아님)');
 if(h.trend_status)rows.push('추세 전용1자리: '+h.trend_status);
 rows.push('연결 허용은 체결 확인이 아닙니다. 끊김 횟수는 재시작 시 초기화됩니다.');
 if(h.program_version)rows.push('진입 진단 기록은 재시작 후에도 보존됩니다(최근 파일 최대 약4MiB).');
 if(h.history_write_errors)rows.push('진단 기록 저장 오류 '+h.history_write_errors+'회');
 el.style.whiteSpace='pre-line';el.textContent=rows.join('\n');
};

