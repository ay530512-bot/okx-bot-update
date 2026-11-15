const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={},buttons=[],requests=[];
function element(){return {style:{},appendChild(el){if(el.id)nodes[el.id]=el;if(el.type==='button')buttons.push(el);}};}
nodes.programUpdate=element();
const context={render(){},document:{getElementById(id){return nodes[id]||null;},createElement:element},crypto:{randomUUID:()=> 'test-1234'},async api(url,opt){requests.push({url,body:JSON.parse(opt.body)});return {message:'변경 요청'};}};
vm.createContext(context);
const source=fs.readFileSync(process.env.OKX_TEST_HOST+'/phone_update_ui.js','utf8').split('// Calculation mode:')[1];
vm.runInContext('// Calculation mode:'+source,context);
(async()=>{
context.render({performance:{parallel:{requested:4,effective:4,workers_alive:4,aggregate_rss_mib:300,aggregate_cpu_one_core_pct:180}}});
assert(nodes.parallelState126.textContent.includes('4개 분산'));assert(nodes.parallelState126.textContent.includes('180%'));
assert.equal(buttons.length,2);await buttons[1].onclick();assert.equal(requests[0].body.key,'serial');assert.equal(requests[0].url,'/api/control/calculation');assert.equal(buttons[1].disabled,false);
context.render({performance:{parallel:{requested:0,effective:0,workers_alive:0,last_error:'TimeoutError'}}});assert(nodes.parallelState126.textContent.includes('기존 1.2.5'));assert(nodes.parallelState126.textContent.includes('자동 복원'));assert.equal(buttons.length,2);
await buttons[0].onclick();assert.equal(requests[1].body.key,'parallel4');
console.log('4 mode UI checks passed');
})().catch(e=>{console.error(e);process.exit(1)});
