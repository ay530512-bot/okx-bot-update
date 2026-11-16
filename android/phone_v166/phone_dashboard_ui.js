// Received account values only. Display updates never grant order readiness.
const phoneDashboard={source:null,part:'',last:null,received:0,opened:0,fullAt:0,
 fallbackAt:0,fallbackBusy:false,paint:false,goalSignature:'',marketNodes:new Map(),marketOrder:''};
function phoneDashboardVisible(){return !document.hidden&&!$('dashboard').hidden}
function phoneDashboardOld(d){
 return d.ui_version!==UI_BUILD||!d.captured_ms||Date.now()-d.captured_ms>15000||
  d.account_age_seconds==null||d.account_age_seconds>30||d.account_live?.connected===false;
}
function phoneDashboardText(id,value){const el=$(id);if(el&&el.textContent!==String(value))el.textContent=String(value)}
function phoneDashboardFresh(d){
 const live=d.account_live,age=d.account_age_seconds;
 const seconds=live?.received_ms==null?null:Math.max(0,(Date.now()-live.received_ms)/1000);
 phoneDashboardText('fresh',(live?.account_live&&seconds!==null&&seconds<=5?'잔고 수신 '+seconds.toFixed(1)+'초 전':'잔고 · 마지막 확인값')+
  ' · 주문 대조 '+(age==null?'대기':Math.round(age)+'초 전')+'\n'+
  (live?.account_live?'손익: 마지막 입출금 대조 기준':'잔고·손익: 마지막 확인값')+' · 실시간 갱신');
}
function phoneDashboardMerge(base){
 const latest=phoneDashboard.last;
 return latest&&Date.now()-phoneDashboard.received<5000&&(latest.display_ms||0)>=(base.display_ms||0)?{...base,...latest}:base;
}
function phoneDashboardAccept(d){
 if(!d||!Number.isFinite(d.display_ms)||d.display_ms<(phoneDashboard.last?.display_ms||0))return false;
 phoneDashboard.last={...(phoneDashboard.last||{}),...d};phoneDashboard.received=Date.now();
 if(state.data?.ui_version===UI_BUILD)state.data=phoneDashboardMerge(state.data);
 phoneDashboardDraw();return true;
}
function phoneDashboardDraw(){
 if(phoneDashboard.paint||!phoneDashboardVisible())return;
 phoneDashboard.paint=true;
 requestAnimationFrame(()=>{
  phoneDashboard.paint=false;if(!phoneDashboardVisible()||state.data?.ui_version!==UI_BUILD)return;
  const d=state.data,s=d.state||{},old=phoneDashboardOld(d);
  phoneDashboardText('equity',cash(s.equity));phoneDashboardText('profit',cash(s.day_profit,true));color($('profit'),s.day_profit);
  phoneDashboardText('available',cash(s.available));phoneDashboardText('cost','$'+cash(s.api_spent,false,3));
  phoneDashboardText('status',(old?'자료 지연 · ':'')+(d.status||'폰 계정 자료 대기'));
  $('status').classList.toggle('warning',old||s.recovering||!s.account_connected);phoneDashboardFresh(d);
  const goal=JSON.stringify([s.daily_goal,old||!s.account_connected]);
  if(goal!==phoneDashboard.goalSignature){phoneDashboard.goalSignature=goal;renderGoal(s.daily_goal,old||!s.account_connected)}
  $('livePrepare').disabled=!d.controls_enabled||controlBusy;$('pauseEntries').disabled=!d.controls_enabled||controlBusy;
  const positions=d.positions||[];phoneDashboardText('count',positions.length);
  $('closeAll').disabled=tradeBusy||!d.controls_enabled||old||!positions.length;
  if(activePart==='chart'){phoneRenderPositions(d,positions,tradeBusy,old);updateTradeButtons();draw()}
  if(activePart==='market')renderMarket();
 });
}
const phoneDashboardFullRender=render;
render=function(data){const d=phoneDashboardMerge(data);phoneDashboardFullRender(d);phoneDashboardFresh(d)};
refresh=async function(){
 if(document.hidden||state.busy||Date.now()-phoneDashboard.fullAt<2000)return;
 state.busy=true;phoneDashboard.fullAt=Date.now();
 try{const d=await api('/api/snapshot');showDashboard();render(d);if(activePart==='chart'&&!state.chartKey)void refreshChart()}
 catch(e){if(!$('dashboard').hidden){phoneDashboardText('status','연결 지연 · '+e.message);$('status').classList.add('warning');renderGoal(state.data.state?.daily_goal,true)}}
 finally{state.busy=false}
};
function phoneDashboardDisconnect(){phoneDashboard.source?.close();phoneDashboard.source=null;phoneDashboard.part=''}
async function phoneDashboardFallback(part){
 if(phoneDashboard.fallbackBusy||Date.now()-phoneDashboard.fallbackAt<500)return;
 phoneDashboard.fallbackBusy=true;phoneDashboard.fallbackAt=Date.now();
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),2000);
 try{const d=await phoneChartRead('/api/phone/dashboard-live?part='+part,controller);
  if(phoneDashboardVisible()&&activePart===part)phoneDashboardAccept(d);
 }catch(e){/* Full snapshot refresh remains independent. */}
 finally{clearTimeout(timer);phoneDashboard.fallbackBusy=false}
}
function phoneDashboardPulse(){
 if(!phoneDashboardVisible()){if(phoneDashboard.part)phoneDashboardDisconnect();return}
 if(phoneDashboard.part!==activePart){
  phoneDashboardDisconnect();phoneDashboard.part=activePart;phoneDashboard.opened=Date.now();phoneDashboard.received=0;
  if(typeof EventSource!=='undefined'){
   const source=new EventSource('/api/phone/dashboard-live?part='+activePart+'&stream=1');phoneDashboard.source=source;
   source.onmessage=event=>{if(source!==phoneDashboard.source||!phoneDashboardVisible())return;
    try{phoneDashboardAccept(JSON.parse(event.data))}catch(e){/* Ignore malformed observations. */}};
  }
 }
 if(!phoneDashboard.source||Date.now()-(phoneDashboard.received||phoneDashboard.opened)>1500)void phoneDashboardFallback(activePart);
}
const phoneDashboardSetPart=setPart;
setPart=function(part){phoneDashboardSetPart(part);if(state.data?.ui_version===UI_BUILD)render(state.data);phoneDashboardPulse()};
const phoneDashboardActivities=renderActivities;
renderActivities=function(rows){if(activePart==='settings')phoneDashboardActivities(rows)};
const phoneDashboardMovers=renderMovers;
let phoneDashboardMoverSignature='';
renderMovers=function(rows){if(activePart!=='home')return;const sig=JSON.stringify(rows);if(sig!==phoneDashboardMoverSignature){phoneDashboardMoverSignature=sig;phoneDashboardMovers(rows)}};
renderMarket=function(force=false){
 if(activePart!=='market'){updateTradeButtons();return}
 const f=state.data.futures||{},query=$('marketSearch').value.trim().toUpperCase(),sort=$('marketSort').value;
 const rows=(f.rows||[]).filter(r=>r.symbol.includes(query));
 rows.sort(sort==='name'?((a,b)=>a.symbol.localeCompare(b.symbol)):sort==='up'?((a,b)=>a.change-b.change):((a,b)=>b.change-a.change));
 phoneDashboardText('marketSummary',rows.length+'종목 · KST09시 등락률 · '+(f.stale||Date.now()-(f.observed_ms||0)>30000?'시세 지연':kst(f.observed_ms)+' 갱신'));
 const box=$('marketRows'),wanted=new Set(rows.map(r=>r.symbol));
 for(const [key,entry] of phoneDashboard.marketNodes)if(!wanted.has(key)){entry.button.remove();phoneDashboard.marketNodes.delete(key)}
 for(const r of rows){
  let entry=phoneDashboard.marketNodes.get(r.symbol);
  if(!entry){
   const symbol=r.symbol,button=node('button',undefined,'marketrow'),name=node('span',symbol.replace('-USDT-SWAP','/USDT')),value=node('span'),change=node('b');button.append(name,value,change);
   button.onclick=()=>{state.symbol=symbol;phoneDashboardText('marketSelected',symbol.replace('-USDT-SWAP','/USDT')+' · 직접 진입');setPart('chart');chooseChart(symbol);$('chartPanel').scrollIntoView({behavior:'smooth',block:'start'})};
   entry={button,value,change};phoneDashboard.marketNodes.set(symbol,entry);
  }
  const p=price(r.last),pct=cash(r.change*100,true)+'%';
  if(entry.value.textContent!==p)entry.value.textContent=p;if(entry.change.textContent!==pct)entry.change.textContent=pct;
  entry.change.className=r.change>=0?'positive':'negative';entry.button.className='marketrow'+(r.symbol===state.symbol?' selected':'');
 }
 const order=rows.map(r=>r.symbol).join('|');
 if(order!==phoneDashboard.marketOrder||force){const scroll=box.scrollTop;for(const r of rows)box.append(phoneDashboard.marketNodes.get(r.symbol).button);box.scrollTop=scroll;phoneDashboard.marketOrder=order}
 updateTradeButtons();
};
document.addEventListener('visibilitychange',()=>{phoneDashboardPulse();if(!document.hidden){phoneDashboard.fullAt=0;void refresh()}});
window.addEventListener('pagehide',phoneDashboardDisconnect);
setInterval(phoneDashboardPulse,250);
