"""Offline release checks, with no credentials, live APIs or order submission."""
import hashlib,json,os,re,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
WORK=REPO.parent
HOST=WORK/'fixture121/host-v23'
env=dict(os.environ,OKX_TEST_CORE=str(WORK/'core121'),OKX_TEST_HOST=str(HOST),
         PYTHONPATH=os.pathsep.join(map(str,(HOST,REPO/'android/phone_v118',Path('/tmp/okx123deps')))))
commands=[
 [sys.executable,'-B',str(HERE/'test_cpu_paths.py')],
 [sys.executable,'-B',str(HERE/'test_release.py')],
 [sys.executable,'-B',str(REPO/'android/phone_v123/test_candidate_fast.py')],
 [sys.executable,'-B',str(REPO/'android/phone_v123/test_entry_clock.py')],
 [sys.executable,'-B',str(REPO/'android/phone_v120/test_pullback_size.py')],
 [sys.executable,'-B',str(REPO/'android/phone_v123/test_runtime_health.py')],
 [sys.executable,'-B','-m','unittest','test_handover','test_update_transaction'],
 [sys.executable,'-B','-m','unittest','discover','-s',str(REPO/'android/phone_v124'),'-p','test_*.py'],
 ['node',str(REPO/'android/phone_v124/test_health_ui.cjs')]]
logs=[];count=0
for command in commands:
    r=subprocess.run(command,env=env,capture_output=True,text=True,cwd=WORK)
    text=r.stdout+r.stderr
    logs.append('COMMAND '+repr(command)+'\n'+text)
    if r.returncode:
        (HERE/'test_results.txt').write_text('\n'.join(logs));raise RuntimeError(text)
    count+=sum(int(x) for x in re.findall(r'Ran (\d+) tests?',text))
assert count==82,count
(HERE/'test_results.txt').write_text('\n'.join(logs))
old=json.loads((HERE/'benchmark_host22.json').read_text());new=json.loads((HERE/'benchmark_host23.json').read_text())
assert old['inputs_sha256']==new['inputs_sha256']
assert old['result_sha256']==new['result_sha256']
for name in old['feed']:
    assert old['feed'][name]['final_bars_sha256']==new['feed'][name]['final_bars_sha256']
preserved=['phone_public_ws.py','phone_account.py','phone_pullback_size.py','phone_handover.py',
           'phone_sources.json','phone_performance.py','phone_host.py','phone_runtime_health.py']
for name in preserved:
    assert (HOST/name).read_bytes()==(WORK/'fixture121/host-v22'/name).read_bytes(),name
reduction=lambda a,b:round(100*(1-b/a),2)
report=dict(version='1.2.5',date_kst='2026-11-15',python_tests_passed=count,ui_dom_scenarios=3,
    offline_warm_scan_cpu_reduction_pct=reduction(old['scan_median_cpu_s'],new['scan_median_cpu_s']),
    offline_feed_cpu_reduction_pct={n:reduction(old['feed'][n]['median_cpu_s'],new['feed'][n]['median_cpu_s']) for n in old['feed']},
    benchmark_conditions='Same 289 synthetic/fixture symbols; 150 warm scans per release. 30000 frames x 5 trials for each feed workload. Median process CPU time; no network.',
    preserved_byte_for_byte=preserved,changed_runtime_modules=['phone_frozen_bars.py','phone_feed_fast.py','phone_candidate_fast.py','phone_signal_cache.py'],
    installer_sha256=hashlib.sha256((REPO/'android/phone_1_2_5_setup.py').read_bytes()).hexdigest(),
    candidate_source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')},
    issues_found_and_fixed=['Generated feed indentation rejected during tests; replaced with AST node transform.',
        'Tuple rows in positive signal evidence differed from original lists; positive/manual packet outputs now thaw to original shape.',
        'Initial changing-price benchmark accidentally repeated prices per symbol; corrected workload.',
        'Initial changed-price fast path was about 4% slower; removed max/min call overhead and reran both workloads.'],
    live_phone_verified=False,live_orders_sent=False,limitations=['CPU savings apply to measured code paths, not whole-phone CPU percentage.',
        'No real Fold latency, heat, battery or sustained connection measurement.',
        'No live fill/stop-registration verification, no new profitability backtest.',
        'Single sequential trading engine retained; no new parallel order owner.'])
(HERE/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
