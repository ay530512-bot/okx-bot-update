const fs=require('fs'),assert=require('assert');
const {chromium}=require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root='/tmp/phone132';
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:390,height:844},deviceScaleFactor:1});
 let controlRequests=0,charts=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 const now=Date.now(),close=now-now%900000;
 const health={observed_at:now/1000,elapsed_s:700,public_connected:true,account_connected:true,account_fresh:true,entry_enabled:true,disconnect_count:1,last_disconnect_at:now/1000-400,last_disconnect_cause:'read_eof',program_version:'1.3.2',entry_observation_totals:{scans:107,candidate_returns:0},trend_status:'상승1위 새 돌파 신호 대기',entry:{observed_at:now/1000,duration_s:.615,pending:0,result:'진입 후보 대기',reasons:{'확정봉 규칙 조건 미충족':289},routes:{trend_pullback:{pass_count:0,wait_count:73,data_wait_count:0,inactive_count:216,reasons:{'시간봉 상태에 따라 다른 기존 경로 선택':216,'눌림/시간봉 추세 지속성 확인 대기':73}},confirmed_reversal:{pass_count:0,wait_count:216,data_wait_count:0,inactive_count:73,reasons:{'완료봉 패턴 확인 대기':206}},double_wick:{pass_count:0,wait_count:289,data_wait_count:0,inactive_count:0,reasons:{'두 꼬리 모양·고저점·확인종가 미충족':285,'1시간 추세·효율·MA50 방향 미충족':4}}}}};
 const data={ui_version:'7.32-Q2X',controls_enabled:true,captured_ms:now,account_age_seconds:1,status:'폰 실거래 가동 중',state:{equity:300,available:297,day_profit:0,live:true,account_connected:true,market_connected:true},entry_gate:{allowed:true},positions:[],activities:[],movers:[],futures:{observed_ms:now,stale:false,rows:[{symbol:'ALT-USDT-SWAP',last:110,change:.12,ts:now}]},program_update:{message:'현재 버전 1.3.2'},performance:{recent:{count:30,mean_s:3.945,p95_s:8.087159},cache:{hit_pct:98.4},resources:{rss_mib:170,cpu_one_core_pct:95},runtime_health:health},market_alerts:{checked_at_ms:now,coverage_fresh:289,coverage_total:289,items:[{id:'ALT:'+close,symbol:'ALT-USDT-SWAP',opening:100,close:110,change_pct:10,close_ms:close},{id:'OLD:'+close,symbol:'OLD-USDT-SWAP',opening:100,close:90,change_pct:-10,close_ms:close}]}};
 await page.route('**/*',async r=>{
  const url=new URL(r.request().url()),p=url.pathname;
  if(p.startsWith('/api/control/')){controlRequests++;return r.fulfill({json:{status:'failed',message:'test only'}});}
  if(p==='/api/chart'){
   charts.push(url.searchParams.get('symbol'));
   const bars=Array.from({length:40},(_,i)=>[close-(40-i)*900000,100,111,99,110,10]);
   return r.fulfill({json:{symbol:url.searchParams.get('symbol'),frame:'15m',bars,stale:false}});
  }
  if(p.startsWith('/api/'))return r.fulfill({json:data});
  const n=p==='/'?'index.html':p.slice(1);
  if(['index.html','style.css','app.js'].includes(n))return r.fulfill({body:fs.readFileSync(root+'/'+n),contentType:n.endsWith('js')?'text/javascript':n.endsWith('css')?'text/css':'text/html'});
  return r.fulfill({status:404,body:''});
 });
 await page.goto('http://phone.test/');
 await page.evaluate(d=>{showDashboard();render(d);setPart('market');},data);
 await page.locator('#phoneMovesPanel').scrollIntoViewIfNeeded();
 assert.equal(await page.locator('.phone-move-card').count(),2);
 assert.equal(await page.locator('.phone-move-card').nth(1).isDisabled(),true);
 await page.screenshot({path:root+'/market.png'});
 await page.locator('.phone-move-card').first().click();
 await page.waitForFunction(()=>state.symbol==='ALT-USDT-SWAP'&&state.chartKey==='ALT-USDT-SWAP:15m');
 assert.equal(await page.locator('#part-chart').isVisible(),true);
 assert.equal(await page.locator('#frame').inputValue(),'15m');
 assert.equal(controlRequests,0);assert(charts.includes('ALT-USDT-SWAP'));
 assert.equal(await page.locator('#chartLong').isDisabled(),false);
 // Preserve existing guards when stale/disconnected, no card may bypass them.
 await page.evaluate(d=>{d.entry_gate={allowed:false,code:'recovering',reason:'복구 중'};render(d);},data);
 assert.equal(await page.locator('#chartLong').isDisabled(),true);
 await page.evaluate(d=>{render(d);setPart('settings');},data);
 assert.equal(await page.locator('.phone-rule-card').count(),3);
 for(const title of ['연결 상태','신호 검사','규칙별 검사 결과','추세 전용 1자리','기록 안내'])assert((await page.locator('#phoneHealthSummary').innerText()).includes(title));
 const overflow=await page.evaluate(()=>[...document.querySelectorAll('#phoneHealthSummary div,#phoneMovesPanel')].some(e=>e.scrollWidth>e.clientWidth+2));assert.equal(overflow,false);
 await page.locator('#phoneHealthSummary').screenshot({path:root+'/diagnostics.png'});
 // Stale and missing input, safe text rendering and no unbounded list growth.
 await page.evaluate(d=>{d.performance.runtime_health.observed_at-=100;render(d);},data);
 assert((await page.locator('#phoneHealthSummary').innerText()).includes('진단 자료 지연'));
 await page.evaluate(d=>{d.performance.runtime_health={unavailable:true};d.market_alerts.items=[];render(d);},data);
 assert((await page.locator('#phoneHealthSummary').innerText()).includes('수집 중'));
 assert.equal(await page.locator('.phone-move-card').count(),0);
 assert.equal(controlRequests,0);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({browser:'Chromium',viewport:'390x844',checks:'alert cards, unavailable symbol, chart click, zero order requests, existing gate, grouped sections, no overflow, stale/missing states',page_errors:errors,order_requests:controlRequests}));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
