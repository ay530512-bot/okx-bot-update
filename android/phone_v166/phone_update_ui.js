// Reconcile text in place; never empty a live reading region on refresh.
function phoneUiKey(el,key){el.phoneUiKey=key;return el}
function phoneUiText(el,value){const text=String(value);if(el.textContent!==text)el.textContent=text}
function phoneUiSync(target,source){
 if(target.className!==source.className)target.className=source.className;
 const incoming=Array.from(source.children);
 if(!incoming.length){phoneUiText(target,source.textContent);return}
 // The initial HTML may contain a plain-text placeholder before its first rows.
 if(!target.children.length&&target.textContent)phoneUiText(target,'');
 const key=(el,i)=>el.phoneUiKey??(el.id||(el.tagName+':'+i));
 const old=new Map(Array.from(target.children,(el,i)=>[key(el,i),el])),keep=new Set();
 for(let i=0;i<incoming.length;i++){
  const wanted=incoming[i],id=key(wanted,i);let child=old.get(id);
  if(child&&child.tagName===wanted.tagName)phoneUiSync(child,wanted);else child=wanted;
  keep.add(child);
  if(target.children[i]!==child)target.insertBefore(child,target.children[i]||null);
 }
 for(const child of Array.from(target.children))if(!keep.has(child))child.remove();
}
function phoneUiScrollMark(el){
 if(!el)return null;
 const mark={el,top:el.scrollTop||0};
 if(mark.top&&el.getBoundingClientRect&&el.querySelectorAll){
  const box=el.getBoundingClientRect();
  for(const child of el.querySelectorAll('h3,h4,p')){
   const rect=child.getBoundingClientRect();
   if(rect.bottom>box.top&&rect.top<box.bottom){mark.anchor=child;mark.offset=rect.top-box.top;break}
  }
 }
 return mark;
}
function phoneUiScrollRestore(mark){
 if(!mark)return;
 const {el,anchor}=mark;
 if(anchor?.isConnected){
  const delta=(anchor.getBoundingClientRect().top-el.getBoundingClientRect().top)-mark.offset;
  if(Math.abs(delta)>.5)el.scrollTop+=delta;
 }
 else if(el.scrollTop!==mark.top)el.scrollTop=mark.top;
}

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
 if(typeof activePart!=='undefined'&&activePart!=='settings')return;
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
 const box=phoneUiKey(node('div',undefined,'phone-diagnostic-section'),title);
 box.append(node('h3',title));for(const line of lines)box.append(node('p',line));
 parent.append(box);return box;
}
function phoneLeaderLines(d,h){
 const f=d.futures||{},r=f.live_rank,now=Date.now();
 const fresh=r?.ready===true&&!f.stale&&Number.isFinite(r.observed_ms)&&
  now-r.observed_ms>=-5000&&now-r.observed_ms<=10000&&r.day===Math.floor(now/86400000)*86400000;
 if(!fresh)return ['현재 상승률 1위: 전체 시세 갱신 대기','현재가 순위가 확정되면 검사 대상도 함께 갱신합니다.'];
 const leader=r.leader;
 if(!leader)return ['현재 상승률 1위: 상승 종목 없음','KST09시 대비 상승 종목이 생기면 검사합니다.'];
 const symbol=leader.symbol.replace('-USDT-SWAP','');
 const lines=['현재 상승률 1위: '+symbol+' / +'+(leader.gain*100).toFixed(2)+'%',
  '전체 매매 대상 · KST09시 대비 현재가 · 1위 변경 시 자동 교체'];
 const hour=Math.floor((now+9*3600000)%86400000/3600000);
 if(hour>=2&&hour<5)lines.push('숏 대기 대상: '+symbol+' · 05:00부터 조건 충족 시 진입');
 else if(hour>=8&&hour<15)lines.push('롱 대기 대상: '+symbol+' · 15:00부터 조건 충족 시 진입');
 else{
  const morning=hour>=5&&hour<8,rank=morning?h?.morning_rank:h?.trend_rank;
  const checked=morning?h?.morning_rank_checked_ms:h?.trend_rank_checked_ms;
  lines.push((morning?'오전 숏':'추세 롱')+' 검사 대상: '+symbol);
  const valid=rank?.symbol===leader.symbol&&checked===Math.floor(now/900000)*900000&&
   Number.isFinite(h?.observed_at)&&now/1000-h.observed_at>=-5&&now/1000-h.observed_at<=10;
  lines.push(valid?(morning?h.morning_status:h.trend_status)||'완료봉 조건 검사 대기':'해당 종목의 완료봉 조건 검사 대기');
 }
 return lines;
}
const healthRender123=render;
let phoneDiagnosticData=null;
const phoneDiagnosticView={lastHealth:null,paused:false};
function phoneDiagnosticPanel(d){
 phoneDiagnosticData=d;
 let el=$('phoneHealthSummary');
 if(el)return el;
 const toolbar=node('div',undefined,'phone-diagnostic-toolbar');
 const save=node('button','연결·진입 진단 저장');save.id='phoneDiagnosticSave';save.type='button';
 const reading=node('button','읽기 고정');reading.id='phoneDiagnosticRead';reading.type='button';
 const readStatus=node('p','자동 갱신', 'muted');readStatus.id='phoneDiagnosticReadStatus';
 if(reading.setAttribute)reading.setAttribute('aria-pressed','false');
 if(readStatus.setAttribute)readStatus.setAttribute('role','status');
 reading.onclick=()=>{
  phoneDiagnosticView.paused=!phoneDiagnosticView.paused;
  phoneUiText(reading,phoneDiagnosticView.paused?'최신 보기':'읽기 고정');
  if(reading.setAttribute)reading.setAttribute('aria-pressed',String(phoneDiagnosticView.paused));
  phoneRenderDiagnostics(phoneDiagnosticData||{});
 };
 const status=node('p','', 'muted');status.id='phoneDiagnosticSaveStatus';
 if(status.setAttribute)status.setAttribute('role','status');
 save.onclick=async()=>{
  if(save.disabled)return;
  save.disabled=true;status.textContent='진단 파일 준비 중';
  try{await phoneSaveDiagnostics(phoneDiagnosticData||{});status.textContent='진단 파일 저장 요청 완료';}
  catch(e){status.textContent='진단 저장 실패: '+e.message;}
  finally{save.disabled=false;}
 };
 const actions=node('div',undefined,'phone-diagnostic-actions');actions.append(save,reading);
 toolbar.append(actions,status,readStatus);
 el=node('div');el.id='phoneHealthSummary';el.tabIndex=0;
 if(el.setAttribute){el.setAttribute('role','region');el.setAttribute('aria-label','연결·진입 진단 · 내부 스크롤');}
 $('programUpdate').append(toolbar,el);return el;
}
function phoneRenderDiagnostics(d){
 const live=phoneDiagnosticPanel(d),incoming=d.performance?.runtime_health;
 const usable=incoming&&!incoming.unavailable&&Number.isFinite(incoming.observed_at);
 if(usable)phoneDiagnosticView.lastHealth=incoming;
 if(phoneDiagnosticView.paused){phoneUiText($('phoneDiagnosticReadStatus'),'읽기 고정 · 화면만 멈춤 · 시세·매매는 계속');return}
 phoneUiText($('phoneDiagnosticReadStatus'),usable?'자동 갱신':'진단 갱신 대기 · 마지막 확인값 유지');
 const panelMark=phoneUiScrollMark(live),journeyMark=phoneUiScrollMark($('phoneSignalJourney'));
 const el=node('div'),h=usable?incoming:phoneDiagnosticView.lastHealth;
 const commit=()=>{phoneUiSync(live,el);phoneUiScrollRestore(journeyMark);phoneUiScrollRestore(panelMark)};
 if(!h){
  phoneDiagnosticSection(el,'추세 전용 1자리 · 상승률 1위',phoneLeaderLines(d,h));
  phoneDiagnosticSection(el,'연결·진입 진단',['진단 수집 중']);commit();return;
 }
 const fresh=Math.max(0,Date.now()/1000-h.observed_at);
 const allowed=h.entry_enabled&&!h.user_paused&&!h.entry_cancelled&&!h.recovering&&h.public_connected&&h.account_fresh;
 const connection=[Math.round(fresh)+'초 전 확인 · 이번 실행 '+Math.floor((h.elapsed_s||0)/60)+'분',
  '진입·보유 시세 '+(h.public_connected===true?'연결':h.public_connected===false?'끊김':'확인 대기')+' / 계좌 '+(h.account_connected&&h.account_fresh?'최신 자료 수신':'연결·자료 확인 중'),
  '신규 진입: '+(!usable||fresh>10?'진단 자료 지연':allowed?'허용 · 조건·주문 검사 필요':'대기·차단'),
  '이번 실행 시세 끊김 '+(h.disconnect_count??'확인 중')+'회'];
 if(h.monitor_connected!==undefined)connection.push('전체 종목 감시 '+(h.monitor_connected===true?'연결':h.monitor_connected===false?'복구 중':'확인 대기')+' · 진입·보유 끊김 '+(h.execution_disconnect_count??0)+'회 / 감시 끊김 '+(h.monitor_disconnect_count??0)+'회');
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
   const card=phoneUiKey(node('div',undefined,'phone-rule-card'),key);card.append(node('h4',names[key]||key));
   card.append(node('p','봉 조건 통과 '+x.pass_count+' · 조건 대기 '+x.wait_count+' · 자료 대기 '+x.data_wait_count));
   if(x.inactive_count)card.append(node('p','다른 기존 경로 선택 '+x.inactive_count+'종목'));
   const reasons=Object.entries(x.reasons||{}).filter(([k])=>!k.includes('다른 기존 경로 선택')).sort((a,b)=>b[1]-a[1]);
   for(const [k,n] of reasons.slice(0,3))card.append(phoneUiKey(node('p',k+' '+n+'건'),'reason:'+k));
   rules.append(card);
  }
  rules.append(node('p','봉 조건 통과는 유효시간·실시간 시세·주문 검사를 통과했다는 뜻이 아닙니다.'));
  rules.append(node('p','눌림목·확정반전은 1시간 추세 상태에 따라 한 경로를 선택합니다. 두꼬리는 별도 OR 검사입니다.'));
 }
 const journey=h.signal_journey;
 if(journey){
  const section=phoneDiagnosticSection(el,'최근 신호 진행 기록',[]);
  section.append(node('p','최근 보존된 고유 신호 '+journey.unique_observed+'개 · 처음 볼 때 이미 90초 경과 '+journey.first_seen_expired+'개 (최대 1,024개 보존 · 놓친 거래 수 아님)','phone-journey-count'));
  const scroll=node('div',undefined,'phone-signal-scroll');scroll.id='phoneSignalJourney';scroll.tabIndex=0;
  if(scroll.setAttribute){scroll.setAttribute('role','region');scroll.setAttribute('aria-label','최근 신호 진행 기록 · 스크롤');}
  section.append(scroll);
  for(const x of journey.rows||[]){
   const lines=[];
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
     (v.acknowledged?' · 거래소 구독 확인':v.subscribed?' · 구독 요청 전송됨':v.wanted?' · 구독 전송 대기':' · 구독 대상 지정 전')).join(' / '));
    if(Number.isFinite(x.last_market.request_wait_s))lines.push('당시 요청 간격·횟수 제한 대기: '+x.last_market.request_wait_s+'초');
   }
   const item=phoneUiKey(node('div',undefined,'phone-signal-item'),[x.symbol,x.action,x.valid_from_ms,x.route||''].join('|'));
   for(const line of lines)item.append(node('p',line));
   scroll.append(item);
  }
 }
 const trendLines=phoneLeaderLines(d,h), ti=d.futures?.live_rank;
 if(ti){
  trendLines.push('순위용 현재가 '+ti.quotes_ready+'/'+ti.eligible+'종목');
  if(ti.missing_quotes?.length)trendLines.push('시세 대기: '+ti.missing_quotes.join(', '));
  if(ti.baseline_ineligible_count)trendLines.push('09시 이후 신규 상장 '+ti.baseline_ineligible_count+'종목 · 다음 09시부터 비교');
 }
 phoneDiagnosticSection(el,'추세 전용 1자리 · 상승률 1위',trendLines);
 phoneDiagnosticSection(el,'오전 숏 · 추가 규칙',[
  '신규 진입 KST05:00~08:00 미만 · 이후에도 보유분 추적손절 계속',
  '상승률: KST09시 대비 현재가 · 바뀐 1위로 계속 갱신',
  '15분봉: 2%·1.5ATR 이상 눌림 → 0.5ATR 이상 반등 → 직전 고점 미돌파·재하락',
  '5배 숏 · 반등 고점 위 초기SL · 최저 관측가격 + 2×15분 ATR 전량 추적',
  '추세 롱 보유 중 숏 조건 발생: 롱 청산 확인 → 시간·신호 재검사 → 숏 전환',
  '전용1자리 공유 · 전체 최대4포지션 · 일반/수동 포지션은 전환 대상 아님']);
 const notes=['진입 허용은 체결 확인이 아닙니다. 끊김 횟수는 재시작 시 초기화됩니다.'];
 if(h.program_version)notes.push('진입 진단 기록은 재시작 후에도 보존됩니다 (최근 파일 최대 약 4MiB).');
 if(h.history_write_errors)notes.push('진단 기록 저장 오류 '+h.history_write_errors+'회');
 phoneDiagnosticSection(el,'기록 안내',notes);
 commit();
}
render=function(d){
 healthRender123(d);
 if(typeof activePart!=='undefined'&&activePart!=='settings')return;
 phoneRenderDiagnostics(d);
};

// Calculation mode: authenticated controls, no order or trading-mode action.
const parallelRender126=render;
render=function(d){
 parallelRender126(d);
 if(typeof activePart!=='undefined'&&activePart!=='settings')return;
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
