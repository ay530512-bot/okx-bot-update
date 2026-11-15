// DOM contract test for text-only diagnostic UI (not a browser render test).
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={programUpdate:{appendChild(el){nodes[el.id]=el;}}};
const context={Date,Math,Object,render(){},document:{getElementById(id){return nodes[id]||null;},createElement(){return {style:{}};}}};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/health_ui.js','utf8'),context);
const h={observed_at:Date.now()/1000,elapsed_s:600,public_connected:true,account_connected:true,account_fresh:true,entry_enabled:true,disconnect_count:2,last_disconnect_at:Date.now()/1000-120,last_disconnect_cause:'read_eof',entry:{observed_at:Date.now()/1000-2,duration_s:2.4,pending:1,result:'진입 후보 대기',reasons:{'실시간 자료 대기':1},waiting:[{symbol:'XRP-USDT-SWAP',channels:['books5'],remaining_s:42}]}};
context.render({performance:{runtime_health:h}});
for(const x of ['시세 연결','끊김 2회','books5','42초','허용','소켓 수신 종료(EOF)'])assert(nodes.phoneHealthSummary.textContent.includes(x),x);
h.observed_at-=40;h.public_connected=false;context.render({performance:{runtime_health:h}});
assert(nodes.phoneHealthSummary.textContent.includes('진단 자료 지연'));assert(nodes.phoneHealthSummary.textContent.includes('시세 끊김'));
context.render({performance:{runtime_health:{unavailable:true}}});assert(nodes.phoneHealthSummary.textContent.includes('수집 중'));
console.log('3 diagnostic DOM state checks passed');
