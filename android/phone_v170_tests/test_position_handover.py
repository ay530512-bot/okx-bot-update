"""Real engine fill records + read-only handover validation (no live orders)."""
import copy
import importlib.util
import json
import unittest
import threading
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from execution_harness import Harness,D,HOST,NETWORK_ATTEMPTS
import phone_handover as h
from phone_position_details import describe
from test_morning import fixture

FIXTURES=json.loads((D/'fixtures.json').read_text())['fixtures']
FIXTURES['morning_SHORT']=fixture()
from test_ema_support import fixture as support_fixture
FIXTURES['ema20_support_LONG']=support_fixture()


class RealRecords(unittest.TestCase):
    def test_all_rules_real_records_prove_old_failure_and_new_handover(self):
        spec=importlib.util.spec_from_file_location('previous_handover',HOST.parent/'phone_v153/phone_handover.py')
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        for name,f in FIXTURES.items():
            with self.subTest(rule=name):
                e=Harness(copy.deepcopy(f),0)
                try:
                    o=e.submit(e.signal());e.api.fill(o['client_id']);e.reconcile(o)
                    self.assertEqual(o['phase'],'active');self.assertTrue(o['protection_verified'])
                    self.assertNotIn('avg_px',o)
                    snap=e.e.snapshot();algos=e.api.pending_algos(full=True)
                    # Fake exchange omits these documented response fields;
                    # complete the fixture rather than weakening production.
                    for a in algos:a.update(tdMode='isolated',side='buy' if o['direction']=='short' else 'sell')
                    original=copy.deepcopy(e.e.journal.data);posts=len(e.api.opening_posts())
                    with self.assertRaisesRegex(KeyError,'avg_px'):old.validate_protected(original,snap,algos)
                    self.assertIsInstance(h.validate_protected(original,snap,algos),str)
                    details=describe(o);self.assertNotEqual(details['rule'],'진입 규칙 기록 없음')
                    self.assertEqual(details['source'],'persisted_entry_decision')
                    self.assertTrue(details['evidence']);self.assertEqual(details['confirmed_ms'],o['v4_signal']['valid_from_ms'])
                    self.assertEqual(e.e.journal.data,original);self.assertEqual(len(e.api.opening_posts()),posts)
                    broken=copy.deepcopy(snap);broken['positions'][0]['posId']='different'
                    with self.assertRaisesRegex(ValueError,'식별자'):h.validate_protected(original,broken,algos)
                    with self.assertRaises(ValueError):h.validate_protected(original,snap,[])
                    # Loss/profit and mark changes don't change ownership proof.
                    changed=copy.deepcopy(snap);changed['positions'][0].update(markPx='999',upl='-20')
                    self.assertEqual(h.validate_protected(original,snap,algos),h.validate_protected(original,changed,algos))
                    # Exercise actual pause+rejected-quit semantics; the old
                    # synthetic handover fixture incorrectly added a quit event.
                    from test_handover import fixtures as handover_fixture
                    from phone_legacy_restart import pause_events,restore_intent
                    e.e.journal.data['entry_continuity732']=copy.deepcopy(handover_fixture()[0]['entry_continuity732'])
                    e.e.run_requested=True
                    before=copy.deepcopy(e.e.journal.data)
                    e.e.handle('pause',{})
                    with self.assertRaises(Exception):e.e.handle('quit',{})
                    after=copy.deepcopy(e.e.journal.data)
                    self.assertEqual(pause_events(before,after),[('operator_stop','사용자가 신규 진입 중지')])
                    with patch('phone_legacy_restart.save_json'):
                        self.assertTrue(restore_intent(e.root,before,after)['entry_continuity732']['requested'])
                finally:e.close()
        self.assertFalse(NETWORK_ATTEMPTS)
    def test_absent_or_mismatched_evidence_is_not_invented(self):
        for r in ({},{'direction':'short','v4_signal':{'reason':'some current explanation'}},
                  {'direction':'long','v4_signal':{'decision_record':{'volume_wick_proof':{'route721':'double_wick','action':'SHORT'}}}}):
            d=describe(r);self.assertEqual(d['rule'],'진입 규칙 기록 없음');self.assertEqual(d['evidence'],[])
    def test_real_fill_fields_and_no_silent_price_change(self):
        self.assertEqual(h.entry_average({'fill_px':'2.638611'}),h.number('2.638611'))
        self.assertEqual(h.entry_average({'market_fill_stats':{'avg_px':'2.638611'},'fill_px':'2.6'}),h.number('2.638611'))
        for r in ({},{'fill_px':'NaN'},{'fill_px':'0'}):
            with self.assertRaises(ValueError):h.entry_average(r)
    def test_mobile_capture_keeps_only_display_evidence(self):
        from phone_mobile import mobile_module
        from execution_harness import CORE
        m=mobile_module(CORE)
        mobile=SimpleNamespace(config={},hidden=(),lock=threading.RLock(),chart_cache={})
        details=dict(rule='두꼬리',summary='저장된 조건',evidence=[])
        view=SimpleNamespace(state={},positions=[dict(symbol='X-USDT-SWAP',entry_details=details,secret='DO_NOT_EXPORT')],
            activities=[],data_seen=0,running_state=lambda:('test',))
        m.Mobile.capture(mobile,view)
        self.assertEqual(mobile.snapshot['positions'][0]['entry_details'],details)
        self.assertNotIn('DO_NOT_EXPORT',json.dumps(mobile.snapshot))
    def test_update_error_is_current_and_bounded(self):
        from phone_update import install_failure
        from phone_account import save_json
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'phone_update_result.json'
            save_json(p,dict(phase='deferred',observed_at=101,message='진입 평균가 인계 대조 실패'))
            self.assertIn('평균가',install_failure(root,100))
            self.assertNotIn('평균가',install_failure(root,102))
            save_json(p,dict(phase='deferred',observed_at=101,message='x'*501))
            self.assertNotIn('x'*501,install_failure(root,100))

if __name__=='__main__':unittest.main()
