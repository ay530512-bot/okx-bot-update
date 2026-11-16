"""Offline validation entry point; never starts the phone service or real API."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

D = Path(__file__).resolve().parent
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
           PYTHONPATH=os.pathsep.join((str(D.parent/'phone_v162'), str(D.parents[2]/'core121'))))
SCRIPTS = ('test_dashboard_live.py', 'test_chart_live.py', 'test_live_rank.py', 'test_export.py', 'test_mobile.py', 'test_transport.py',
           'test_paths.py', 'test_window.py', 'test_latency.py', 'test_handover.py',
           'test_release.py', 'test_execution.py', 'test_morning.py', 'test_switch.py', 'test_lanes.py',
           'test_dynamic_entry.py', 'test_listing_baseline.py', 'test_position_handover.py', 'test_legacy_restart.py',
           'test_restart_ancestry.py')


def main():
    for name in ('prepare_tests.py', 'build_release.py'):
        subprocess.run([sys.executable, str(D/name)], env=ENV, check=True)
    logs = D/'validation_logs'
    logs.mkdir(exist_ok=True)
    previous = json.loads((D/'validation.json').read_text()) if '--failed-only' in sys.argv else None
    release = json.loads((D/'release.json').read_text())
    if previous and previous['release'] != release:
        raise ValueError('Runtime changed; run full validation instead')
    results = previous['results'] if previous else []
    selected = [x['script'] for x in results if x['returncode']] if previous else (*SCRIPTS, 'test_ui.cjs', 'test_positions_ui.cjs', 'test_chart_ui.cjs', 'test_dashboard_ui.cjs')
    for name in selected:
        command = ['node' if name.endswith('.cjs') else sys.executable, str(D/name)]
        result = subprocess.run(command, env=ENV, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=180)
        (logs/(name+'.log')).write_text(result.stdout)
        found = re.search(r'Ran (\d+) tests? in ', result.stdout)
        results = [x for x in results if x['script'] != name]
        results.append(dict(script=name, returncode=result.returncode,
                            tests=int(found[1]) if found else None,
                            log_sha256=hashlib.sha256(result.stdout.encode()).hexdigest()))
        print(f"{name}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
    report = dict(version='1.6.2', release=release,
                  python_tests=sum(x['tests'] or 0 for x in results), javascript_suites=4,
                  all_passed=all(x['returncode'] == 0 for x in results), results=results,
                  actual_phone_tested=False, actual_exchange_order_requests=0,
                  profitability_backtest=False,
                  runner_note='Inherited transport timeout expectation accounts for the upstream fix in websocket-client 1.9; legacy 1.8 is validated separately.',
                  scope='Real strategy/engine functions with fake exchange I/O; synthetic morning candles. UI uses a minimal DOM.')
    (D/'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('release', 'results')}))
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
