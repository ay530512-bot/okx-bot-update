"""Real pinned mobile server adapter; mocked chart feed, no exchange access."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
import urllib.request
import urllib.error

class Integration(unittest.TestCase):
    def test_authenticated_update_queue_and_asset(self):
        core=Path(os.environ['OKX_TEST_CORE'])
        sys.path.insert(0,str(core))
        from phone_mobile import mobile_module
        from phone_host import route_control, View
        module=mobile_module(core)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'runtime-q2x';root.mkdir()
            mobile=module.PhoneMobile(root,{},dict(module.credential('fixture-pass'),https_host='',controls_enabled=True),feed_factory=lambda *a: Mock(),port=0)
            try:
                mobile.start()
                host=f'127.0.0.1:{mobile.port}'
                url='http://'+host+'/api/control/update'
                body=json.dumps({'client_id':'integration_update_001'}).encode()
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(urllib.request.Request(url,data=body,headers={'Origin':'http://'+host,'Content-Type':'application/json'}))
                self.assertIn(caught.exception.code,(401,403))
                import time
                mobile.sessions['fixture-session']=time.monotonic()+60
                headers={'Origin':'http://'+host,'Content-Type':'application/json','Cookie':'mobile_session=fixture-session'}
                with urllib.request.urlopen(urllib.request.Request(url,data=body,headers=headers)) as response:
                    result=json.load(response)
                self.assertEqual(result['status'],'queued')
                headers['Origin']='https://untrusted.example'
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(urllib.request.Request(url,data=body,headers=headers))
                self.assertEqual(caught.exception.code,403)
                command=mobile.control_commands.get_nowait()
                self.assertEqual(command['op'],'update')
                mobile.updater=Mock(installing=False)
                engine=Mock();route_control(engine,command,mobile)
                mobile.updater.request.assert_called_once_with(command)
                engine.send.assert_not_called()
                mobile.updater.installing=True
                with self.assertRaises(ValueError):mobile.enqueue_control('prepare','fixture-owner','integration_prepare_01')
                route_control(engine,dict(command,op='confirm'),mobile)
                engine.send.assert_not_called()
                self.assertIn(b'mobileUpdateButton',module.asset('index.html'))
                self.assertNotIn(b'#programUpdate,#globalUpdateNotice{display:none',module.asset('style.css'))
                js=module.asset('app.js')
                self.assertIn(b'phoneOriginalRender',js)
                (Path(temp)/'app.js').write_bytes(js)
                import subprocess
                subprocess.run(['node','--check',str(Path(temp)/'app.js')],check=True)
            finally:mobile.stop()

if __name__=='__main__':unittest.main()
