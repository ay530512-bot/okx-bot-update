"""Compact references to already-inspected mock entries; never pool with forward results."""
import json,sys
from pathlib import Path
def main(audit,out):
    def read(p):return json.loads((audit/p).read_bytes())
    out.write_text(json.dumps(dict(cohort='historical diagnostic; not a new account session',current_package='2.16.0',pc_215_shadow='not_read',actual_account='not_read',source='OKX-60-Trade-Review / OKX-60-Trade-Data.zip; previously used 22-contract sample',features=read('features/summary.json'),symmetric_direction_diagnostics=read('reverse/summary.json'),net_protection=read('exits/summary.json'),same_quantity_fixed_exit=read('strategy/size-matched.json')),indent=1))
if __name__=='__main__':main(*map(Path,sys.argv[1:]))
