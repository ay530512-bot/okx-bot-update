// Presentation only. Use persisted entry evidence, never the current scan.
const phonePositionExpanded = new Set();
function phoneEntryRows(parent, entries){
 const dl=node('dl',undefined,'phone-entry-rows');
 for(const [label,value] of entries){if(value==null||value==='')continue;dl.append(node('dt',label),node('dd',String(value)));}
 parent.append(dl);
}
function phoneRenderPositions(d,positions,tradeBusy,old){
 const root=$('positions');root.replaceChildren();
 for(const p of positions){
  const card=node('article',undefined,'position'+(p.symbol===state.symbol?' selected':''));
  const header=node('div',undefined,'row');
  const chart=node('button',p.symbol.replace('-USDT-SWAP','/USDT'),'phone-position-symbol');chart.type='button';
  chart.setAttribute('aria-label',p.symbol+' 차트 보기');
  chart.onclick=()=>{setPart('chart');chooseChart(p.symbol);render(state.data);$('chartPanel').scrollIntoView({behavior:'smooth',block:'start'});};
  header.append(chart,node('span',(p.source==='manual'?'수동':'자동')+' · '+(p.direction==='short'?'숏':'롱')+' '+p.leverage+'×','badge'));
  card.append(header);
  const metrics=node('div',undefined,'metrics');
  for(const [label,value,v] of [['증거금 USDT',cash(p.margin),null],['ROE',cash(num(p.roe)===null?null:num(p.roe)*100,true)+'%',p.roe],['손익 USDT',cash(p.pnl,true),p.pnl],['진입가',price(p.entry),null],['현재가',price(p.mark),null],['보호 SL',price(p.stop),null]]){
   const box=node('div');box.append(node('span',label));const b=node('b',value);if(v!==null)color(b,v);box.append(b);metrics.append(box);
  }
  card.append(metrics);
  const reason=p.entry_details||{};
  phoneEntryRows(card,[['진입 규칙',reason.rule||'진입 규칙 기록 없음'],['충족 조건',reason.summary||'저장된 조건 기록 없음']]);
  const footer=node('div',undefined,'phone-position-actions');
  if(reason.evidence?.length||reason.entry_ms||reason.confirmed_ms){
   const details=node('div',undefined,'phone-entry-more');details.hidden=!phonePositionExpanded.has(p.key);
   details.id='entry-proof-'+p.key;
   const rows=[];
   if(reason.frame)rows.push(['기준 봉',reason.frame==='15m'?'15분 완료봉':reason.frame]);
   if(Number.isFinite(reason.confirmed_ms))rows.push(['확인봉 마감',phoneMoveStamp(reason.confirmed_ms)+' KST']);
   if(Number.isFinite(reason.entry_ms))rows.push(['진입 요청',phoneMoveStamp(reason.entry_ms)+' KST']);
   for(const x of reason.evidence||[])rows.push([x.label,x.value]);
   phoneEntryRows(details,rows);
   card.append(details);
   const toggle=node('button','진입 근거 · 시간','phone-entry-toggle');toggle.type='button';
   toggle.setAttribute('aria-expanded',String(!details.hidden));toggle.setAttribute('aria-controls',details.id);
   toggle.onclick=()=>{details.hidden=!details.hidden;toggle.setAttribute('aria-expanded',String(!details.hidden));
    if(details.hidden)phonePositionExpanded.delete(p.key);else phonePositionExpanded.add(p.key);};
   footer.append(toggle);
  }
  if(p.protection_note)card.append(node('p',p.protection_note,'muted phone-protection-note'));
  if(p.close_key){
   const close=node('button','이 포지션 전량 청산','danger closeone');close.type='button';
   close.disabled=tradeBusy||!d.controls_enabled||old||p.phase==='closing';
   close.onclick=()=>trade('close_one',{key:p.close_key});footer.append(close);
  }
  if(footer.children.length)card.append(footer);
  root.append(card);
 }
 const active=new Set(positions.map(p=>p.key));for(const k of phonePositionExpanded)if(!active.has(k))phonePositionExpanded.delete(k);
 if(!positions.length)root.append(node('p','보유 포지션이 없습니다.','muted'));
}
