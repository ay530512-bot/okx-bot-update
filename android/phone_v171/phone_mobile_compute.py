"""Bounded nonblocking computation service. It cannot place or manage orders.

Only one submitted batch exists. Completed results require exact full-input,
clock bucket, preference revision and connection generation agreement. Existing
valid candidates remain available while another batch is being calculated.
"""
import atexit
import copy
import concurrent.futures as futures
from pathlib import Path
import pickle
import threading
import time
import zlib


class Manager:
    def __init__(self, root, pins, core, timer):
        self.root = Path(root); self.pins = pins; self.core = core; self.timer = timer
        self.pool = None; self.pool_keys = {}; self.keys = {}; self.packets = {}
        self.cfg_key = None; self.bucket = None; self.connection = None; self.revision = None
        self.effective = 0; self.last_error = None; self.last_scan_s = None
        self.previous_resources = None
        self.executor = futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='mobile-compute')
        self.future = None; self.request = None; self.published_signature = None
        self.stopped = threading.Event(); self.serial = 0
        self.started_at = None; self.discarded = 0; self.completed = 0
        self.published_timing = {}
        atexit.register(self.close)

    def close(self):
        self.stopped.set()
        if self.pool: self.pool.close()
        self.pool = None; self.effective = 0
        self.executor.shutdown(wait=False, cancel_futures=True)

    def work(self, job):
        from phone_parallel import Pool, key
        from okx_core import BotError
        import okx_channel701 as channel
        started = time.monotonic()
        cfg, rows, now, workers = job['cfg'], job['rows'], job['now'], job['workers']
        try:
            if workers == 4:
                if self.pool is None:
                    self.pool = Pool(self.core, self.pins); self.pool_keys = {}
                if self.stopped.is_set(): return None
                self.serial += 1
                keys = {r['symbol']:key(r) for r in rows}
                groups = [[] for _ in range(4)]
                for r in rows: groups[zlib.crc32(r['symbol'].encode()) % 4].append(r)
                tasks = [(self.serial, now, cfg, [r['symbol'] for r in group],
                    [r for r in group if self.pool_keys.get(r['symbol']) != keys[r['symbol']]]) for group in groups]
                answers = self.pool.run(tasks)
                packets = {}
                for task, answer in zip(tasks, answers):
                    revision, part = answer
                    if revision != self.serial or set(part) != set(task[3]) or packets.keys() & part.keys():
                        raise ValueError('worker response mismatch')
                    packets.update(part)
                if len(answers) != len(tasks): raise ValueError('worker count mismatch')
                self.pool_keys = keys
            else:
                if self.pool:
                    self.pool.close(); self.pool = None; self.pool_keys = {}
                packets = {}
                self.timer.local.group = 'optimized'
                for row in rows:
                    if self.stopped.is_set(): return None
                    try:
                        with self.timer.signal_cache.packet_scope(row['symbol']):
                            packets[row['symbol']] = (True, channel._phone_worker_packet(row, cfg, now))
                    except (BotError, ValueError, KeyError) as error:
                        packets[row['symbol']] = (False, str(error))
            return dict(packets=packets, seconds=round(time.monotonic()-started, 4))
        except Exception:
            if self.pool: self.pool.close()
            self.pool = None; self.pool_keys = {}
            raise
        finally:
            if self.stopped.is_set() and self.pool:
                self.pool.close(); self.pool = None

    def prepare(self, e):
        from phone_parallel import preference, set_preference, key, connection_token
        from phone_frozen_bars import freeze, FrozenBars
        from okx_pattern15 import allowed
        if self.stopped.is_set(): return False
        try:
            pref = preference(self.root)
        except Exception as error:
            self.last_error = type(error).__name__; self.packets = {}
            try: set_preference(self.root, 0, '계산 설정 오류 · 모바일 단일 계산으로 복원')
            except Exception: pass
            return False
        now = e.api.now_ms(); token = connection_token(e)
        cfg = {'indicators': copy.deepcopy(e.cfg['indicators'])}
        cfg_key = pickle.dumps(cfg, protocol=5)
        # Immediately invalidate publication when any execution generation changes.
        if (self.connection != token or self.revision != pref.get('revision') or
                self.bucket != now//900000 or self.cfg_key != cfg_key):
            self.packets = {}; self.published_signature = None
        if self.future is not None and self.future.done():
            future, job = self.future, self.request
            self.future = None; self.request = None
            try:
                answer = future.result()  # done() above: this never waits.
                if answer is not None and set(answer['packets']) != set(job['keys']):
                    raise ValueError('incomplete mobile computation result')
                if (answer is not None and job['connection'] == token and
                        job['revision'] == pref.get('revision') and job['bucket'] == now//900000 and
                        job['cfg_key'] == cfg_key and token[1] is not False and token[3] is not False):
                    self.keys = job['keys']; self.packets = answer['packets']
                    self.cfg_key = cfg_key; self.bucket = job['bucket']; self.connection = token
                    self.revision = job['revision']; self.published_signature = job['signature']
                    self.last_scan_s = answer['seconds']; self.last_error = None
                    self.effective = job['workers']; self.completed += 1
                    self.published_timing = dict(submitted_ms=job['now'], published_ms=now,
                        compute_s=answer['seconds'], input_ms=job['input_ms'])
                else: self.discarded += 1
            except Exception as error:
                self.last_error = type(error).__name__; self.effective = 0
                self.packets = {}; self.published_signature = None
                # Same pure policy on one background worker. No new orders in a worker.
                if job['workers'] == 4:
                    set_preference(self.root, 0, '계산 작업 오류 · 모바일 단일 계산으로 복원')
                    return False
        if self.future is not None: return True
        if token[1] is False or token[3] is False: return False
        result, _ = e.universe.read()
        if not result: return True
        blocked = {r['symbol'] for r in e.records()} | e.blocked_manual_symbols()
        rows = [r for r in result.get('rows', []) if r['symbol'] not in blocked and allowed(r['instrument'], e.cfg)]
        keys = {r['symbol']:key(r) for r in rows}
        signature = (cfg_key, now//900000, pref.get('revision'), token, tuple(sorted(keys.items())))
        if self.published_signature == signature: return True
        # Full row copies are made once per changed batch. Frozen frames are immutable.
        frozen = [dict(symbol=r['symbol'], instrument=copy.deepcopy(r['instrument']),
            live_frames={f:b if type(b) is FrozenBars else freeze(copy.deepcopy(b))
                         for f,b in r.get('live_frames', {}).items()}) for r in rows]
        job = dict(cfg=cfg, cfg_key=cfg_key, rows=frozen, keys=keys, now=now,
            input_ms={r['symbol']:r.get('observed_ms') for r in rows},
            bucket=now//900000, workers=pref['workers'], revision=pref.get('revision'),
            connection=token, signature=signature)
        self.started_at = time.monotonic(); self.request = job
        self.future = self.executor.submit(self.work, job)
        return True

    def lookup(self, row, cfg, now):
        from phone_parallel import key
        from okx_core import BotError
        if (self.bucket != now//900000 or self.cfg_key != pickle.dumps({'indicators':cfg['indicators']}, protocol=5)
                or self.keys.get(row['symbol']) != key(row) or row['symbol'] not in self.packets): return None
        good, value = self.packets[row['symbol']]
        if not good: raise BotError(value)
        return copy.deepcopy(value)

    def report(self):
        from phone_parallel import resource_report
        d = resource_report(self)
        d.update(architecture='mobile140', calculating=self.future is not None,
            batch_age_s=round(time.monotonic()-self.started_at,3) if self.future is not None else None,
            completed_batches=self.completed, discarded_batches=self.discarded,
            cached_symbols=len(self.packets), nonblocking=True)
        return d

    def timing(self, symbol):
        d=self.published_timing
        return dict(input_published_ms=d.get('input_ms',{}).get(symbol),
            computation_submitted_ms=d.get('submitted_ms'),
            computation_published_ms=d.get('published_ms'), compute_s=d.get('compute_s'))

