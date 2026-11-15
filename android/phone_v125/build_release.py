"""Build pinned 1.2.4 -> 1.2.5 immutable input and feed hot-path optimization."""
from pathlib import Path
import hashlib
import importlib.util

HERE=Path(__file__).resolve().parent
ANDROID=HERE.parent
ROOT=ANDROID.parent.parent/'fixture121'


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def main():
    prev=load(ANDROID/'phone_1_2_4_setup.py','release124')
    expected=prev.candidate(prev.read_pins(ROOT))
    assert all((ROOT/'host-v22'/n).read_bytes()==b for n,b in expected.items())
    pins={n:hashlib.sha256(b).hexdigest() for n,b in expected.items()}
    src=(ANDROID/'phone_1_2_4_setup.py').read_text()
    header=src[:src.index('PINNED =')].replace('1.2.3 -> 1.2.4 periodic keepalive regression candidate','1.2.4 -> 1.2.5 CPU overhead reduction')
    helpers=src[src.index('\ndef digest(')+1:src.index('\ndef candidate(originals)')+1].replace('1.2.3','1.2.4').replace('host-v21','host-v22')
    candidate=src[src.index('\ndef candidate(originals)')+1:src.index('\ndef stage(')+1]
    start=candidate.index("    files['phone_public_ws.py']")
    end=candidate.index("    service = originals['phone_service.py']")
    candidate=candidate[:start]+"    for name, text in MODULES.items():\n        files[name] = text.encode('utf-8')\n"+candidate[end:]
    for a,b in [('1.2.4','1.2.5'),('1.2.3','1.2.4'),('phone-service-22','phone-service-23'),('phone-service-21','phone-service-22'),('v22 managed','v23 managed'),('v21 managed','v22 managed'),('CURRENT = 22','CURRENT = 23'),('CURRENT = 21','CURRENT = 22'),('host-v21','host-v22'),('host-v20','host-v21')]:
        candidate=candidate.replace(a,b)
    tail=src[src.index('\ndef stage(')+1:].replace('host-v22','host-v23').replace('1.2.4','1.2.5').replace('연결 유지 방식 복원 후보','반복 봉 변환 및 시세 처리 부하 개선')
    output=header+'PINNED = '+repr(pins)+"\nHOST_OLD = 'host-v22'\nHOST_NEW = 'host-v23'\n"
    output+='MODULES = '+repr({name:(HERE/name).read_text() for name in ('phone_frozen_bars.py','phone_feed_fast.py','phone_signal_cache.py','phone_candidate_fast.py')})+'\n'
    dest=ANDROID/'phone_1_2_5_setup.py';dest.write_text(output+'\n'+helpers+candidate+tail)
    installer=load(dest,'release125')
    files=installer.candidate(installer.read_pins(ROOT))
    installer.stage(ROOT,files);installer.stage(ROOT,files)
    allowed={'phone_signal_cache.py','phone_candidate_fast.py','phone_service.py','phone_mobile.py','phone_update.py','phone_button_upgrade.py','phone_button_old_sources.json'}
    assert {n for n in expected if files[n]!=expected[n]} == allowed
    assert set(files)-set(expected) == {'phone_frozen_bars.py','phone_feed_fast.py'}
    print('Transport, account, sizing, handover and strategy sources preserved')
    print('Installer:',len(dest.read_bytes()),hashlib.sha256(dest.read_bytes()).hexdigest())


if __name__=='__main__':main()
