"""Exact-input memoization of pure indicators inside candidate packet only.

No packet, time-sensitive verdict, market quote, API response or order is cached.
Keys cover full inputs (including historical corrections and configuration).
Cached results are copied because the caller adds evidence to pattern objects.
"""
from collections import OrderedDict
from contextlib import contextmanager
import copy
import functools
import hashlib
import inspect
from pathlib import Path
import pickle
import threading


class SignalCache:
    def __init__(self, timer, capacity=4096):
        self.timer=timer;self.capacity=capacity;self.data=OrderedDict()
        self.lock=threading.Lock();self.local=threading.local()
        self.hits=0;self.misses=0;self.bypasses=0

    @contextmanager
    def packet_scope(self):
        old=getattr(self.local,'active',False);self.local.active=True
        try:yield
        finally:self.local.active=old

    def wrap(self, fn, label):
        @functools.wraps(fn)
        def cached(*args,**kwargs):
            # Final admission and protection calls are outside packet_scope.
            if not getattr(self.local,'active',False) or getattr(self.timer.local,'group',None)!='optimized':
                with self.lock:self.bypasses+=1
                with self.timer.scope(label+'.compute'):return fn(*args,**kwargs)
            with self.timer.scope(label+'.key'):
                payload=pickle.dumps((args,kwargs),protocol=5)
                key=(label,hashlib.sha256(payload).digest())
            with self.lock:
                if key in self.data:
                    value=self.data.pop(key);self.data[key]=value;self.hits+=1
                    hit=True
                else:self.misses+=1;hit=False
            if hit:
                with self.timer.scope(label+'.reuse'):return copy.deepcopy(value)
            # Exceptions are never cached; original function executes unchanged.
            frozen_args,frozen_kwargs=pickle.loads(payload)
            with self.timer.scope(label+'.compute'):value=fn(*frozen_args,**frozen_kwargs)
            saved=copy.deepcopy(value)
            with self.lock:
                self.data[key]=saved
                while len(self.data)>self.capacity:self.data.popitem(last=False)
            return value
        return cached

    def report(self):
        with self.lock:return dict(version='phone-signal-cache-1',hits=self.hits,misses=self.misses,
            bypasses=self.bypasses,entries=len(self.data),capacity=self.capacity)


def install(timer,pins):
    import okx_channel701 as channel
    import okx_two_wick732 as patterns
    import okx_band_flow as indicators
    import okx_pattern15 as analysis
    modules=(channel,patterns,indicators,analysis)
    for module in modules:
        path=Path(inspect.getsourcefile(module))
        if hashlib.sha256(path.read_bytes()).hexdigest()!=pins['files'][path.name]:
            raise ValueError('신호 계산 대상 원본 해시 불일치')
    cache=SignalCache(timer);timer.signal_cache=cache
    for module,name,label in ((patterns,'select','signal.pattern'),(indicators,'view','signal.indicators'),(analysis,'summary','signal.trend')):
        setattr(module,name,cache.wrap(getattr(module,name),label))
    original=channel.packet
    @functools.wraps(original)
    def packet(*args,**kwargs):
        with timer.scope('signal.packet'):
            with cache.packet_scope():return original(*args,**kwargs)
    channel.packet=packet
    return cache
