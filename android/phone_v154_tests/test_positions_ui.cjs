// Small isolated DOM model; this does not claim pixel/browser/device coverage.
const vm=require('vm'),fs=require('fs'),path=require('path'),assert=require('assert');
const nodes={},actions=[];
function node(tag,text,cls){return {tag,text:text||'',className:cls||'',children:[],attrs:{},isConnected:true,
 append(...els){this.children.push(...els)},replaceChildren(...els){for(const x of this.children)x.isConnected=false;this.children=els},
 setAttribute(k,v){this.attrs[k]=v},get textContent(){return this.text+this.children.map(x=>x.textContent).join('|')}}}
nodes.positions=node('div');
const ctx={node,$:x=>nodes[x],state:{symbol:'TEST-USDT-SWAP'},Set,Number,String,cash:String,num:Number,price:String,color(){},
 phoneMoveStamp:x=>'KST '+x,trade:(op,args)=>actions.push([op,args]),setPart(){throw Error('unexpected chart navigation')},chooseChart(){throw Error('unexpected chart navigation')},render(){}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'../phone_v154/phone_position_ui.js'),'utf8'),ctx);
const row={key:'one',symbol:'TEST-USDT-SWAP',direction:'short',source:'auto',leverage:10,margin:'47.5',roe:'-.03',pnl:'-1.44',entry:'2.638611',mark:'2.6466',stop:'2.7592',phase:'active',close_key:'EXACT_KEY',protection_note:'보호 정보',entry_details:{rule:'두꼬리',summary:'연속 윗꼬리 · 고점 미돌파 확인',frame:'15m',confirmed_ms:123,entry_ms:456,evidence:[{label:'직전 고점',value:'2.7'}]}};
function walk(e,pred){if(pred(e))return e;for(const x of e.children){const v=walk(x,pred);if(v)return v}}
ctx.phoneRenderPositions({controls_enabled:true},[row],false,false);
let card=nodes.positions.children[0];assert.equal(card.tag,'article');assert(card.textContent.includes('충족 조건'));assert(card.textContent.includes('고점 미돌파'));assert(card.textContent.includes('직전 고점'));assert(!card.onclick);
let close=walk(card,e=>e.className==='danger closeone');close.onclick();assert.equal(actions[0][0],'close_one');assert.equal(actions[0][1].key,'EXACT_KEY');
walk(card,e=>e.className==='phone-entry-toggle').onclick();ctx.phoneRenderPositions({controls_enabled:true},[row],false,false);
assert(!walk(nodes.positions,e=>e.className==='phone-entry-more').hidden,'details expansion lost');
for(const [enabled,busy,old,phase] of [[false,false,false,'active'],[true,true,false,'active'],[true,false,true,'active'],[true,false,false,'closing']]){
 ctx.phoneRenderPositions({controls_enabled:enabled},[{...row,phase}],busy,old);assert(walk(nodes.positions,e=>e.className==='danger closeone').disabled);
}
ctx.phoneRenderPositions({controls_enabled:true},[{...row,entry_details:null}],false,false);
assert(nodes.positions.textContent.includes('진입 규칙 기록 없음'));assert(!nodes.positions.textContent.includes('두꼬리'));
assert(!walk(nodes.positions,e=>e.className==='phone-entry-more'));
ctx.phoneRenderPositions({controls_enabled:true},[],false,false);assert(nodes.positions.textContent.includes('보유 포지션이 없습니다'));
const css=fs.readFileSync(path.join(__dirname,'../phone_v154/phone_sections.css'),'utf8');
for(const rule of ['max-height:min(280px,42dvh)','overflow-y:auto','touch-action:pan-y','grid-template-columns:65px minmax(0,1fr)','#positions .metrics b{font-size:15px'])assert(css.includes(rule),rule);
console.log('PASS position DOM: recorded reasons, aligned rows, retained expansion, exact close key and stale/busy/disabled gates; bounded scroll CSS');
