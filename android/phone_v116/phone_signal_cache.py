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
    def __init__(self, timer, capacity=4096, max_bytes=32*1024*1024):
        self.timer=timer;self.capacity=capacity;self.data=OrderedDict()
        self.lock=threading.Lock();self.local=threading.local()
        self.hits=0;self.misses=0;self.bypasses=0
        self.pool={};self.evictions=0;self.replacements=0
        self.max_bytes=max_bytes;self.key_bytes=0;self.serializations=0;self.shared_inputs=0

    @contextmanager
    def packet_scope(self, symbol=None):
        old=self.local.__dict__.copy()
        self.local.active=True;self.local.inputs={};self.local.symbol=symbol;self.local.calls={}
        try:yield
        finally:
            self.local.__dict__.clear();self.local.__dict__.update(old)

    def release(self, entry):
        for blob in entry[0]+(entry[1],):
            canonical,refs=self.pool[blob]
            if refs==1:
                self.key_bytes-=len(canonical);del self.pool[blob]
            else:self.pool[blob]=(canonical,refs-1)

    def intern(self, blob):
        canonical,refs=self.pool.get(blob,(blob,0))
        if not refs:self.key_bytes+=len(blob)
        self.pool[canonical]=(canonical,refs+1)
        return canonical

    def wrap(self, fn, label):
        @functools.wraps(fn)
        def cached(*args,**kwargs):
            # Final admission and protection calls are outside packet_scope.
            if not getattr(self.local,'active',False) or getattr(self.timer.local,'group',None)!='optimized':
                with self.lock:self.bypasses+=1
                with self.timer.scope(label+'.compute'):return fn(*args,**kwargs)
            with self.timer.scope(label+'.key'):
                # Share serialization of the same bars/config only within this
                # synchronous packet. Never retain identity-based validity across packets.
                def encoded(value):
                    inputs=self.local.inputs;identity=id(value)
                    if identity in inputs and inputs[identity][0] is value:
                        with self.lock:self.shared_inputs+=1
                        return inputs[identity][1]
                    blob=pickle.dumps(value,protocol=5)
                    inputs[identity]=(value,blob)
                    with self.lock:self.serializations+=1
                    return blob
                parts=tuple(encoded(value) for value in args)
                named=encoded(kwargs) if kwargs else b''
                # Exact byte equality also validates hash collisions; no large
                # hashlib call that can release the GIL into the busy WS thread.
                symbol=self.local.symbol
                index=self.local.calls.get(label,0);self.local.calls[label]=index+1
                # One latest generation per symbol/function/frame slot. Exact
                # complete input comparison validates every reuse, not just time.
                key=(symbol,label,index) if symbol is not None else (label,parts,named)
                size=sum(map(len,set(parts+(named,))))
            with self.lock:
                entry=self.data.get(key)
                hit=entry is not None and entry[:2]==(parts,named)
                if hit:
                    self.data.move_to_end(key);self.hits+=1;value=entry[2]
                else:self.misses+=1
            if hit:
                with self.timer.scope(label+'.reuse'):return copy.deepcopy(value)
            frozen_args=tuple(pickle.loads(blob) for blob in parts)
            frozen_kwargs=pickle.loads(named) if named else {}
            with self.timer.scope(label+'.compute'):value=fn(*frozen_args,**frozen_kwargs)
            saved=copy.deepcopy(value)
            with self.lock:
                if key in self.data:
                    self.release(self.data.pop(key));self.replacements+=1
                if size<=self.max_bytes:
                    canonical=tuple(self.intern(blob) for blob in parts)
                    self.data[key]=(canonical,self.intern(named),saved)
                    while len(self.data)>self.capacity or self.key_bytes>self.max_bytes:
                        _,old=self.data.popitem(last=False);self.release(old);self.evictions+=1
            return value
        return cached

    def report(self):
        with self.lock:return dict(version='phone-signal-cache-3',hits=self.hits,misses=self.misses,
            bypasses=self.bypasses,entries=len(self.data),capacity=self.capacity,key_bytes=self.key_bytes,max_key_bytes=self.max_bytes,
            serializations=self.serializations,shared_inputs=self.shared_inputs,evictions=self.evictions,replacements=self.replacements,unique_inputs=len(self.pool))


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
            with cache.packet_scope((args[0] if args else kwargs['row']).get('symbol')):return original(*args,**kwargs)
    channel.packet=packet
    return cache
