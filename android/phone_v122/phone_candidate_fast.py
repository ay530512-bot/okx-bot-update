"""Candidate-only lazy auxiliary analysis, uncached original closed-bar validation.
No quote, signal expiry, admission, position protection or order is cached.
"""
import ast
import functools
import hashlib
import inspect
from pathlib import Path
import threading
from types import FunctionType


def install(channel, cache, pins):
    path = Path(inspect.getsourcefile(channel))
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pins['files'][path.name]:
        raise ValueError('candidate fast path source hash mismatch')
    original_packet, original_candidate, original_closed = channel.packet, channel.candidate, channel.closed
    state = threading.local()
    tree = ast.parse(raw)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'packet')
    matches = [i for i,n in enumerate(node.body) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0]) == '(v, or_status)']
    if len(matches) != 1:
        raise ValueError('candidate select anchor mismatch')
    node.body.insert(matches[0]+1, ast.parse("if not v:\n return dict(entry_setups=[], or_status=or_status)").body[0])
    unit = ast.Module(body=[node],type_ignores=[]); ast.fix_missing_locations(unit)
    ns = {}; exec(compile(unit, str(path)+'<candidate-fast>', 'exec'), ns)
    fast = FunctionType(ns['packet'].__code__, channel.__dict__, 'packet', original_packet.__defaults__)
    def enabled():
        return getattr(state,'candidate',False) and getattr(cache.timer.local,'group',None)=='optimized'
    @functools.wraps(original_candidate)
    def candidate(*args, **kwargs):
        previous = getattr(state,'candidate',False); state.candidate=True
        try:return original_candidate(*args, **kwargs)
        finally:state.candidate=previous
    @functools.wraps(original_packet)
    def packet(*args, **kwargs):
        with cache.timer.scope('signal.packet_body'):
            return (fast if enabled() else original_packet)(*args, **kwargs)
    @functools.wraps(original_closed)
    def closed(b,now,step=900000,required=22):
        # Returning a deep-copied full candle array cost more than validation
        # on the deployed phone. Always validate original input, including the
        # exact current cutoff, without serializing/copying a candle cache.
        with cache.timer.scope('signal.closed_validation.compute'):
            return original_closed(b,now,step,required)
    channel.candidate=candidate;channel.packet=packet;channel.closed=closed
