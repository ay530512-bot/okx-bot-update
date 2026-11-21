"""Playwright regressions for the PC home and settings, using local mock data only."""
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

PACKAGE = Path(os.environ.get('OKX_PC_TEST_PACKAGE','OKX_PC_PACKAGE')).resolve()
sys.path[:0] = [str(PACKAGE),str(PACKAGE/'runtime'),str(PACKAGE/'core')]
from phone_dashboard_live import Dashboard
from phone_mobile import mobile_module


class ScheduleTest(unittest.TestCase):
    def test_home_projection(self):
        mobile=SimpleNamespace(lock=threading.Lock(),snapshot={'wick_alert_status':'15분봉 수신 대기'})
        for part in ('home','market'):
            self.assertEqual(Dashboard(mobile).snapshot(part=part)['wick_alert_status'],mobile.snapshot['wick_alert_status'])

    def test_only_manual_alerts_even_with_cached_qualified_rules(self):
        app=mobile_module(PACKAGE/'core')
        now=int(time.time()*1000)
        old_state={'legacy_entries207':True,'forward':{'rules':{'trend_long':{'ready':True,'n':20}}}}
        data=dict(ui_version=app.UI_VERSION,captured_ms=now,display_ms=now,account_age_seconds=1,
                  controls_enabled=True,state=dict(account_connected=True),positions=[],movers=[],activities=[],
                  wick_alert_status='텔레그램 연결 설정 필요',program_update=old_state)
        writes, errors=[],[]
        mime={'index.html':'text/html','style.css':'text/css','app.js':'text/javascript'}

        def route(request):
            path=urlsplit(request.request.url).path
            name=path.removeprefix('/') or 'index.html'
            if request.request.method!='GET':
                writes.append(path)
                request.fulfill(status=405)
            elif name in mime:
                request.fulfill(content_type=mime[name]+'; charset=utf-8', body=app.asset(name))
            elif path in ('/api/snapshot','/api/phone/dashboard-live'):
                request.fulfill(json=data)
            else:
                request.fulfill(json={})

        with sync_playwright() as pw:
            launch={}
            if os.getenv('PC_TEST_CHROME'):
                launch=dict(executable_path=os.environ['PC_TEST_CHROME'],args=['--no-sandbox','--disable-gpu','--single-process'])
            browser=pw.chromium.launch(**launch)
            page=browser.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,reduced_motion='reduce')
            page.on('pageerror',lambda err:errors.append(str(err)))
            page.route('**/*',route)
            page.add_init_script('window.setInterval=()=>0; window.EventSource=undefined;')
            page.goto('http://pc.test/')
            el=page.locator
            expect(el('#dashboard')).to_be_visible()
            expect(el('#pcWickStatus')).to_have_text(data['wick_alert_status'])
            expect(el('#pcEntryAlerts')).to_contain_text('24시간 · 롱·숏 수동 진입')
            for selector in ('[data-forward-rule]','#pcWatchGroup','#rules207','#restoreEntryRules','#pcScheduleSettings'):
                expect(el(selector)).to_have_count(0)
            self.assertNotIn('모의 관찰',el('#part-home').text_content())
            self.assertNotIn('자동매매 활성화',el('#part-home').text_content())
            el('#pcManualWicks summary').click()
            expect(el('#pcManualWicks figure')).to_have_count(2)
            expect(el('#pcManualWicks figure').first).to_contain_text('롱 알림')
            expect(el('#pcManualWicks figure').last).to_contain_text('숏 알림')
            el('#pcManualWicks .entry-replay').click()
            el('#pcManualWicks summary').click()
            data['program_update'].update(legacy_entries207=False)
            data.update(wick_alert_status='15분봉 감시 20/31종목',display_ms=now+100,captured_ms=now+100)
            self.assertTrue(page.evaluate('d=>phoneDashboardAccept(d)',data))
            expect(el('#pcWickStatus')).to_have_text(data['wick_alert_status'])
            for width in (320,390,1024):
                page.set_viewport_size({'width':width,'height':844})
                self.assertTrue(el('#pcEntryAlerts').evaluate('r=>r.scrollWidth<=r.clientWidth+1 && r.getBoundingClientRect().right<=innerWidth+1'))
            el('#nav-settings').click()
            expect(el('#mobileUpdateButton')).to_be_visible()
            self.assertNotIn('전일 상위',el('#part-settings').inner_text())
            self.assertNotIn('규칙 복원',el('#part-settings').inner_text())
            el('#nav-chart').click()
            expect(el('#chartLong')).to_be_visible()
            expect(el('#chartShort')).to_be_visible()
            self.assertEqual(writes,[])
            self.assertEqual(errors,[])
            browser.close()


if __name__=='__main__':
    unittest.main()
