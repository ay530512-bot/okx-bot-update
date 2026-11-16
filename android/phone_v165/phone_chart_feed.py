"""Small REST candle refreshes; analysis has an independent read-only worker."""
import ast
import copy
import hashlib
import inspect
import threading
import time
from pathlib import Path
from types import FunctionType


def factory(source):
    import okx_position_chart as chart
    import json
    pins=json.loads(Path(__file__).with_name('phone_sources.json').read_text())['files']
    path=Path(inspect.getsourcefile(chart))
    if path.resolve().parent != Path(source).resolve() or hashlib.sha256(path.read_bytes()).hexdigest()!=pins[path.name]:
        raise ValueError('차트 원본 검증 실패')
    tree=ast.parse(path.read_text())
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ChartFeed')
    run=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    blocks=[n for n in ast.walk(run) if isinstance(n,ast.If) and ast.unparse(n.test)=='not older']
    if len(blocks)!=1:raise ValueError('차트 분석 분리 기준 불일치')
    block=blocks[0]
    analysis=ast.parse('def _analyze(self, api, symbol, frame, bars, now):\n pass').body[0]
    analysis.body=copy.deepcopy(block.body)
    block.body=ast.parse('self.schedule_analysis(symbol,frame,bars,now,rev)').body
    # With analysis moved off this worker, the early and final chart events
    # contain the same candles. Publish once: avoid cleaning/copying 300+ bars
    # twice every second while retaining the original success/error event.
    removed=0
    for parent in ast.walk(run):
        body=getattr(parent,'body',None)
        if not isinstance(body,list):continue
        for index,item in enumerate(body):
            if (isinstance(item,ast.Assign) and len(item.targets)==1
                    and isinstance(item.targets[0],ast.Name) and item.targets[0].id=='early'):
                following=body[index+1]
                if not isinstance(following,ast.With) or "('position_chart', early)" not in ast.unparse(following):
                    raise ValueError('차트 중복 게시 기준 불일치')
                del body[index:index+2];removed+=1;break
    if removed!=1:raise ValueError('차트 중복 게시 개수 불일치')
    class SmallerRefresh(ast.NodeTransformer):
        count=0
        def visit_Call(self,n):
            self.generic_visit(n)
            if (isinstance(n.func,ast.Attribute) and n.func.attr=='public'
                    and n.args and isinstance(n.args[0],ast.Constant)
                    and n.args[0].value=='/api/v5/market/candles'):
                for kw in n.keywords:
                    if kw.arg=='limit':
                        kw.value=ast.parse('self.candle_limit(key,api.now_ms())',mode='eval').body
                        self.count+=1
            return n
    transform=SmallerRefresh();run=transform.visit(run)
    if transform.count!=1:raise ValueError('차트 봉 조회 기준 불일치')
    namespace={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[run,analysis],type_ignores=[])),
                 str(path)+'<phone-live-chart>','exec'),namespace)
    fast_run=FunctionType(namespace['run'].__code__,chart.__dict__,'run')
    analyze=FunctionType(namespace['_analyze'].__code__,chart.__dict__,'_analyze')

    class FastChartFeed(chart.ChartFeed):
        run=fast_run
        _analyze=analyze

        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.analysis_job=None;self.analysis_thread=None;self.analysis_key=None;self.analysis_at=-float('inf')

        def start(self):
            if not self.analysis_thread:
                self.analysis_thread=threading.Thread(target=self.analysis_loop,daemon=True,name='phone-chart-analysis')
                self.analysis_thread.start()
            super().start()

        def candle_limit(self,key,now):
            bars=self.cache.get(key,[])
            step=chart.STEPS[key[1]]
            return '2' if bars and 0<=now-bars[-1][0]<2*step else '300'

        def schedule_analysis(self,symbol,frame,bars,now,rev):
            # Coalesce selected-symbol analysis, never queue a backlog.
            with self.condition:
                if self.closed or rev!=self.revision:return
                key=(symbol,rev,now//900000)
                if key==self.analysis_key and time.monotonic()-self.analysis_at<5:return
                self.analysis_key=key;self.analysis_at=time.monotonic()
                self.analysis_job=(symbol,frame,bars,now,rev)
                self.condition.notify_all()

        def analysis_loop(self):
            api=None
            try:
                while True:
                    with self.condition:
                        while self.analysis_job is None and not self.closed:self.condition.wait(1)
                        if self.closed:return
                        symbol,frame,bars,now,rev=self.analysis_job;self.analysis_job=None
                    try:
                        if api is None:
                            from okx_core import OKX
                            api=(self.factory or OKX)(self.settings)
                        self._analyze(api,symbol,frame,bars,now)
                    except Exception:
                        # Analysis gates remain unavailable/stale; chart continues.
                        pass
            finally:
                if api:api.session.close()

    return FastChartFeed
