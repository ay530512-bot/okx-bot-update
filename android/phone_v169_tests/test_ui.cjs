(async()=>{
// Exercise final combined UI and KST date formatting with a minimal DOM. No trade requests.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const host=path.join(__dirname,'../phone_v169'),roots={},requests=[];
function findNode(id){const walk=el=>el.id===id?el:el.children.map(walk).find(Boolean);return roots[id]||Object.values(roots).map(walk).find(Boolean)}
const nodes=new Proxy(roots,{get:(obj,id)=>findNode(id)});
let clock=Date.parse('2026-11-16T12:43:00Z');
class ClockDate extends Date{static now(){return clock}}
function element(tag,text,cls){return {tag,tagName:tag.toUpperCase(),id:'',own:text||'',className:cls||'',style:{},children:[],parentElement:null,scrollTop:0,writes:0,clears:0,
 append(...els){for(const x of els)this.insertBefore(x,null)},appendChild(el){this.append(el)},
 insertBefore(el,before){if(before===el)return;el.remove();const i=before?this.children.indexOf(before):this.children.length;assert(i>=0);this.children.splice(i,0,el);el.parentElement=this;return el},
 remove(){const p=this.parentElement;if(p){p.children.splice(p.children.indexOf(this),1);this.parentElement=null}},
 replaceChildren(...els){this.clears++;for(const x of [...this.children])x.remove();this.own='';this.append(...els)},
 setAttribute(k,v){this[k]=String(v)},getAttribute(k){return this[k]},
 set textContent(v){this.writes++;this.own=String(v);for(const x of [...this.children])x.remove()},get textContent(){return this.own+this.children.map(x=>x.textContent).join('\n')}}}
for(const id of ['programUpdate','mobileUpdateButton','mobileUpdateStatus','phoneMoveRows','phoneMoveStatus']){roots[id]=element('div');roots[id].id=id}
const c={console,Intl,Date:ClockDate,Math,Object,Number,Set,render(){},state:{data:{}},node:element,$:id=>nodes[id],document:{getElementById:id=>nodes[id],createElement:element},crypto:{randomUUID:()=> 'test'},api(){throw Error('No requests allowed')},kst:ms=>String(ms),price:String};
vm.createContext(c);vm.runInContext(fs.readFileSync(host+'/phone_update_ui.js','utf8')+'\n'+fs.readFileSync(host+'/phone_market_ui.js','utf8'),c);
for(const [iso,want] of [['2026-11-16T02:15:00Z','11/16 11:15'],['2026-12-31T15:00:00Z','01/01 00:00'],['2026-01-01T14:59:00Z','01/01 23:59']])assert.equal(c.phoneMoveStamp(Date.parse(iso)),want);
const h={observed_at:Date.now()/1000,elapsed_s:600,public_connected:true,account_connected:true,account_fresh:true,entry_enabled:true,disconnect_count:3,last_disconnect_at:Date.now()/1000-90,last_disconnect_cause:'read_eof',disconnect_history:[{observed_at:Date.now()/1000-90,cause:'read_eof',connection_uptime_s:99,server_notice:{code:'64008'}}],entry:{observed_at:Date.now()/1000,duration_s:.6,pending:0,result:'진입 후보 대기',routes:{confirmed_reversal:{pass_count:1,wait_count:288,inactive_count:0,data_wait_count:0,reasons:{}}}},signal_journey:{unique_observed:2,first_seen_expired:1,rows:[{symbol:'OP-USDT-SWAP',action:'LONG',stage_label:'실시간 시세 준비 대기',valid_from_ms:Date.parse('2026-11-16T02:15:00Z'),first_delay_s:3.2,last_market:{channels:{books5:{ready:false,subscribed:false}}}}]}};
c.render({performance:{runtime_health:h,parallel:{architecture:'mobile140',effective:4,requested:4,calculating:true,workers_alive:4}},futures:{rows:[{symbol:'OP-USDT-SWAP'}]},market_alerts:{items:[{symbol:'OP-USDT-SWAP',close_ms:Date.parse('2026-11-16T02:15:00Z'),change_pct:11,opening:1,close:1.11},{symbol:'OP-USDT-SWAP',close_ms:Date.parse('2026-11-15T02:15:00Z'),change_pct:-11,opening:1,close:.89}]}});
const text=nodes.programUpdate.textContent;
assert(text.includes('모바일 전용 처리'));assert(text.includes('후보 시세·주문 검사 별도 진행'));assert(text.includes('단일 계산으로 전환'));
for(const x of ['봉 조건 통과 1','최근 신호 진행 기록','3.2초 후','11/16 11:15','books5 미수신','구독 대상 지정 전','끊김 3회','사전통지 수신'])assert(text.includes(x),x);
assert.equal(nodes.phoneMoveRows.children.length,1);assert(nodes.phoneMoveRows.textContent.includes('11/16 11:15'));

const now=clock, t=Math.floor(now/900000)*900000;
function futuresAt(symbol,at,extra={}){return {stale:false,observed_ms:at,rows:[{symbol,change:.278,ts:at}],
 live_rank:{ready:true,day:Math.floor(at/86400000)*86400000,observed_ms:at,eligible:285,quotes_ready:285,
  leader:{symbol,gain:.278,basis:'kst09_live'},...extra}};}
let futures=futuresAt('HUMA-USDT-SWAP',now);
let lines=c.phoneLeaderLines({futures},{trend_rank:{symbol:'CASHCAT-USDT-SWAP',gain:.3},trend_rank_checked_ms:t,observed_at:now/1000});
assert(lines[0].includes('HUMA / +27.80%'));
assert(lines.some(x=>x.includes('검사 대상: HUMA')));
assert(!lines.some(x=>x.includes('CASHCAT')));
assert(lines.some(x=>x.includes('완료봉 조건 검사 대기')));
lines=c.phoneLeaderLines({futures:{...futures,stale:true}},null);
assert(!lines[0].includes('HUMA'));assert(lines[0].includes('갱신 대기'));
lines=c.phoneLeaderLines({futures},null);assert(lines[0].includes('HUMA'));
c.render({futures,performance:{runtime_health:{...h,trend_status:'이전 종목 눌림 대기',trend_rank:{symbol:'CASHCAT-USDT-SWAP'}}}});
assert(nodes.programUpdate.textContent.includes('현재 상승률 1위: HUMA / +27.80%'));
assert(nodes.programUpdate.textContent.includes('순위용 현재가 285/285종목'));
assert(!nodes.programUpdate.textContent.includes('이전 종목 눌림 대기'));
assert(nodes.programUpdate.textContent.includes('롱 청산 확인'));
clock=Date.parse('2026-11-16T17:05:10Z'); // KST02:05
lines=c.phoneLeaderLines({futures:futuresAt('HUMA-USDT-SWAP',clock)},null);
assert(lines.some(x=>x.includes('숏 대기 대상: HUMA')&&x.includes('05:00부터')));
clock+=1000;
lines=c.phoneLeaderLines({futures:futuresAt('NEW-USDT-SWAP',clock)},null);
assert(lines.some(x=>x.includes('숏 대기 대상: NEW')));assert(!lines.some(x=>x.includes('HUMA')));
clock=Date.parse('2026-11-16T20:00:10Z');
lines=c.phoneLeaderLines({futures:futuresAt('NEW-USDT-SWAP',clock)},
 {morning_rank:{symbol:'NEW-USDT-SWAP'},morning_rank_checked_ms:Math.floor(clock/900000)*900000,
  observed_at:clock/1000,morning_status:'현재 상승1위 큰 눌림→반등 실패→재하락 대기'});
assert(lines.some(x=>x.includes('오전 숏 검사 대상: NEW')));
assert(lines.some(x=>x.includes('반등 실패→재하락')));
assert(!lines.some(x=>x.includes('추세 롱 검사 대상')));
clock=Date.parse('2026-11-16T23:00:00Z'); // KST08
lines=c.phoneLeaderLines({futures:futuresAt('NEW-USDT-SWAP',clock)},null);
assert(lines.some(x=>x.includes('롱 대기 대상: NEW')&&x.includes('15:00부터')));
clock=now;
lines=c.phoneLeaderLines({futures:futuresAt('HUMA-USDT-SWAP',now-10001)},null);
assert(lines[0].includes('갱신 대기'));

let download;
const panel=nodes.phoneHealthSummary,save=nodes.phoneDiagnosticSave;
const section=title=>panel.children.find(x=>x.children[0]?.textContent===title);
const connectionSection=section('연결 상태'),connectionHeading=connectionSection.children[0],connectionCount=connectionSection.children[4];
const staticNote=section('오전 숏 · 추가 규칙').children[1],journeyNode=nodes.phoneSignalJourney,journeyItem=journeyNode.children[0];
const staticWrites=staticNote.writes;
panel.scrollTop=240;save.disabled=true;
for(let i=0;i<20;i++){
 const health={...h,history_write_errors:i,entry:{...h.entry,reasons:Object.fromEntries(Array.from({length:i},(_,j)=>['변하는 대기 사유 '+j,j]))}};
 c.render({performance:{runtime_health:health},program_update:{notes:'안내\n'.repeat(i)}});
 assert.strictEqual(nodes.phoneDiagnosticSave,save);assert.strictEqual(nodes.phoneHealthSummary,panel);
 assert.equal(save.disabled,true);assert.equal(panel.scrollTop,240);
 assert(!panel.children.some(x=>x===save));
 assert.strictEqual(section('연결 상태'),connectionSection);assert.strictEqual(connectionSection.children[0],connectionHeading);
 assert.strictEqual(connectionSection.children[4],connectionCount);assert.strictEqual(nodes.phoneSignalJourney,journeyNode);
 assert.strictEqual(nodes.phoneSignalJourney.children[0],journeyItem);assert.strictEqual(section('오전 숏 · 추가 규칙').children[1],staticNote);
}
assert.equal(panel.clears,0);assert.equal(staticNote.writes,staticWrites);
let scrollWrites=0,anchorTop=100,scrollTop=50;
const scrolling={get scrollTop(){return scrollTop},set scrollTop(v){scrollWrites++;scrollTop=v},getBoundingClientRect:()=>({top:0})};
const scrollMark={el:scrolling,top:50,offset:100,anchor:{isConnected:true,getBoundingClientRect:()=>({top:anchorTop})}};
c.phoneUiScrollRestore(scrollMark);assert.equal(scrollWrites,0,'unchanged refresh must not interrupt touch scrolling');
anchorTop=123;c.phoneUiScrollRestore(scrollMark);assert.equal(scrollTop,73);assert.equal(scrollWrites,1);
c.render({});assert.strictEqual(nodes.phoneDiagnosticSave,save);assert.equal(panel.scrollTop,240);
assert.strictEqual(section('연결 상태'),connectionSection);assert(panel.textContent.includes('끊김 3회'));
assert(nodes.phoneDiagnosticReadStatus.textContent.includes('마지막 확인값'));
c.render({performance:{runtime_health:{unavailable:true}}});assert.strictEqual(nodes.phoneSignalJourney,journeyNode);
assert(!panel.textContent.includes('진단 수집 중'));
nodes.phoneDiagnosticRead.onclick();const frozen=panel.textContent;
c.render({performance:{runtime_health:{...h,disconnect_count:9}}});assert.equal(panel.textContent,frozen);
assert(nodes.phoneDiagnosticReadStatus.textContent.includes('화면만 멈춤'));
nodes.phoneDiagnosticRead.onclick();assert(panel.textContent.includes('끊김 9회'));assert.strictEqual(section('연결 상태'),connectionSection);
assert.equal(nodes.programUpdate.children.filter(x=>x.className==='phone-diagnostic-toolbar').length,1);
const css=fs.readFileSync(host+'/phone_sections.css','utf8');
for(const id of ['phoneHealthSummary','mobileUpdateStatus','phonePerfSummary','parallelState126','phoneDiagnosticSaveStatus']){
 const rules=[...css.matchAll(new RegExp('#'+id+'\\{([^}]+)\\}','g'))].map(x=>x[1]).join(';');
 assert(/(?:^|;)height:/.test(rules),id+' needs a fixed height');assert(rules.includes('overflow-y:auto'),id+' needs internal scrolling');
}
console.log('PASS diagnostic refresh preserves text-node identity, nested scroll, last-good data and reading freeze without trading actions');

for(const id of ['directionAnalysis','longScore','shortScore','fundingPreview']){roots[id]=element('div');roots[id].id=id}
nodes.directionAnalysis.textContent='종목 선택 후 분석합니다.';
const base=fs.readFileSync(path.resolve(__dirname,'../../../core121/mobile_assets/app.js'),'utf8');
vm.runInContext(base.slice(base.indexOf('function analysisReady()'),base.indexOf('\nfunction renderFunding()')),c);
c.renderFunding=()=>{};
vm.runInContext(fs.readFileSync(host+'/phone_analysis_ui.js','utf8'),c);
c.state.symbol='HUMA-USDT-SWAP';c.state.data.entry_gate={preview_margin:'47.44'};
const analysis={symbol:c.state.symbol,ready:true,observed_ms:clock,quote_ms:clock,long_score:78.2,short_score:21.8,preference:'롱 우세',price:.00895,leverage:5,
 frames:{'15m':{close_ms:Math.floor(clock/900000)*900000,rsi:68.8,volume_ratio:.62,signals:{MA:.5,BOLL:.5,RSI:.5,VOLUME:-.5},missing_ma:[]},'1H':{close_ms:Math.floor(clock/3600000)*3600000,rsi:75.2,volume_ratio:2.73,signals:{MA:1,BOLL:1,RSI:1,VOLUME:1},missing_ma:[240]}},
 directions:{LONG:{sl:.008274286,sl_roe:-37.7,sl_net_per_margin:-.3871,partial_price:.009308,partial_net_per_margin:.0949,resistance_or_support:.009168},SHORT:{sl:.009625714,sl_roe:-37.7,sl_net_per_margin:-.3878,partial_price:.008592,partial_net_per_margin:.0951,resistance_or_support:.007023}}};
c.state.chartData={analysis};c.renderAnalysis();
const analysisRoot=nodes.directionAnalysis,tablePart=analysisRoot.children.find(x=>x.phoneUiKey==='plans'),detail=analysisRoot.children.find(x=>x.tag==='details');
assert(!analysisRoot.textContent.includes('종목 선택 후 분석합니다.'));
assert.equal(nodes.longScore.textContent,'롱 78.2%');assert.equal(nodes.shortScore.textContent,'숏 21.8%');
for(const text of ['분석 기준','확정봉 지표','방향별 손절·1차 익절','0.008274286','+4.502 USDT','-18.364 USDT','MA 240 미수집','비용·잔량 관리 기준'])assert(analysisRoot.textContent.includes(text),text);
assert(!analysisRoot.textContent.includes('롱 78.2%'));detail.open=true;
for(let i=0;i<30;i++)c.renderAnalysis();assert.strictEqual(analysisRoot.children.find(x=>x.phoneUiKey==='plans'),tablePart);assert.equal(detail.open,true);
c.state.data.entry_gate.preview_margin='50';c.renderAnalysis();assert.strictEqual(analysisRoot.children.find(x=>x.phoneUiKey==='plans'),tablePart);assert.equal(detail.open,true);
assert(analysisRoot.textContent.includes('+4.745 USDT'));
clock+=36000;c.renderAnalysis();assert.equal(nodes.longScore.textContent,'롱 —');assert(analysisRoot.textContent.includes('마지막 분석'));assert(analysisRoot.textContent.includes('+4.745 USDT'));
c.state.symbol='NEW-USDT-SWAP';c.renderAnalysis();assert(!analysisRoot.textContent.includes('0.008274286'));assert(analysisRoot.textContent.includes('분석 대기'));
clock-=36000;c.state.symbol=analysis.symbol;c.state.data.entry_gate={};c.renderAnalysis();assert(analysisRoot.textContent.includes('1 USDT당'));assert(analysisRoot.textContent.includes('+0.095 USDT'));
console.log('PASS structured analysis keeps original scores, conditional PnL, stale/symbol gates and details state; no trade API invoked');
c.state.data.entry_gate={preview_margin:48.35};c.state.fundingReceivedAt=clock;
const funding={symbol:c.state.symbol,usable:true,rate:-.0066815,settlement_ms:clock+3600000,valid_for_ms:60000};
c.state.chartData.funding=funding;c.renderFunding();
assert.equal(nodes.fundingPreview.children.length,2);
assert(nodes.fundingPreview.textContent.includes('-0.66815%'));
assert(nodes.fundingPreview.textContent.includes('롱 수취 1.615 / 숏 지급 1.615 USDT'));
const fundingLine=nodes.fundingPreview.children[0],fundingFlow=nodes.fundingPreview.children[1],writes=fundingLine.writes;
for(let i=0;i<20;i++)c.renderFunding();
assert.strictEqual(nodes.fundingPreview.children[0],fundingLine);assert.equal(fundingLine.writes,writes);
funding.rate=.001;c.renderFunding();assert(nodes.fundingPreview.textContent.includes('롱 지급 0.242 / 숏 수취 0.242'));
funding.rate=0;c.renderFunding();assert(nodes.fundingPreview.textContent.includes('롱 0.000 / 숏 0.000'));
c.state.data.entry_gate={};c.renderFunding();assert(nodes.fundingPreview.textContent.includes('증거금 미확인'));assert(!nodes.fundingPreview.children[1].textContent.includes('0.000'));
c.state.data.entry_gate={preview_margin:48.35};funding.rate=-.0066815;
for(const delta of [-1,30000,60001]){c.state.fundingReceivedAt=clock-delta;c.renderFunding();assert(nodes.fundingPreview.textContent.includes('예상액 미표시'));assert(!nodes.fundingPreview.textContent.includes('1.615'))}
c.state.fundingReceivedAt=clock;funding.settlement_ms=clock;c.renderFunding();assert(!nodes.fundingPreview.textContent.includes('0.66815'));
funding.settlement_ms=clock+3600000;funding.symbol='WRONG';c.renderFunding();assert(!nodes.fundingPreview.textContent.includes('0.66815'));
funding.symbol=c.state.symbol;funding.usable=false;c.renderFunding();assert(!nodes.fundingPreview.textContent.includes('0.66815'));
assert.strictEqual(nodes.fundingPreview.children[1],fundingFlow);assert.equal(nodes.fundingPreview.clears,0);
console.log('PASS compact two-line funding, pay/receive signs, unknown margin, stale/settlement/symbol guards and stable text nodes');
const similarHealth={...h,entry:{...h.entry,similarity:{reference_symbol:'AAA-USDT-SWAP',action:'LONG',observed_ms:clock,status:'기존 조건 통과 후보 중 유사 종목 우선 검토',
 candidates:[{symbol:'BBB-USDT-SWAP',score:92,relative_volume:1.4,passed:true},{symbol:'CCC-USDT-SWAP',score:80,relative_volume:.8,passed:false}]}}};
c.phoneRenderDiagnostics({performance:{runtime_health:similarHealth}});
const similarSection=section('유사 종목 후보');assert(similarSection);
assert(similarSection.textContent.includes('BBB · 유사 92'));assert(similarSection.textContent.includes('봉 통과·주문 검사 대기'));
assert(similarSection.textContent.includes('CCC · 유사 80'));assert(similarSection.textContent.includes('유사도는 승률 아님'));
const similarRows=[...similarSection.children];
for(let i=0;i<10;i++){
 similarHealth.entry.similarity.candidates[0].score=92+i/10;
 c.phoneRenderDiagnostics({performance:{runtime_health:similarHealth}});
 assert.strictEqual(section('유사 종목 후보'),similarSection);
 assert.deepStrictEqual(similarSection.children,similarRows);assert.equal(similarSection.clears,0);
}
c.URL={createObjectURL(blob){download=blob.parts.join('');return 'blob:test'},revokeObjectURL(){}};
c.Blob=function(parts,opts){this.parts=parts};c.setTimeout=fn=>fn();
c.document.body={appendChild(link){}};c.document.createElement=()=>({click(){},remove(){}});
c.api=async route=>{assert.equal(route,'/api/phone/diagnostic');return {runtime_health:h,history:[{run_id:'old'}],historical_signals:[{symbol:'OP-USDT-SWAP'}]}};
await c.phoneSaveDiagnostics({account:{apiKey:'SECRET'},performance:{runtime_health:h,last_admission:[{category:'spread_check'}]}});
assert(!download.includes('SECRET'));assert(JSON.parse(download).runtime_health.signal_journey);
console.log('PASS KST month/day including midnight/new year; combined diagnostic DOM, latest-per-symbol single row, no trade requests');

})().catch(e=>{console.error(e);process.exitCode=1});
