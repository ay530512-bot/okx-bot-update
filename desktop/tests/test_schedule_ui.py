"""Run beside OKX_PC_PACKAGE with Playwright Chromium installed."""
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

PACKAGE = Path(os.environ.get('OKX_PC_TEST_PACKAGE', 'OKX_PC_PACKAGE')).resolve()
sys.path[:0] = [str(PACKAGE), str(PACKAGE/'runtime'), str(PACKAGE/'core')]
from phone_dashboard_live import Dashboard
from phone_mobile import mobile_module
from pc_timing import policies


class ScheduleTest(unittest.TestCase):
    def test_home_projection(self):
        mobile = SimpleNamespace(lock=threading.Lock(), snapshot={
            'program_update': {'legacy_entries207': False},
            'wick_alert_status': '텔레그램 연결 설정 필요'})
        for part in ('home', 'market'):
            result = Dashboard(mobile).snapshot(part=part)
            self.assertEqual(result['wick_alert_status'], mobile.snapshot['wick_alert_status'])
            self.assertEqual(result['program_update'], mobile.snapshot['program_update'])

    def test_home_and_settings(self):
        app = mobile_module(PACKAGE/'core')
        rules = {key: dict(ready=False, n=0, pending=False) for key in policies()}
        data = dict(ui_version=app.UI_VERSION, account_age_seconds=1, controls_enabled=True,
                    state=dict(account_connected=True), positions=[], movers=[], activities=[],
                    wick_alert_status='텔레그램 연결 설정 필요',
                    program_update=dict(legacy_entries207=False))
        clock = int(time.time()*1000)
        writes, errors = [], []
        mime = {'index.html':'text/html', 'style.css':'text/css', 'app.js':'text/javascript'}

        def route(request):
            path = urlsplit(request.request.url).path
            name = path.removeprefix('/') or 'index.html'
            if request.request.method != 'GET':
                writes.append(path)
                request.fulfill(status=405)
            elif name in mime:
                request.fulfill(content_type=mime[name]+'; charset=utf-8', body=app.asset(name))
            elif path in ('/api/snapshot','/api/phone/dashboard-live'):
                request.fulfill(json=dict(data, captured_ms=clock, display_ms=clock))
            else:
                request.fulfill(json={})

        with sync_playwright() as pw:
            launch = {}
            if os.getenv('PC_TEST_CHROME'):
                launch.update(executable_path=os.environ['PC_TEST_CHROME'],
                              args=['--no-sandbox','--disable-gpu','--single-process'])
            browser = pw.chromium.launch(**launch)
            page = browser.new_page(viewport=dict(width=390, height=844), is_mobile=True,
                                    has_touch=True, reduced_motion='reduce')
            page.on('pageerror', lambda err: errors.append(str(err)))
            page.route('**/*', route)
            # Feed a new snapshot only when a test state changes.
            page.add_init_script('window.setInterval=()=>0; window.EventSource=undefined;')
            page.goto('http://pc.test/')
            el = page.locator
            home, status = el('#part-home'), el('#pcForwardStatus')
            manual, group = el('#pcManualWicks'), el('#pcWatchGroup')
            eligible, watch = el('#pcEligibleRows > details'), el('#pcWatchRows > details')
            expect(el('#dashboard')).to_be_visible()
            expect(status).to_have_text('실거래 자격 확인 중')
            expect(group).to_be_hidden()
            expect(el('#pcWickStatus')).to_have_text('텔레그램 연결 설정 필요')
            self.assertNotIn('V7.32-Q2X',home.inner_text())

            def refresh():
                nonlocal clock
                clock += 100
                snapshot = dict(data, display_ms=clock, captured_ms=clock)
                self.assertTrue(page.evaluate('(d)=>phoneDashboardAccept(d)', snapshot))
                page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')

            forward = dict(rules=rules, blocked=False, error='')
            data['program_update']['forward'] = forward
            refresh()
            expect(status).to_have_text('실거래 자격을 충족한 규칙이 없습니다.')
            expect(el('#pcWatchCount')).to_have_text(f'모의 관찰 규칙 {len(rules)}개')
            self.assertIsNone(group.get_attribute('open'))
            self.assertNotIn('확정반전 숏',home.inner_text())
            expect(el('#rules207')).to_be_hidden()
            expect(manual.locator('summary')).to_contain_text('롱·숏 수동 진입')
            page.evaluate("()=>window.scrollTo(0,document.documentElement.scrollHeight)")
            clear = el('#pcWatchGroup > summary').evaluate(
                "(r)=>r.getBoundingClientRect().bottom<=document.querySelector('.bottom-nav').getBoundingClientRect().top")
            self.assertTrue(clear)
            if os.getenv('PC_TEST_SCREENSHOT'):
                el('#rules208').screenshot(path=os.environ['PC_TEST_SCREENSHOT'])

            manual.locator('summary').click()
            expect(manual.locator('figure')).to_have_count(2)
            self.assertIn('롱 알림',manual.inner_text())
            self.assertIn('숏 알림',manual.inner_text())
            self.assertNotIn('기준 종가',manual.inner_text())
            expect(manual.locator('.entry-marker').first).to_be_visible()
            el('#pcWatchGroup > summary').click()
            keys = watch.evaluate_all('(rows)=>rows.map(r=>r.dataset.forwardRule)')
            self.assertEqual(set(keys),set(rules))
            self.assertEqual([policies()[k]['start'] for k in keys], sorted(p['start'] for p in policies().values()))
            expect(el('[data-forward-rule="rank_short"] summary')).to_contain_text('16:00–익일 04:00')
            expect(el('[data-forward-rule="late_reversal"] summary')).to_contain_text('20:00–24:00')
            reversal = el('[data-forward-rule="reversal"]')
            reversal.locator('summary').click()
            expect(manual.locator('figure').first).to_be_hidden()
            expect(reversal.locator('figure')).to_be_visible()
            reversal.locator('.entry-replay').click()
            refresh()
            self.assertIsNotNone(reversal.get_attribute('open'))
            reversal.evaluate('(r)=>r.open=false')

            rules['reversal'].update(n=20, ready=True)
            rules['rank_short'].update(n=20, ready=True, pending=True)
            refresh()
            expect(eligible).to_have_count(2)
            self.assertEqual(eligible.first.get_attribute('data-forward-rule'),'reversal')
            expect(el('#pcWatchCount')).to_have_text(f'모의 관찰 규칙 {len(rules)-2}개')
            rules['reversal']['ready'] = False
            refresh()
            expect(eligible).to_have_count(1)
            expect(el('#pcEligibleRows')).to_contain_text('1건 추적 중')
            expect(watch).to_have_count(len(rules)-1)
            for value in rules.values():
                value.update(ready=True,n=20)
            refresh()
            expect(group).to_be_hidden()
            expect(eligible).to_have_count(len(rules))
            forward['blocked'],forward['error'] = True,'모의체결 기록 읽기 실패'
            refresh()
            expect(status).to_contain_text('모의체결 기록 읽기 실패')
            expect(el('#pcEligibleRows')).to_be_hidden()
            forward['blocked'],forward['error'] = False,''
            del rules['reversal']
            refresh()
            expect(status).to_have_text('실거래 자격 확인 중')
            expect(group).to_be_hidden()
            data['program_update']['legacy_entries207'] = True
            refresh()
            expect(el('#rules207')).to_be_visible()
            expect(manual).to_be_visible()
            data['program_update']['legacy_entries207'] = False
            refresh()
            expect(el('#rules207')).to_be_hidden()

            for width in (320,390,1024):
                page.set_viewport_size(dict(width=width,height=800))
                fits=el('#rules208').evaluate('(r)=>r.scrollWidth<=r.clientWidth+1 && r.getBoundingClientRect().right<=innerWidth+1')
                self.assertTrue(fits,width)
            el('#nav-settings').click()
            expect(el('#restoreEntryRules')).to_be_hidden()
            el('#pcScheduleSettings > summary').click()
            expect(el('#restoreEntryRules')).to_be_visible()
            self.assertEqual(writes,[])
            self.assertEqual(errors,[])
            browser.close()


if __name__ == '__main__':
    unittest.main()
