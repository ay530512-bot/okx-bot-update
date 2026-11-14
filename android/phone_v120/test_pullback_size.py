"""Offline behavior checks against the exact pinned Q2X application ZIP."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import phone_pullback_size as sizing

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_SHA256 = '6b2a0a90f02cca914ffc5cc0996555e8c1435b7a61618575ee94ee2ebdc2dad1'
FEE = '.0005'
NOW_MS = 5000


class ReadBook:
    """Fixture with no signed exchange client or mutation methods."""
    def __init__(self):
        self.reads = []

    def now_ms(self):
        return NOW_MS

    def public(self, path, **query):
        if path != '/api/v5/market/books' or query != {'instId': 'ARB-USDT-SWAP', 'sz': '400'}:
            raise AssertionError((path, query))
        self.reads.append((path, query))
        return [dict(ts=NOW_MS, asks=[['10', '1000']], bids=[['9.996', '1000']])]


def signal(proof, **extra):
    return dict(action=proof['action'], rule_channel701=True, leverage=10,
                strategy='band_flow', pattern15=True,
                stop='9' if proof['action']=='LONG' else '11',
                decision_record=dict(source='CHANNEL701', volume_wick_proof=proof), **extra)


def entry_fixture():
    instrument = dict(instId='ARB-USDT-SWAP', state='live', settleCcy='USDT',
                      ctType='linear', ctValCcy='ARB', instCategory='1',
                      ctVal='1', lotSz='.01', minSz='.01', tickSz='.01',
                      maxMktSz='1000', lever='10')
    snapshot = dict(equity='83', available='83', positions=[],
                    config=dict(perm='read_only,trade'))
    engine = SimpleNamespace(cfg=dict(risk=dict(entry_cash_reserve_usdt=3),
                                      selection={}, liquidity=dict(max_book_age_ms=1000)),
                api=ReadBook(), stream=SimpleNamespace(ready=lambda *a: True),
                risk_snapshot=lambda _s: None, records=lambda: [],
                snapshot=lambda: snapshot, margin_room=lambda _s: Decimal('80'),
                allocation_seed=lambda s: Decimal(s['equity'])-Decimal(3),
                selection_row=lambda _inst: {}, blocked_manual_symbols=lambda: set())
    return engine, instrument, snapshot


class PullbackSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        archive = ROOT / 'release-input' / 'OKX_PROGRAM_UPDATE.zip'
        if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
            raise AssertionError('wrong pinned Q2X fixture archive')
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.source = Path(temp.name)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(cls.source)
            module_names = [Path(p).stem for p in bundle.namelist()
                            if Path(p).parent == Path('.') and p.endswith('.py')]
        originals = {name: sys.modules.pop(name) for name in module_names if name in sys.modules}

        def restore_modules():
            for name in module_names:
                sys.modules.pop(name, None)
            sys.modules.update(originals)

        cls.addClassCleanup(restore_modules)
        sys.path.insert(0, str(cls.source))
        cls.addClassCleanup(sys.path.remove, str(cls.source))
        cls.policy = importlib.import_module('okx_risk732')
        cls.pattern = importlib.import_module('okx_pattern15')
        cls.wick = importlib.import_module('okx_two_wick732')
        cls.fill = staticmethod(importlib.import_module('okx_market_orders').fill_assessment)
        cls.error = importlib.import_module('okx_core').BotError

    def setUp(self):
        self.e, self.i, self.snap = entry_fixture()
        self.plan = dict(buy='10', sell='10')
        self.original = self.policy.cap_plan
        self.addCleanup(setattr, self.policy, 'cap_plan', self.original)
        sizing.install(self.source)

    def run_plan(self, order, direction=None, original=False):
        cap = self.original if original else self.policy.cap_plan
        return cap(self.e, self.plan, self.i, order,
                   direction or order['action'].lower(), self.snap, FEE)

    def test_both_same_reduces_only_the_baseline_selected_trend_long(self):
        pullback = dict(action='LONG', route721='trend_pullback', confirmation_ms=0)
        two_wick = dict(action='LONG', route721='double_wick', confirmation_ms=0)
        chosen, mode = self.wick.combine(pullback, two_wick)
        order = signal(chosen)
        saved = deepcopy(order)
        old = self.run_plan(order, original=True)
        new = self.run_plan(order)
        self.assertEqual(mode, 'both_same')
        self.assertEqual(order, saved)
        self.assertEqual(Decimal(new['initial_margin_target']), Decimal('5'))
        for field in ('initial_margin_target', 'margin_bound', 'quantity', 'estimated_loss',
                      'initial_quantity', '_initial_risk_budget'):
            self.assertEqual(Decimal(new[field])*4, Decimal(old[field]), field)
        for field in ('long_stop', 'buy', 'cost_rate', '_account_equity', '_allocation_seed',
                      '_fee', 'fixed_initial', 'initial_size_mode'):
            self.assertEqual(new[field], old[field], field)
        self.assertEqual(new['risk732']['target_multiplier'], '0.25')
        self.assertEqual(new['risk732']['route'], 'trend_pullback')
        self.assertEqual(self.wick.combine(pullback, dict(two_wick, action='SHORT')),
                         (None, 'conflict'))

        owned = dict(direction='long', stop_px=new['long_stop'], ct_val=self.i['ctVal'],
                     leverage=order['leverage'], cost_rate=new['cost_rate'],
                     original_risk_budget=new['_initial_risk_budget'],
                     v4_signal=order, initial_size_mode=new['initial_size_mode'])
        stats, reason = self.fill(dict(pos=new['quantity'], avgPx='10', liqPx='8'), owned, self.e.cfg)
        self.assertIsNone(reason)
        self.assertEqual(Decimal(stats['estimated_stop_loss']), Decimal(new['estimated_loss']))
        _, reason = self.fill(dict(pos=new['quantity'], avgPx='10.005', liqPx='8'), owned, self.e.cfg)
        self.assertIn('예상 손실 한도 초과', reason)

    def test_unrelated_orders_have_exact_original_plan(self):
        cases = [('standalone wick long', signal(dict(action='LONG', route721='double_wick'))),
                 ('pullback short', signal(dict(action='SHORT', route721='trend_pullback'))),
                 ('unknown route', signal(dict(action='LONG', route721='other'))),
                 ('missing route', signal(dict(action='LONG'))),
                 ('direction disagrees with proof', dict(signal(dict(action='SHORT', route721='trend_pullback')),
                                                       action='LONG', stop='9')),
                 ('not a 732 channel order', dict(signal(dict(action='LONG', route721='trend_pullback')),
                                                  rule_channel701=False))]
        cases.extend((flag, signal(dict(action='LONG', route721='trend_pullback'), **{flag: True}))
                     for flag in ('click716', 'user_chat_order', 'selected_ai_order'))
        for name, order in cases:
            with self.subTest(name=name):
                self.assertEqual(self.run_plan(order), self.run_plan(order, original=True))

    def test_minimum_lot_and_account_reserve_are_retained(self):
        order = signal(dict(action='LONG', route721='trend_pullback'))
        self.i['minSz'] = '6'
        self.assertEqual(Decimal(self.run_plan(order, original=True)['quantity']), Decimal(20))
        with self.assertRaisesRegex(self.error, '거래소 허용 범위'):
            self.run_plan(order)

        self.i['minSz'] = '.01'
        self.snap['available'] = '8'
        with self.assertRaisesRegex(self.error, '증거금·수수료 부족'):
            self.run_plan(order)

        self.snap['available'] = '83'
        self.i['lotSz'] = '3'
        with self.assertRaisesRegex(self.error, '오차 3% 초과'):
            self.run_plan(order)

    def test_prepare_and_final_recheck_do_not_scale_twice(self):
        order = signal(dict(action='LONG', route721='trend_pullback'))
        self.e.prepared_signal = order
        plan = self.policy.prepare_plan(self.e, self.plan, self.i, dict(askPx='10', bidPx='9.996'),
                                        dict(_v4=order), 'long', self.snap, FEE)
        self.assertEqual(Decimal(plan['quantity']), Decimal('5'))
        with patch.object(self.pattern, 'check_entry', return_value=None) as evidence_check:
            self.policy.submit_check(self.e, plan, self.i, 'long')
            evidence_check.assert_called_once_with(self.e, order, 10.0)
            self.assertEqual(Decimal(plan['quantity']), Decimal('5'))
            self.assertEqual(Decimal(plan['initial_margin_target']), Decimal('5'))
            self.assertEqual(len(self.e.api.reads), 2)

            self.snap['equity'] = '99'  # Changed shared equity implies a new sized plan.
            with self.assertRaisesRegex(self.error, '재산정 대기'):
                self.policy.submit_check(self.e, plan, self.i, 'long')
            self.assertEqual(Decimal(plan['quantity']), Decimal('5'))

    def test_idempotent_overlay_and_source_hash_fail_closed(self):
        current = self.policy.cap_plan
        sizing.install(self.source)
        self.assertIs(self.policy.cap_plan, current)
        path = self.source / 'okx_risk732.py'
        original = path.read_bytes()
        try:
            path.write_bytes(original + b'\n')
            with self.assertRaisesRegex(ValueError, '원본 해시 불일치'):
                sizing.install(self.source)
            self.assertIs(self.policy.cap_plan, current)
        finally:
            path.write_bytes(original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
