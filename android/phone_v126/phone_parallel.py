"""Four pure packet workers; parent alone owns admission, orders and protection.
Serial mode follows the exact 1.2.5 candidate path. No exchange clients in workers.
"""
import atexit
import concurrent.futures as futures
import json
import multiprocessing as mp
import os
from pathlib import Path
import pickle
import sys
import threading
import time


def preference(root):
    p=Path(root)/'phone_calculation.json'
    if not p.exists():return {'workers':4,'revision':'initial'}
    if p.is_symlink():raise ValueError('calculation preference link')
    d=json.loads(p.read_text())
    if type(d.get('workers')) is not int or d['workers'] not in (0,4):raise ValueError('calculation preference')
    return d


def set_preference(root,workers,reason='사용자 선택'):
    if type(workers) is not int or workers not in (0,4):raise ValueError('calculation workers')
    from phone_account import save_json
    import uuid
    d=dict(workers=workers,revision=uuid.uuid4().hex,reason=reason,at=time.time())
    save_json(Path(root)/'phone_calculation.json',d)
    return d


def key(row):
    from phone_frozen_bars import FrozenBars
    return (row['symbol'],pickle.dumps(row.get('instrument',{}),protocol=5),
        tuple((k,b._encoded if type(b) is FrozenBars else pickle.dumps(b,protocol=5))
              for k,b in sorted(row.get('live_frames',{}).items())))


def connection_token(e):
    stream=getattr(e,'stream',None);account=getattr(e,'account_stream',None)
    return (getattr(stream,'generation',None),getattr(stream,'connected',None),
            getattr(account,'generation',None),account.fresh() if account is not None else None)


def worker(pipe,core,pins):
    # Spawn has no engine, API session, journal or trading keys as arguments.
    sys.path.insert(0,core)
    from phone_performance import Timing
    from phone_signal_cache import install
    from phone_frozen_bars import freeze
    from okx_core import BotError
    import okx_channel701 as channel
    timer=Timing('/tmp');timer.local.group='optimized';cache=install(timer,pins)
    rows={};last=-1
    try:
        pipe.send(('ready',os.getpid()))
        while True:
            task=pipe.recv()
            if task is None:return
            revision,now,cfg,symbols,updates=task
            if revision<=last:raise ValueError('stale task')
            last=revision
            for r in updates:
                rows[r['symbol']]=dict(r,live_frames={f:freeze(b) for f,b in r.get('live_frames',{}).items()})
            rows={s:rows[s] for s in symbols}
            packets={}
            for s in symbols:
                try:
                    with cache.packet_scope(s):value=channel._phone_worker_packet(rows[s],cfg,now)
                    packets[s]=(True,value)
                except (BotError,ValueError,KeyError) as error:
                    packets[s]=(False,str(error))
            pipe.send((revision,packets))
    finally:pipe.close()


class Pool:
    def __init__(self,core,pins):
        self.procs=[];self.pipes=[];self.executor=futures.ThreadPoolExecutor(max_workers=4,thread_name_prefix='packet-ipc')
        try:
            ctx=mp.get_context('spawn')
            for i in range(4):
                a,b=ctx.Pipe();p=ctx.Process(target=worker,args=(b,core,pins),name='okx-packet-'+str(i),daemon=True)
                p.start();b.close();self.pipes.append(a);self.procs.append(p)
            deadline=time.monotonic()+8
            for pipe in self.pipes:
                if not pipe.poll(max(0,deadline-time.monotonic())) or pipe.recv()[0]!='ready':raise TimeoutError('worker startup')
        except BaseException:
            self.close();raise

    def run(self,tasks,timeout=8):
        def exchange(pipe,task):
            pipe.send(task)
            return pipe.recv()
        pending=[self.executor.submit(exchange,p,t) for p,t in zip(self.pipes,tasks)]
        done,waiting=futures.wait(pending,timeout=timeout)
        if waiting:raise TimeoutError('worker scan')
        return [f.result() for f in pending]

    def close(self):
        for p in self.procs:
            if p.is_alive():p.terminate()
        for p in self.procs:
            p.join(.3)
            if p.is_alive():p.kill();p.join(.3)
        for p in self.pipes:
            try:p.close()
            except OSError:pass
        self.executor.shutdown(wait=False,cancel_futures=True)


