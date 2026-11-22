import unittest
from test_pc280 import OfflineEngine, P, SYMBOL
from pc_candidates import signals, NEW, RULES, FIVE
from pc_wick_entries import WickEntries
from phone_trend_slot import install

class OptionalStrategies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install(P/'core')

    def breakout(self,e):
        end=e.api.now//FIVE*FIVE
        e.api.now=end+200
        rows=[(end+(i-60)*FIVE,100,100.12,99.98,100.01,100) for i in range(60)]
        rows[-1]=(end-FIVE,100.01,100.26,100.,100.24,220)
        hits=signals(rows,FIVE,.01)
        hit=next(h for h in hits if h['variant']=='breakout')
        e.api.bid,e.api.ask=100.24,100.25
        return hit,tuple(rows)

    def test_closed_signal_order_and_disable(self):
        for off in (False,True):
            e=OfflineEngine()
            h,rows=self.breakout(e)
            e.wick_entries.offer(SYMBOL,h,'.01',rows)
            if off:
                e.wick_entries.change_rule('off:breakout')
            e.wick_entries.poll()
            self.assertEqual(len(e.api.orders()),int(not off),e.status())
            if not off:
                held=e.records()[0]
                self.assertEqual(held['v4_signal']['pattern'],'breakout')
                self.assertTrue(e.api.orders()[0]['attachAlgoOrds'])
            else:
                entries=WickEntries(e)
                self.assertIn('breakout',entries.disabled_rules)
                entries.offer(SYMBOL,h,'.01',rows)
                self.assertFalse(entries.pending)
                entries.change_rule('on:breakout')
                self.assertFalse(entries.disabled_rules)

    def test_switches_and_mode_are_independent(self):
        from pc_rule_examples import alert_panel
        e=OfflineEngine()
        panel=alert_panel()
        for rule in RULES:
            self.assertIn('data-entry-rule="'+rule+'"',panel)
            e.wick_entries.change_rule('off:'+rule)
            self.assertEqual(e.wick_entries.disabled_rules,[rule])
            e.wick_entries.change_rule('on:'+rule)
        self.assertEqual(e.wick_entries.mode,'standard')
