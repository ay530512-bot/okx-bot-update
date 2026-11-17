"""Pure rejection explanations and bounded background history; no API/orders."""
import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import time
from types import FunctionType

DATA_REASONS = {'완료15분봉241개 대기', '봉 데이터 오류', '15분봉 누락',
                '최신 완료1시간봉 대기', '1시간봉 누락', '1시간봉 데이터 오류'}
WICK_LABELS = ['15분봉55개 부족', 'ATR 유효성 미충족', '봉 가격범위 미충족',
               '두 꼬리 모양·고저점·확인종가 미충족', '최신 완료1시간봉 대기',
               '1시간봉 누락', '1시간 추세·효율·MA50 방향 미충족',
               'MA50 거리 또는 확인봉 거래량 미충족']


def make_selector(pins):
    import okx_two_wick732 as wick
    from okx_entry725 import analyze
    from okx_entry724 import efficiency
    from okx_entry722 import hourly_from_15m
    path = Path(inspect.getsourcefile(wick))
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pins['files'][path.name]:
        raise ValueError('diagnostic wick source hash mismatch')
    node = next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'setup')
    returns = sorted((n for n in ast.walk(node) if isinstance(n, ast.Return)), key=lambda n:n.lineno)
    assert len(returns) == 9 and all(isinstance(n.value,ast.Constant) and n.value.value is None for n in returns[:-1])
    # Only pair each original return value with a label. No predicate changes.
    for n,label in zip(returns, WICK_LABELS+['조건 통과']):
        n.value=ast.Tuple(elts=[n.value,ast.Constant(label)],ctx=ast.Load())
    module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
    ns={};exec(compile(module,str(path)+'<diagnostic131>','exec'),ns)
    explained_wick=FunctionType(ns['setup'].__code__,wick.__dict__,'setup',(None,))

    def select(b,hourly=None):
        result=analyze(b,hourly,variant='mild726')
        base=max(result['setups'],key=lambda v:v['lookback721']) if result['setups'] else None
        second,wick_reason=explained_wick(b,hourly)
        chosen,status=wick.combine(base,second)
        reason=result['reason'];data=reason if reason in DATA_REASONS else None
        end=b[-1][0]+900000 if b else 0
        h=hourly_from_15m(b) if hourly is None else [r for r in hourly if r[0]+3600000<=end]
        branch=None if data else ('trend_pullback' if efficiency([r[4] for r in h])>=.30 else 'confirmed_reversal')
        routes={}
        for name in ('trend_pullback','confirmed_reversal'):
            routes[name] = dict(status='data_wait' if data else 'inactive' if branch!=name else 'pass' if base else 'wait',
                reason=data or ('시간봉 상태에 따라 다른 기존 경로 선택' if branch!=name else reason))
        routes['double_wick']=dict(status='pass' if second else 'data_wait' if wick_reason in DATA_REASONS or wick_reason=='15분봉55개 부족' else 'wait',reason=wick_reason)
        diagnostic=dict(routes=routes, data_issue=data, or_status=status,
            completed15_count=len(b),completed1h_count=len(h),
            completed15_ms=end,completed1h_ms=h[-1][0]+3600000 if h else None)
        return chosen,status,diagnostic
    return select


def accumulate(d,p,symbol):
    detail=p.get('entry_diagnostic')
    if not detail:return
    routes=d.setdefault('routes',{})
    for name,value in detail['routes'].items():
        item=routes.setdefault(name,dict(pass_count=0,wait_count=0,inactive_count=0,data_wait_count=0,reasons={}))
        item[value['status']+'_count']+=1
        if value['status']!='pass':
            reason=value['reason'];item['reasons'][reason]=item['reasons'].get(reason,0)+1
    if len(d.setdefault('examples',[]))<3:
        d['examples'].append(dict(symbol=symbol,**detail))


class History:
    """Called by the existing performance writer, never by the order thread.

    Samples are at most one per minute, plus a bounded latest-observation tail.
    These are observations, not unique trading signals or proof of fills.
    """
    def __init__(self,root):
        self.root=Path(root);self.last=0;self.errors=0
        self.run_id=str(os.getpid())+'-'+str(time.time_ns())
        self.last_result=None

    def observe(self,health,report):
        now=time.time()
        if now-self.last<60:return
        self.last=now
        target=self.root/'phone_entry_history.jsonl'
        backup=self.root/'phone_entry_history.previous.jsonl'
        try:
            if target.is_symlink() or backup.is_symlink():raise ValueError('history link')
            if target.exists() and target.stat().st_size>2*1024*1024:
                os.replace(target,backup)
            admission=[dict(group=x['group'],calls=x['calls'],errors=x['errors'])
                       for x in report.get('metrics',[]) if x['label']=='entry.admission_and_order']
            row=dict(version='phone-entry-history-1',run_id=self.run_id,observed_at=now,
                     health=health,admission=admission)
            with target.open('a',encoding='utf-8') as f:
                os.chmod(target,0o600)
                f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
            self.last_result=now
        except Exception:self.errors+=1
