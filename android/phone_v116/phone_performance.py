"""Bounded timing and conservative empty-slot read elimination. No new API calls."""
import ast
import sys
from contextlib import contextmanager
from collections import deque
import functools
import hashlib
import inspect
import json
from pathlib import Path
import threading
import time
import textwrap

VERSION='phone-performance-4'

class Timing:
    def __init__(self, root, clock=time.perf_counter):
        self.root=Path(root);self.clock=clock;self.lock=threading.Lock();self.local=threading.local()
        self.exceptions=deque(maxlen=40);self.admission_exceptions=deque(maxlen=40);self.exception_counts={}
        self.metrics={};self.baseline_done=0;self.skipped=0;self.recent=deque(maxlen=30)
        self.summary_cache={};self.started=time.time();self.observer_errors=0;self.optimization_enabled=False

    @contextmanager
    def scope(self,label):
        stack=getattr(self.local,'stack',None)
        if stack is None:stack=[];self.local.stack=stack
        item=[self.clock(),0.0];stack.append(item);failed=False
        try:yield
        except BaseException as error:
            failed=True
            if label in ('signal.packet','entry.admission_and_order'):
                try:self.record_exception(label,error)
                except Exception:self.observer_errors+=1
            raise
        finally:
            elapsed=max(0,self.clock()-item[0]);stack.pop()
            if stack:stack[-1][1]+=elapsed
            group=getattr(self.local,'group','background')
            try:
                with self.lock:
                    key=(group,label)
                    if key not in self.metrics and len(self.metrics)>=160:pass
                    else:
                        row=self.metrics.setdefault(key,dict(calls=0,errors=0,total_s=0.,self_s=0.,max_s=0.,last_s=0.))
                        row['calls']+=1;row['errors']+=int(failed);row['total_s']+=elapsed
                        row['self_s']+=max(0,elapsed-item[1]);row['max_s']=max(row['max_s'],elapsed);row['last_s']=elapsed
            except Exception:self.observer_errors+=1

    def record_exception(self,label,error):
        # Only approved static categories and source location; never raw API
        # responses, credentials, account IDs or arbitrary exception messages.
        categories=(('규칙 최신 완료봉 대기','latest_closed_candle_wait'),
            ('규칙 완료봉 자료 부족','insufficient_closed_candles'),
            ('규칙 봉 수치 오류','invalid_candle_values'),
            ('규칙 봉 연속성 오류','candle_gap'),
            ('시장가 실제 체결가 기준 포지션 예상 손실 한도 초과','postfill_risk_limit'),
            ('신호 만료','signal_expired'),('최소 주문','minimum_order'),
            ('잔고','balance_check'),('스프레드','spread_check'),
            ('슬리피지','slippage_check'),('손실 한도','risk_limit'))
        message=str(error)
        category=next((code for text,code in categories if text in message),'unclassified')
        tb=error.__traceback__
        while tb and tb.tb_next:tb=tb.tb_next
        where=(Path(tb.tb_frame.f_code.co_filename).name+':'+str(tb.tb_lineno)+':'+tb.tb_frame.f_code.co_name) if tb else ''
        with self.lock:
            item=dict(at=time.time(),stage=label,type=type(error).__name__,category=category,location=where)
            self.exceptions.append(item)
            if label=='entry.admission_and_order':self.admission_exceptions.append(item)
            key=label+':'+category
            row=self.exception_counts.setdefault(key,dict(count=0,first_at=item['at'],last_at=item['at']))
            row['count']+=1;row['last_at']=item['at']

    def wrap(self,fn,label):
        @functools.wraps(fn)
        def timed(*a,**kw):
            with self.scope(label):return fn(*a,**kw)
        return timed

    def skip_empty(self,engine,slot):
        # Keep every original snapshot while paused/recovering and keep the last
        # slot's snapshot even when empty. Never cache account data or skip an
        # owned slot. Initial account check and entry's final checks remain.
        skip=(getattr(self.local,'group',None)=='optimized' and not engine.recovering
              and engine.enabled and not engine.user_paused
              and not engine.journal.data['owned'] and slot<engine.slot_count()-1)
        if skip:
            with self.lock:self.skipped+=1
        return skip

    def tick(self,engine,fn):
        eligible=bool(engine.enabled and not engine.user_paused and not engine.recovering)
        mode=('optimized' if self.baseline_done>=5 and self.optimization_enabled else 'baseline') if eligible else 'safety_or_paused'
        previous=getattr(self.local,'group','background');self.local.group=mode
        before=self.clock();failed=False
        try:
            with self.scope('engine.tick'):return fn()
        except BaseException:
            failed=True;raise
        finally:
            duration=self.clock()-before;self.local.group=previous
            with self.lock:
                if eligible and mode=='baseline' and not failed:self.baseline_done+=1
                self.recent.append(dict(at=time.time(),mode=mode,seconds=round(duration,6),error=failed))

    def report(self):
        with self.lock:
            return dict(version=VERSION,observed_at=time.time(),started_at=self.started,
                signal_cache=self.signal_cache.report() if hasattr(self,'signal_cache') else None,
                baseline_completed=self.baseline_done,optimization_enabled=self.optimization_enabled,
                skipped_empty_slot_snapshots=self.skipped,observer_errors=self.observer_errors,
                metrics=[dict(group=g,label=l,**{k:round(v,6) if isinstance(v,float) else v for k,v in row.items()}) for (g,l),row in sorted(self.metrics.items())],
                recent_ticks=list(self.recent),recent_exceptions=list(self.exceptions),
                recent_admission_exceptions=list(self.admission_exceptions),exception_counts={k:dict(v) for k,v in self.exception_counts.items()},
                limitations=['Inclusive times overlap; use self_s for measured exclusive time.',
                'Baseline and optimized windows have different live workloads; not a controlled PC comparison.',
                'HTTP time includes network/server wait; self time is not pure CPU.',
                'Only intermediate empty-slot reads are removed; protection/rate limits/final admission checks remain.'])

    def start_writer(self,stop):
        def run():
            from phone_account import save_json
            while not stop.is_set():
                try:
                    report=self.report()
                    totals={x['group']:x for x in report['metrics'] if x['label']=='engine.tick'}
                    self.summary_cache=dict(baseline_completed=report['baseline_completed'],skipped=report['skipped_empty_slot_snapshots'],ticks={k:dict(calls=v['calls'],mean_s=round(v['total_s']/v['calls'],3),max_s=v['max_s']) for k,v in totals.items()})
                    save_json(self.root/'phone_performance.json',report)
                except Exception:self.observer_errors+=1
                stop.wait(5)
        threading.Thread(target=run,name='phone-performance-writer',daemon=True).start()


