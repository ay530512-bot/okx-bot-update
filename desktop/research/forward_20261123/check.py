"""Offline invariants for the registration and its cached session."""
import gzip,hashlib,json,sys
from pathlib import Path
from cache_day import SYMBOLS
from scan import native_pace
from accounts import simulate
def test(path):
    coverage=json.loads((path/'coverage.json').read_bytes());lo=coverage['start_ms'];hi=coverage['end_exclusive_ms']
    assert hi-lo==86400000 and set(coverage['symbols'])==set(SYMBOLS)
    for sym,x in coverage['symbols'].items():
        blob=(path/(sym+'.json.gz')).read_bytes();assert hashlib.sha256(blob).hexdigest()==x['sha256']
        data=json.loads(gzip.decompress(blob))
        for frame,step in [('1m',60000),('5m',300000),('15m',900000),('1H',3600000),('mark1m',60000)]:
            assert [int(r[0]) for r in data[frame] if int(r[0])>=lo]==list(range(lo,hi,step))
            assert all(r[-1]=='1' for r in data[frame])
        assert x['inputs']['funding']['history_reaches_open']
    F=300000
    sample=[[i*F,10,11,9,10,1,1,20,1] for i in range(40)]
    assert native_pace(sample,40*F)=='normal'
    for b in sample[-2:]:b[2]=12;b[7]=21
    assert native_pace(sample,40*F)=='fast'
    assert native_pace(sample[:-1],40*F)=='unknown'
    assert simulate([], 'A',None,150,{},True)['status']=='below'
    assert simulate([], 'A',None,150,{},False)['closing_nav'] is None
if __name__=='__main__':test(Path(sys.argv[1]))
