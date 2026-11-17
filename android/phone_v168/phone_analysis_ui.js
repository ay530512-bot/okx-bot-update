// Read-only presentation of the existing analysis. No entry-gate or order changes.
const phoneAnalysisView={symbol:null,last:null,signature:null};
function phoneAnalysisNumber(value,digits=2,signed=false){
 const v=value==null?NaN:Number(value);
 return Number.isFinite(v)?(signed&&v>=0?'+':'')+v.toFixed(digits):'—';
}
function phoneAnalysisPrice(value){
 const v=value==null?NaN:Number(value);return Number.isFinite(v)?Number(v.toPrecision(7)).toString():'—';
}
function phoneAnalysisStamp(value){
 return Number.isFinite(value)?new Date(value).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false}):'확인 중';
}
renderFunding=function(){
 const root=$('fundingPreview');if(!root)return;
 const f=state.chartData?.funding,now=Date.now(),elapsed=now-(state.fundingReceivedAt||0);
 const valid=f&&f.symbol===state.symbol&&state.symbol&&f.usable&&Number.isFinite(f.rate)&&
  Number.isFinite(f.settlement_ms)&&f.settlement_ms>now&&Number.isFinite(f.valid_for_ms)&&
  elapsed>=0&&elapsed<Math.min(30000,f.valid_for_ms);
 let line='펀딩 갱신 대기 · 예상액 미표시',flow='정산 시 보유분 · 1회 예상';
 if(valid){
  const stamp=new Date(f.settlement_ms).toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour12:false,hour:'2-digit',minute:'2-digit'});
  line='펀딩(1회 예상) '+phoneAnalysisNumber(f.rate*100,5,true)+'% · '+stamp+' KST';
  const raw=state.data?.entry_gate?.preview_margin,margin=raw==null?NaN:Number(raw);
  if(Number.isFinite(margin)&&margin>0){
   const fee=margin*5*f.rate;
   const cash=v=>(v>0?'수취 ':v<0?'지급 ':'')+phoneAnalysisNumber(Math.abs(v),3);
   flow='롱 '+cash(-fee)+' / 숏 '+cash(fee)+' USDT';
  }else flow='증거금 미확인 · 예상액 미표시';
 }
 const view=node('div');view.append(node('div',line),node('div',flow));phoneUiSync(root,view);
 root.title='수동 5배 · 목표 증거금 기준 · 정산 시 보유분에 적용되는 1회 예상. 수량·마크가격·펀딩률에 따라 실제 금액은 달라집니다. TP/SL 예시에는 펀딩 미포함.';
};
function phoneAnalysisPart(root,key,title){
 const part=phoneUiKey(node('div',undefined,'phone-analysis-part'),key);
 part.append(node('h4',title));root.append(part);return part;
}
function phoneAnalysisPair(root,label,value,key=label){
 const row=phoneUiKey(node('div',undefined,'phone-analysis-pair'),key);
 row.append(node('span',label),node('b',value));root.append(row);
}
function phoneAnalysisTable(root,headers,rows,key){
 const table=phoneUiKey(node('table',undefined,'phone-analysis-table'),key),head=node('thead'),tr=node('tr'),body=node('tbody');
 for(const label of headers){const th=node('th',label);th.scope='col';tr.append(th)}
 head.append(tr);table.append(head,body);
 for(const [label,...values] of rows){
  const row=phoneUiKey(node('tr'),label),th=node('th',label);th.scope='row';row.append(th);
  for(const value of values)row.append(node('td',value));body.append(row);
 }
 root.append(table);return table;
}
renderAnalysis=function(){
 renderFunding();
 const root=$('directionAnalysis');if(!root)return;
 const current=state.chartData?.analysis,ready=analysisReady();
 if(phoneAnalysisView.symbol!==state.symbol){phoneAnalysisView.symbol=state.symbol;phoneAnalysisView.last=null;phoneAnalysisView.signature=null}
 const rawMargin=state.data?.entry_gate?.preview_margin;
 const margin=rawMargin!=null&&Number.isFinite(Number(rawMargin))&&Number(rawMargin)>0?Number(rawMargin):null;
 if(ready)phoneAnalysisView.last={a:current,margin};
 const saved=phoneAnalysisView.last,a=saved?.a;
 phoneUiText($('longScore'),ready?'롱 '+phoneAnalysisNumber(current.long_score,1)+'%':'롱 —');
 phoneUiText($('shortScore'),ready?'숏 '+phoneAnalysisNumber(current.short_score,1)+'%':'숏 —');
 const reason=current?.symbol===state.symbol?current.reason:null;
 const signature=JSON.stringify([state.symbol,ready,a,saved?.margin,reason]);
 if(signature===phoneAnalysisView.signature)return;
 phoneAnalysisView.signature=signature;
 const view=node('div');
 if(!a){view.append(node('p','분석 대기 · '+(reason||'최신 확정봉·시세 확인 중'),'phone-analysis-status'));phoneUiSync(root,view);return}
 const status=ready?a.preference:'갱신 대기 · 아래는 마지막 분석';
 view.append(phoneUiKey(node('p',status,'phone-analysis-status'+(ready?'':' warning')),'status'));
 if(!ready&&reason)view.append(phoneUiKey(node('p',reason,'phone-analysis-note'),'waiting-reason'));
 const basis=phoneAnalysisPart(view,'basis','분석 기준');
 const pairs=node('div',undefined,'phone-analysis-pairs');basis.append(pairs);
 phoneAnalysisPair(pairs,'기준가',phoneAnalysisPrice(a.price));
 phoneAnalysisPair(pairs,'배율',phoneAnalysisNumber(a.leverage,0)+'배');
 phoneAnalysisPair(pairs,'증거금',saved.margin===null?'미확인 · 1 USDT당':phoneAnalysisNumber(saved.margin)+' USDT');
 phoneAnalysisPair(pairs,'확인 시각',phoneAnalysisStamp(a.observed_ms)+' KST');
 const indicators=phoneAnalysisPart(view,'indicators','확정봉 지표');
 const rows=[];
 for(const [key,label] of [['15m','15분'],['1H','1시간']]){
  const f=a.frames?.[key]||{};
  rows.push([label,phoneAnalysisNumber(f.rsi,1),phoneAnalysisNumber(f.volume_ratio)+'배']);
 }
 phoneAnalysisTable(indicators,['시간봉','RSI','거래량'],rows,'frames');
 for(const [key,label] of [['15m','15분'],['1H','1시간']]){
  const f=a.frames?.[key]||{},signals=f.signals||{};
  const marks=[['MA','MA'],['BOLL','BB'],['RSI','RSI'],['VOLUME','거래량']].map(([k,n])=>n+(Number.isFinite(signals[k])?(signals[k]>.1?'↑':signals[k]<-.1?'↓':'↔'):'—'));
  indicators.append(phoneUiKey(node('p',label+' · '+marks.join(' · '),'phone-analysis-marks'),key));
  if(f.missing_ma?.length)indicators.append(phoneUiKey(node('p',label+' MA '+f.missing_ma.join('·')+' 미수집 · 점수 제외','phone-analysis-note'),key+'-missing'));
 }
 if(a.conflict)indicators.append(phoneUiKey(node('p','15분·1시간 방향 상충','warning'),'conflict'));
 if(a.entry_block_reason)indicators.append(phoneUiKey(node('p',a.entry_block_reason,'warning'),'block'));
 const plans=phoneAnalysisPart(view,'plans','방향별 손절·1차 익절');
 plans.append(node('p','초기 SL 2ATR · +20% ROE에서 50% 익절','phone-analysis-note'));
 const l=a.directions?.LONG||{},s=a.directions?.SHORT||{},factor=saved.margin??1;
 const amount=(v)=>Number.isFinite(v)?phoneAnalysisNumber(v*factor,3,true)+' USDT':'—';
 phoneAnalysisTable(plans,['항목','롱','숏'],[
  ['초기 SL',phoneAnalysisPrice(l.sl),phoneAnalysisPrice(s.sl)],
  ['SL 기준 ROE',phoneAnalysisNumber(l.sl_roe,1,true)+'%',phoneAnalysisNumber(s.sl_roe,1,true)+'%'],
  ['전량 SL 손익',amount(l.sl_net_per_margin),amount(s.sl_net_per_margin)],
  ['1차 익절가',phoneAnalysisPrice(l.partial_price),phoneAnalysisPrice(s.partial_price)],
  ['절반 익절 손익',amount(l.partial_net_per_margin),amount(s.partial_net_per_margin)],
  ['참고 저항 / 지지',phoneAnalysisPrice(l.resistance_or_support),phoneAnalysisPrice(s.resistance_or_support)]
 ],'scenarios');
 plans.append(node('p',saved.margin===null?'증거금 미확인 · 위 손익은 1 USDT당 계산':'목표 증거금 기준 · 계약 수량 반올림 전','phone-analysis-note'));
 const details=phoneUiKey(node('details',undefined,'phone-analysis-details'),'details');
 details.append(node('summary','비용·잔량 관리 기준'));
 for(const line of ['조건부 손익 예시 · 기대수익·최종수익 미산정',a.cost_assumption||'편도 수수료 0.05% + 슬리피지 0.05% · 펀딩 제외',
  '시장가·가격단위·펀딩에 따라 실제 손익과 SL은 달라짐','잔량: 수익보호·추적 SL · 최대 6시간 · 고정 전량 TP 없음'])details.append(node('p',line));
 view.append(details);phoneUiSync(root,view);
};
