import sys,unittest
sys.path.insert(0,'chart_update')
from okx_dashboard_data import chart_exit_fields
class ExitLabels(unittest.TestCase):
 def calc(self,side='long',**extra):
  r=dict(direction=side,leverage=10,ct_val='.1',stop_px=98 if side=='long' else 102,phase='active');r.update(extra)
  return chart_exit_fields(dict(avgPx=100,pos=20),r)
 def test_long(self):
  r=self.calc();self.assertEqual(float(r['partial_price']),102);self.assertIn('+2.00 USDT',r['partial_note']);self.assertIn('-4.00 USDT',r['stop_note'])
 def test_short(self):
  r=self.calc('short');self.assertEqual(float(r['partial_price']),98);self.assertIn('+2.00 USDT',r['partial_note']);self.assertIn('-4.00 USDT',r['stop_note'])
 def test_profitable_stop(self):self.assertIn('+2.00 USDT',self.calc(stop_px=101)['stop_note'])
 def test_used(self):self.assertIsNone(self.calc(partial_used=True)['partial_price'])
 def test_pending(self):self.assertIsNone(self.calc(phase='partial_closing')['partial_price'])
 def test_unsplittable(self):self.assertIsNone(self.calc(partial_unsplittable=True)['partial_price'])
 def test_missing(self):self.assertEqual(self.calc(ct_val=None)['stop_note'],'예상 손익 미확인')
 def test_nonfinite(self):self.assertIsNone(self.calc(ct_val='NaN')['partial_price'])
 def test_actual_leverage(self):self.assertEqual(float(self.calc(leverage=5)['partial_price']),104)
if __name__=='__main__':unittest.main()
