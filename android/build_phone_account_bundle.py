#!/usr/bin/env python3
"""Build a private, self-contained phone setup file with the user's exact config.

Never commit the generated bundle: it contains the user's strategy configuration.
It contains no API credentials. Desktop release assets are not modified.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import zipfile
from phone_prepare import checked_members, ARCHIVE_SHA256

BOOTSTRAP = '''#!/usr/bin/env python3
"""Private OKX phone account setup. Orders and trading-engine startup are absent."""
import base64,hashlib,importlib.util,io,json,os,sys,zipfile
from pathlib import Path
PAYLOAD = __PAYLOAD__
PAYLOAD_SHA = __PAYLOAD_SHA__
CONFIG_SHA = __CONFIG_SHA__

def put(path, data):
    if path.is_symlink():
        raise ValueError("기존 경로가 연결 파일입니다. 덮어쓰지 않습니다.")
    if path.exists():
        if not path.is_file() or path.read_bytes()!=data:
            raise ValueError("기존 폰 파일이 다릅니다. 덮어쓰지 않습니다: "+path.name)
        os.chmod(path,0o600)
        return
    with path.open('xb') as f:
        os.chmod(path,0o600);f.write(data);f.flush();os.fsync(f.fileno())

def install(root=None, stage=None):
    os.umask(0o077)
    root=Path(root or Path.home()/'okx-phone')
    stage=Path(stage or Path.home()/'okx-phone-stage'/'q2x-source')
    if root.is_symlink():
        raise ValueError("설치 폴더 확인 필요")
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(root,0o700)
    raw=base64.b64decode(PAYLOAD,validate=True)
    if hashlib.sha256(raw).hexdigest()!=PAYLOAD_SHA:
        raise ValueError("설치 파일 해시 불일치")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        required={'phone_prepare.py','phone_account.py','strategy_config.json','Q2X.zip'}
        if set(z.namelist())!=required or len(z.namelist())!=4:
            raise ValueError("설치 파일 구성 오류")
        parts={name:z.read(name) for name in required}
    if hashlib.sha256(parts['strategy_config.json']).hexdigest()!=CONFIG_SHA:
        raise ValueError("설정 원본 해시 불일치")
    for name in ('phone_prepare.py','phone_account.py','strategy_config.json'):
        put(root/name,parts[name])
    spec=importlib.util.spec_from_file_location('phone_prepare_bundle',root/'phone_prepare.py')
    prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)
    members=prepare.checked_members(parts['Q2X.zip'])
    prepare.stage_source(parts['Q2X.zip'],stage)
    meta=dict(version='phone-account-1',source_version='7.32-Q2X',
              source_path=str(stage.resolve()),source_archive_sha256=prepare.ARCHIVE_SHA256,
              source_files={name:hashlib.sha256(data).hexdigest() for name,data in sorted(members.items())},
              config_sha256=CONFIG_SHA,trading_enabled=False)
    put(root/'phone_installation.json',json.dumps(meta,sort_keys=True,ensure_ascii=False,indent=2).encode())
    return root

if __name__=='__main__':
    try:
        root=install()
        print('보내준 설정 원본 저장 완료 / Q2X 소스 검증 완료',flush=True)
        if '--install-only' not in sys.argv:
            os.execv(sys.executable,[sys.executable,'-B',str(root/'phone_account.py')])
    except Exception as exc:
        print('폰 설정 미완료:',str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        print('기존 PC와 주문은 변경하지 않았습니다.')
        sys.exit(1)
'''


def build(config_path, archive_path, output):
    config = Path(config_path).read_bytes()
    parsed = json.loads(config.decode("utf-8-sig"))
    if not isinstance(parsed,dict) or not parsed.get("execution",{}).get("rule_channel701"):
        raise ValueError("expected rule configuration")
    raw = Path(archive_path).read_bytes()
    checked_members(raw)
    # No credentials or local journal are included, only these exact four inputs.
    here=Path(__file__).resolve().parent
    entries={"strategy_config.json":config,"Q2X.zip":raw,
             "phone_account.py":(here/"phone_account.py").read_bytes(),
             "phone_prepare.py":(here/"phone_prepare.py").read_bytes()}
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in entries.items():
            info=zipfile.ZipInfo(name,date_time=(2026,11,13,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data)
    payload=buffer.getvalue()
    script=BOOTSTRAP.replace("__PAYLOAD__",repr(base64.b64encode(payload).decode()))
    script=script.replace("__PAYLOAD_SHA__",repr(hashlib.sha256(payload).hexdigest()))
    script=script.replace("__CONFIG_SHA__",repr(hashlib.sha256(config).hexdigest()))
    Path(output).write_text(script,encoding="utf-8")
    return dict(source_archive_sha256=ARCHIVE_SHA256,config_sha256=hashlib.sha256(config).hexdigest(),
                output_sha256=hashlib.sha256(Path(output).read_bytes()).hexdigest(),size_bytes=Path(output).stat().st_size)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",required=True);parser.add_argument("--archive",required=True);parser.add_argument("--output",required=True)
    args=parser.parse_args()
    print(json.dumps(build(args.config,args.archive,args.output),indent=2))
