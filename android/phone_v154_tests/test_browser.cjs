// Full production assets in a local browser with all HTTP requests intercepted.
// Every position/fill is a fixture. No trade endpoint can reach a network.
const {chromium}=require('playwright'),fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const folder=process.argv[2],out=process.argv[3]||folder,requests=[],errors=[];
 const position=JSON.parse(fs.readFileSync(path.join(folder,'position.json')));
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1,isMobile:true,hasTouch:true});
 page.on('pageerror',e=>errors.push(e.message));
 const now=Date.now(),data={ui_version:'7.32-Q2X',controls_enabled:true,captured_ms:now,account_age_seconds:0,
  state:{equity:'300',available:'225',day_profit:'0',account_connected:true},positions:[position],movers:[],activities:[],
  performance:{runtime_health:{observed_at:now/1000,elapsed_s:100,entry:{},signal_journey:{unique_observed:24,first_seen_expired:0,rows:Array.from({length:24},(_,i)=>({symbol:'TEST'+i+'-USDT-SWAP',action:'LONG',stage_label:'실시간 시세 준비 대기',valid_from_ms:now-30000,first_delay_s:2,route:'double_wick',last_market:{channels:{trades:{ready:false,subscribed:true}}}}))}}}};
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());requests.push(u.pathname);
  if(u.pathname==='/api/snapshot')return route.fulfill({json:{...data,captured_ms:Date.now()}});
  if(u.pathname.startsWith('/api/'))return route.fulfill({json:{bars:[]}});
  const name=u.pathname==='/'?'index.html':u.pathname.slice(1);
  if(!['index.html','style.css','app.js'].includes(name))return route.abort();
  return route.fulfill({body:fs.readFileSync(path.join(folder,name)),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
 });
 await page.goto('http://phone.test/');await page.locator('#dashboard').waitFor({state:'visible'});
 await page.locator('#nav-chart').click();await page.locator('.phone-entry-rows').first().waitFor({state:'visible'});
 const metrics=[];
 for(const width of [320,390,430,768]){
  await page.setViewportSize({width,height:844});await page.locator('#current').scrollIntoViewIfNeeded();
  const measure=await page.evaluate(()=>({viewport:innerWidth,pageWidth:document.documentElement.scrollWidth,
   card:document.querySelector('#positions .position').getBoundingClientRect().height,
   metricFont:getComputedStyle(document.querySelector('#positions .metrics b')).fontSize,
   columns:getComputedStyle(document.querySelector('#positions .metrics')).gridTemplateColumns}));
  assert(measure.pageWidth<=width,'horizontal overflow');assert.equal(measure.metricFont,'15px');metrics.push(measure);
  if(width===390)await page.locator('#current').screenshot({path:path.join(out,'position-390.png')});
 }
 await page.setViewportSize({width:390,height:844});
 await page.locator('.phone-entry-toggle').click();
 await page.waitForFunction(()=>!document.querySelector('.phone-entry-more').hidden);
 await page.evaluate(()=>render(state.data));
 assert(await page.locator('.phone-entry-more').evaluate(e=>!e.hidden),'expanded state lost on refresh');
 await page.locator('.phone-entry-more').screenshot({path:path.join(out,'entry-details-390.png')});
 await page.locator('#nav-settings').click();
 await page.locator('#phoneSignalJourney').scrollIntoViewIfNeeded();
 const scroll=await page.locator('#phoneSignalJourney').evaluate(e=>{e.scrollTop=150;return {height:e.clientHeight,total:e.scrollHeight,top:e.scrollTop}});
 assert(scroll.total>scroll.height);assert(scroll.height<=280);assert(scroll.top>0);
 await page.evaluate(()=>render(state.data));
 assert.equal(await page.locator('#phoneSignalJourney').evaluate(e=>e.scrollTop),scroll.top,'scroll reset after refresh');
 await page.locator('#phoneSignalJourney').screenshot({path:path.join(out,'signals-390.png')});
 // No synthetic click on a financial control. Inspect binding and disabled gates.
 await page.evaluate(()=>{const d={...state.data,controls_enabled:false};render(d)});
 assert(await page.locator('#positions .closeone').isDisabled());
 assert(!requests.some(x=>x.startsWith('/api/control/')),'unexpected control request');assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({metrics,scroll,errors,controlRequests:0},null,2));
 await browser.close();console.log('PASS full mobile UI: 320/390/430/768px, entry evidence, retained expansion and scroll, no trade request');
})().catch(e=>{console.error(e);process.exit(1)});