class Manager:
    def __init__(self,root,pins,core):
        self.root=Path(root);self.pins=pins;self.core=core;self.pool=None
        self.keys={};self.packets={};self.cfg_key=None;self.bucket=None
        self.serial=0;self.revision=None;self.effective=0;self.last_error=None;self.failed_revision=None
        self.last_scan_s=None;self.previous_resources=None;self.status_lock=threading.Lock()
        atexit.register(self.close)

    def close(self):
        pool,self.pool=self.pool,None
        if pool:pool.close()
        self.keys={};self.packets={};self.effective=0

    def fail(self,error):
        self.close();self.last_error=type(error).__name__
        try:self.failed_revision=set_preference(self.root,0,'계산 작업 오류로 기존 방식 자동 복원')['revision']
        except Exception:self.failed_revision=self.revision

    def prepare(self,e):
        self.packets={}
        try:d=preference(self.root)
        except Exception as err:self.fail(err);return False
        self.revision=d.get('revision')
        if d['workers']==0 or self.revision==self.failed_revision:
            self.close();return True
        if not e.can_open_position():return True
        result,_=e.universe.read()
        if not result:return True
        started=time.monotonic()
        connection=connection_token(e)
        if connection[1] is False or connection[3] is False:return False
        from okx_pattern15 import allowed
        held={r['symbol'] for r in e.records()}|e.blocked_manual_symbols()
        rows=[r for r in result.get('rows',[]) if r['symbol'] not in held and allowed(r['instrument'],e.cfg)]
        # Only pure indicator config crosses the boundary.
        cfg={'indicators':e.cfg['indicators']};cfg_key=pickle.dumps(cfg,protocol=5)
        now=e.api.now_ms();keys={r['symbol']:key(r) for r in rows}
        try:
            if self.pool is None:self.pool=Pool(self.core,self.pins);self.keys={}
            self.serial+=1;groups=[[] for _ in range(4)]
            # Stable symbol shard, independent of universe ordering/removal.
            import zlib
            for r in rows:groups[zlib.crc32(r['symbol'].encode())%4].append(r)
            tasks=[(self.serial,now,cfg,[r['symbol'] for r in group],
                    [r for r in group if self.keys.get(r['symbol'])!=keys[r['symbol']]]) for group in groups]
            answers=self.pool.run(tasks)
            packets={}
            for expected,(revision,part) in zip(tasks,answers):
                if revision!=self.serial or set(part)!=set(expected[3]) or packets.keys()&part.keys():raise ValueError('worker response mismatch')
                packets.update(part)
            current_connection=connection_token(e)
            if current_connection!=connection or current_connection[1] is False or current_connection[3] is False:
                self.keys={} # Next pass republishes complete data; no stale batch accepted.
                return False
            # A button pressed while work was pending takes precedence.
            if preference(self.root).get('revision')!=self.revision:
                self.close();return False
            self.keys=keys;self.packets=packets;self.cfg_key=cfg_key;self.bucket=now//900000
            self.effective=4;self.last_error=None
            self.last_scan_s=round(time.monotonic()-started,4)
            return True
        except Exception as err:
            self.fail(err)
            return False # No order candidate this tick; next pass uses serial.

    def lookup(self,row,cfg,now):
        if (self.effective!=4 or self.bucket!=now//900000 or self.cfg_key!=pickle.dumps({'indicators':cfg['indicators']},protocol=5)
                or self.keys.get(row['symbol'])!=key(row) or row['symbol'] not in self.packets):return None
        from okx_core import BotError
        good,value=self.packets[row['symbol']]
        if not good:raise BotError(value)
        return value

    def report(self):
        try:d=preference(self.root);requested=d['workers']
        except Exception:requested=0
        pool=self.pool;pids=[p.pid for p in pool.procs if p.is_alive()] if pool else []
        result=dict(requested=requested,effective=self.effective,workers_alive=len(pids),
            last_error=self.last_error,last_scan_s=self.last_scan_s)
        try:
            ticks=os.sysconf('SC_CLK_TCK');cpu=0;rss=0
            for pid in [os.getpid()]+pids:
                stat=Path('/proc/'+str(pid)+'/stat').read_text().split(') ',1)[1].split()
                cpu+=(int(stat[11])+int(stat[12]))/ticks
                rss+=int(stat[21])*os.sysconf('SC_PAGE_SIZE')/1048576
            now=time.monotonic();ident=tuple(pids)
            if self.previous_resources and self.previous_resources[0]==ident:
                _,at,used=self.previous_resources
                result['aggregate_cpu_one_core_pct']=round(max(0,cpu-used)*100/max(.001,now-at),1)
            self.previous_resources=(ident,now,cpu)
            result['aggregate_rss_mib']=round(rss,1)
        except (OSError,ValueError,IndexError):pass
        return result


def install(timer,pins):
    import okx_channel701 as channel
    import inspect
    manager=Manager(timer.root,pins,str(Path(inspect.getsourcefile(channel)).parent))
    timer.parallel=manager
    old_report=timer.report;old_summary=timer.make_summary
    def report():
        d=old_report();d['parallel']=manager.report();return d
    def summary(d):
        x=old_summary(d);x['parallel']=d.get('parallel',{});return x
    timer.report=report;timer.make_summary=summary
    return manager


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['serial','parallel4']);p.add_argument('--root',default=str(Path.home()/'okx-phone'))
    a=p.parse_args();set_preference(a.root,0 if a.mode=='serial' else 4)
    print('기존 방식 복원 요청 완료' if a.mode=='serial' else '4개 분산 요청 완료')
    print('다음 신호 검사부터 반영됩니다. 포지션·주문·매매 규칙은 변경하지 않습니다.')
