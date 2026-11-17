// Display-only price stream. Trade buttons retain the original analysis gates.
const phoneChartLive={source:null,key:'',last:null,received:0,opened:0,paint:false,
 fullId:0,fullKey:'',fullAt:0,controller:null,fallbackBusy:false,fallbackAt:0,statusAt:0};
function phoneChartKey(){return state.symbol?state.symbol+':'+state.frame:''}
function phoneChartVisible(){return !document.hidden&&activePart==='chart'&&!$('dashboard').hidden&&!!state.symbol}
function phoneBarStart(ts,frame){const step={'1m':60000,'5m':300000,'15m':900000,'1H':3600000,'4H':14400000,'1D':86400000,'1W':604800000}[frame],offset=frame==='1W'?345600000:0;return Math.floor((ts-offset)/step)*step+offset}
function phoneChartPrice(){
 const p=phoneChartLive.last;
 return p&&p.symbol+':'+p.frame===phoneChartKey()&&p.live&&p.quote&&Number.isFinite(p.quote.last)&&p.quote.last>0&&Number.isFinite(p.quote.ts)&&
  Date.now()-phoneChartLive.received<=3000&&Date.now()-p.quote.ts<=3500&&Date.now()-p.quote.ts>=-1000?p.quote.last:null;
}
function phoneChartFollowing(){
 const last=state.bars[state.bars.length-1];
 return state.end===null||!last||state.end>=last[0];
}
function phoneProjectChart(){
 // REST observed_ms is a receipt time, not the last trade's exchange time.
 // Use one fresh quote for BOTH the forming candle and its price marker.
 const p=phoneChartLive.last,current=phoneChartPrice(),last=state.bars[state.bars.length-1];
 if(current===null||state.chartKey!==phoneChartKey()||!last||last[6]||
    phoneBarStart(p.quote.ts,state.frame)!==last[0])return;
 const next=last.slice();next[2]=Math.max(next[2],current);next[3]=Math.min(next[3],current);next[4]=current;
 state.bars[state.bars.length-1]=next;
}
function phoneFollowChart(){
 state.end=null;state.shift=0;state.scale=1;draw();void refreshChart();
}
function phoneChartNavigation(){
 const b=$('phoneChartNow');if(!b)return;
 b.textContent=phoneChartFollowing()?'현재 봉':'현재 봉으로';
 b.disabled=phoneChartFollowing();b.onclick=phoneFollowChart;
}
function phoneChartCountdown(){
 const p=phoneChartLive.last;
 if(!p||p.symbol+':'+p.frame!==phoneChartKey()||!Number.isFinite(p.server_ms))return '--:--';
 const now=p.server_ms+Math.max(0,Date.now()-phoneChartLive.received);
 const steps={'1m':60000,'5m':300000,'15m':900000,'1H':3600000,'4H':14400000,'1D':86400000,'1W':604800000};
 const step=steps[state.frame],start=phoneBarStart(now,state.frame),bar=state.bars[state.bars.length-1];
 if(!step||!bar||bar[6]||bar[0]!==start)return '봉 대기';
 let seconds=Math.max(0,Math.ceil((start+step-now)/1000));
 const days=Math.floor(seconds/86400);seconds%=86400;
 const hours=Math.floor(seconds/3600),minutes=Math.floor(seconds%3600/60),remain=seconds%60;
 const two=x=>String(x).padStart(2,'0');
 return (days?days+'일 ':'')+(days||hours?two(hours)+':':'')+two(minutes)+':'+two(remain);
}
function phoneChartMarker(ctx,w,h){
 const g=chartGeometry,current=phoneChartPrice();
 if(!g||current===null||!phoneChartFollowing())return;
 const yy=g.y(current);
 if(!Number.isFinite(yy)||yy<g.top||yy>g.bottom)return;
 const left=g.right+2,width=w-left-3,height=29,top=Math.max(g.top,Math.min(g.bottom-height,yy-height/2));
 if(width<40)return;
 ctx.save();ctx.lineWidth=1;ctx.strokeStyle='#bcbcbc';ctx.setLineDash([3,3]);
 ctx.beginPath();ctx.moveTo(8,yy);ctx.lineTo(left,yy);ctx.stroke();ctx.setLineDash([]);
 ctx.fillStyle='#101010';ctx.fillRect(left,top,width,height);ctx.strokeRect(left+.5,top+.5,width-1,height-1);
 ctx.textAlign='center';ctx.fillStyle='#eeeeee';ctx.font='10px system-ui';
 ctx.fillText(price(current),left+width/2,top+11,width-6);
 ctx.font='9px system-ui';ctx.fillStyle='#bcbcbc';ctx.fillText(phoneChartCountdown(),left+width/2,top+24,width-6);
 ctx.restore();
}
function phoneMergeChart(packet,received=true){
 if(!packet||packet.symbol+':'+packet.frame!==phoneChartKey()||!Number.isFinite(packet.server_ms))return false;
 const previous=phoneChartLive.last;
 if(received&&previous&&previous.symbol===packet.symbol&&previous.frame===packet.frame&&packet.server_ms<previous.server_ms)return false;
 if(received&&previous?.live&&packet.live&&previous.symbol===packet.symbol&&previous.frame===packet.frame&&packet.quote?.ts<previous.quote?.ts)return false;
 if(received){phoneChartLive.last=packet;phoneChartLive.received=Date.now()}
 if(state.chartKey!==phoneChartKey()||!state.bars.length)return true;
 const sourceAt=state.chartData?.observed_ms||0;
 const bars=new Map(state.bars.map(b=>[b[0],b]));
 for(const row of packet.bars||[]){
  if(!Array.isArray(row)||row.length<7||!row.slice(0,6).every(Number.isFinite)||
   Math.min(...row.slice(1,5))<=0||row[5]<0||row[3]>Math.min(row[1],row[4])||row[2]<Math.max(row[1],row[4]))continue;
  const old=bars.get(row[0]);
  if(old?.[6]&&!row[6])continue; // Never turn a completed bar into a live one.
  if((packet.candle_ms||0)>=sourceAt){
   const next=row.slice();
   if(old&&!old[6]&&!row[6]){next[2]=Math.max(old[2],row[2]);next[3]=Math.min(old[3],row[3])}
   bars.set(row[0],next);
  }else if(old&&!old[6]&&packet.live&&packet.quote&&packet.quote.ts>=sourceAt&&phoneBarStart(packet.quote.ts,packet.frame)===row[0]){
   const next=old.slice(),p=packet.quote.last;
   if(Number.isFinite(p)&&p>0){next[2]=Math.max(next[2],p);next[3]=Math.min(next[3],p);next[4]=p;bars.set(row[0],next)}
  }
 }
 state.bars=[...bars.values()].sort((a,b)=>a[0]-b[0]);
 if(state.chartData&&packet.candle_ms>=sourceAt){
  state.chartData.observed_ms=packet.candle_ms;
  state.chartData.error=packet.candle_error||null;
  state.chartData.stale=!!packet.candle_error;
 }
 phoneProjectChart();
 return true;
}
async function phoneChartRead(path,controller){
 const response=await fetch(path,{cache:'no-store',credentials:'same-origin',signal:controller.signal});
 const data=await response.json();
 if(response.status===401){showLogin();throw Error('다시 로그인하세요.')}
 if(!response.ok)throw Error(data.error||'차트 조회 실패');
 return data;
}
refreshChart=async function(older=false){
 if(!phoneChartVisible())return;
 const key=phoneChartKey(),now=Date.now();
 if(state.chartBusy&&phoneChartLive.fullKey===key)return;
 if(!older&&state.chartKey===key&&state.bars.length&&now-phoneChartLive.fullAt<5000)return;
 phoneChartLive.controller?.abort();
 const controller=new AbortController(),id=++phoneChartLive.fullId;
 phoneChartLive.controller=controller;phoneChartLive.fullKey=key;phoneChartLive.fullAt=now;
 state.chartBusy=true;state.lastChartRequest=now;
 const timer=setTimeout(()=>controller.abort(),5000);
 try{
  const d=await phoneChartRead('/api/chart?symbol='+encodeURIComponent(state.symbol)+'&frame='+state.frame+(older?'&older=1':''),controller);
  if(id!==phoneChartLive.fullId||key!==phoneChartKey())return;
  state.chartKey=key;state.chartData=d;state.fundingReceivedAt=Date.now();
  if(d.bars?.length)state.bars=d.bars;
  if(phoneChartLive.last)phoneMergeChart(phoneChartLive.last,false);
  draw();updateTradeButtons();
 }catch(e){if(id===phoneChartLive.fullId&&e.name!=='AbortError')$('chartInfo').textContent=e.message}
 finally{clearTimeout(timer);if(id===phoneChartLive.fullId){state.chartBusy=false;phoneChartLive.controller=null}}
};
function phoneChartDisconnect(){
 phoneChartLive.source?.close();phoneChartLive.source=null;phoneChartLive.key='';
 phoneChartLive.fullId++;phoneChartLive.controller?.abort();phoneChartLive.controller=null;
 state.chartBusy=false;phoneChartLive.fullAt=0;
}
async function phoneChartFallback(key){
 if(phoneChartLive.fallbackBusy||Date.now()-phoneChartLive.fallbackAt<500)return;
 phoneChartLive.fallbackBusy=true;phoneChartLive.fallbackAt=Date.now();
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),2000);
 try{
  const p=await phoneChartRead('/api/phone/chart-live?symbol='+encodeURIComponent(state.symbol)+'&frame='+state.frame,controller);
  if(phoneChartVisible()&&phoneChartKey()===key&&phoneMergeChart(p))draw();
 }catch(e){/* Keep last observed prices; freshness text reports the gap. */}
 finally{clearTimeout(timer);phoneChartLive.fallbackBusy=false}
}
function phoneChartPulse(){
 if(!phoneChartVisible()){if(phoneChartLive.key)phoneChartDisconnect();return}
 const key=phoneChartKey();
 if(key!==phoneChartLive.key){
  phoneChartDisconnect();phoneChartLive.key=key;phoneChartLive.last=null;phoneChartLive.received=0;phoneChartLive.opened=Date.now();
  if(typeof EventSource!=='undefined'){
   const source=new EventSource('/api/phone/chart-live?symbol='+encodeURIComponent(state.symbol)+'&frame='+state.frame+'&stream=1');
   phoneChartLive.source=source;
   source.onmessage=event=>{
    if(source!==phoneChartLive.source||!phoneChartVisible()||phoneChartKey()!==key)return;
    try{if(phoneMergeChart(JSON.parse(event.data)))draw()}catch(e){/* Reject malformed updates. */}
   };
  }
  void refreshChart();
 }
 if(!phoneChartLive.source||Date.now()-(phoneChartLive.received||phoneChartLive.opened)>1500)void phoneChartFallback(key);
 if(Date.now()-phoneChartLive.statusAt>=1000){phoneChartLive.statusAt=Date.now();draw()}
}
const phoneChartPaint=draw;
draw=function(){
 if(phoneChartLive.paint||!phoneChartVisible())return;
 phoneChartLive.paint=true;
 requestAnimationFrame(()=>{
  phoneChartLive.paint=false;if(!phoneChartVisible())return;
  phoneProjectChart();phoneChartPaint();phoneChartNavigation();
  const p=phoneChartLive.last,info=$('chartInfo');
  if(p&&p.symbol+':'+p.frame===phoneChartKey()){
   info.textContent+=' · '+(!phoneChartFollowing()?'과거 구간 · 현재 봉으로 이동 가능':phoneChartPrice()===null?'시세 수신 대기':'실시간 체결가 '+price(p.quote.last));
  }
 });
};
document.addEventListener('visibilitychange',phoneChartPulse);
window.addEventListener('pagehide',phoneChartDisconnect);
setInterval(phoneChartPulse,250);
