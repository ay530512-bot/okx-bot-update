"""Rebuild one *closed* public research date in an isolated workspace. Research only."""
import argparse,json,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from cache_day import main as cache_day,SYMBOLS
from scan import scan
from direct_ticks import main as direct
from wick15 import run as wick
from events import join
from paired import run as paired
from finalize import summarize
from excursions import enrich
from charts import plot
from check import test
def run(day,root,package,previous=None):
    for n in ('work','cache','ticks','direct','wick15','joined','paired_all','result'):(root/n).mkdir(parents=True,exist_ok=True)
    cache=root/'cache';tape=root/'ticks'
    if not (cache/'coverage.json').exists():cache_day(day,cache)
    test(cache)
    if json.loads((cache/'coverage.json').read_bytes())['day_kst']!=day:raise ValueError('wrong cached day')
    s=root/'work/scan_day.json';scan(day,cache,package,s)
    direct(s,cache,tape,root/'direct')
    def run_wick(sym):
        p=root/'wick15'/(sym+'.json')
        if not p.exists():p.write_text(json.dumps(wick(sym,cache,tape,package),separators=(',',':')))
    with ThreadPoolExecutor(8) as pool:list(pool.map(run_wick,SYMBOLS))
    join(root/'direct',root/'wick15',root/'joined')
    def run_pairs(sym):
        p=root/'paired_all'/(sym+'.json')
        if not p.exists():
            events=json.loads((root/'joined'/p.name).read_bytes())
            p.write_text(json.dumps(paired(sym,cache,tape,events,package),separators=(',',':')))
    with ThreadPoolExecutor(8) as pool:list(pool.map(run_pairs,SYMBOLS))
    summarize(root,package,json.loads(previous.read_bytes()) if previous else None);enrich(root);plot(root)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('day');p.add_argument('root',type=Path);p.add_argument('package',type=Path);p.add_argument('--previous',type=Path)
    a=p.parse_args();run(a.day,a.root,a.package,a.previous)
