"""Old-manager process replacement with a proven external partial close.

Only disposable local processes and GET-only fake exchange observations.
The installer does not rewrite the trade journal or place a protection order.
"""
import copy
import unittest
from unittest.mock import patch
import phone_button_upgrade as upgrade
import phone_handover as handover
import phone_legacy_restart as restart
from phone_account import save_json
from phone_migrate import process_token
import test_legacy_restart as base

ORIGINAL_INSPECT = upgrade.inspect_account


class UpgradeReduction(unittest.TestCase):
    wait=base.Processes.wait
    tearDown=base.Processes.tearDown
    def setUp(self):
        base.Processes.setUp(self)
        self.inspect.stop()
        o=self.j['owned'];o.update(posId='owned-position',leverage=5)
        self.snap.update(ms=4000)
        self.snap['positions'][0].update(pos='1',posId=o['posId'],lever='5')
        save_json(self.root/'runtime-q2x/bot_state.json',self.j)
        self.fills=[dict(instId=o['symbol'],posSide='long',side='buy',fillSz='2',
                        fillTime='1000',billId='1',clOrdId=o['client_id']),
                    dict(instId=o['symbol'],posSide='long',side='sell',fillSz='1',
                         fillTime='3000',billId='2',clOrdId='external-close')]
        def get(path,**params):
            assert path=='/api/v5/trade/fills-history'
            self.api.calls.append('GET fills-history')
            return copy.deepcopy(self.fills)
        self.api.get=get
        def inspect(api,root,pins):
            self.checks+=1
            with patch.object(upgrade,'verify_owner'):
                return ORIGINAL_INSPECT(api,root,pins)
        self.inspect=patch.object(upgrade,'inspect_account',side_effect=inspect)
        self.inspect.start()
    def test_existing_quantity_mismatch_can_update_with_exchange_stop_retained(self):
        before=copy.deepcopy(self.j['owned']);old_algos=copy.deepcopy(self.algos)
        ack=restart.checkpoint_restart(self.root,self.old,self.target,self.tokens,self.api,{})
        restart.complete(ack)
        self.assertIsNone(process_token(self.host))
        self.assertTrue(ack['requested']);self.assertTrue(self.api._phone_reduction_handover167)
        self.assertEqual(handover.load(self.root/'runtime-q2x/bot_state.json')['owned'],before)
        self.assertEqual(self.algos,old_algos)
        self.assertTrue(all(x.startswith('GET ') for x in self.api.calls))
        self.assertEqual(self.checks,3)
    def test_missing_reduction_proof_keeps_existing_manager_running(self):
        self.fills=[]
        with self.assertRaisesRegex(ValueError,'대조 대기'):
            restart.checkpoint_restart(self.root,self.old,self.target,self.tokens,self.api,{})
        self.assertIsNotNone(process_token(self.host));self.assertIsNone(self.p.poll())
        self.assertEqual(handover.load(self.root/'runtime-q2x/bot_state.json'),self.j)


if __name__=='__main__':unittest.main(verbosity=2)
