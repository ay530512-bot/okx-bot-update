"""Reproduce Q2X pattern comparison against the frozen 30-alt research data."""
from pathlib import Path
import hashlib, importlib.util, json, sys
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE/'app'))
import okx_long_wick_exit732 as live
spec=importlib.util.spec_from_file_location('frozen_features',ROOT/'long_wick_research/features.py')
reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
shape=json.loads((ROOT/'trail30_research/inputs/shape.json').read_text())
raw=np.memmap(ROOT/'trail30_research/inputs/bars.bin',dtype='<f8',mode='r',shape=(shape['n'],30,9))
checks=positives=0; rng=np.random.default_rng(7320224)
for si,symbol in enumerate(shape['symbols']):
    b=reference.aggregate(raw[:,si,:4],15);masks,_,_=reference.wick_masks(b)
    candidates=np.flatnonzero(masks[1:])+1
    indices=np.unique(np.r_[rng.choice(np.arange(1,len(b)),200,replace=False),rng.choice(candidates,200,replace=False)])
    for j in indices:
        stamps=shape['start']+np.arange(max(0,j-299),j+1)*live.STEP
        bars=[[int(t),*r,100.] for t,r in zip(stamps,b[max(0,j-299):j+1])]
        now=int(stamps[-1]+live.STEP)
        for side,bit in (('short',1),('long',2)):
            actual=live.signal(bars,side,shape['start'],now)
            expected=bool(masks[j]&bit)
            assert bool(actual)==expected,(symbol,int(j),side,actual,expected)
            checks+=1;positives+=expected
result=dict(checks=checks,positive_cases=positives,mismatches=0,symbols=shape['symbols'],
            timeframe='15m',seed=7320224,reused_data=True,new_profitability_test=False,
            reference_sha256=hashlib.sha256((ROOT/'long_wick_research/features.py').read_bytes()).hexdigest(),
            live_sha256=hashlib.sha256((HERE/'app/okx_long_wick_exit732.py').read_bytes()).hexdigest())
(HERE/'pattern_parity.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
