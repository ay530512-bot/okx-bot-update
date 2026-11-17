"""Display-only local evidence. No new exchange requests or order writes."""
import hashlib,inspect,json,textwrap,threading
from pathlib import Path
from decimal import Decimal,InvalidOperation
LOCK=threading.Lock()
def number(v):
 try:
  x=Decimal(str(v));return x if x.is_finite() else None
 except (InvalidOperation,ValueError,TypeError):return None

def record_partial(root,o,state,order):
 # Called with the order response already obtained by the existing reconciler.
 # Evidence write failures must never interfere with protection or execution.
 try:
  filled=number(order.get('accFillSz'));before=number(state.get('before'))
  if order.get('state') not in ('filled','canceled') or filled is None or filled<=0 or not before:return
  if order.get('clOrdId')!=state.get('client_id'):return
  event=dict(symbol=o['symbol'],direction=o['direction'],posId=o.get('posId'),entry_ms=o['entry_ms'],
   client_id=state['client_id'],filled=str(filled),before=str(before),fraction=str(filled/before),
   pnl=order.get('pnl'),fee=order.get('fee'),fee_ccy=order.get('feeCcy'),reason=state.get('reason'),
   end_ms=int(order.get('uTime') or state['started_ms']),order_state=order['state'])
  with LOCK:
   path=Path(root)/'phone_partial_evidence.json'
   data=json.loads(path.read_text()) if path.exists() else {}
   if data.get(event['client_id'])==event:return
   data[event['client_id']]=event
   data=dict(sorted(data.items(),key=lambda x:x[1]['end_ms'])[-2000:])
   tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False));tmp.replace(path)
 except Exception:pass

def install(source):
 import okx_partial as partial
 if getattr(partial,'_phone_exit_details',False):return
 path=Path(source)/'okx_partial.py'
 pins=json.loads(Path(__file__).with_name('phone_sources.json').read_text())['files']
 if hashlib.sha256(path.read_bytes()).hexdigest()!=pins[path.name]:raise ValueError('Partial source mismatch')
 fn=partial.PartialExits.reconcile_partial
 raw=textwrap.dedent(inspect.getsource(fn))
 anchor="filled=dec(order.get('accFillSz') or 0); remaining=dec(state['before'])-filled"
 if raw.count(anchor)!=1:raise ValueError('Partial evidence anchor mismatch')
 raw=raw.replace(anchor,"_phone_record_partial(self.root,o,state,order)\n    "+anchor)
 ns=dict(fn.__globals__,_phone_record_partial=record_partial)
 exec(compile(raw,str(path),'exec'),ns)
 partial.PartialExits.reconcile_partial=ns['reconcile_partial'];partial._phone_exit_details=True

def read_json(p,default):
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return default

def same(raw,event):
 try:
  return bool(raw.get('posId') and event.get('posId') and str(raw['posId'])==str(event['posId'])
   and raw['instId']==event.get('symbol') and (raw.get('direction') or raw.get('posSide'))==event.get('direction')
   and abs(int(raw['cTime'])-int(event.get('entry_ms',0)))<=120000)
 except (ValueError,TypeError,KeyError):return False

def enrich(root,data):
 from okx_position_history import key
 root=Path(root);cache=read_json(root/'position_history_cache.json',{})
 raw_by_key={hashlib.sha256(key(v).encode()).hexdigest()[:20]:v for v in cache.values() if isinstance(v,dict)}
 settled=[]
 try:
  for line in (root/'position_results.jsonl').read_text().splitlines():
   try:settled.append(json.loads(line))
   except ValueError:pass
 except OSError:pass
 evidence=read_json(root/'phone_partial_evidence.json',{})
 for row in data.get('rows',[]):
  raw=raw_by_key.get(row['key'],{});end=int(raw.get('uTime') or 0)
  matches=[s for s in settled if isinstance(s,dict) and same(raw,s) and abs(int(s.get('end_ms',0))-end)<=120000]
  # Never infer an exit cause from the sign of PnL.
  row['exit_reason_detail']=str(matches[0].get('reason') or '청산 사유 기록 없음') if len(matches)==1 else '청산 사유 확인 불가 · 연결된 기록 없음 또는 중복'
  if row.get('source')=='manual' and len(matches)!=1:row['exit_reason_detail']='수동 포지션 · 상세 청산 사유 기록 없음'
  parts=sorted((v for v in evidence.values() if isinstance(v,dict) and same(raw,v) and int(raw.get('cTime') or 0)<=int(v.get('end_ms',0))<=end),key=lambda v:v['end_ms'])
  row['partial_details']=[]
  for v in parts:
   pnl=number(v.get('pnl'));fraction=number(v.get('fraction'))
   label='1차 절반청산' if fraction is not None and Decimal('.49')<=fraction<=Decimal('.51') else '부분청산'
   row['partial_details'].append(dict(label=label,pnl=str(pnl) if pnl is not None else None,fee=v.get('fee'),fee_ccy=v.get('fee_ccy'),reason=v.get('reason') or '사유 기록 없음',fraction=v.get('fraction')))
  row['partial_note']='부분청산 기록 없음 · 과거 절반청산 여부/금액 확인 불가' if not parts else '부분손익은 체결 손익(수수료·펀딩 제외). 위 총손익은 포지션 최종 순손익입니다.'
 return data
