"""Offline process-sharding experiment; no exchange clients, sockets or orders.
Runs isolated cases with spawn, stable symbol partitions, versioned requests.
Worker calculations use unmodified pinned 1.2.5 candidate/cache code. Final
quote/admission/protection stay out of workers (ready=False in this experiment).
"""
import argparse,copy,hashlib,json,multiprocessing as mp,os,pickle,platform,queue,random
import statistics,subprocess,sys,threading,time
from pathlib import Path
from types import SimpleNamespace as NS

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1];WORK=REPO.parent
HOST=WORK/'fixture121/host-v23';CORE=WORK/'core121'

def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def memory():
    out={}
    for path,fields in [('/proc/self/status',('VmRSS:',)),('/proc/self/smaps_rollup',('Pss:',))]:
        try:
            for line in Path(path).read_text().splitlines():
                if line.startswith(fields):out[line.split(':')[0]]=int(line.split()[1])/1024
        except OSError:pass
    return out

def dataset(kind):
    f=json.loads((REPO/'android/phone_v118/test_signal_fixture.json').read_text())
    row=f['row'];now=int(f['now']);result=[]
    for i in range(289):
        positive=i==0 or (kind=='many_signals' and i%5==0)
        frames={k:[[int(r[0])]+(r[1:] if positive else [100.,101.,99.,100.,100.]) for r in b]
                for k,b in row['live_frames'].items()}
        symbol=f'X{i:03}-USDT-SWAP'
        instrument=dict(instId=symbol,state='live',settleCcy='USDT',ctType='linear',ctValCcy=symbol.split('-')[0],instCategory='1',lever='100')
        result.append(dict(symbol=symbol,instrument=instrument,live_frames=frames))
    return result,now

class Calculator:
    def __init__(self):
        sys.path[:0]=[str(HOST),str(CORE)]
        import okx_channel701 as ch,okx_band_flow as band
        from phone_performance import Timing
        from phone_signal_cache import install
        self.ch=ch;self.band=band
        self.timer=Timing('/tmp');self.timer.local.group='optimized'
        self.cache=install(self.timer,json.loads((HOST/'phone_sources.json').read_text()))
        self.rows={};self.now=0;self.version=-1
        self.e=NS(api=NS(now_ms=lambda:self.now),can_open_position=lambda:True,
            universe=NS(read=lambda:({'rows':list(self.rows.values())},None)),records=lambda:[],
            blocked_manual_symbols=lambda:set(),cfg={'selection':{},'indicators':{'bb_period':20,'bb_multiplier':2,'ma_periods':[15,20,50,100,120,200]}},
            journal=NS(data={}),stream=NS(watch=lambda _:None,ready=lambda *a:False),
            chat=NS(watch=lambda:[]),pipeline=lambda *a,**kw:None,events=queue.Queue())
    def run(self,request):
        ident,now,updates,clear=request
        if ident<=self.version:raise ValueError('non-increasing snapshot revision')
        self.version=ident;self.now=now
        if clear:self.rows={};self.e.channel_pending={}
        for row in updates:
            self.rows[row['symbol']]=dict(row,live_frames={f:self.band.merge_completed(None,b,f,now,300) for f,b in row['live_frames'].items()})
        self.ch.candidate(self.e)
        return dict(self.e.channel_pending)

def worker(pipe):
    try:
        calc=Calculator();pipe.send(('ready',os.getpid()))
        while True:
            raw=pipe.recv_bytes()
            if raw==b'STOP':break
            cpu=time.process_time();request=pickle.loads(raw)
            signals=calc.run(request)
            # Serialize the returned evidence inside measured worker CPU work.
            result=pickle.dumps((request[0],signals),protocol=5)
            pipe.send_bytes(pickle.dumps((result,time.process_time()-cpu),protocol=5))
        pipe.send(memory())
    except BaseException as e:
        try:pipe.send(('error',type(e).__name__,str(e)))
        except Exception:pass
        raise
    finally:pipe.close()

class Probe:
    def __init__(self):self.stop=threading.Event();self.samples=[]
    def run(self):
        target=time.perf_counter()+.005
        while not self.stop.wait(max(0,target-time.perf_counter())):
            now=time.perf_counter();self.samples.append((now,max(0,now-target)))
            target=now+.005

def percentile(values,q):
    a=sorted(values);return a[min(len(a)-1,int((len(a)-1)*q))] if a else None