def patch_tick(cls, expected_hash):
    source_file=Path(inspect.getsourcefile(cls))
    if hashlib.sha256(source_file.read_bytes()).hexdigest()!=expected_hash:
        raise ValueError('속도 개선 대상 원본 해시 불일치')
    text=textwrap.dedent(inspect.getsource(cls.tick))
    old="                snap=self.snapshot(); o=self.journal.data['owned']"
    # dedent removes the class indentation; use AST rather than whitespace.
    tree=ast.parse(text);found=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.For) and isinstance(node.target,ast.Name) and node.target.id=='slot':
            for sub in ast.walk(node):
                if isinstance(sub,ast.Try) and sub.body and isinstance(sub.body[0],ast.Assign):
                    first=sub.body[0]
                    if ast.unparse(first)== 'snap = self.snapshot()':found.append(sub)
    if len(found)!=1:raise ValueError('빈 슬롯 조회 구간 불일치')
    guard=ast.parse('if self._phone_perf.skip_empty(self, slot):\n    continue').body[0]
    found[0].body.insert(0,guard);ast.fix_missing_locations(tree)
    ns={};exec(compile(tree,str(source_file)+'<phone-performance>','exec'),cls.tick.__globals__,ns)
    cls.tick=ns['tick']


def install_before_engine(root):
    from okx_v5 import RuleEngine
    from okx_core import OKX
    if getattr(RuleEngine,'_phone_perf_installed',False):raise ValueError('성능 계측 중복 설치')
    pins=json.loads(Path(__file__).with_name('phone_sources.json').read_text())
    timer=Timing(root)
    from phone_signal_cache import install
    install(timer,pins)
    patch_tick(RuleEngine,pins['files']['okx_v5.py']);timer.optimization_enabled=True
    RuleEngine._phone_perf_installed=True
    old_init=OKX.__init__;old_request=OKX.request
    def init(api,*a,**kw):
        old_init(api,*a,**kw)
        api.session.request=timer.wrap(api.session.request,'api.http_roundtrip')
    @functools.wraps(old_request)
    def request(api,method,path,*a,**kw):
        endpoint=path.split('?')[0]
        label=('api.'+method+' '+endpoint) if endpoint.startswith('/api/v5/') and len(endpoint)<90 else 'api.other'
        with timer.scope(label):return old_request(api,method,path,*a,**kw)
    OKX.__init__=init;OKX.request=request
    import okx_read_control
    okx_read_control.before_read=timer.wrap(okx_read_control.before_read,'wait.private_read_pacing')
    from okx_candle_gate732 import CANDLE_READ_GATE
    CANDLE_READ_GATE.acquire=timer.wrap(CANDLE_READ_GATE.acquire,'wait.candle_rate_gate')
    return timer


def attach(engine,timer):
    engine._phone_perf=timer
    for name,label in {'snapshot':'account.snapshot','refresh_day':'account.daily_cashflows',
        'reconcile':'protection.reconcile','verify_protection':'protection.verify_sl',
        'chart_job':'protection.chart_job','trail':'protection.trail','close':'protection.close',
        'partial_close':'protection.partial_close','guard_once':'protection.fast_guard',
        'algos':'account.conditional_orders','candidate_decision':'entry.signal_evaluation',
        'entry':'entry.admission_and_order','settle':'account.settle','publish_portfolio':'ui.publish'}.items():
        if hasattr(engine,name):setattr(engine,name,timer.wrap(getattr(engine,name),label))
    engine.universe.scan=timer.wrap(engine.universe.scan,'scan.universe')
    if getattr(engine.universe,'full_market',None):
        market=engine.universe.full_market
        market.bars=timer.wrap(market.bars,'scan.candle_fetch_or_cache')
    original=engine.tick
    engine.tick=lambda:timer.tick(engine,original)
    timer.start_writer(engine.stop_event)

if __name__=='__main__':
    p=Path.home()/'okx-phone/phone_performance.json'
    d=json.loads(p.read_text());d['record_age_s']=round(time.time()-d['observed_at'],1)
    if '--brief' in sys.argv:
        wanted={'engine.tick','entry.signal_evaluation','entry.admission_and_order','signal.packet'}
        d['metrics']=[dict(row,mean_s=round(row['total_s']/max(1,row['calls']),6)) for row in d['metrics'] if row['label'] in wanted]
        d.pop('recent_exceptions',None)
    else:d['metrics']=sorted(d['metrics'],key=lambda x:x['total_s'],reverse=True)[:45]
    print(json.dumps(d,ensure_ascii=False,indent=2))
