// Read-only move cards. A card only navigates; existing trade() handles entry.
function phoneOpenMove(symbol){
 const rows=state.data.futures?.rows||[];
 if(!rows.some(r=>r.symbol===symbol))return;
 state.frame='15m';$('frame').value='15m';
 $('marketSelected').textContent=symbol.replace('-USDT-SWAP','/USDT')+' · 직접 진입';
 setPart('chart');chooseChart(symbol);renderMarket(true);
 $('chartPanel').scrollIntoView({behavior:'smooth',block:'start'});
 // Existing 500ms chart refresh also retries if another chart was in flight.
}
let phoneMovesSignature='';
function renderPhoneMoves(d){
 const a=d.market_alerts||{},box=$('phoneMoveRows'),status=$('phoneMoveStatus');
 if(!box||!status)return;
 const age=a.checked_at_ms?Math.max(0,Math.floor((Date.now()-a.checked_at_ms)/1000)):null;
 status.textContent=age===null?(a.status||'수신봉 검사 대기'):
  '검사 '+age+'초 전 · 최신 확정봉 '+(a.coverage_fresh||0)+'/'+(a.coverage_total||0)+'종목'+
  (age>15?' · 검사 지연':'')+(a.save_errors?' · 기록 저장 오류':'');
 const available=new Set((d.futures?.rows||[]).map(x=>x.symbol));
 const items=(a.items||[]).slice(0,100);
 const sig=JSON.stringify([items,items.map(x=>available.has(x.symbol))]);
 if(sig===phoneMovesSignature)return;phoneMovesSignature=sig;
 box.replaceChildren();
 if(!items.length){box.append(node('p','수신한 최근 24시간 봉에서 ±10% 알림이 없습니다. 자료 미수신 종목은 포함되지 않습니다.','muted'));return;}
 for(const e of items){
  const b=node('button',undefined,'phone-move-card');b.type='button';
  const up=e.change_pct>=0,head=node('span',undefined,'phone-move-head');
  head.append(node('strong',(up?'급등 ':'급락 ')+e.symbol.replace('-USDT-SWAP','/USDT')),
   node('b',(up?'+':'')+Number(e.change_pct).toFixed(2)+'%',up?'positive':'negative'));
  b.append(head,node('span',price(e.opening)+' → '+price(e.close)+' USDT','phone-move-prices'),
   node('small',kst(e.close_ms)+' 마감 · 15분봉'),
   node('small',available.has(e.symbol)?'차트 열기 · 수동 롱/숏 진입 →':'현재 시세 목록에 없는 종목'));
  b.disabled=!available.has(e.symbol);b.onclick=()=>phoneOpenMove(e.symbol);
  box.append(b);
 }
}
const phoneMovesRender=render;
render=function(d){phoneMovesRender(d);renderPhoneMoves(d);};
