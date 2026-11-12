const vm=require('vm'),fs=require('fs'),assert=require('assert');
const elems=new Map();const ctx=new Proxy({},{get:()=>()=>{}});
class El{constructor(){this.hidden=false;this.children=[];this.style={};this.dataset={};this.value='';this.clientWidth=350;this.clientHeight=500;this.offsetWidth=218;this.offsetHeight=290;this.events={};this.classList={toggle(){},add(){},remove(){}}}append(...e){this.children.push(...e)}replaceChildren(...e){this.children=e}addEventListener(n,f){(this.events[n]??=[]).push(f)}getBoundingClientRect(){return {left:0,top:0,width:350,height:500}}getContext(){return ctx}setPointerCapture(){}setAttribute(k,v){this[k]=v}get textContent(){return (this.text||'')+this.children.map(x=>x.textContent).join(' ')}set textContent(x){this.text=x}}
const document={hidden:true,getElementById(id){if(!elems.has(id))elems.set(id,new El());return elems.get(id)},createElement(){return new El()},addEventListener(){}};
const sandbox={document,window:{addEventListener(){},scrollTo(){},devicePixelRatio:1},devicePixelRatio:1,Intl,Date,URL,location:{href:'https://example.com/'},history:{},requestAnimationFrame(f){f()},setInterval(){},setTimeout(){return 1},clearTimeout(){},console};vm.createContext(sandbox);vm.runInContext(fs.readFileSync('chart_update/mobile_assets/app.js','utf8'),sandbox);
vm.runInContext(`state.symbol='AKE-USDT-SWAP';state.data={positions:[{symbol:state.symbol}]};state.bars=Array.from({length:70},(_,i)=>[i*900000,.0024,.0034,.0023,.0032,1234,true,5678,12.34]);draw();selectCandle(70,100);`,sandbox);
const tip=elems.get('candleTip');assert(!tip.hidden);assert(tip.textContent.includes('+33.33%'));assert(tip.textContent.includes('5,678.00'));assert(tip.textContent.includes('12.34'));assert(parseFloat(tip.style.left)>=0);assert(parseFloat(tip.style.left)+218<=350);
vm.runInContext(`state.symbol='OTHER';draw()`,sandbox);assert(tip.hidden);vm.runInContext(`state.symbol='AKE-USDT-SWAP';draw();selectCandle(70,100);state.bars=[];draw()`,sandbox);assert(tip.hidden);
console.log('PASS: tooltip OHLC, return, volume units, bounds, symbol isolation, empty chart');
vm.runInContext("renderUpdateNotice({available:true,version:'7.32-Q2N'})",sandbox);assert(!elems.get('updateNotice').hidden);assert(elems.get('updateNotice').textContent.includes('업데이트하세요'));vm.runInContext('renderUpdateNotice({available:false})',sandbox);assert(elems.get('updateNotice').hidden);console.log('PASS update notice show/hide');

vm.runInContext("state.chartBusy=true;for(const key of partKeys){setPart(key);for(const other of partKeys){if($('part-'+other).hidden!==(key!==other))throw Error('tab isolation')}}",sandbox);console.log('PASS bottom navigation isolation and active screen switching');

for(const type of ['contextmenu','selectstart','dragstart','touchstart','touchmove']){let prevented=false;for(const fn of elems.get('chart').events[type])fn({cancelable:true,preventDefault(){prevented=true}});assert(prevented,type)}console.log('PASS canvas native selection/callout suppression handlers');

const fire=(name,id,x,y)=>{for(const fn of elems.get('chart').events[name]||[])fn({pointerId:id,pointerType:'touch',clientX:x,clientY:y,offsetX:x,cancelable:true,preventDefault(){}})};
const get=x=>vm.runInContext(x,sandbox);
vm.runInContext("state.bars=Array.from({length:300},(_,i)=>[i*900000,1,2,.5,1.5,10,true]);state.count=60;state.end=null;state.scale=1;state.shift=0;draw()",sandbox);
fire('pointerdown',1,320,100);fire('pointermove',1,320,160);assert(get('state.scale')>1);assert.equal(get('state.end'),null);fire('pointerup',1,320,160);
fire('pointerdown',1,90,100);fire('pointerdown',2,190,100);fire('pointermove',2,290,100);assert(get('state.count')<60);fire('pointerup',2,290,100);fire('lostpointercapture',2,290,100);assert.equal(get('fingers.size'),1);fire('pointermove',1,130,100);assert.notEqual(get('state.end'),null);fire('pointerup',1,130,100);
fire('pointerdown',1,100,100);fire('pointerup',1,100,100);fire('pointerdown',1,100,100);fire('pointerup',1,100,100);assert.equal(get('state.scale'),1);assert.equal(get('state.end'),null);
assert(!fs.readFileSync('chart_update/mobile_assets/index.html','utf8').includes('class="chartcontrols"'));
console.log('PASS axis drag, pinch zoom, pinch-to-pan continuation, double-tap reset and toolbar removal');
