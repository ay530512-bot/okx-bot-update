function phoneHistoryDetails(e,p){
 for(const part of p.partial_details||[]){
  const amount=part.pnl==null?'금액 확인 불가':cash(part.pnl,true)+' USDT';
  e.append(node('p',part.label+' 손익: '+amount+' (비용 전)'));
  if(part.fee!=null&&part.fee_ccy)e.append(node('p','해당 청산 수수료: '+cash(part.fee,true)+' '+part.fee_ccy));
  e.append(node('p','부분청산 이유: '+part.reason));
 }
 e.append(node('p',p.partial_note||'부분청산 기록 확인 불가'));
 e.append(node('p',((p.partial_details||[]).length?'잔량 청산 이유: ':'청산 이유: ')+(p.exit_reason_detail||'기록 확인 불가')));
}
