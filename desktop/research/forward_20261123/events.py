"""Join streams by symbol for paired research, preserving distinct opportunity IDs."""
import json,sys
from pathlib import Path
def join(direct,wick,out):
    out.mkdir(exist_ok=True)
    for p in sorted(direct.glob('*.json')):
        w=wick/p.name
        if not w.exists():continue
        rows=json.loads(p.read_bytes())
        # A seed with no previous consumed-anchor ledger cannot establish eligibility of cross-midnight setups.
        for r in rows:
            if 'ts' in r and (r['anchor']+9*3600000)//86400000<(r['ts']+9*3600000)//86400000:
                r['prior_anchor_state']='unknown'

        for e in json.loads(w.read_bytes())['events']:
            rows.append(dict(e,status='reaction',source='deployed_wick15',anchor=e['anchor_ms'],atr=e['anchor_atr']))
        (out/p.name).write_text(json.dumps(sorted(rows,key=lambda r:r.get('ts',r.get('window',0))),separators=(',',':')))
if __name__=='__main__':join(*map(Path,sys.argv[1:]))
