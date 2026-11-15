// DOM contract checks; no browser/layout or real order execution claim.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={};
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.style={};this._text='';this.disabled=false;}
 set id(v){this._id=v;nodes[v]=this;}get id(){return this._id;}
 set textContent(v){this._text=String(v);this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent).join('\n');}
 append(...xs){this.children.push(...xs);}appendChild(x){this.append(x);}
 replaceChildren(...xs){this._text='';this.children=xs;}scrollIntoView(){this.scrolled=true;}
}
function node(tag,text,cls){let e=new Element(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
for(const id of ['programUpdate','phoneMoveRows','phoneMoveStatus','frame','marketSelected','chartPanel']){const e=node('div');e.id=id;}
let orderCalls=0,selected=[],parts=[],refreshes=0;
const context={Date,Math,Object,Set,JSON,Number,node,$:id=>nodes[id],render(){},price:String,kst:t=>String(t),
 document:{getElementById:id=>nodes[id],createElement:node},state:{data:{}},
 setPart:p=>parts.push(p),chooseChart:s=>selected.push(s),renderMarket:()=>refreshes++,trade:()=>orderCalls++};
vm.createContext(context);
vm.runInContext(fs.readFileSync(__dirname+'/health_ui.js','utf8'),context);
vm.runInContext(fs.readFileSync(__dirname+'/phone_market_ui.js','utf8'),context);
const now=Date.now(),h={observed_at:now/1000,elapsed_s:600,public_connected:true,account_connected:true,account_fresh:true,entry_enabled:true,disconnect_count:1,last_disconnect_at:now/1000-120,last_disconnect_cause:'read_eof',program_version:'1.3.2',entry:{observed_at:now/1000-2,duration_s:.615,pending:0,result:'진입 후보 대기',routes:{trend_pullback:{pass_count:0,wait_count:73,inactive_count:216,data_wait_count:0,reasons:{'시간봉 상태에 따라 다른 기존 경로 선택':216,'눌림 조건 대기':73}},confirmed_reversal:{pass_count:0,wait_count:216,inactive_count:73,data_wait_count:0,reasons:{}},double_wick:{pass_count:0,wait_count:289,inactive_count:0,data_wait_count:0,reasons:{'<img onerror=alert(1)>':289}}}},entry_observation_totals:{scans:107,candidate_returns:0},trend_status:'새 돌파 대기'};
const d={performance:{runtime_health:h},futures:{rows:[{symbol:'ALT-USDT-SWAP'}]},market_alerts:{checked_at_ms:now,coverage_fresh:289,coverage_total:289,items:[{symbol:'ALT-USDT-SWAP',close_ms:now,opening:100,close:110,change_pct:10},{symbol:'OLD-USDT-SWAP',close_ms:now,opening:100,close:90,change_pct:-10}]}};
context.state.data=d;context.render(d);
const sections=nodes.phoneHealthSummary.children;
assert.deepEqual(sections.map(x=>x.children[0].textContent),['연결 상태','신호 검사','규칙별 검사 결과','추세 전용 1자리','기록 안내']);
assert(nodes.phoneHealthSummary.textContent.includes('다른 기존 경로 선택 216종목'));
assert(!nodes.phoneHealthSummary.textContent.includes('상태별 비활성'));
assert.equal(sections[2].children.filter(x=>x.className==='phone-rule-card').length,3);
assert(nodes.phoneHealthSummary.textContent.includes('<img onerror=alert(1)>')); // Text only.
const cards=nodes.phoneMoveRows.children;assert.equal(cards.length,2);assert.equal(cards[1].disabled,true);
cards[0].onclick();assert.deepEqual(selected,['ALT-USDT-SWAP']);assert.deepEqual(parts,['chart']);assert.equal(context.state.frame,'15m');assert.equal(nodes.frame.value,'15m');assert.equal(orderCalls,0);assert.equal(refreshes,1);
cards[1].onclick();assert.equal(selected.length,1);
context.render(d);assert.strictEqual(nodes.phoneMoveRows.children[0],cards[0]); // polling preserves focus.
h.observed_at-=60;context.render(d);assert(nodes.phoneHealthSummary.textContent.includes('진단 자료 지연'));
d.performance.runtime_health={unavailable:true};d.market_alerts.items=[];context.render(d);
assert(nodes.phoneHealthSummary.textContent.includes('수집 중'));assert(nodes.phoneMoveRows.textContent.includes('알림이 없습니다'));
console.log(JSON.stringify({checks:10,order_requests:orderCalls,browser_layout_tested:false}));
