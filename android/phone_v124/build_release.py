"""Build pinned 1.2.3 -> 1.2.4 transport-only regression candidate."""
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
    prev=load(ANDROID/'phone_1_2_3_setup.py','release123')
    expected=prev.candidate(prev.read_pins(ROOT))
    assert all((ROOT/'host-v21'/n).read_bytes()==b for n,b in expected.items())
    pins={n:hashlib.sha256(b).hexdigest() for n,b in expected.items()}
    src=(ANDROID/'phone_1_2_3_setup.py').read_text()
    header=src[:src.index('PINNED =')].replace('1.2.2 -> 1.2.3 candidate latency patch','1.2.3 -> 1.2.4 periodic keepalive regression candidate')
    helpers=src[src.index('\ndef digest(')+1:src.index('\ndef candidate(originals)')+1].replace('1.2.2','1.2.3').replace('host-v20','host-v21')
    candidate=src[src.index('\ndef candidate(originals)')+1:src.index('\ndef stage(')+1]
    start=candidate.index("    files['phone_candidate_fast.py']")
    end=candidate.index("    service = originals['phone_service.py']")
    candidate=candidate[:start]+'''    files['phone_public_ws.py'] = TRANSPORT_MODULE.encode('utf-8')
    ui=originals['phone_update_ui.js'].decode()
    files['phone_update_ui.js']=replace_once(ui,OLD_HEALTH_UI,HEALTH_UI,'phone_update_ui.js').encode()
    trace=originals['phone_connection_trace.py'].decode()
    files['phone_connection_trace.py']=replace_once(trace,"'phone-public-ws-3',","'phone-public-ws-4', 'phone-public-ws-3',",'phone_connection_trace.py').encode()
'''+candidate[end:]
    for a,b in [('1.2.3','1.2.4'),('1.2.2','1.2.3'),('phone-service-21','phone-service-22'),('phone-service-20','phone-service-21'),('v21 managed','v22 managed'),('v20 managed','v21 managed'),('CURRENT = 21','CURRENT = 22'),('CURRENT = 20','CURRENT = 21'),('host-v20','host-v21'),('host-v19','host-v20')]:
        candidate=candidate.replace(a,b)
    tail=src[src.index('\ndef stage(')+1:].replace('host-v21','host-v22').replace('1.2.3','1.2.4').replace('신호 계산 지연 개선','연결 유지 방식 복원 후보')
    output=header+'PINNED = '+repr(pins)+"\nHOST_OLD = 'host-v21'\nHOST_NEW = 'host-v22'\n"
    for key,value in [('TRANSPORT_MODULE',(HERE/'phone_public_ws.py').read_text()),('HEALTH_UI',(HERE/'health_ui.js').read_text()),('OLD_HEALTH_UI',(ANDROID/'phone_v123/health_ui.js').read_text())]:
        output+=key+' = '+repr(value)+'\n'
    dest=ANDROID/'phone_1_2_4_setup.py';dest.write_text(output+'\n'+helpers+candidate+tail)
    installer=load(dest,'release124')
    files=installer.candidate(installer.read_pins(ROOT))
    installer.stage(ROOT,files);installer.stage(ROOT,files)
    allowed={'phone_public_ws.py','phone_update_ui.js','phone_connection_trace.py','phone_service.py','phone_mobile.py','phone_update.py','phone_button_upgrade.py','phone_button_old_sources.json'}
    assert {n for n in files if files[n]!=expected[n]} == allowed
    print('Preserved all strategy, signal-cache, candidate, account, sizing and handover modules byte-for-byte')
    print('Installer:',len(dest.read_bytes()),hashlib.sha256(dest.read_bytes()).hexdigest())


if __name__=='__main__':main()
