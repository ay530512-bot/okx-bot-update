(async()=>{
// Exercise final combined UI and KST date formatting with a minimal DOM. No trade requests.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const host=path.join(__dirname,'../phone_v161'),nodes={},requests=[];
let clock=Date.parse('2026-11-16T12:43:00Z');
class ClockDate extends Date{static now(){return clock}}
function element(tag,text,cls){return {tag,own:text||'',className:cls,style:{},children:[],append(...els){for(const x of els){this.children.push(x);if(x.id)nodes[x.id]=x}},appendChild(el){this.append(el)},replaceChildren(...els){this.children=[];this.append(...els)},set textContent(v){this.own=v;this.children=[]},get textContent(){return this.own+this.children.map(x=>x.textContent).join('\n')}}}
for(const id of ['programUpdate','mobileUpdateButton','mobileUpdateStatus','phoneMoveRows','phoneMoveStatus'])nodes[id]=element('div');
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
c.URL={createObjectURL(blob){download=blob.parts.join('');return 'blob:test'},revokeObjectURL(){}};
c.Blob=function(parts,opts){this.parts=parts};c.setTimeout=fn=>fn();
c.document.body={appendChild(link){}};c.document.createElement=()=>({click(){},remove(){}});
c.api=async route=>{assert.equal(route,'/api/phone/diagnostic');return {runtime_health:h,history:[{run_id:'old'}],historical_signals:[{symbol:'OP-USDT-SWAP'}]}};
await c.phoneSaveDiagnostics({account:{apiKey:'SECRET'},performance:{runtime_health:h,last_admission:[{category:'spread_check'}]}});
assert(!download.includes('SECRET'));assert(JSON.parse(download).runtime_health.signal_journey);
console.log('PASS KST month/day including midnight/new year; combined diagnostic DOM, latest-per-symbol single row, no trade requests');

})().catch(e=>{console.error(e);process.exitCode=1});
