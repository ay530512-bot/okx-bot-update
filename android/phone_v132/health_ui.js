// Separate diagnostic sections. All observed values are text, never HTML.
function phoneDiagnosticSection(parent,title,lines){
 const box=node('div',undefined,'phone-diagnostic-section');
 box.append(node('h3',title));for(const line of lines)box.append(node('p',line));
 parent.append(box);return box;
}
const healthRender123=render;
render=function(d){
 healthRender123(d);
 let el=$('phoneHealthSummary');
 if(!el){el=node('div');el.id='phoneHealthSummary';$('programUpdate').append(el);}
 el.replaceChildren();
 const h=d.performance?.runtime_health;
 if(!h||h.unavailable){phoneDiagnosticSection(el,'연결·진입 진단',['진단 수집 중']);return;}
 const fresh=Math.max(0,Date.now()/1000-h.observed_at);
 const allowed=h.entry_enabled&&!h.user_paused&&!h.entry_cancelled&&!h.recovering&&h.public_connected&&h.account_fresh;
 const connection=[Math.round(fresh)+'초 전 확인 · 이번 실행 '+Math.floor((h.elapsed_s||0)/60)+'분',
  '시세 '+(h.public_connected===true?'연결':h.public_connected===false?'끊김':'확인 대기')+' / 계좌 '+(h.account_connected&&h.account_fresh?'최신 자료 수신':'연결·자료 확인 중'),
  '신규 진입: '+(fresh>10?'진단 자료 지연':allowed?'허용 · 조건·주문 검사 필요':'대기·차단'),
  '이번 실행 시세 끊김 '+(h.disconnect_count??'확인 중')+'회'];
 if(h.last_disconnect_at)connection.push('마지막 끊김 '+new Date(h.last_disconnect_at*1000).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})+' KST');
 const causes={read_eof:'소켓 수신 종료(EOF)',socket_already_closed:'이미 닫힌 소켓',websocket_closed:'웹소켓 종료',tcp_reset:'TCP 연결 초기화',write_broken_pipe:'송신 연결 종료',idle_timeout:'수신 무응답',peer_close_frame:'상대 종료 프레임',other_transport_error:'기타 통신 오류'};
 if(h.last_disconnect_cause)connection.push('종료 유형: '+(causes[h.last_disconnect_cause]||'분류 확인 필요'));
 phoneDiagnosticSection(el,'연결 상태',connection);
 const e=h.entry||{},scan=[];
 if(e.observed_at){
  scan.push(Math.round(Math.max(0,Date.now()/1000-e.observed_at))+'초 전 검사 · '+e.duration_s+'초 소요');
  scan.push('준비 '+(e.pending??0)+'개 · '+e.result);
  for(const [k,v] of Object.entries(e.reasons||{}))scan.push(k+' '+v+'건');
  for(const w of e.waiting||[])scan.push(w.symbol+' · '+w.channels.join(', ')+' 대기 · 검사 당시 유효시간 '+w.remaining_s+'초');
 }else scan.push('첫 신호 검사 대기');
 if(h.entry_observation_totals)scan.push('이번 실행 '+h.entry_observation_totals.scans+'회 검사 / 주문 전 검사 전달 '+h.entry_observation_totals.candidate_returns+'회 (체결 건수 아님)');
 phoneDiagnosticSection(el,'신호 검사',scan);
 if(e.routes){
  const rules=phoneDiagnosticSection(el,'규칙별 검사 결과',[]);
  const names={trend_pullback:'눌림목',confirmed_reversal:'확정반전',double_wick:'두꼬리'};
  for(const [key,x] of Object.entries(e.routes)){
   const card=node('div',undefined,'phone-rule-card');card.append(node('h4',names[key]||key));
   card.append(node('p','통과 '+x.pass_count+' · 조건 대기 '+x.wait_count+' · 자료 대기 '+x.data_wait_count));
   if(x.inactive_count)card.append(node('p','다른 기존 경로 선택 '+x.inactive_count+'종목'));
   const reasons=Object.entries(x.reasons||{}).filter(([k])=>!k.includes('다른 기존 경로 선택')).sort((a,b)=>b[1]-a[1]);
   for(const [k,n] of reasons.slice(0,3))card.append(node('p',k+' '+n+'건'));
   rules.append(card);
  }
  rules.append(node('p','눌림목·확정반전은 1시간 추세 상태에 따라 한 경로를 선택합니다. 두꼬리는 별도 OR 검사입니다.'));
 }
 phoneDiagnosticSection(el,'추세 전용 1자리',[h.trend_status||'추세 검사 대기']);
 const notes=['진입 허용은 체결 확인이 아닙니다. 끊김 횟수는 재시작 시 초기화됩니다.'];
 if(h.program_version)notes.push('진입 진단 기록은 재시작 후에도 보존됩니다 (최근 파일 최대 약 4MiB).');
 if(h.history_write_errors)notes.push('진단 기록 저장 오류 '+h.history_write_errors+'회');
 phoneDiagnosticSection(el,'기록 안내',notes);
};
