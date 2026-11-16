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
 const rows=['계산 성능','최근 '+(r.count||0)+'회 검사 · 평균 '+(Number.isFinite(r.mean_s)?r.mean_s.toFixed(3):'측정 중')+'초 · 95% 지점 '+(Number.isFinite(r.p95_s)?r.p95_s.toFixed(3):'측정 중')+'초',
  '계산 재사용 '+(c.hit_pct??'측정 중')+'% · 입력 저장 '+(c.input_mib??0)+' MiB · 밀려난 계산 '+(c.evictions??0)+'개',
  '프로세스 메모리 '+(m.rss_mib??'측정 중')+' MiB · CPU '+(m.cpu_one_core_pct??'측정 중')+'% (1코어 기준)'];
 const last=p.last_admission?.[0];
 if(last)rows.push('최근 진입 확인 결과: '+last.category+' · '+last.type);
 rows.push('실측 참고값 · 새 시세와 주문 직전 조건은 매번 확인');
 el.style.whiteSpace='pre-line';el.textContent=rows.join('\n');
};

// Separate diagnostic sections. All observed values are text, never HTML.
async function phoneSaveDiagnostics(d){
 const p=d.performance||{},h=p.runtime_health||{};
 // Authenticated, read-only export also includes retained prior-run records.
 const report=await api('/api/phone/diagnostic');
 const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download='okx_phone_diagnostic_'+(h.program_version||'unknown')+'.json';
 document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function phoneDiagnosticSection(parent,title,lines){
 const box=node('div',undefined,'phone-diagnostic-section');
 box.append(node('h3',title));for(const line of lines)box.append(node('p',line));
 parent.append(box);return box;
}
function phoneLeaderLines(d,h){
 const f=d.futures||{},now=Date.now(),rows=(f.rows||[]).filter(r=>
  typeof r.symbol==='string'&&Number.isFinite(r.change)&&r.change>0&&
  Number.isFinite(r.ts)&&r.ts<=now+5000&&now-r.ts<=60000&&
  Math.floor(r.ts/86400000)===Math.floor(now/86400000));
 rows.sort((a,b)=>b.change-a.change||a.symbol.localeCompare(b.symbol));
 const fresh=!f.stale&&Number.isFinite(f.observed_ms)&&now-f.observed_ms>=-5000&&now-f.observed_ms<=60000;
 const leader=fresh?rows[0]:null;
 const lines=[leader?'현재 시세 상승률 1위: '+leader.symbol.replace('-USDT-SWAP','')+' / +'+(leader.change*100).toFixed(2)+'%':
  '현재 시세 상승률 1위: '+(fresh?'상승 종목 없음 또는 시세 자료 대기':'시세 갱신 대기 · 이전 값을 현재 1위로 표시하지 않음')];
 if(leader)lines.push('시세 화면과 같은 KST09시 대비 현재가 · '+new Date(f.observed_ms).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})+' 확인');
 const ti=h?.trend_inputs,kstHour=Math.floor((now+9*3600000)%86400000/3600000),morning=kstHour>=5&&kstHour<8;
 const rank=morning?h?.morning_rank:h?.trend_rank;
 const checked=morning?h?.morning_rank_checked_ms:h?.trend_rank_checked_ms,label=morning?'오전 숏':'추세 롱';
 const valid=rank?.symbol&&ti?.ready===true&&checked===Math.floor(now/900000)*900000&&
  Number.isFinite(h.observed_at)&&now/1000-h.observed_at>=-5&&now/1000-h.observed_at<=10;
 if(valid){
  lines.push(label+' 규칙의 검사 대상: '+rank.symbol.replace('-USDT-SWAP','')+' / +'+(rank.gain*100).toFixed(2)+'% (최근 완료1시간봉 기준)');
  lines.push(morning?(h.morning_status||'이 종목의 큰 눌림·반등 실패·재하락 대기'):
   h.trend_armed_symbol===rank.symbol?'새 돌파 확인됨 · 이 종목의 눌림 종가 대기':h.trend_status||'이 종목의 돌파·눌림 조건 검사 중');
  if(leader&&leader.symbol!==rank.symbol)lines.push('현재가 순위와 완료1시간봉 순위가 다릅니다. 규칙의 순위 계산 기준은 유지합니다.');
 }else lines.push(label+' 규칙의 현재 검사 대상: 미확정 · 아래 자료/시간 대기 사유 확인');
 lines.push('자료 누락 종목은 상승률 1위나 진입 대상이라는 뜻이 아닙니다.');
 return lines;
}
const healthRender123=render;
render=function(d){
 healthRender123(d);
 let el=$('phoneHealthSummary');
 if(!el){el=node('div');el.id='phoneHealthSummary';$('programUpdate').append(el);}
 el.replaceChildren();
 const h=d.performance?.runtime_health;
 if(!h||h.unavailable){
  phoneDiagnosticSection(el,'추세 전용 1자리 · 상승률 1위',phoneLeaderLines(d,h));
  phoneDiagnosticSection(el,'연결·진입 진단',['진단 수집 중']);return;
 }
 const fresh=Math.max(0,Date.now()/1000-h.observed_at);
 const allowed=h.entry_enabled&&!h.user_paused&&!h.entry_cancelled&&!h.recovering&&h.public_connected&&h.account_fresh;
 const connection=[Math.round(fresh)+'초 전 확인 · 이번 실행 '+Math.floor((h.elapsed_s||0)/60)+'분',
  '시세 '+(h.public_connected===true?'연결':h.public_connected===false?'끊김':'확인 대기')+' / 계좌 '+(h.account_connected&&h.account_fresh?'최신 자료 수신':'연결·자료 확인 중'),
  '신규 진입: '+(fresh>10?'진단 자료 지연':allowed?'허용 · 조건·주문 검사 필요':'대기·차단'),
  '이번 실행 시세 끊김 '+(h.disconnect_count??'확인 중')+'회'];
 if(h.last_disconnect_at)connection.push('마지막 끊김 '+new Date(h.last_disconnect_at*1000).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})+' KST');
 const causes={read_eof:'소켓 수신 종료(EOF)',socket_already_closed:'이미 닫힌 소켓',websocket_closed:'웹소켓 종료',tcp_reset:'TCP 연결 초기화',write_broken_pipe:'송신 연결 종료',idle_timeout:'수신 무응답',peer_close_frame:'상대 종료 프레임',other_transport_error:'기타 통신 오류'};
 if(h.last_disconnect_cause)connection.push('종료 유형: '+(causes[h.last_disconnect_cause]||'분류 확인 필요'));
 for(const x of (h.disconnect_history||[]).slice(-3)){
  const time=new Date(x.observed_at*1000).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false});
  connection.push(time+' · '+(causes[x.cause]||x.cause)+' · 이전 연결 '+Math.round(x.connection_uptime_s||0)+'초 유지'+(x.server_notice?.code==='64008'?' · OKX 서버 점검 사전통지 수신':''));
 }
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
   card.append(node('p','봉 조건 통과 '+x.pass_count+' · 조건 대기 '+x.wait_count+' · 자료 대기 '+x.data_wait_count));
   if(x.inactive_count)card.append(node('p','다른 기존 경로 선택 '+x.inactive_count+'종목'));
   const reasons=Object.entries(x.reasons||{}).filter(([k])=>!k.includes('다른 기존 경로 선택')).sort((a,b)=>b[1]-a[1]);
   for(const [k,n] of reasons.slice(0,3))card.append(node('p',k+' '+n+'건'));
   rules.append(card);
  }
  rules.append(node('p','봉 조건 통과는 유효시간·실시간 시세·주문 검사를 통과했다는 뜻이 아닙니다.'));
  rules.append(node('p','눌림목·확정반전은 1시간 추세 상태에 따라 한 경로를 선택합니다. 두꼬리는 별도 OR 검사입니다.'));
 }
 const journey=h.signal_journey;
 if(journey){
  const lines=['최근 보존된 고유 신호 '+journey.unique_observed+'개 · 처음 볼 때 이미 90초 경과 '+journey.first_seen_expired+'개 (최대 1,024개 보존 · 놓친 거래 수 아님)'];
  for(const x of journey.rows||[]){
   lines.push(x.symbol+' '+x.action+' · '+x.stage_label);
   lines.push('확인봉 마감 '+phoneMoveStamp(x.valid_from_ms)+' KST · 첫 관측 '+x.first_delay_s+'초 후');
   if(x.route)lines.push('진입 경로: '+x.route);
   const timing=x.timing||{};
   const stamps=[['input_published_ms','입력 묶음 게시'],['rank_inputs_captured_ms','순위 입력 확인'],['computation_submitted_ms','계산 요청'],['computation_published_ms','계산 결과 확인']]
    .filter(([k])=>Number.isFinite(timing[k])).map(([k,label])=>label+' '+((timing[k]-x.valid_from_ms)/1000).toFixed(3)+'초');
   if(stamps.length)lines.push('봉 마감 기준 · '+stamps.join(' / ')+' (원격 수신시각과 다를 수 있음)');
   if(Number.isFinite(x.first_market_ready_ms))lines.push('시세 준비 확인: 봉 마감 '+((x.first_market_ready_ms-x.valid_from_ms)/1000).toFixed(3)+'초 후');
   if(x.rejection)lines.push('재검사 사유: '+x.rejection);
   if(x.last_market){
    const missing=Object.entries(x.last_market.channels||{}).filter(([k,v])=>!v.ready);
    const at=x.last_market.observed_ms??x.last_market_wait_ms;
    if(Number.isFinite(at))lines.push('마지막 시세 대기 관측: 봉 마감 '+((at-x.valid_from_ms)/1000).toFixed(3)+'초 후 · 당시 기록');
    lines.push('마지막 시세 대기: '+missing.map(([k,v])=>k+' '+(v.receive_age_s==null?'미수신':v.receive_age_s+'초 전 수신')+
     (v.subscribed?' · 구독 요청 전송됨':v.wanted?' · 구독 전송 대기':' · 구독 대상 지정 전')).join(' / '));
    if(Number.isFinite(x.last_market.request_wait_s))lines.push('당시 요청 간격·횟수 제한 대기: '+x.last_market.request_wait_s+'초');
   }
  }
  phoneDiagnosticSection(el,'최근 신호 진행 기록',lines);
 }
 const trendLines=[...phoneLeaderLines(d,h),h.trend_status||'추세 검사 대기'], ti=h.trend_inputs;
 if(ti&&Number.isFinite(ti.observed_ms)){
  trendLines.push('순위용 완료1시간봉 '+ti.hourly_ready+'/'+ti.eligible+'종목 · 전체 수집 진행 '+ti.scan_rows+'/'+ti.universe);
  if(ti.missing_hourly?.length)trendLines.push('순위 계산에 필요한 자료 누락 종목: '+ti.missing_hourly.join(', ')+' · 1위 종목 표시가 아닙니다');
  for(const x of ti.missing_hourly_details||[])trendLines.push(x.symbol+' · '+x.reason+' · 보관 1시간봉 '+x.completed1h_count+'개');
 }
 phoneDiagnosticSection(el,'추세 전용 1자리 · 상승률 1위',trendLines);
 phoneDiagnosticSection(el,'오전 숏 · 추가 규칙',[
  h.morning_status||'오전 숏 검사 대기',
  '신규 진입 KST05:00~08:00 미만 · 이후에도 보유분 추적손절 계속',
  '상승률: KST09시 시가 대비 최근 완료1시간봉 · 전체 허용종목 중 1위',
  '15분봉: 2%·1.5ATR 이상 눌림 → 0.5ATR 이상 반등 → 직전 고점 미돌파·재하락',
  '5배 숏 · 반등 고점 위 초기SL · 최저 관측가격 + 2×15분 ATR 전량 추적',
  '추세 롱 보유 중 숏 조건 발생: 롱 청산 확인 → 시간·신호 재검사 → 숏 전환',
  '전용1자리 공유 · 전체 최대4포지션 · 일반/수동 포지션은 전환 대상 아님']);
 const notes=['진입 허용은 체결 확인이 아닙니다. 끊김 횟수는 재시작 시 초기화됩니다.'];
 if(h.program_version)notes.push('진입 진단 기록은 재시작 후에도 보존됩니다 (최근 파일 최대 약 4MiB).');
 if(h.history_write_errors)notes.push('진단 기록 저장 오류 '+h.history_write_errors+'회');
 const recordBox=phoneDiagnosticSection(el,'기록 안내',notes);
 const save=node('button','연결·진입 진단 저장');save.type='button';
 save.onclick=async()=>{save.disabled=true;try{await phoneSaveDiagnostics(d);}catch(e){recordBox.append(node('p','진단 저장 실패: '+e.message));}finally{save.disabled=false;}};
 recordBox.append(save);
};

