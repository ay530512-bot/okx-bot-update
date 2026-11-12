import copy
import hashlib
import http.client
import json
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import phone_host as host
from phone_mobile import mobile_module

BASE = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get('OKX_PHONE_TEST_SOURCE', str(BASE / 'release_q2x/app')))
CONFIG = Path(os.environ.get('OKX_PHONE_TEST_CONFIG', str(BASE / 'upload/strategy_config.json')))
sys.path.insert(0, str(SOURCE))


def snapshot(uid='fixture-account'):
    return dict(config=dict(uid=uid, acctLv='2', posMode='long_short_mode'),
                positions=[], orders=[], equity=Decimal('300'), available=Decimal('300'), ms=int(time.time()*1000))


class API:
    def __init__(self, snaps=None, algos=None):
        self.snaps = snaps or [snapshot()]
        self.algos = algos or []
        self.i = 0

    def snapshot(self):
        value = self.snaps[min(self.i, len(self.snaps)-1)]
        self.i += 1
        return copy.deepcopy(value)

    def pending_algos(self, full=False):
        assert full
        return copy.deepcopy(self.algos)


class HostGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw = CONFIG.read_bytes() if CONFIG.exists() else b'{"fixture":true}'
        (self.root / 'strategy_config.json').write_bytes(self.raw)
        self.pins = dict(source_sha256='f'*64, config_sha256=hashlib.sha256(self.raw).hexdigest())
        self.runtime = host.prepare_runtime(self.root, self.pins)

    def tearDown(self):
        self.temp.cleanup()

    def own(self, api=None, ack=host.ACK):
        return host.take_ownership(self.root, self.runtime, api or API(), self.pins, ack, wait=lambda n: None)

    def test_exact_config_preserved(self):
        self.assertEqual(self.raw, (self.runtime/'strategy_config.json').read_bytes())
        self.assertEqual(self.runtime, host.prepare_runtime(self.root, self.pins))

    def test_runtime_config_conflict_not_overwritten(self):
        (self.runtime/'strategy_config.json').write_text('{}')
        with self.assertRaises(ValueError):
            host.prepare_runtime(self.root, self.pins)
        self.assertEqual('{}', (self.runtime/'strategy_config.json').read_text())

    def test_explicit_pc_confirmation_required(self):
        api = API()
        with self.assertRaises(ValueError):
            self.own(api, 'yes')
        self.assertEqual(api.i, 0)
        self.assertFalse((self.root/'phone_owner.json').exists())

    def test_positions_block_even_if_second_snapshot_flat(self):
        s = snapshot(); s['positions'] = [dict(pos='1')]
        with self.assertRaisesRegex(ValueError, '보유 1'):
            self.own(API([s, snapshot()]))

    def test_pending_regular_blocks(self):
        s = snapshot(); s['orders'] = [dict(ordId='fixture')]
        with self.assertRaisesRegex(ValueError, '미체결 1'):
            self.own(API([s]))

    def test_conditional_blocks(self):
        with self.assertRaisesRegex(ValueError, '조건주문 1'):
            self.own(API(algos=[dict(algoId='fixture')]))

    def test_nonfinite_position_blocks(self):
        s = snapshot(); s['positions'] = [dict(pos='NaN')]
        with self.assertRaises(ValueError):
            self.own(API([s]))

    def test_second_snapshot_position_blocks(self):
        s = snapshot(); s['positions'] = [dict(pos='-1')]
        with self.assertRaises(ValueError):
            self.own(API([snapshot(), s]))
        self.assertFalse((self.root/'phone_owner.json').exists())

    def test_identity_change_blocks(self):
        with self.assertRaisesRegex(ValueError, '계정 변경'):
            self.own(API([snapshot(), snapshot('different')]))

    def test_missing_uid_or_wrong_mode_blocks(self):
        for key, value in [('uid', ''), ('acctLv', '3'), ('posMode', 'net_mode')]:
            s = snapshot(); s['config'][key] = value
            with self.assertRaises(ValueError):
                self.own(API([s]))

    def test_two_checks_and_bound_owner(self):
        api = API()
        self.own(api)
        self.assertEqual(api.i, 2)
        owner = host.verify_owner(self.root, self.pins, snapshot())
        self.assertFalse(owner['pc_remotely_verified'])
        with self.assertRaises(ValueError):
            host.verify_owner(self.root, self.pins, snapshot('wrong'))
        with self.assertRaises(ValueError):
            host.verify_owner(self.root, dict(self.pins, config_sha256='0'*64), snapshot())

    def test_orphan_journal_never_discarded(self):
        p = self.runtime/'bot_state.json'; p.write_text('private existing state')
        with self.assertRaises(ValueError):
            self.own()
        self.assertEqual('private existing state', p.read_text())

    def test_repeat_takeover_not_allowed(self):
        self.own()
        with self.assertRaises(ValueError):
            self.own()

    def test_owner_restart_allows_positions_without_wiping_journal(self):
        self.own()
        p = self.runtime/'bot_state.json'; p.write_text('existing state')
        s = snapshot(); s['positions'] = [dict(pos='2')]
        host.verify_owner(self.root, self.pins, s)
        self.assertEqual(p.read_text(), 'existing state')

    def test_missing_or_other_account_journal_blocks_restart(self):
        with self.assertRaises(ValueError):
            host.verify_restart_journal(self.runtime, snapshot())
        p = self.runtime/'bot_state.json'
        p.write_text(json.dumps(dict(account='wrong')))
        with self.assertRaises(ValueError):
            host.verify_restart_journal(self.runtime, snapshot())
        p.write_text(json.dumps(dict(account=hashlib.sha256(b'fixture-account').hexdigest())))
        host.verify_restart_journal(self.runtime, snapshot())

    def test_watch_labels_position_and_never_calls_post(self):
        s = snapshot()
        s['positions'] = [dict(pos='1', instId='TIA-USDT-SWAP', posSide='short', avgPx='.4', lever='10')]
        view = host.View({}, True)
        host.watch_once(API([s]), view)
        self.assertEqual(view.positions[0]['source'], 'PC')
        self.assertIsNone(view.positions[0]['close_key'])
        self.assertFalse(view.state['live'])

    def test_route_preserves_serial_control_and_rejects_updater(self):
        e = SimpleNamespace(send=Mock(), budget=6)
        m = SimpleNamespace(complete_control=Mock())
        command = dict(op='prepare', owner='a', request_id='b', issued_at=time.monotonic())
        host.route_control(e, command, m)
        e.send.assert_called_once_with('mobile_control', **dict(command, budget=6))
        e.send.reset_mock()
        host.route_control(e, dict(command, op='update'), m)
        e.send.assert_not_called()
        m.complete_control.assert_called_once()


