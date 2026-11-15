import os,sys,subprocess,re,json,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1];WORK=REPO.parent;HOST=WORK/'fixture121/host-v24'
env=dict(os.environ,OKX_TEST_CORE=str(WORK/'core121'),OKX_TEST_HOST=str(HOST),PYTHONPATH=os.pathsep.join(map(str,(HOST,REPO/'android/phone_v118',Path('/tmp/okx123deps')))))
commands=[[sys.executable,'-B',str(HERE/f)] for f in ('test_parallel.py','test_controls.py','test_release.py')]
commands += [[sys.executable,'-B',str(REPO/'android'/f)] for f in ('phone_v125/test_cpu_paths.py','phone_v123/test_candidate_fast.py','phone_v123/test_entry_clock.py','phone_v120/test_pullback_size.py','phone_v123/test_runtime_health.py')]
commands += [[sys.executable,'-B','-m','unittest','test_handover','test_update_transaction'],[sys.executable,'-B','-m','unittest','discover','-s',str(REPO/'android/phone_v124'),'-p','test_*.py'],['node',str(REPO/'android/phone_v124/test_health_ui.cjs')],['node',str(HERE/'test_parallel_ui.cjs')]]
logs=[];count=0
for command in commands:
 r=subprocess.run(command,env=env,capture_output=True,text=True,cwd=WORK,timeout=120)
 text=r.stdout+r.stderr;logs.append('COMMAND '+repr(command)+'\n'+text)
 (HERE/'test_results.txt').write_text('\n'.join(logs))
 if r.returncode:raise RuntimeError(text)
 count+=sum(int(x) for x in re.findall(r'Ran (\d+) tests?',text))
 print('Passed',command[-1],flush=True)
preserved=['phone_public_ws.py','phone_account.py','phone_pullback_size.py','phone_handover.py','phone_sources.json','phone_host.py','phone_runtime_health.py','phone_signal_cache.py','phone_feed_fast.py','phone_frozen_bars.py']
for name in preserved:assert (HOST/name).read_bytes()==(WORK/'fixture121/host-v23'/name).read_bytes(),name
report=dict(version='1.2.6',python_tests_passed=count,ui_checks_passed=7,preserved_byte_for_byte=preserved,
 scope='Offline spawn, packet/candidate equivalence, source correction, 90s expiry, actual quote freshness reader, worker faults, serial restore, authenticated HTTP preference controls, update handover and rollback mocks. No real orders, no direct Fold verification.',development_corrections=['First parallel test fixture had mismatched instrument ctValCcy; corrected the fixture rather than bypassing the real universe filter.','Added request-id replay protection to calculation mode control before release.'],
 installer_sha256=hashlib.sha256((REPO/'android/phone_1_2_6_setup.py').read_bytes()).hexdigest(),source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')})
(HERE/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('TOTAL',count,'Python tests; 7 UI checks')
