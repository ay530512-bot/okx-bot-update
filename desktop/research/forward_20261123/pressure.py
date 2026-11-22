"""Score prespecified prior-flow gates at the matched timestamp without using later prints."""
from collections import Counter
from pathlib import Path
import json,gzip,math,sys
M=60000
def run(root):
    f=root/'result/event_paths.json';events=json.loads(f.read_bytes());bars={};meta={}
    for p in (root/'cache').glob('*.json.gz'):
        sym=p.name.split('.')[0];data=json.load(gzip.open(p));bars[sym]={int(r[0]):r for r in data['1m']}
        meta[sym]=float(data['instrument'][0]['tickSz'])
    counts=Counter()
    for e in events:
        s=e['side'];sym=e['sym'];ts=e['signal'];wall=ts//10000*10000;a=wall-60000
        st=ts//M*M;votes=[]
        for other,b in bars.items():
            if other!=sym and st-M in b and st-16*M in b:votes.append(s*(float(b[st-M][4])-float(b[st-16*M][4]))>0)
        breadth=sum(votes)/len(votes) if len(votes)==len(bars)-1 else None
        rows=[];missing=False
        for m in range(a//M*M,wall,M):
            p=root/'ticks'/(sym+'-'+str(m)+'.json.gz')
            if p.exists():rows.extend(x for x in json.load(gzip.open(p)) if a<=x[0]<wall)
            elif m not in bars[sym] or float(bars[sym][m][5])>0:missing=True
        def side_share(rs):
            total=sum(r[2]*r[3] for r in rs)
            return sum(r[2]*r[3] for r in rs if (r[4]=='buy')==(s==1))/total if total else None
        older=[r for r in rows if r[0]<wall-10000];recent=[r for r in rows if r[0]>=wall-10000]
        x=side_share(recent) if not missing else None;y=side_share(older) if not missing else None
        initial=e.get('pre',{}).get('stop')
        ab=None if missing or not initial else bool(len(older)>=5 and len(recent)>=5 and x is not None and y is not None and y<=.40 and x>=.60 and abs(older[-1][2]-older[0][2])<=abs(e['fill_ref'][2]-initial)/4 and s*(recent[-1][2]-recent[0][2])>=meta[sym]*(1-1e-7))
        g=None if x is None or breadth is None else x>=.60 and breadth>=.60
        e['pre_flow']=dict(peer_count=len(votes),peer_alignment=breadth,source_missing=missing,prior50_prints=None if missing else len(older),last10_prints=None if missing else len(recent),last10_aligned=x,prior50_aligned=y,aligned_and_breadth=g,absorption_then_turn=ab)
        counts['missing' if missing else 'covered']+=1
    f.write_text(json.dumps(events,separators=(',',':')))
    (root/'result/pressure_coverage.json').write_text(json.dumps(counts))
if __name__=='__main__':run(Path(sys.argv[1]))
