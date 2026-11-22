"""Upgrade an offline 2.8.1 fixture with the production phone and supervisor path."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import patch

from test_pc281 import P, ReadOnlyExchange, boot, record_start, stop_from_phone, HELD, route_control
import pc_update

def upgrade(asset):
    """Use the PC 2.8.1 phone button/supervisor for both a stopped and a running user intent."""
    from zipfile import ZipFile
    raw=asset.read_bytes()
    with ZipFile(asset) as z:target=json.loads(z.read('OKX_PC_PACKAGE/pc_release.json'))
    manifest=dict(format=1,revision=target['revision'],version=target['version'],bytes=len(raw),
                  sha256=hashlib.sha256(raw).hexdigest(),commit='a'*40,notes='offline')
    for active in (False,True):
        with TemporaryDirectory() as d:
            root=Path(d);fake=ReadOnlyExchange()
            old,up=boot(root,fake);record_start(old)
            old,up=boot(root,fake)
            if not active:stop_from_phone(old,up)
            assert bool(old.run_requested)==active
            fake.holding();old.journal.data['owned']=copy.deepcopy(HELD);old.journal.save()
            stage=pc_update.download_stage;seen=[]
            def launch(args, env):
                current=Path(args[4]).parent;seen.append(current)
                if current==P:
                    up.token=env['OKX_PC_SUPERVISOR'];up.available=manifest
                    cmd=dict(op='update',key='install_'+str(target['revision']),request_id='phone-test',owner='phone',issued_at=time.monotonic())
                    with patch.object(up,'latest',return_value=manifest),patch.object(pc_update,'download_stage',side_effect=lambda a,b,c:stage(a,b,c,download=lambda *x:raw)):
                        route_control(old,cmd,up.mobile);old.handle(*old.commands.get(timeout=10))
                    assert up.restart,up.message
                    assert old.journal.data['owned']==HELD
                    return NS(wait=lambda timeout:pc_update.RESTART)
                env=dict(env,OKX_PC_TEST_PACKAGE=str(current),PYTHONPATH=os.pathsep.join([str(current),str(current/'runtime'),str(current/'core'),str(Path(__file__).resolve().parent),str(Path(sys.modules['test_pc281'].__file__).resolve().parent)]))
                proc=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--verify',str(root),str(active)],env=env,capture_output=True,text=True)
                assert proc.returncode==0,proc.stderr
                return NS(wait=lambda timeout:0)
            assert pc_update.supervise(root,P,[],launch=launch)==0
            assert len(seen)==2 and pc_update.read_json(root/'pc_update_result.json')['message']==target['version']+' 설치 완료'
            print('2.8.1 ->',target['version'],'stored entry intent',active,'and protected holding verified')
if __name__=='__main__':
    if sys.argv[1:2]==['--upgrade']:upgrade(Path(sys.argv[2]).resolve())
    elif sys.argv[1:2]==['--verify']:
        from phone_mobile import mobile_module
        root=Path(sys.argv[2]);fake=ReadOnlyExchange();fake.holding()
        e,u=boot(root,fake);assert bool(e.run_requested)==(sys.argv[3]=='True')
        held=e.journal.data['owned']
        assert all(held.get(k)==v for k,v in HELD.items()),(held,HELD)
        assert 'kst_close_ms' not in (held.get('v4_signal') or {})
        pc_update.position_handover(e.journal.data,fake.snapshot(),fake.pending_algos(full=True))
        assert mobile_module(P/'core').UI_VERSION=='PC-'+u.release['version']
        pc_update.signal_ready(root)
    else:raise SystemExit('use --upgrade ZIP')