class DummyFeed:
    def __init__(self, *args): pass
    def start(self): pass
    def stop(self): pass
    def select(self, *args): pass


class HostBundle(unittest.TestCase):
    def test_install_idempotent_keeps_private_files_and_rejects_modified_host(self):
        from build_phone_host_bundle import build
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root/'setup.py'
            for name in ('phone_credentials.json', 'phone_installation.json', 'strategy_config.json'):
                (root/name).write_bytes(b'private fixture, never bundled')
            build(output)
            ns = {'__name__':'bundle_test'}
            exec(compile(output.read_text(), str(output), 'exec'), ns)
            entry = ns['install'](root)
            self.assertEqual(entry, ns['install'](root))
            self.assertEqual((root/'phone_credentials.json').read_bytes(), b'private fixture, never bundled')
            self.assertNotIn('private fixture, never bundled', output.read_text())
            entry.write_text('changed')
            with self.assertRaises(ValueError):
                ns['install'](root)
            self.assertEqual(entry.read_text(), 'changed')

    def test_missing_account_or_added_python_module_blocks(self):
        from build_phone_host_bundle import build
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = build(root/'setup.py')
            ns = {'__name__':'bundle_test'}
            exec(compile(output.read_text(), str(output), 'exec'), ns)
            with self.assertRaises(ValueError):
                ns['install'](root)
            for name in ('phone_credentials.json', 'phone_installation.json', 'strategy_config.json'):
                (root/name).write_text('{}')
            entry = ns['install'](root)
            (entry.parent/'requests.py').write_text('untrusted')
            with self.assertRaises(ValueError):
                ns['install'](root)


