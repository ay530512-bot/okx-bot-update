"""Build, validate and offline-test Q2X from verified Q2W; no network/orders."""
from pathlib import Path
import base64, hashlib, importlib.util, json, os, subprocess, sys, tempfile, zipfile
from datetime import datetime,timezone
H=Path(__file__).resolve().parent;app=H/'app';out=H/'release-input';out.mkdir(exist_ok=True)
sha=lambda b:hashlib.sha256(b).hexdigest()
base=json.loads((H/'base_manifest.json').read_text())
archive=H.parent/'trail30_research/release_reference.zip'
assert sha(archive.read_bytes())==base['sha256']
with zipfile.ZipFile(archive) as z:
    assert set(z.namelist())==set(base['files'])
    assert all(sha(z.read(n))==s for n,s in base['files'].items())
names=sorted([*base['files'],'okx_long_wick_exit732.py'])
hashes={n:sha((app/n).read_bytes()) for n in names}
for n in names:
    if n.endswith('.py'):compile((app/n).read_bytes(),n,'exec')
ns={};exec((app/'okx_mobile_assets718.py').read_text(),ns)
assert ns['UI_VERSION']=='7.32-Q2X'
for name in ('index.html','app.js','style.css'):
    assert ns['asset'](name)==(app/'mobile_assets'/name).read_bytes()
assert "UI_BUILD='7.32-Q2X'" in ns['ASSETS']['app.js']
assert '732q2x' in ns['ASSETS']['index.html']
assert 'Q2W' not in ns['ASSETS']['app.js']+ns['ASSETS']['index.html']
target=out/'OKX_PROGRAM_UPDATE.zip'
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for n in names:
        info=zipfile.ZipInfo(n,(2026,11,13,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
        info.external_attr=0o100644<<16;z.writestr(info,(app/n).read_bytes())
manifest=dict(schema=1,product='okx-732-desktop',version='7.32-Q2X',sequence=7320224,
              sha256=sha(target.read_bytes()),files=hashes)
(out/'update_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
sys.path.insert(0,str(app))
import okx_update732 as updater
assert updater.VERSION==manifest['version'] and updater.SEQUENCE==manifest['sequence']
with tempfile.TemporaryDirectory() as temp:
    updater.stage_archive(target,manifest,Path(temp)/'app')
    # The updater's extracted files are used for tests, not the working source.
    runtime=Path(temp)/'app'
    env=dict(os.environ,OKX_TEST_APP=str(runtime),PYTHONPATH=str(runtime))
    log=[]
    for test in ('test_long_wick_exit_q2x.py','test_chart_exits_q2w.py'):
        run=subprocess.run([sys.executable,'-S',str(H/test)],env=env,text=True,capture_output=True)
        log.append(test+'\n'+run.stdout+run.stderr)
        assert run.returncode==0,log[-1]
    (H/'test_results.txt').write_text('\n'.join(log))
subprocess.run(['node','--check',str(app/'mobile_assets/app.js')],check=True)
changed=[n for n in names if hashes[n]!=base['files'].get(n)]
assert set(changed)=={'okx_long_wick_exit732.py','okx_profit_guard714.py','okx_partial.py',
 'okx_update732.py','release_info.json','okx_dashboard.py','okx_bot.py',
 'okx_mobile_assets718.py','mobile_assets/index.html','mobile_assets/app.js'}
parity=json.loads((H/'pattern_parity.json').read_text())
assert parity['live_sha256']==hashes['okx_long_wick_exit732.py']
audit=dict(version=manifest['version'],created_utc=datetime.now(timezone.utc).isoformat(),
 base_version=base['version'],base_sha256=base['sha256'],zip_sha256=manifest['sha256'],
 manifest_sha256=sha((out/'update_manifest.json').read_bytes()),changed_files=changed,
 unchanged_file_count=len(names)-len(changed),files=len(names),compiled=True,
 exact_zip_management_tests=29,existing_chart_tests=9,tests_passed=True,
 embedded_mobile_matches=True,javascript_syntax=True,updater_stage_archive=True,
 pattern_parity=parity,new_profitability_test=False,live_orders_sent=0,
 decision='User approved 15m long-wick protection; entries remain Q2W mild726 OR two_wick732.',
 limitations=['Requires fresh confirmed bars and quotes; no zero-loss guarantee.',
 'Live execution net gate is stricter than next-open research simulation.',
 'Fee rates/slippage are estimates; funding during a partial is allocated from the pre-request snapshot.',
 'Legacy partial without a snapshot counts all net funding debits, ignores credits.',
 'Missing accumulated funding disables only the new exit, including unsupported exchange adapters.'])
(H/'validation.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(audit,ensure_ascii=False,indent=2))
