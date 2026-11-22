"""Pack immutable public execution evidence by contract; restore exact JSON values for reruns."""
import argparse,gzip,hashlib,json,lzma
from pathlib import Path
from cache_day import SYMBOLS
def pack(source,out):
    out.mkdir(parents=True,exist_ok=True);index={}
    for sym in SYMBOLS:
        files=sorted({p for pat in (sym+'-*.json.gz','mark-'+sym+'-*.json.gz','boundary-'+sym+'-*.json.gz') for p in source.glob(pat)})
        values={p.name:json.loads(gzip.decompress(p.read_bytes())) for p in files}
        data=lzma.compress(json.dumps(values,separators=(',',':')).encode(),preset=4)
        path=out/(sym+'.json.xz');path.write_bytes(data)
        index[sym]=dict(files=len(files),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    (out/'index.json').write_text(json.dumps(index,indent=1))
def restore(source,out):
    out.mkdir(parents=True,exist_ok=True)
    for k,d in json.loads((source/'index.json').read_bytes()).items():
        data=(source/(k+'.json.xz')).read_bytes()
        if hashlib.sha256(data).hexdigest()!=d['sha256']:raise ValueError('evidence digest mismatch')
        for name,v in json.loads(lzma.decompress(data)).items():
            if Path(name).name!=name or not name.endswith('.json.gz'):raise ValueError('invalid cache name')
            (out/name).write_bytes(gzip.compress(json.dumps(v,separators=(',',':')).encode(),mtime=0))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['pack','restore']);p.add_argument('source',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();(pack if a.mode=='pack' else restore)(a.source,a.out)
