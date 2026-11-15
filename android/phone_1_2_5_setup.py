#!/usr/bin/env python3
"""Verified 1.2.4 -> 1.2.5 CPU overhead reduction. Stage then safe serial handover. No exchange orders here."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


PINNED = {'phone_host.py': '21b9139454ff32c6afc7a4f0c9dece4540cc4cc9eb1d2a619c8e895f2b8afdce', 'phone_mobile.py': 'b3f592c0409f89fa3c6012d0398b18057bc752b6c9202164e822f3c18b2247c0', 'phone_account.py': '3c4c9f9cccaeaa60a41cc3ff3fdde68c04372aabcd8861098cefb8d918406f81', 'phone_sources.json': '1e8a54e5baff2e9f77aa48e1335dea650ae74cc1e5ebfaf562d796960d0838c7', 'phone_remote.py': 'f891e8cc8c8e822eb7f75ccd22d441b4b451162de0bf87a134b3c925e9073e97', 'phone_service.py': '4d724640164f56179b55fabea5966597f5cafb227a2822a10900626cb389229b', 'phone_migrate.py': 'aafbe024259d3f4dffc81b9b4ec7c9e9307a3487efeb969b1feed257f66399fb', 'phone_migration_sources.json': '214293c5bf0d7fd79838b1037ab9499a2a5428c91758fe3df7c439d790e3691d', 'phone_remote_check.py': '7d20cb6dcbbd2d784dab6c9fd8131722175d2f684b2202c3499fc13e8fd194d1', 'phone_clock.py': 'c1465b5e7d796937e16897c28d29d6ea78d4523b1c3a235a3384a97c2af7074c', 'phone_connection_trace.py': '6beaf1d2bad2f0043a50c16c309cbd200dc4692c0686cab00cc519900249face', 'phone_public_ws.py': '81e7a423c4a62081e25dbc7a30271d067fd09c84286311967fe4b6239b5b4582', 'phone_performance.py': '6247cb8f03e118de3ca0420c197a7c3ef61297280f21847e7f4fca78b9c632db', 'phone_signal_cache.py': '071eb2defa234b3055d439ab775e8c9ec0384b8f36b8d0464d241ac442d94827', 'phone_update.py': '1df69733a33681f7bc8fb3eda33c107363150d1e7d195f89f94929da1fc98a53', 'phone_update_ui.js': '838a19ed49161f58c0456cb23437a2c3e0ee3981c1a5796dcb1aeecd7046dc32', 'phone_button_upgrade.py': '98c22dab1672174f9bd3553fe965e0e58aa8ee9ae9d9c6070c7d3548500a5cc8', 'phone_button_old_sources.json': '3748b6026e54757db0ac2c586313fc816d76a790df78a99babd97782c52b9544', 'phone_handover.py': '11d26680baa581043998005af8b2016a40a4df1eff7730d9d34b10706c89523c', 'phone_pullback_size.py': '556c076220d5af838cd6082a224388f1ac23869fd7f0c479a220d2f381887f41', 'phone_candidate_fast.py': 'a13ca10ee3884abdff60e230bd3a250ff29d6204e683865e2b12047245b628d6', 'phone_runtime_health.py': '4177c24e5da1806dd0ebc9afcfb13629562474e763c8a97cfe40af608905a38e'}
HOST_OLD = 'host-v22'
HOST_NEW = 'host-v23'
MODULES = {'phone_frozen_bars.py': '"""Immutable published candle inputs. No clocks, quotes or order verdicts cached."""\nimport copy\nimport functools\nimport hashlib\nimport inspect\nimport pickle\nimport math\n\n\nclass FrozenBars(tuple):\n    def __new__(cls, rows):\n        # Copy every nested row, preserving numeric types and exact values.\n        values = tuple(tuple(row) for row in rows)\n        if any(type(x) not in (int, float) or not math.isfinite(x)\n               for row in values for x in row):\n            raise ValueError(\'unsupported immutable candle input\')\n        result = tuple.__new__(cls, values)\n        object.__setattr__(result, \'_encoded\', pickle.dumps(result.thaw(), protocol=5))\n        object.__setattr__(result, \'_aligned15\', all(row and type(row[0]) is int\n                                                  and row[0] % 900000 == 0 for row in values))\n        return result\n\n    def __setattr__(self, name, value):\n        raise TypeError(\'immutable candle snapshot\')\n\n    def __delattr__(self, name):\n        raise TypeError(\'immutable candle snapshot\')\n\n    def thaw(self):\n        return [list(row) for row in self]\n\n    def __deepcopy__(self, memo):\n        # Legacy chart/candidate consumers expect an editable independent list.\n        value = self.thaw()\n        memo[id(self)] = value\n        return value\n\n    def __reduce__(self):\n        return (list, (self.thaw(),))\n\n\ndef freeze(rows):\n    if type(rows) is FrozenBars:\n        return rows\n    if type(rows) not in (list, tuple) or any(type(row) not in (list, tuple) for row in rows):\n        return rows\n    try:\n        return FrozenBars(rows)\n    except (ValueError, TypeError, OverflowError):\n        # Invalid/unusual data follows all original validation, without a fast key.\n        return rows\n\n\ndef install(module, pins):\n    path = inspect.getsourcefile(module)\n    with open(path, \'rb\') as source:\n        if hashlib.sha256(source.read()).hexdigest() != pins[\'files\'][\'okx_band_flow.py\']:\n            raise ValueError(\'immutable candle producer source hash mismatch\')\n    original = module.merge_completed\n    if getattr(original, \'_phone_frozen_bars\', False):\n        return\n\n    @functools.wraps(original)\n    def merged(*args, **kwargs):\n        return freeze(original(*args, **kwargs))\n    merged._phone_frozen_bars = True\n    module.merge_completed = merged\n', 'phone_feed_fast.py': '"""Keep every quote and mark callback; avoid rebuilding unchanged OHLC tuples."""\nimport ast\nimport hashlib\nimport inspect\nfrom types import FunctionType\n\n\ndef install(pins):\n    import okx_stream\n    cls = okx_stream.MarketStream\n    if getattr(cls, \'_phone_feed_fast\', False):\n        return\n    path = inspect.getsourcefile(okx_stream)\n    with open(path, \'rb\') as handle:\n        raw = handle.read()\n    if hashlib.sha256(raw).hexdigest() != pins[\'files\'][\'okx_stream.py\']:\n        raise ValueError(\'public feed source hash mismatch\')\n    tree = ast.parse(raw)\n    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == \'MarketStream\')\n    node = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == \'feed\')\n    before = \'self.band_prices[key] = (start, max(previous[1], price), min(previous[2], price), price, self.generation)\'\n    class SkipIdentical(ast.NodeTransformer):\n        count = 0\n        def visit_Assign(self, item):\n            if ast.unparse(item) != before:\n                return item\n            self.count += 1\n            # Prices are finite and positive here; preserve tie selection while\n            # avoiding two Python function calls on every changed-price bar.\n            assign = ast.parse(\'self.band_prices[key] = (start, \'\n                               \'previous[1] if previous[1] >= price else price, \'\n                               \'previous[2] if previous[2] <= price else price, \'\n                               \'price, self.generation)\').body[0]\n            return ast.If(test=ast.parse(\'previous[3] != price\', mode=\'eval\').body,\n                          body=[assign], orelse=[])\n    transform = SkipIdentical()\n    node = transform.visit(node)\n    if transform.count != 1:\n        raise ValueError(\'public feed patch anchor mismatch\')\n    namespace = {}\n    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),\n                 path+\'<phone125>\', \'exec\'), namespace)\n    cls.feed = FunctionType(namespace[\'feed\'].__code__, okx_stream.__dict__, \'feed\')\n    cls._phone_feed_fast = True\n', 'phone_signal_cache.py': '"""Exact-input memoization of pure indicators inside candidate packet only.\n\nNo packet, time-sensitive verdict, market quote, API response or order is cached.\nKeys cover full inputs (including historical corrections and configuration).\nCached results are copied because the caller adds evidence to pattern objects.\n"""\nfrom collections import OrderedDict\nfrom contextlib import contextmanager\nimport copy\nimport functools\nimport hashlib\nimport inspect\nfrom pathlib import Path\nimport pickle\nfrom phone_frozen_bars import FrozenBars\nimport threading\n\n\nclass SignalCache:\n    def __init__(self, timer, capacity=4096, max_bytes=32*1024*1024):\n        self.timer=timer;self.capacity=capacity;self.data=OrderedDict()\n        self.lock=threading.Lock();self.local=threading.local()\n        self.hits=0;self.misses=0;self.bypasses=0\n        self.pool={};self.evictions=0;self.replacements=0\n        self.max_bytes=max_bytes;self.key_bytes=0;self.serializations=0;self.shared_inputs=0;self.frozen_reuses=0\n\n    @contextmanager\n    def packet_scope(self, symbol=None):\n        old=self.local.__dict__.copy()\n        self.local.active=True;self.local.inputs={};self.local.symbol=symbol;self.local.calls={}\n        try:yield\n        finally:\n            self.local.__dict__.clear();self.local.__dict__.update(old)\n\n    def release(self, entry):\n        for blob in entry[0]+(entry[1],):\n            canonical,refs=self.pool[blob]\n            if refs==1:\n                self.key_bytes-=len(canonical);del self.pool[blob]\n            else:self.pool[blob]=(canonical,refs-1)\n\n    def intern(self, blob):\n        canonical,refs=self.pool.get(blob,(blob,0))\n        if not refs:self.key_bytes+=len(blob)\n        self.pool[canonical]=(canonical,refs+1)\n        return canonical\n\n    def wrap(self, fn, label):\n        @functools.wraps(fn)\n        def cached(*args,**kwargs):\n            # Final admission and protection calls are outside packet_scope.\n            if not getattr(self.local,\'active\',False) or getattr(self.timer.local,\'group\',None)!=\'optimized\':\n                with self.lock:self.bypasses+=1\n                with self.timer.scope(label+\'.compute\'):return fn(*args,**kwargs)\n            with self.timer.scope(label+\'.key\'):\n                # Share serialization of the same bars/config only within this\n                # synchronous packet. Never retain identity-based validity across packets.\n                def encoded(value):\n                    inputs=self.local.inputs;identity=id(value)\n                    if identity in inputs and inputs[identity][0] is value:\n                        with self.lock:self.shared_inputs+=1\n                        return inputs[identity][1]\n                    if type(value) is FrozenBars:\n                        blob=value._encoded\n                        with self.lock:self.frozen_reuses+=1\n                    else:\n                        blob=pickle.dumps(value,protocol=5)\n                        with self.lock:self.serializations+=1\n                    inputs[identity]=(value,blob)\n                    return blob\n                parts=tuple(encoded(value) for value in args)\n                named=encoded(kwargs) if kwargs else b\'\'\n                # Exact byte equality also validates hash collisions; no large\n                # hashlib call that can release the GIL into the busy WS thread.\n                symbol=self.local.symbol\n                index=self.local.calls.get(label,0);self.local.calls[label]=index+1\n                # One latest generation per symbol/function/frame slot. Exact\n                # complete input comparison validates every reuse, not just time.\n                key=(symbol,label,index) if symbol is not None else (label,parts,named)\n            with self.lock:\n                entry=self.data.get(key)\n                hit=entry is not None and entry[:2]==(parts,named)\n                if hit:\n                    self.data.move_to_end(key);self.hits+=1;value=entry[2]\n                else:self.misses+=1\n            if hit:\n                with self.timer.scope(label+\'.reuse\'):return copy.deepcopy(value)\n            frozen_args=tuple(pickle.loads(blob) for blob in parts)\n            frozen_kwargs=pickle.loads(named) if named else {}\n            with self.timer.scope(label+\'.compute\'):value=fn(*frozen_args,**frozen_kwargs)\n            saved=copy.deepcopy(value)\n            size=sum(map(len,set(parts+(named,))))\n            with self.lock:\n                if key in self.data:\n                    self.release(self.data.pop(key));self.replacements+=1\n                if size<=self.max_bytes:\n                    canonical=tuple(self.intern(blob) for blob in parts)\n                    self.data[key]=(canonical,self.intern(named),saved)\n                    while len(self.data)>self.capacity or self.key_bytes>self.max_bytes:\n                        _,old=self.data.popitem(last=False);self.release(old);self.evictions+=1\n            return value\n        return cached\n\n    def report(self):\n        with self.lock:return dict(version=\'phone-signal-cache-4\',hits=self.hits,misses=self.misses,\n            bypasses=self.bypasses,entries=len(self.data),capacity=self.capacity,key_bytes=self.key_bytes,max_key_bytes=self.max_bytes,\n            serializations=self.serializations,shared_inputs=self.shared_inputs,frozen_reuses=self.frozen_reuses,evictions=self.evictions,replacements=self.replacements,unique_inputs=len(self.pool))\n\n\ndef install(timer,pins):\n    import okx_channel701 as channel\n    import okx_two_wick732 as patterns\n    import okx_band_flow as indicators\n    import okx_pattern15 as analysis\n    modules=(channel,patterns,indicators,analysis)\n    for module in modules:\n        path=Path(inspect.getsourcefile(module))\n        if hashlib.sha256(path.read_bytes()).hexdigest()!=pins[\'files\'][path.name]:\n            raise ValueError(\'신호 계산 대상 원본 해시 불일치\')\n    from phone_frozen_bars import install as install_frozen\n    install_frozen(indicators,pins)\n    from phone_feed_fast import install as install_feed\n    install_feed(pins)\n    cache=SignalCache(timer);timer.signal_cache=cache\n    for module,name,label in ((patterns,\'select\',\'signal.pattern\'),(indicators,\'view\',\'signal.indicators\'),(analysis,\'summary\',\'signal.trend\')):\n        setattr(module,name,cache.wrap(getattr(module,name),label))\n    from phone_candidate_fast import install as install_fast\n    install_fast(channel,cache,pins)\n    original=channel.packet\n    @functools.wraps(original)\n    def packet(*args,**kwargs):\n        with timer.scope(\'signal.packet\'):\n            with cache.packet_scope((args[0] if args else kwargs[\'row\']).get(\'symbol\')):return original(*args,**kwargs)\n    channel.packet=packet\n    return cache\n', 'phone_candidate_fast.py': '"""Exact-input candidate selection memo; fresh execution-clock checks.\n\nCache only the small pattern result, never an entire candle array. All input\nbytes and the completed-bar cutoff participate in cache validity. Final order\nadmission/position protection stay uncached and run original core checks.\n"""\nimport ast\nimport functools\nimport hashlib\nimport inspect\nfrom pathlib import Path\nimport threading\nimport time\nfrom types import FunctionType\nfrom phone_frozen_bars import FrozenBars\n\n\ndef replace_once(text, old, new):\n    if text.count(old) != 1:\n        raise ValueError(\'candidate patch anchor mismatch\')\n    return text.replace(old, new, 1)\n\n\ndef rejection(error):\n    text = str(error)\n    for match, label in (\n        (\'최신 완료봉 대기\',\'최신 확정봉 대기\'), (\'완료봉 자료 부족\',\'봉 자료 부족\'),\n        (\'봉 수치 오류\',\'봉 수치 오류\'), (\'봉 연속성 오류\',\'봉 간격 오류\'),\n        (\'90초 만료\',\'90초 만료\'), (\'신호 만료\',\'90초 만료\'),\n        (\'손절 유효성\',\'가격·손절 범위\'), (\'초기SL 도달\',\'대기 중 손절선 도달\'),\n        (\'원래 완료봉 신호 변경\',\'원래 신호 변경\'), (\'진입 경로 변경\',\'진입 경로 변경\')):\n        if match in text:\n            return label\n    return \'자료·신호 검사 거절\'\n\n\ndef install(channel, cache, pins):\n    path = Path(inspect.getsourcefile(channel))\n    raw = path.read_bytes()\n    if hashlib.sha256(raw).hexdigest() != pins[\'files\'][path.name]:\n        raise ValueError(\'candidate fast path source hash mismatch\')\n    original_packet, original_candidate, original_closed = channel.packet, channel.candidate, channel.closed\n    state = threading.local()\n    import okx_two_wick732 as patterns\n    # The existing exact-input pattern wrapper was just installed by our caller.\n    # Fold its pure original into one validation+selection cache so full bars\n    # are serialized once and never deep-copied on a cache hit.\n    original_select = inspect.unwrap(patterns.select)\n\n    def select_validated(bars, hourly, now):\n        with cache.timer.scope(\'signal.closed_validation.compute\'):\n            b = original_closed(bars, now)\n        return original_select(b, hourly)\n    memo_select = cache.wrap(select_validated, \'signal.validated_selection\')\n\n    def select_fast(bars, hourly, now):\n        # Aligned integer timestamps make floor(now/15m) an EXACT equivalent\n        # cutoff, including future/in-progress bars. Unusual input falls back.\n        aligned = (type(now) is int and type(bars) in (list, tuple) and all(type(r) in (list, tuple) and len(r)>0\n            and type(r[0]) is int and r[0] % 900000 == 0 for r in bars))\n        if type(bars) is FrozenBars:\n            aligned = type(now) is int and bars._aligned15\n        return memo_select(bars, hourly, now//900000*900000) if aligned else select_validated(bars, hourly, now)\n\n    def gate(label):\n        d = getattr(state, \'diagnostic\', None)\n        if d is not None:\n            d[\'reasons\'][label] = d[\'reasons\'].get(label, 0)+1\n\n    def wait_for_market(e, symbol, signal, now):\n        gate(\'실시간 자료 대기\')\n        d = getattr(state, \'diagnostic\', None)\n        if d is not None and len(d[\'waiting\']) < 4:\n            missing = e.stream.missing(symbol, e.cfg, now) if hasattr(e.stream,\'missing\') else []\n            # Only known channel names and the already-public instrument ID.\n            symbol = str(symbol)\n            if len(symbol) <= 64 and all(c.isascii() and (c.isalnum() or c==\'-\') for c in symbol):\n                d[\'waiting\'].append(dict(symbol=symbol,\n                    channels=[x for x in missing if x in (\'tickers\',\'trades\',\'books5\',\'mark-price\')],\n                    remaining_s=round(max(0,signal[\'expires_ms\']-now)/1000,1)))\n\n    channel._phone_select_validated = select_fast\n    channel._phone_entry_gate = gate\n    channel._phone_entry_rejection = rejection\n    channel._phone_entry_wait = wait_for_market\n    channel._phone_thaw_row = lambda row: dict(row, live_frames={\n        name: bars.thaw() if type(bars) is FrozenBars else bars\n        for name, bars in row.get(\'live_frames\', {}).items()})\n    tree = ast.parse(raw)\n    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == \'packet\')\n    src = ast.unparse(node)\n    src = replace_once(src, "frames = {}\\n    b = closed(row.get(\'live_frames\', {}).get(\'15m\', []), now)", "frames = {}")\n    src = replace_once(src, "v, or_status = select(b, row.get(\'live_frames\', {}).get(\'1H\'))", "v, or_status = _phone_select_validated(row.get(\'live_frames\', {}).get(\'15m\', []), row.get(\'live_frames\', {}).get(\'1H\'), now)\\n    if not v:\\n        return dict(entry_setups=[], or_status=or_status)\\n    b = closed(row.get(\'live_frames\', {}).get(\'15m\', []), now)")\n    src = replace_once(src, "b = closed(row.get(\'live_frames\', {}).get(\'15m\', []), now)",\n                       "row = _phone_thaw_row(row)\\n    b = closed(row.get(\'live_frames\', {}).get(\'15m\', []), now)")\n    def compiled(text, name, defaults=None):\n        ns = {}; exec(compile(text, str(path)+\'<phone123>\', \'exec\'), ns)\n        return FunctionType(ns[name].__code__, channel.__dict__, name, defaults)\n    fast = compiled(src, \'packet\', original_packet.__defaults__)\n\n    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == \'candidate\')\n    src = ast.unparse(node)\n    # Refresh after the complete scan, then again for each execution check.\n    # The original <=500ms future tolerance remains unmodified.\n    anchor = "e.channel_pending = {k: s for k, s in e.channel_pending.items()"\n    src = replace_once(src, anchor, "now = e.api.now_ms()\\n    for pending in e.channel_pending.values():\\n        if now > pending[\'expires_ms\']:\\n            _phone_entry_gate(\'90초 만료\')\\n    "+anchor)\n    anchor = "for symbol, s in sorted(e.channel_pending.items(), key=rank_item):"\n    src = replace_once(src, anchor, anchor+"\\n        now = e.api.now_ms()\\n        if now > s[\'expires_ms\']:\\n            e.channel_pending.pop(symbol, None)\\n            _phone_entry_gate(\'90초 만료\')\\n            continue")\n    src = replace_once(src, "if not e.stream.ready(symbol, e.cfg, now):\\n            continue", "if not e.stream.ready(symbol, e.cfg, now):\\n            _phone_entry_wait(e, symbol, s, now)\\n            continue")\n    src = replace_once(src, "q = e.stream.read(symbol, \'tickers\', 15, now)", "q = e.stream.read(symbol, \'tickers\', 15, e.api.now_ms())")\n    src = replace_once(src, "if not q or not q.get(\'last\'):\\n            continue", "if not q or not q.get(\'last\'):\\n            _phone_entry_gate(\'최신 체결가 대기\')\\n            continue")\n    src = replace_once(src, "except (BotError, ValueError, KeyError):\\n            continue", "except (BotError, ValueError, KeyError) as error:\\n            _phone_entry_gate(_phone_entry_rejection(error))\\n            continue")\n    src = replace_once(src, "except BotError as err:\\n            e.channel_pending.pop", "except BotError as err:\\n            _phone_entry_gate(_phone_entry_rejection(err))\\n            e.channel_pending.pop")\n    src = replace_once(src, "if float(row[\'instrument\'].get(\'lever\') or 0) < s[\'leverage\']:\\n                continue", "if float(row[\'instrument\'].get(\'lever\') or 0) < s[\'leverage\']:\\n                _phone_entry_gate(\'거래소 배율 한도\')\\n                continue")\n    src = replace_once(src, "if symbol + \':\' + s[\'signal_id\'] in e.journal.data.get(\'seen_signals\', {}):\\n                continue", "if symbol + \':\' + s[\'signal_id\'] in e.journal.data.get(\'seen_signals\', {}):\\n                _phone_entry_gate(\'이미 처리한 신호\')\\n                continue")\n    src = replace_once(src, "if not v:\\n                if p.get(\'or_status\')", "if not v:\\n                _phone_entry_gate(\'패턴 조건 미충족\')\\n                if p.get(\'or_status\')")\n    fixed_candidate = compiled(src, \'candidate\')\n\n    def enabled():\n        return getattr(state,\'candidate\',False) and getattr(cache.timer.local,\'group\',None)==\'optimized\'\n    @functools.wraps(original_candidate)\n    def candidate(e):\n        previous = state.__dict__.copy()\n        state.candidate = True\n        d = dict(observed_at=time.time(), reasons={}, waiting=[])\n        state.diagnostic = d\n        started = time.perf_counter(); result = None\n        try:\n            result = fixed_candidate(e)\n            return result\n        finally:\n            d[\'duration_s\'] = round(time.perf_counter()-started,3)\n            d[\'pending\'] = len(getattr(e,\'channel_pending\',{}))\n            d[\'result\'] = \'주문 전 최종 검사로 전달\' if result else \'진입 후보 대기\'\n            d[\'observed_at\'] = time.time()\n            e.phone_entry_diagnostic = d  # Replace atomically; readers never mutate.\n            state.__dict__.clear(); state.__dict__.update(previous)\n    @functools.wraps(original_packet)\n    def packet(*args, **kwargs):\n        with cache.timer.scope(\'signal.packet_body\'):\n            if enabled():\n                return fast(*args, **kwargs)\n            # UI/manual consumers retain the original editable-list packet shape.\n            if args:\n                args = (channel._phone_thaw_row(args[0]),) + args[1:]\n            else:\n                kwargs = dict(kwargs, row=channel._phone_thaw_row(kwargs[\'row\']))\n            return original_packet(*args, **kwargs)\n    @functools.wraps(original_closed)\n    def closed(b,now,step=900000,required=22):\n        with cache.timer.scope(\'signal.closed_validation.compute\'):\n            return original_closed(b.thaw() if type(b) is FrozenBars else b,now,step,required)\n    channel.candidate=candidate;channel.packet=packet;channel.closed=closed\n'}

def digest(data):
    return hashlib.sha256(data).hexdigest()


def replace_once(text, before, after, file):
    if not before or text.count(before) != 1:
        raise ValueError(file + ': 수정 대상이 정확히 일치하지 않습니다. 변경 안 함')
    return text.replace(before, after, 1)


def safe_path(path):
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise ValueError('운용 루트 폴더가 없거나 링크입니다.')
    return path.resolve(strict=True)


def read_pins(root):
    old = root/HOST_OLD
    if old.is_symlink() or not old.is_dir():
        raise ValueError('현재 1.2.4 host-v22 폴더를 확인하지 못했습니다.')
    originals = {}
    for name, checksum in PINNED.items():
        file = old/name
        if file.is_symlink() or not file.is_file():
            raise ValueError(name + ': 필수 원본 파일이 없습니다.')
        data = file.read_bytes()
        actual = digest(data)
        if actual != checksum:
            raise ValueError(name + ': 승인된 1.2.4 원본과 다릅니다. 자동 변경하지 않았습니다.')
        originals[name] = data
    for file in old.rglob('*'):
        rel = file.relative_to(old)
        if file.is_symlink():
            raise ValueError('이전 실행기 안에 파일 링크가 있어 중단합니다.')
        if file.is_file() and '__pycache__' not in rel.parts and rel.as_posix() not in PINNED:
            raise ValueError('1.2.4 실행기에 예상하지 않은 파일이 있어 중단합니다: ' + str(rel))
    return originals


def candidate(originals):
    files = dict(originals)
    for name, text in MODULES.items():
        files[name] = text.encode('utf-8')
    service = originals['phone_service.py'].decode()
    service = replace_once(service,"VERSION = 'phone-service-22'","VERSION = 'phone-service-23'",'phone_service.py')
    service = replace_once(service,"MARKER = '# OKX phone service v22 managed boot hook'","MARKER = '# OKX phone service v23 managed boot hook'",'phone_service.py')
    service = replace_once(service,'LEGACY_MARKERS = (',"LEGACY_MARKERS = ('# OKX phone service v22 managed boot hook', ",'phone_service.py')
    files['phone_service.py'] = service.encode()
    mobile = originals['phone_mobile.py'].decode()
    if mobile.count('1.2.4') != 4: raise ValueError('mobile version mismatch')
    files['phone_mobile.py'] = mobile.replace('1.2.4','1.2.5').encode()
    update = originals['phone_update.py'].decode()
    update = replace_once(update,'CURRENT = 22','CURRENT = 23','phone_update.py')
    update = replace_once(update,"DISPLAY_VERSION = '1.2.4'","DISPLAY_VERSION = '1.2.5'",'phone_update.py')
    files['phone_update.py'] = update.encode()
    up = originals['phone_button_upgrade.py'].decode().replace('1.2.4','1.2.5')
    up = replace_once(up,"if matches != ['host-v21']:","if matches != ['host-v22']:",'phone_button_upgrade.py')
    files['phone_button_upgrade.py'] = up.encode()
    oldpins=json.loads(originals['phone_button_old_sources.json'])
    if HOST_OLD in oldpins: raise ValueError('duplicate predecessor')
    oldpins[HOST_OLD]=PINNED
    files['phone_button_old_sources.json']=(json.dumps(oldpins,ensure_ascii=False,indent=2)+'\n').encode()
    for name,data in files.items():
        if name.endswith('.py'): compile(data,name,'exec')
    return files


def stage(root, files):
    dest = root/HOST_NEW
    if dest.is_symlink():
        raise ValueError('host-v23 경로 링크 오류')
    if dest.exists():
        if not dest.is_dir():
            raise ValueError('host-v23은 폴더가 아닙니다.')
        seen = {}
        for file in dest.rglob('*'):
            rel = file.relative_to(dest)
            if file.is_symlink():
                raise ValueError('host-v23 내 파일 링크 오류')
            if file.is_file() and '__pycache__' not in rel.parts:
                seen[rel.as_posix()] = file.read_bytes()
        if seen != files:
            raise ValueError('다른 host-v23이 존재합니다. 덮어쓰지 않았습니다.')
        print('이미 검증된 1.2.5 파일이 준비되어 있습니다.')
        return dest
    tmp = Path(tempfile.mkdtemp(prefix='.host-v23-stage-', dir=root))
    try:
        for name, data in files.items():
            target = tmp/name
            with target.open('xb') as fp:
                fp.write(data)
                os.fchmod(fp.fileno(), 0o600)
        for name, data in files.items():
            if (tmp/name).read_bytes() != data:
                raise ValueError('설치 파일 저장 검증 실패')
        tmp.rename(dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)
    print('해시 확인된 1.2.5 파일 준비:', dest)
    return dest


def main():
    parser = argparse.ArgumentParser(description='OKX Fold3 1.2.5 반복 봉 변환 및 시세 처리 부하 개선')
    parser.add_argument('--root', default=str(Path.home()/'okx-phone'))
    parser.add_argument('--stage-only', action='store_true', help='검증 및 파일 준비만 수행; 실행기 인계 없음')
    args = parser.parse_args()
    root = safe_path(args.root)
    dest = stage(root, candidate(read_pins(root)))
    if args.stage_only:
        return
    print('기존 보유/미체결/보호주문을 확인하고 안전 인계를 요청합니다.')
    print('보호 상태가 불확실하면 기존 실행기를 유지하고 설치를 보류합니다.')
    proc = subprocess.run([sys.executable, '-B', str(dest/'phone_button_upgrade.py'), '--root', str(root)],
                          cwd=str(dest), check=False)
    if proc.returncode:
        raise SystemExit('업데이트 보류: 기존 앱이 보유분 보호 중일 수 있습니다. 강제 종료하지 마세요.')
    print('설치 완료: 모바일 버전 1.2.5, 기존 운용 상태를 확인하세요.')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, UnicodeError) as exc:
        print('설치 보류:', str(exc))
        raise SystemExit(1)
