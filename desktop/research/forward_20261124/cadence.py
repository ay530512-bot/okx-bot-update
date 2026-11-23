"""Pre-entry trade-arrival acceleration on existing native-5m or native-15m retests."""
from statistics import median
from datetime import datetime,timedelta,timezone
KST=timezone(timedelta(hours=9))
def evaluate(ts,side,rows,coverage):
    hour=datetime.fromtimestamp(ts/1000,KST).hour
    if not (6<=hour<10 or 18<=hour<22):return {'status':'outside_hours'}
    end=ts//5000*5000;start=end-90000
    if not coverage(start,end):return {'status':'missing_input'}
    blocks=[[] for _ in range(18)]
    for t,i,px,sz,aggressor in rows:
        if start<=t<end:blocks[(t-start)//5000].append((px,sz,aggressor))
    baseline=median(len(g) for g in blocks[:15]);qualified=0
    for g in blocks[15:]:
        total=sum(p*q for p,q,_ in g)
        same=sum(p*q for p,q,a in g if (a=='buy')==(side==1))
        if len(g)>=max(3,1.5*baseline) and total>0 and same/total>=.60:qualified+=1
    return {'status':'pass' if qualified>=2 else 'wait','qualified_5s_groups':qualified,'median_prior5s_count':baseline}
def development():
    import json,gzip,lzma,zipfile
    from pathlib import Path
    from collections import Counter
    root=Path('study/20261122');dest=Path('publish/development_check.json')
    with zipfile.ZipFile(root/'session_20261122.zip') as z:events=json.loads(z.read('result/event_paths.json'))
    rows=[]
    for sym in sorted({r['sym'] for r in events}):
        tape=json.loads(lzma.decompress((root/'tape'/f'{sym}.json.xz').read_bytes()))
        bars={int(r[0]):float(r[5]) for r in json.load(gzip.open(root/'cache'/f'{sym}.json.gz'))['1m']}
        for e in (r for r in events if r['sym']==sym):
            ts=e['signal'];end=ts//5000*5000;mrange=range((end-90000)//60000*60000,end,60000)
            known=all(f'{sym}-{m}.json.gz' in tape or bars.get(m)==0 for m in mrange)
            ticks=[r for m in mrange for r in tape.get(f'{sym}-{m}.json.gz',[])]
            decision=evaluate(ts,e['side'],ticks,lambda lo,hi:known)
            rows.append(dict(symbol=sym,signal=ts,side=e['side'],source=e['source'],decision=decision,existing_exit_net=e.get('B',{}).get('net')))
    counts=Counter(r['decision']['status'] for r in rows)
    dest.write_text(json.dumps(dict(date='2026-11-22',role='development, never independent',counts=counts,
       paired_verified_B_net_by_gate={g:dict(n=len(v),net_sum=sum(v)) for g in counts for v in [[r['existing_exit_net'] for r in rows if r['decision']['status']==g and r['existing_exit_net'] is not None]]},rows=rows),separators=(',',':')))
if __name__=='__main__':development()
