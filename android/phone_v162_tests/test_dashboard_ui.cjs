(async()=>{
'use strict';
const vm=require('vm'),fs=require('fs'),path=require('path'),assert=require('assert');
const source=fs.readFileSync(path.join(__dirname,'../phone_v162/phone_dashboard_ui.js'),'utf8');
const T=1794852000000;
function setup(){
 let now=T+2000,created=0,timer=0;const nodes={},raf=[],sources=[],requests=[],events={};
 function node(tag,text='',cls=''){
  created++;return {tag,own:String(text),className:cls,children:[],hidden:false,disabled:false,scrollTop:0,value:'',
   classList:{toggle(){},add(){},remove(){}},
   append(...els){for(const e of els){if(e.parent)e.remove();this.children.push(e);e.parent=this}},
   remove(){if(this.parent){const p=this.parent;p.children=p.children.filter(x=>x!==this);this.parent=null}},
   replaceChildren(...els){for(const e of [...this.children])e.remove();this.append(...els)},
   set textContent(v){this.own=String(v)},get textContent(){return this.own+this.children.map(x=>x.textContent).join('')},scrollIntoView(){}};
 }
 for(const key of ['dashboard','equity','profit','available','cost','status','fresh','livePrepare','pauseEntries','closeAll','count','marketSearch','marketSort','marketSummary','marketRows','marketSelected','chartPanel'])nodes[key]=node('div');
 nodes.marketSort.value='down';
 class Clock extends Date{static now(){return now}}
 class Source{constructor(url){this.url=url;sources.push(this)}close(){this.closed=true}emit(d){this.onmessage?.({data:JSON.stringify(d)})}}
 const c={console,Date:Clock,Math,Number,String,Set,Map,JSON,EventSource:Source,AbortController,
  UI_BUILD:'7.32-Q2X',activePart:'home',tradeBusy:false,controlBusy:false,
  state:{data:{ui_version:'7.32-Q2X',display_ms:T,captured_ms:T+2000,account_age_seconds:1,controls_enabled:true,status:'운용',state:{equity:'100',available:'80',day_profit:'0',api_spent:'0',account_connected:true},positions:[]},chartKey:'ready',busy:false},
  $:id=>nodes[id],node,cash:x=>x==null?'—':String(x),price:String,color(){},kst:String,
  document:{hidden:false,addEventListener:(k,f)=>events[k]=f},window:{addEventListener:(k,f)=>events[k]=f},
  setTimeout:()=>++timer,clearTimeout(){},setInterval:(fn,ms)=>{assert.equal(ms,250);c.pulse=fn},requestAnimationFrame:fn=>raf.push(fn),
  render(d){c.state.data=d;c.fullPaints++},renderGoal(){c.goals++},renderActivities(){c.activityPaints++},renderMovers(){c.moverPaints++},renderMarket(){},
  phoneRenderPositions(){c.positionPaints++},updateTradeButtons(){c.buttonPaints++},draw(){c.chartPaints++},
  refresh(){},refreshChart(){},showDashboard(){nodes.dashboard.hidden=false},setPart(p){c.activePart=p},chooseChart(s){c.state.symbol=s},
  api:url=>new Promise(resolve=>requests.push({url,resolve})),phoneChartRead:url=>new Promise(resolve=>requests.push({url,resolve})),
  fullPaints:0,goals:0,activityPaints:0,moverPaints:0,positionPaints:0,buttonPaints:0,chartPaints:0};
 vm.createContext(c);vm.runInContext(source+'\nglobalThis.live=phoneDashboard;',c);
 return {c,nodes,raf,sources,requests,events,advance:ms=>now+=ms,now:()=>now,created:()=>created,flush(){for(const f of raf.splice(0))f()},
  packet(extra={}){return {display_ms:now,captured_ms:now,account_age_seconds:1,...extra}}};
}
const tick=async()=>{for(let i=0;i<8;i++)await Promise.resolve()};let count=0;
async function check(name,fn){await fn();count++;console.log('PASS '+name)}
await check('received balances repaint without waiting for a blocked full snapshot',async()=>{
 const h=setup(),{c,nodes}=h;const pending=c.refresh();assert(c.state.busy);
 c.phoneDashboardAccept(h.packet({state:{equity:'104.50',available:'82.50',day_profit:'4.50',api_spent:'0',account_connected:true},account_live:{connected:true,account_live:true,received_ms:h.now()}}));
 h.flush();assert.equal(nodes.equity.textContent,'104.50');assert.equal(nodes.profit.textContent,'4.50');assert.equal(c.fullPaints,0);assert.equal(c.positionPaints,0);assert(nodes.fresh.textContent.includes('입출금 대조 기준'));
 h.requests[0].resolve({...c.state.data,display_ms:T-1,state:{equity:'10'}});await pending;assert.equal(c.state.data.state.equity,'104.50');
});
await check('heartbeat-only deltas retain account and position fields; stale packets cannot roll back',()=>{
 const h=setup(),{c}=h;c.phoneDashboardAccept(h.packet({state:{equity:'110'},positions:[{key:'p'}]}));h.advance(250);
 c.phoneDashboardAccept(h.packet());assert.equal(c.state.data.state.equity,'110');assert.equal(c.state.data.positions[0].key,'p');
 assert.equal(c.phoneDashboardAccept({display_ms:T,state:{equity:'1'}}),false);assert.equal(c.state.data.state.equity,'110');
 const newer={...c.state.data,display_ms:h.now()+1,state:{equity:'120'}};c.render(newer);assert.equal(c.state.data.state.equity,'120');
});
await check('private updates never make stale order/account controls ready',()=>{
 const h=setup(),{c,nodes}=h;c.activePart='chart';
 c.phoneDashboardAccept(h.packet({account_age_seconds:31,positions:[{key:'one'}],account_live:{connected:true,account_live:true,received_ms:h.now()}}));h.flush();assert(nodes.closeAll.disabled);
 h.advance(250);c.phoneDashboardAccept(h.packet({account_age_seconds:1,account_live:{connected:false,account_live:false}}));h.flush();assert(nodes.closeAll.disabled);
 h.advance(250);c.phoneDashboardAccept(h.packet({controls_enabled:false,account_live:{connected:true}}));h.flush();assert(nodes.livePrepare.disabled);assert(nodes.closeAll.disabled);
});
await check('fast paint requests coalesce and do not rebuild hidden panels',()=>{
 const h=setup(),{c}=h;for(let i=0;i<30;i++)c.phoneDashboardAccept(h.packet({state:{equity:String(i)}}));assert.equal(h.raf.length,1);h.flush();assert.equal(h.nodes.equity.textContent,'29');
 assert.equal(c.activityPaints,0);assert.equal(c.positionPaints,0);assert.equal(c.chartPaints,0);
 c.renderActivities([]);assert.equal(c.activityPaints,0);c.activePart='settings';c.renderActivities([]);assert.equal(c.activityPaints,1);
});
await check('streams close on page changes and hiding; old source callbacks are ignored',()=>{
 const h=setup(),{c}=h;c.phoneDashboardPulse();assert.equal(h.sources.length,1);h.sources[0].emit(h.packet({state:{equity:'105'}}));
 c.activePart='chart';c.phoneDashboardPulse();assert(h.sources[0].closed);assert.equal(h.sources.length,2);
 h.sources[0].emit(h.packet({display_ms:h.now()+100,state:{equity:'999'}}));assert.equal(c.state.data.state.equity,'105');
 c.document.hidden=true;c.phoneDashboardPulse();assert(h.sources[1].closed);c.phoneDashboardDraw();h.flush();assert.equal(h.nodes.equity.textContent,'');
});
await check('fallback is bounded and inactive pages perform no requests',async()=>{
 const h=setup(),{c}=h;c.phoneDashboardPulse();h.advance(1501);c.phoneDashboardPulse();assert.equal(h.requests.length,1);
 c.phoneDashboardPulse();c.phoneDashboardPulse();assert.equal(h.requests.length,1);h.requests[0].resolve(h.packet({state:{equity:'103'}}));await tick();
 h.advance(500);c.phoneDashboardPulse();assert.equal(h.requests.length,1);c.document.hidden=true;h.advance(5000);c.phoneDashboardPulse();assert.equal(h.requests.length,1);
});
await check('full snapshots are throttled while streaming remains independent',async()=>{
 const h=setup(),{c}=h;const p=c.refresh();h.requests[0].resolve(c.state.data);await p;
 h.advance(500);await c.refresh();h.advance(500);await c.refresh();assert.equal(h.requests.length,1);
 h.advance(1000);const q=c.refresh();assert.equal(h.requests.length,2);h.requests[1].resolve(c.state.data);await q;
});
await check('market prices update existing nodes and preserve scroll and selection',()=>{
 const h=setup(),{c,nodes}=h;c.activePart='market';c.state.symbol='A-USDT-SWAP';
 c.state.data.futures={observed_ms:h.now(),rows:[{symbol:'A-USDT-SWAP',last:1,change:.2},{symbol:'B-USDT-SWAP',last:2,change:.1}]};
 c.renderMarket();assert.equal(nodes.marketRows.children.length,2);const a=nodes.marketRows.children[0],b=nodes.marketRows.children[1],created=h.created();nodes.marketRows.scrollTop=90;
 c.state.data.futures.rows[0].last=1.1;c.renderMarket();assert.strictEqual(nodes.marketRows.children[0],a);assert.equal(a.children[1].textContent,'1.1');assert.equal(h.created(),created);assert.equal(nodes.marketRows.scrollTop,90);
 c.state.data.futures.rows[1].change=.3;c.renderMarket();assert.strictEqual(nodes.marketRows.children[0],b);assert.equal(nodes.marketRows.scrollTop,90);
 nodes.marketSearch.value='A-';c.renderMarket();assert.equal(nodes.marketRows.children.length,1);assert.strictEqual(nodes.marketRows.children[0],a);
 c.activePart='home';c.state.data.futures.rows.push({symbol:'C-USDT-SWAP',last:3,change:.4});c.renderMarket();assert.equal(h.created(),created);
});
console.log(`PASS ${count} dashboard scenarios; simulated DOM and network only; no exchange orders`);
})().catch(e=>{console.error(e);process.exitCode=1});
