import copy
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import patch, Mock
from execution_harness import Harness, FakeExchange, D, BotError, dec, trend, NETWORK_ATTEMPTS
import phone_morning_short as m

def stamp(s):
    return int(datetime.fromisoformat(s+'+09:00').timestamp()*1000)

T = stamp('2026-11-17T05:15:00')

def fixture(t=T, symbol='MORNING-USDT-SWAP'):
    b = [[t-(70-i)*m.STEP,100,100.5,99.5,100,100] for i in range(70)]
    for i,v in enumerate([(104,110,103,109),(109,109.5,103.5,104),(104,104.5,102,103),
                           (103,106,102.8,105),(105,105.5,101.5,102.4)],65):
        b[i][1:5] = v
    end = t//m.HOUR*m.HOUR
    h = [[end-(70-i)*m.HOUR,100+i,101+i,99+i,100.5+i,100] for i in range(70)]
    return dict(now=t+1000,rows=[dict(symbol=symbol,live_frames={'15m':b,'1H':h,'4H':[]})])

class PureTests(unittest.TestCase):
    def test_boundaries_all_minutes_and_year_roll(self):
        for day in ('2026-11-17','2027-01-01'):
            base=stamp(day+'T00:00:00')
            for minute in range(1440):
                self.assertEqual(m.in_window(base+minute*60000),300<=minute<480)
            self.assertFalse(m.in_window(base+5*m.HOUR-1))
            self.assertTrue(m.in_window(base+8*m.HOUR-1))
            self.assertFalse(m.in_window(base+8*m.HOUR))
    def test_ordered_pattern_and_stop(self):
        b=fixture()['rows'][0]['live_frames']['15m'];v=m.pattern(b)
        self.assertEqual(v['action'],'SHORT');self.assertLess(v['peak_ms'],v['trough_ms'])
        self.assertLess(v['trough_ms'],v['rebound_ms']);self.assertLess(v['rebound_ms'],v['confirmation_ms'])
        self.assertGreater(v['structural_stop'],v['rebound_high']);self.assertGreater(v['pullback_pct'],.02)
    def test_no_rebound_no_new_low_green_bar_or_high_break_no_signal(self):
        for kind in ('no_bounce','green','no_break','new_high','tiny_drop'):
            b=fixture()['rows'][0]['live_frames']['15m']
            if kind=='no_bounce':b[-2][1:5]=[105,106,102.8,103]
            if kind=='green':b[-1][1]=102
            if kind=='no_break':b[-1][4]=103
            if kind=='new_high':b[-2][2]=111
            if kind=='tiny_drop':
                for r in b:
                    r[1:5]=[100+(x-100)*.1 for x in r[1:5]]
            self.assertIsNone(m.pattern(b),kind)
    def test_forming_candle_excluded(self):
        b=fixture()['rows'][0]['live_frames']['15m'];b.append([T,102,130,80,90,999])
        self.assertEqual(m.pattern(trend.completed(b,T+1000,m.STEP,30)),m.pattern(b[:-1]))
    def test_cutoff_clears_only_pending(self):
        state=dict(pending={'symbol':'X'},rank={'symbol':'X'},last=T)
        e=NS(api=NS(now_ms=lambda:stamp('2026-11-17T08:00:00')),journal=NS(data={m.STATE:state,'held':'SHORT'},save=Mock()))
        self.assertIsNone(m.scan(e));self.assertEqual(e.journal.data['held'],'SHORT');self.assertIsNone(state['pending'])