// Calculation mode: authenticated controls, no order or trading-mode action.
const parallelRender126=render;
render=function(d){
 parallelRender126(d);
 let box=document.getElementById('parallel126');
 if(!box){
  box=document.createElement('div');box.id='parallel126';
  const text=document.createElement('p');text.id='parallelState126';text.className='muted';box.appendChild(text);
  for(const [key,label] of [['parallel4','4개 분산 사용'],['serial','단일 계산으로 전환']]){
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
 const lines=['계산 방식: '+(p.effective===4?'4개 분산':p.effective===0?'모바일 단일 계산':'확인 중'),
  '선택: '+(p.requested===4?'4개 분산':p.requested===0?'모바일 단일 계산':'확인 중')+' · 실행 작업자 '+(p.workers_alive??0)+'개'];
 if(p.architecture==='mobile140')lines.push('모바일 전용 처리 · '+(p.calculating?'새 봉 계산 중':'계산 결과 준비')+' · 후보 시세·주문 검사 별도 진행');
 if(p.last_error)lines.push('계산 오류 · 모바일 단일 계산으로 복원: '+p.last_error);
 if(p.aggregate_rss_mib!=null)lines.push('부모+작업자 RSS 합계 '+p.aggregate_rss_mib+' MiB · CPU '+(p.aggregate_cpu_one_core_pct??'측정 중')+'% (1코어 환산)');
 lines.push('변경은 다음 신호 검사부터 적용 · 재시작 후에도 선택 유지 · 포지션/매매 규칙 유지');
 document.getElementById('parallelState126').style.whiteSpace='pre-line';
 document.getElementById('parallelState126').textContent=lines.join('\n');
};