@unittest.skipUnless((SOURCE/'okx_mobile.py').exists(), 'Set OKX_PHONE_TEST_SOURCE to verified Q2X source')
class LocalUI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mod = mobile_module(SOURCE)
        self.config = dict(self.mod.credential('fixture-password'), https_host='', controls_enabled=True)
        self.mobile = self.mod.PhoneMobile(Path(self.temp.name), {}, self.config, feed_factory=DummyFeed, port=0)
        self.mobile.start()
        self.address = f'127.0.0.1:{self.mobile.port}'
        self.origin = 'http://' + self.address
        self.cookie = ''

    def tearDown(self):
        self.mobile.stop(); self.temp.cleanup()

    def post(self, path, body, origin=None, hostname=None):
        c = http.client.HTTPConnection('127.0.0.1', self.mobile.port, timeout=3)
        c.request('POST', path, json.dumps(body), headers={'Host': hostname or self.address,
                  'Origin': origin or self.origin, 'Content-Type': 'application/json', 'Cookie': self.cookie})
        response = c.getresponse(); result = response.status, json.loads(response.read()), response.getheader('Set-Cookie')
        c.close()
        return result

    def login(self):
        status, _, cookie = self.post('/login', {'password':'fixture-password'})
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', cookie); self.assertIn('SameSite=Strict', cookie)
        self.cookie = cookie.split(';')[0]

    def test_authenticated_local_control_queued_not_directly_executed(self):
        self.assertEqual(self.post('/api/control/prepare', {'client_id':'fixture-request-1'})[0], 401)
        self.login()
        result = self.post('/api/control/prepare', {'client_id':'fixture-request-1'})
        self.assertEqual(result[0], 202)
        self.assertEqual(self.mobile.control_commands.get_nowait()['op'], 'prepare')
        self.assertTrue(self.mobile.control_commands.empty())

    def test_cross_origin_and_host_rejected(self):
        self.login()
        for kwargs in [dict(origin='https://evil.invalid'), dict(hostname='evil.invalid')]:
            self.assertEqual(self.post('/api/control/prepare', {'client_id':'fixture-request-2'}, **kwargs)[0], 403)
        self.assertTrue(self.mobile.control_commands.empty())

    def test_readonly_and_desktop_update_blocked(self):
        self.login()
        self.assertEqual(self.post('/api/control/update', {'client_id':'fixture-request-3'})[0], 400)
        self.mobile.config['controls_enabled'] = False
        self.assertEqual(self.post('/api/control/confirm', {'client_id':'fixture-request-4', 'ticket':'x'})[0], 403)
        self.assertTrue(self.mobile.control_commands.empty())

    def test_duplicate_click_only_enqueues_once(self):
        self.login()
        self.post('/api/control/prepare', {'client_id':'fixture-request-5'})
        self.post('/api/control/prepare', {'client_id':'fixture-request-5'})
        self.assertEqual(self.mobile.control_commands.qsize(), 1)

    def test_capture_no_tk_secrets_hidden_and_phone_assets(self):
        finder = host.NoTk(); sys.meta_path.insert(0, finder)
        try:
            view = host.View({}, True)
            self.mobile.hidden = ('fixture-secret',)
            view.add('fixture-secret')
            self.mobile.capture(view)
            self.assertNotIn('fixture-secret', json.dumps(self.mobile.snapshot))
            self.assertTrue(self.mobile.snapshot['phone_host'])
            self.assertIn('이 폰', self.mod.asset('index.html').decode())
            self.assertNotIn('집 PC', self.mod.asset('index.html').decode())
        finally:
            sys.meta_path.remove(finder)


@unittest.skipUnless(CONFIG.exists() and (SOURCE/'okx_v5.py').exists(), 'Supply private config and verified Q2X source locally')
class Q2XCompatibility(unittest.TestCase):
    def test_source_hashes_and_strategy_config_unchanged_on_construct(self):
        # Transport blocked: constructing the actual engine must not trade/connect.
        import requests
        finder = host.NoTk(); sys.meta_path.insert(0, finder)
        manifest = json.loads((BASE/'android/phone_sources.json').read_text())
        for name, expected in manifest['files'].items():
            self.assertEqual(hashlib.sha256((SOURCE/name).read_bytes()).hexdigest(), expected)
        try:
            with tempfile.TemporaryDirectory() as tmp, patch.object(requests.Session, 'request', side_effect=AssertionError('network forbidden')):
                root = Path(tmp)
                shutil.copyfile(CONFIG, root/'strategy_config.json')
                from okx_v5 import RuleEngine
                keys = dict(OKX_API_KEY='fixture-key', OKX_SECRET_KEY='fixture-secret', OKX_PASSPHRASE='fixture-pass', TRADING_EXCHANGE='okx')
                e = RuleEngine(root, keys, queue.Queue())
                self.assertFalse(e.enabled)
                self.assertTrue(e.user_paused)
                self.assertEqual(e.records(), [])
                self.assertIsNone(e.worker)
                self.assertEqual((root/'strategy_config.json').read_bytes(), CONFIG.read_bytes())
                # Actual lifecycle: pause/quit cannot discard a managed position.
                from okx_core import BotError
                e.journal.data['owned'] = dict(client_id='fixture-position')
                e.handle('pause', {})
                with self.assertRaises(BotError):
                    e.handle('quit', {})
                self.assertFalse(e.stop_event.is_set())
                self.assertIsNotNone(e.journal.data['owned'])
                e.journal.data['owned'] = None
                e.handle('quit', {})
                self.assertTrue(e.stop_event.is_set())
                e.chat.stop()
                for p in [e.executor, e.chart_executor, e.chart_pool, e.approval_pool]:
                    p.shutdown(wait=False, cancel_futures=True)
                e.api.session.close()
        finally:
            sys.meta_path.remove(finder)


if __name__ == '__main__':
    unittest.main()