def case(mode,kind,rep):
    rows,now=dataset(kind);partitions={r['symbol']:i%max(1,mode) for i,r in enumerate(rows)}
    ctx=mp.get_context('spawn');procs=[];pipes=[];startup=time.perf_counter()
    if mode:
        for _ in range(mode):
            parent,child=ctx.Pipe();p=ctx.Process(target=worker,args=(child,));p.start();child.close();pipes.append(parent);procs.append(p)
        for pipe in pipes:
            if not pipe.poll(30):raise TimeoutError('worker startup')
            ready=pipe.recv()
            if ready[0]!='ready':raise RuntimeError(ready)
        calc=None
    else:calc=Calculator()
    startup=time.perf_counter()-startup
    probe=Probe();thread=threading.Thread(target=probe.run,daemon=True);thread.start()
    records=[];ident=0
    def scan(label,updates,at,clear=False):
        nonlocal ident
        ident+=1;start=time.perf_counter();cpu=time.process_time();extra_cpu=0;sent=received=0
        if mode:
            batches=[[] for _ in range(mode)]
            for row in updates:batches[partitions[row['symbol']]].append(row)
            for pipe,batch in zip(pipes,batches):
                data=pickle.dumps((ident,at,batch,clear),protocol=5);sent+=len(data);pipe.send_bytes(data)
            signals={}
            for pipe in pipes:
                if not pipe.poll(30):raise TimeoutError('worker scan')
                raw=pipe.recv_bytes();received+=len(raw);data,used=pickle.loads(raw);version,part=pickle.loads(data)
                if version!=ident:raise ValueError('stale worker result')
                if signals.keys() & part.keys():raise ValueError('duplicate symbol result')
                signals.update(part);extra_cpu+=used
        else:signals=calc.run((ident,at,updates,clear))
        # Canonical priority from original core rank_item, performed in parent.
        sys.path[:0]=[str(HOST),str(CORE)]
        from okx_channel701 import rank_item
        ordered=sorted(signals.items(),key=rank_item)
        wall=time.perf_counter()-start;used=time.process_time()-cpu+extra_cpu
        records.append(dict(label=label,wall_s=wall,cpu_s=used,send_bytes=sent,receive_bytes=received,
            signals=len(signals),result_sha=digest(ordered)))
    try:
        scan('cold',rows,now,True)
        for i in range(20):scan('warm',[],now+i+1)
        for i in range(4):
            changed=copy.deepcopy(rows[i]);changed['live_frames']['1H'][-2][5]+=i+1
            rows[i]=changed;scan('one_correction',[changed],now+30+i)
        for i in range(3):
            rows=copy.deepcopy(rows)
            for row in rows:
                row['live_frames']['15m'][-2][5]+=1+i
                row['live_frames']['1H'][-2][5]+=1+i
            scan('all_changed',rows,now+40+i)
        scan('expired',[],now+90001)
        scan('missing_next_candle',[],now+900000)
        # Give the probe a scheduling opportunity after the last CPU interval.
        time.sleep(.01)
        own=memory();children=[]
        for pipe in pipes:pipe.send_bytes(b'STOP')
        for pipe in pipes:
            if not pipe.poll(5):raise TimeoutError('worker shutdown')
            children.append(pipe.recv())
        for p in procs:
            p.join(5)
            if p.exitcode!=0:raise RuntimeError('worker exit '+str(p.exitcode))
        values=[x[1] for x in probe.samples]
        return dict(mode=mode,kind=kind,rep=rep,startup_s=startup,records=records,
            aggregate_rss_mib=own.get('VmRSS',0)+sum(x.get('VmRSS',0) for x in children),
            aggregate_pss_mib=(own.get('Pss',0)+sum(x.get('Pss',0) for x in children)) if 'Pss' in own else None,
            main_heartbeat_lateness_p95_s=percentile(values,.95),main_heartbeat_lateness_max_s=max(values,default=0),
            heartbeat_samples=len(values),input_sha=digest(dataset(kind)[0]))
    finally:
        probe.stop.set();thread.join(1)
        for p in procs:
            if p.is_alive():p.terminate();p.join(2)
        for p in pipes:p.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case',nargs=3);args=parser.parse_args()
    if args.case:
        mode,kind,rep=args.case;print(json.dumps(case(int(mode),kind,int(rep))));return
    cases=[(mode,kind,rep) for rep in range(3) for kind in ('mostly_waiting','many_signals') for mode in (0,1,2,4,8)]
    random.Random(20261115).shuffle(cases)
    results=[]
    for mode,kind,rep in cases:
        r=subprocess.run([sys.executable,'-B',__file__,'--case',str(mode),kind,str(rep)],capture_output=True,text=True,timeout=90)
        if r.returncode:
            (HERE/'failure.txt').write_text(r.stdout+r.stderr);raise RuntimeError(r.stderr)
        data=json.loads(r.stdout);results.append(data)
        (HERE/'results.json').write_text(json.dumps(results,indent=2))
        print(f'completed {len(results)}/{len(cases)} mode={mode} kind={kind}',flush=True)
    for kind in ('mostly_waiting','many_signals'):
        target=next(x for x in results if x['mode']==0 and x['kind']==kind)
        for row in (x for x in results if x['kind']==kind):
            assert row['input_sha']==target['input_sha']
            assert [(r['label'],r['result_sha'],r['signals']) for r in row['records']]==[(r['label'],r['result_sha'],r['signals']) for r in target['records']]
    summary=[]
    for kind in ('mostly_waiting','many_signals'):
        for mode in (0,1,2,4,8):
            rows=[x for x in results if x['kind']==kind and x['mode']==mode]
            stats={}
            for label in ('cold','warm','one_correction','all_changed','expired','missing_next_candle'):
                records=[r for x in rows for r in x['records'] if r['label']==label]
                stats[label]={metric:statistics.median(r[metric] for r in records) for metric in ('wall_s','cpu_s','send_bytes','receive_bytes')}
                stats[label]['wall_p95_s']=percentile([r['wall_s'] for r in records],.95)
            summary.append(dict(kind=kind,mode=mode,stats=stats,**{k:statistics.median(x[k] for x in rows) for k in ('startup_s','aggregate_rss_mib','aggregate_pss_mib','main_heartbeat_lateness_p95_s','main_heartbeat_lateness_max_s')}))
    (HERE/'summary.json').write_text(json.dumps(dict(equivalence=True,process_cases=len(results),scan_comparisons=sum(len(x['records']) for x in results),summary=summary),indent=2))

if __name__=='__main__':main()
