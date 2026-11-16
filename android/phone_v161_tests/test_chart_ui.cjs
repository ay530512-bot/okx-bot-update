(async()=>{
'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path'),cp=require('child_process');
const source=fs.readFileSync(path.join(__dirname,'../phone_v161/phone_chart_ui.js'),'utf8');
const asset=path.join(__dirname,'chart_asset.js');
const syntax=cp.spawnSync(process.execPath,['--check',asset],{encoding:'utf8'});
assert.equal(syntax.status,0,syntax.stderr);
const T=1794852000000,S='TEST-USDT-SWAP',STEP=300000;
const row=(t=T,c=101,done=false)=>[t,101,Math.max(102,c),Math.min(100,c),c,5,done];
const equal=(a,b)=>assert.deepStrictEqual(JSON.parse(JSON.stringify(a)),b);
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve()};
function make(painter='function draw(){paints++; $("chartInfo").textContent="차트"}'){
 let now=T+2000,paints=0,timerId=0;
 const raf=[],requests=[],timers=new Map(),sources=[],events={},nodes={dashboard:{hidden:false},chartInfo:{textContent:''}};
 class Clock extends Date{static now(){return now}}
 class Source{constructor(url){this.url=url;this.closed=false;sources.push(this)}close(){this.closed=true}emit(p){this.onmessage?.({data:JSON.stringify(p)})}}
 const c={console,Date:Clock,AbortController,EventSource:Source,URL,Math,Number,
  state:{symbol:S,frame:'5m',chartKey:S+':5m',bars:[row(T-STEP,101,true),row()],chartData:{observed_ms:T+1000,analysis:{ready:true,observed_ms:T,quote_ms:T}},chartBusy:false,end:null,count:65,scale:1,shift:0,data:{positions:[{symbol:S}]}},
  activePart:'chart',$:id=>nodes[id],document:{hidden:false,addEventListener:(k,f)=>events[k]=f},window:{devicePixelRatio:2,addEventListener:(k,f)=>events[k]=f},
  fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve,data(d,status=200){resolve({ok:status===200,status,json:async()=>d})}})),
  setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId},clearTimeout:id=>timers.delete(id),setInterval:(fn,ms)=>{assert.equal(ms,250);c.pulse=fn},
  requestAnimationFrame:fn=>raf.push(fn),showLogin(){nodes.dashboard.hidden=true},updateTradeButtons(){c.buttonUpdates++},buttonUpdates:0,
  refreshChart(){},price:String,num:x=>x==null?null:Number(x),kst:String,chartGeometry:null,paintCandleTip(){},get paints(){return paints},set paints(v){paints=v}};
 vm.createContext(c);vm.runInContext(painter+'\n'+source+'\nglobalThis.live=phoneChartLive;',c);
 return {c,nodes,requests,sources,events,timers,raf,now:()=>now,advance:ms=>now+=ms,flush(){for(const f of raf.splice(0))f()},
  packet(extra={}){return {symbol:S,frame:'5m',server_ms:now,quote:{last:103,ts:now},live:true,bars:[row(T-STEP,101,true),row(T,103)],candle_ms:T+1000,candle_error:null,...extra}}};
}
let checks=0;
async function check(name,fn){await fn();checks++;console.log('PASS '+name)}
await check('live prices retain official open/volume, closed candles and chart navigation',()=>{
 const h=make(),{c}=h;c.state.end=T-STEP;c.state.count=23;c.state.scale=2;c.state.shift=.2;
 assert(c.phoneMergeChart(h.packet()));equal(c.state.bars.at(-1),row(T,103));
 equal([c.state.end,c.state.count,c.state.scale,c.state.shift],[T-STEP,23,2,.2]);
 equal(c.state.chartData.analysis,{ready:true,observed_ms:T,quote_ms:T});
 c.phoneMergeChart(h.packet({bars:[row(T-STEP,999,false)],server_ms:h.now()+1}));
 equal(c.state.bars[0],row(T-STEP,101,true));
 assert.equal(c.phoneChartPrice(),103);
 h.advance(3501);assert.equal(c.phoneChartPrice(),null);
});
await check('wrong symbols/frames and out-of-order server/quote updates are rejected',()=>{
 const h=make(),{c}=h;c.phoneMergeChart(h.packet());
 for(const change of [{symbol:'OTHER'},{frame:'1m'},{server_ms:T-1},{server_ms:h.now()+1,quote:{last:1,ts:T}}]){
  assert.equal(c.phoneMergeChart(h.packet(change)),false);assert.equal(c.state.bars.at(-1)[4],103);
 }
 assert.equal(c.phoneMergeChart(h.packet({server_ms:NaN})),false);
});
await check('a new candle comes from REST; rollover quote never invents OHLCV',()=>{
 const h=make(),{c}=h;h.advance(STEP);const stamp=h.now();
 c.phoneMergeChart(h.packet({quote:{last:105,ts:stamp},bars:[row(T-STEP,101,true),row()]}));
 assert.equal(c.state.bars.length,2);assert.equal(c.state.bars.at(-1)[0],T);assert.equal(c.phoneChartPrice(),105);
 c.phoneMergeChart(h.packet({server_ms:stamp+1,candle_ms:stamp,bars:[row(T,102,true),row(T+STEP,105)]}));
 assert.equal(c.state.bars.length,3);equal(c.state.bars.at(-1),row(T+STEP,105));assert(c.state.bars.at(-2)[6]);
});
await check('older REST packets cannot downgrade newer candle fields; fresh quote can overlay',()=>{
 const h=make(),{c}=h;c.state.chartData.observed_ms=T+1900;c.state.bars[1][5]=77;
 c.phoneMergeChart(h.packet());assert.equal(c.state.bars[1][4],103);assert.equal(c.state.bars[1][5],77);assert.equal(c.state.chartData.observed_ms,T+1900);
 c.phoneMergeChart(h.packet({server_ms:T+2001,quote:{last:99,ts:T+1900-1}}));assert.equal(c.state.bars[1][4],103);
});
await check('bad OHLC and non-finite prices never draw a live price',()=>{
 const h=make(),{c}=h;
 for(const bad of [[T,101,100,99,103,5,false],[T,0,104,0,103,5,false],[T,101,104,100,103,-1,false],[T,101,Infinity,100,103,5,false]]){
  c.phoneMergeChart(h.packet({bars:[bad],live:false,quote:null}));equal(c.state.bars[1],row());assert.equal(c.phoneChartPrice(),null);
 }
 for(const last of [NaN,Infinity,-1,0]){c.phoneMergeChart(h.packet({quote:{last,ts:h.now()}}));assert.equal(c.phoneChartPrice(),null)}
});
await check('UTC day/week and minute boundaries are handled independently',()=>{
 const {c}=make();for(const [frame,step,offset] of [['1m',60000,0],['1D',86400000,0],['1W',604800000,345600000]]){
  const start=c.phoneBarStart(T,frame);assert.equal((start-offset)%step,0);assert(start<=T&&T<start+step);
 }
});
await check('repaint requests coalesce; hidden charts do no painting or streaming',()=>{
 const h=make(),{c}=h;for(let i=0;i<100;i++)c.draw();assert.equal(h.raf.length,1);h.flush();assert.equal(c.paints,1);
 c.document.hidden=true;c.draw();c.phoneChartPulse();assert.equal(h.raf.length,0);assert.equal(h.sources.length,0);assert.equal(h.requests.length,0);
});
await check('selection changes close the old stream and ignore its late messages',async()=>{
 const h=make(),{c}=h;c.phoneChartPulse();assert.equal(h.sources.length,1);assert.equal(h.requests.length,1);
 h.sources[0].emit(h.packet());assert.equal(c.state.bars[1][4],103);
 c.state.symbol='NEW-USDT-SWAP';c.state.bars=[];c.state.chartKey='';c.phoneChartPulse();
 assert(h.sources[0].closed);assert(h.requests[0].options.signal.aborted);assert.equal(h.sources.length,2);
 h.sources[0].emit(h.packet({quote:{last:999,ts:h.now()}}));assert.equal(c.phoneChartPrice(),null);
 c.document.hidden=true;c.phoneChartPulse();assert(h.sources[1].closed);assert(h.requests[1].options.signal.aborted);assert(!c.state.chartBusy);
 h.requests[1].data({symbol:'NEW-USDT-SWAP',frame:'5m',bars:[row(T,888)]});await tick();assert.equal(c.state.bars.length,0);
});
await check('fallback only starts for a missing stream; one request at most twice per second',async()=>{
 const h=make(),{c}=h;c.phoneChartPulse();h.requests[0].data({bars:c.state.bars,observed_ms:T+1000});await tick();
 h.advance(1000);c.phoneChartPulse();assert.equal(h.requests.length,1);
 h.advance(501);c.phoneChartPulse();assert.equal(h.requests.length,2);assert(h.requests[1].url.startsWith('/api/phone/chart-live?'));
 c.phoneChartPulse();c.phoneChartPulse();assert.equal(h.requests.length,2);
 h.requests[1].data(h.packet());await tick();h.advance(500);c.phoneChartPulse();assert.equal(h.requests.length,2);
 h.advance(1501);c.phoneChartPulse();assert.equal(h.requests.length,3);
 h.requests[2].data(h.packet());await tick();
});
await check('JSON fallback works without EventSource and stops when chart is hidden',async()=>{
 const h=make(),{c}=h;c.EventSource=undefined;c.phoneChartPulse();assert.equal(h.sources.length,0);assert.equal(h.requests.length,2);
 h.requests[1].data(h.packet());await tick();assert.equal(c.phoneChartPrice(),103);
 c.document.hidden=true;h.advance(2000);c.phoneChartPulse();assert.equal(h.requests.length,2);
});
await check('whole history fetches are throttled; older history is available immediately',async()=>{
 const h=make(),{c}=h;const req=c.refreshChart();assert.equal(h.requests.length,1);
 h.requests[0].data({bars:c.state.bars,observed_ms:T+1000});await req;
 for(let i=0;i<8;i++){h.advance(500);await c.refreshChart()}assert.equal(h.requests.length,1);
 const older=c.refreshChart(true);assert.equal(h.requests.length,2);assert(h.requests[1].url.endsWith('&older=1'));
 h.requests[1].data({bars:[row(T-2*STEP,101,true),...c.state.bars],observed_ms:h.now()});await older;
 assert.equal(c.state.bars.length,3);h.advance(5000);const latest=c.refreshChart();assert.equal(h.requests.length,3);
 h.requests[2].data({bars:c.state.bars,observed_ms:h.now()});await latest;
});
await check('new frame requests abort an old slow response; it cannot replace the new chart',async()=>{
 const h=make(),{c}=h;const old=c.refreshChart();
 c.state.frame='15m';c.state.chartKey='';c.state.bars=[];const fresh=c.refreshChart();assert.equal(h.requests.length,2);assert(h.requests[0].options.signal.aborted);
 h.requests[1].data({symbol:S,frame:'15m',bars:[row(T,104)],observed_ms:h.now()});await fresh;
 h.requests[0].data({symbol:S,frame:'5m',bars:[row(T,999)],observed_ms:h.now()+1});await old;
 assert.equal(c.state.chartKey,S+':15m');assert.equal(c.state.bars[0][4],104);assert(!c.state.chartBusy);
});
await check('fresh streaming bars survive a slower full snapshot; quote never refreshes analysis age',async()=>{
 const h=make(),{c}=h;const req=c.refreshChart();h.advance(1000);
 c.phoneMergeChart(h.packet({candle_ms:h.now(),bars:[row(T,105)]}));
 h.requests[0].data({bars:[row()],observed_ms:T+1000,analysis:{observed_ms:T-40000,quote_ms:T-40000}});await req;
 assert.equal(c.state.bars[0][4],105);assert.equal(c.state.chartData.analysis.observed_ms,T-40000);
 c.phoneMergeChart(h.packet({live:false,quote:null,candle_error:'timeout'}));assert.equal(c.phoneChartPrice(),null);
 c.draw();h.flush();assert(h.nodes.chartInfo.textContent.includes('시세 수신 대기'));
});
await check('actual compiled canvas draw retains dimensions across updates and draws current price',()=>{
 const js=fs.readFileSync(asset,'utf8'),start=js.indexOf('function draw(){'),end=js.indexOf('\nfunction pan(',start);
 assert(start>=0&&end>start);const h=make(js.slice(start,end)),{c,nodes}=h,labels=[],transforms=[];
 let width=0,height=0,resizes=0;
 const ctx={scale(){throw Error('cumulative canvas scale is forbidden')},setTransform(...x){transforms.push(x)},fillText(x){labels.push(x)}};
 for(const n of ['setLineDash','fillRect','beginPath','moveTo','lineTo','stroke','save','rect','clip','restore'])ctx[n]=()=>{};
 nodes.chart={clientWidth:390,clientHeight:360,getContext:()=>ctx,get width(){return width},set width(v){width=v;resizes++},get height(){return height},set height(v){height=v;resizes++}};
 nodes.candleTip={hidden:false};nodes.chartTitle={textContent:''};
 c.state.bars=Array.from({length:300},(_,i)=>row(T-(299-i)*STEP,101,i<299));
 c.phoneMergeChart(h.packet());c.draw();h.flush();c.draw();h.flush();
 assert.equal(resizes,2);assert.equal(width,780);assert.equal(height,720);assert.equal(transforms.length,2);assert(labels.some(x=>x==='현재 103'));
 h.advance(4000);labels.length=0;c.draw();h.flush();assert(!labels.some(x=>x.startsWith('현재 ')));assert.equal(resizes,2);
});
console.log(`PASS ${checks} chart scenarios; final asset syntax checked; no exchange orders or real browser claims`);
})().catch(e=>{console.error(e);process.exitCode=1});