class EntryTests(unittest.TestCase):
    def setUp(self):self.h=None
    def tearDown(self):
        if self.h:self.h.close()
        self.assertEqual(NETWORK_ATTEMPTS,[])
    def harness(self,workers=0,t=T):
        self.h=Harness(fixture(t),workers);return self.h
    def positive(self,workers):
        h=self.harness(workers);s=h.signal();self.assertTrue(m.is_signal(s));self.assertEqual(s['leverage'],5)
        o=h.submit(s);self.assertEqual(o['phase'],'submitted');self.assertFalse(o.get('protection_verified'))
        req=h.api.opening_posts()[0];self.assertEqual((req['side'],req['posSide']),('sell','short'))
        self.assertTrue(req['attachAlgoOrds']);self.assertEqual(dec(o['initial_margin_target']),dec('74.25'))
        h.api.fill(o['client_id']);self.assertTrue(h.reconcile(o));self.assertTrue(o['protection_verified'])
        h.e.entry(s);self.assertEqual(len(h.api.opening_posts()),1)
    def test_single_entry_fill_protection(self):self.positive(0)
    def test_four_worker_entry_fill_protection(self):self.positive(4)
    def test_full_tick_entry(self):
        h=self.harness(4);h.compute()
        for _ in range(3):
            h.ready();h.e.tick()
            if h.e.records():break
        self.assertEqual(len(h.api.opening_posts()),1)
        o=h.e.records()[0];h.api.fill(o['client_id']);h.ready();h.e.tick()
        self.assertEqual(o['phase'],'active');self.assertTrue(o['protection_verified'])
    def test_final_time_limit_even_when_pending(self):
        h=self.harness(t=stamp('2026-11-17T07:45:00'));s=h.signal()
        h.api.now=stamp('2026-11-17T08:00:00');h.ready()
        with self.assertRaisesRegex(BotError,'시간 종료'):m.validate_entry(h.e,s,s['entry_reference'])
        with self.assertRaises(BotError):h.submit(s)
        self.assertEqual(h.api.opening_posts(),[])
    def test_expiry_no_resurrection_or_duplicate_structure(self):
        h=self.harness();s=h.signal();h.api.now=s['expires_ms']+1;h.ready()
        self.assertIsNone(m.scan(h.e));self.assertIsNone(m.scan(h.e));self.assertEqual(h.api.opening_posts(),[])
    def test_no_quotes_no_entry_then_recover(self):
        h=self.harness();h.e.stream.data.clear();self.assertIsNone(h.candidate())
        h.ready();self.assertTrue(m.is_signal(h.candidate()))
    def test_changed_candle_or_stop_touch_block(self):
        for flag in ('changed','stop_touch'):
            h=self.harness();s=h.signal();setattr(h.api,flag,True)
            with self.assertRaises(BotError):h.submit(s)
            self.assertEqual(h.api.opening_posts(),[]);h.close();self.h=None
    def test_wide_spread_missing_channel_block(self):
        for mode in ('spread','book'):
            h=self.harness();s=h.signal()
            if mode=='spread':h.api.spread=dec('.002');h.ready()
            else:h.e.stream.data.pop((s['symbol'],'books5'))
            with self.assertRaises(BotError):h.submit(s)
            self.assertEqual(h.api.opening_posts(),[]);h.close();self.h=None
    def test_rank_change_blocks(self):
        h=self.harness();s=h.signal()
        with patch.object(m,'snapshot_rank',return_value=([],dict(symbol='OTHER-USDT-SWAP',hour=T//m.HOUR*m.HOUR))):
            with self.assertRaisesRegex(BotError,'1위 변경'):h.submit(s)
        self.assertEqual(h.api.opening_posts(),[])
    def test_stale_or_incomplete_hourly_blocks_full_rank(self):
        h=self.harness();h.e.universe.full_market.band_cache.pop(('MORNING-USDT-SWAP','1H'))
        self.assertIsNone(m.scan(h.e));self.assertIn('완료1시간봉 대기',h.e.phone_morning_status)
        self.assertEqual(h.e.phone_trend_inputs['missing_hourly_details'][0]['reason'],'1시간봉 미수신')
    def test_long_reserved_slot_and_common_positions_unchanged(self):
        h=self.harness();s=h.signal()
        long=dict(symbol='OLD-USDT-SWAP',direction='long',v4_signal={'trend130':True})
        with patch.object(h.e,'records',return_value=[long]):
            with self.assertRaisesRegex(BotError,'자리 배분'):trend.require_slot(h.e,s)
            trend.require_slot(h.e,dict(symbol='COMMON-USDT-SWAP'))

class ProtectionTests(unittest.TestCase):
    def engine(self,mark=95,low=94,stop=108,now=None):
        now=now or stamp('2026-11-17T08:15:00')
        b=[[now//m.STEP*m.STEP-(20-i)*m.STEP,100,100.5,99.5,100,1] for i in range(20)]
        e=NS(api=NS(now_ms=lambda:now),journal=NS(save=Mock()),chart_job=lambda s:{'15m':b},close=Mock(),trail=Mock())
        o=dict(symbol='MORNING-USDT-SWAP',direction='short',leverage=5,entry_ms=T,stop_px=stop,client_id='test',profit_state714={'peak_mark':low})
        p=dict(avgPx='102.4',markPx=str(mark));return e,o,p
    def test_after08_trails_and_never_loosens(self):
        e,o,p=self.engine();self.assertTrue(m.manage(e,{},p,o));self.assertEqual(e.trail.call_args.args[-1],96)
        self.assertEqual(o['profit_state714']['desired_stop'],96)
        o['morning_amend_ms']=0;e.chart_job=lambda s:{'15m':[[T+i*m.STEP,100,150,50,100,1] for i in range(20)]}
        m.manage(e,{},p,o);self.assertEqual(o['profit_state714']['desired_stop'],96)
    def test_after08_hit_closes_full(self):
        e,o,p=self.engine(mark=109);self.assertTrue(m.manage(e,{},p,o));e.close.assert_called_once()
    def test_stale_atr_keeps_exchange_stop(self):
        e,o,p=self.engine();e.chart_job=lambda s:{};self.assertFalse(m.manage(e,{},p,o));e.trail.assert_not_called()
    def test_observed_low_is_persisted_no_partial_latch(self):
        e,o,p=self.engine(mark=90,low=94);m.observe(e,{},p,o)
        self.assertEqual(o['profit_state714']['peak_mark'],90);self.assertNotIn('partial_due721',o['profit_state714'])
        p['markPx']='94';m.observe(e,{},p,o);self.assertEqual(o['profit_state714']['peak_mark'],90)
    def test_stale_ws_low_used_but_stale_last_not_used(self):
        e,o,p=self.engine();e.profit_lock714=threading.Lock();e.profit_marks714={'test':dict(side=-1,entry=102.4,peak=90,last=91,last_ms=e.api.now_ms()-20000)}
        result=m.observe(e,{},p,o);self.assertEqual(result['markPx'],'95');self.assertEqual(o['profit_state714']['peak_mark'],90)

if __name__=='__main__':unittest.main(verbosity=2)
