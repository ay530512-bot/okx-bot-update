"""Offline regressions for manual entries and management after schedule retirement."""
from contextlib import nullcontext
from pathlib import Path
from queue import Queue
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

P = (Path.cwd()/'OKX_PC_PACKAGE').resolve()
sys.path[:0] = [str(P), str(P/'core'), str(P/'runtime')]
import okx_click716 as click
from okx_core import BotError
from okx_v5 import RuleEngine
from pc_held_positions import HELD_RULES, EARLY_RULES, manage, note_fill
from pc_sizing import valid
from pc_update import PCUpdater

NOW = 1_795_228_200_000


class RetiredSchedule(unittest.TestCase):
    def test_installed_runtime(self):
        subprocess.run([sys.executable,__file__,'installed-runtime'],check=True,timeout=30)

    def test_all_old_routes_rejected_before_leverage_or_orders(self):
        self.assertEqual(len(HELD_RULES),13)
        for rule in HELD_RULES:
            for restore in (True, False):
                for manual_flag in (False,True):
                    e=NS(journal=NS(data={'legacy_entries207':restore}), click_authorized_signal716='stale')
                    sig=dict(monthly208=rule, click716=manual_flag, signal_id='stale', leverage=5)
                    with self.subTest(rule=rule, restore=restore, click=manual_flag):
                        self.assertFalse(valid(sig))
                        with self.assertRaisesRegex(BotError,'직접 요청'):
                            RuleEngine.entry(e,sig)
        with self.assertRaises(BotError):
            RuleEngine.entry(NS(),dict(click716=True,signal_id='expired',leverage=5))

    def test_tick_with_old_qualified_signal_and_restore_preference(self):
        q=Mock()
        e=NS(snapshot=lambda:{'ms':NOW}, raw_snapshot={'positions':[{'instId':'MANUAL','pos':'3'}]},
             enabled=True, preview=False, recovering=False, user_paused=False, queued_risks=set(),
             entry_cancel=threading.Event(),risk_queue=Queue(),good_snapshots=1,connection_key=(1,1),
             cfg={'execution':{'recovery_snapshots':2},'risk':{}}, refresh_day=Mock(), latch_day=lambda snap:False,
             journal=NS(data={'owned':None,'day':{'ended':False},'legacy_entries207':True}),
             records=lambda:[], selected=lambda n:nullcontext(), slot_count=lambda:3,
             stream=NS(connected=True,generation=1,watch=q),account_stream=NS(generation=1,fresh=lambda:True),
             chat=NS(watch=lambda:['USER'],poll_selected=Mock()), algos=lambda full:([],[]),
             can_open_position=lambda:True,margin_room=lambda s:147,pipeline=Mock(),settle=Mock(),publish_portfolio=Mock(),
             channel_pending={'OLD':{}},approval_result={'monthly208':'trend_long','symbol':'OLD'},
             pc_forward=NS(live_candidates=Mock(side_effect=AssertionError('retired scan'))),
             candidate_decision=Mock(side_effect=AssertionError('automatic scan')),
             entry=Mock(side_effect=AssertionError('automatic submission')))
        with patch('okx_search_capacity.sync'), patch('okx_continuity732.resume_if_ready'):
            RuleEngine.tick(e)
        q.assert_called_once_with(['MANUAL','USER'])
        e.entry.assert_not_called()
        e.pc_forward.live_candidates.assert_not_called()
        e.candidate_decision.assert_not_called()
        e.settle.assert_called_once()
        e.publish_portfolio.assert_called_once()

    def test_stale_restore_commands_and_paper_journal(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name)
            paper=folder/'pc_forward_old.json'
            paper.write_bytes(b'archived qualifying results')
            e=NS(cfg={'risk':{}},send=Mock(),handle=Mock(),
                 journal=NS(data={'legacy_entries207':True,'owned':{'stop_id':'open-sl'}},save=Mock()))
            mobile=NS(complete_control=Mock())
            u=PCUpdater(folder,mobile)
            u.token='a'*32
            u.next_check=float('inf')
            u.bind(e)
            self.assertFalse(hasattr(e,'pc_forward'))
            for mode in ('legacy207','monthly208'):
                command=dict(key=mode,issued_at=time.monotonic(),owner='tester',request_id=mode)
                u.request(command)
                self.assertEqual(mobile.complete_control.call_args.args[0]['status'],'failed')
                e.handle('pc_entry_mode',dict(mode=mode,command=command))
                self.assertEqual(mobile.complete_control.call_args.args[0]['status'],'failed')
            self.assertNotIn('forward',u.snapshot())
            self.assertEqual(e.journal.data,{'legacy_entries207':True,'owned':{'stop_id':'open-sl'}})
            e.journal.save.assert_not_called()
            self.assertEqual(paper.read_bytes(),b'archived qualifying results')
            self.assertEqual(list(folder.iterdir()),[paper])

    def test_no_scanner_or_policy_in_ship_manifest(self):
        from pc_update import verify_package
        m=verify_package(P)
        self.assertEqual(m['version'],'2.7.0')
        for name in ('pc_forward.py','pc_monthly.py','pc_timing.py','pc_timing_rules.json','pc_scalp.py','phone_mobile_entry.py'):
            self.assertNotIn('runtime/'+name,m['files'])
        self.assertFalse(hasattr(RuleEngine,'candidate_decision'))

    def test_original_position_trails_stops_and_times_out(self):
        # Latest stored exit settings supplement the older per-rule defaults.
        e=NS(api=NS(now_ms=lambda:NOW),cfg={'risk':{}},trail=Mock(),close=Mock())
        for key,rule in HELD_RULES.items():
            for direction in ((rule.side,) if rule.side else (-1,1)):
                sig=dict(monthly208=key,pc211=True,pc250=True,pc260=True,
                         action='LONG' if direction==1 else 'SHORT',stop=100-direction,
                         holding_rule={'max_hold_seconds':900})
                o=dict(direction='long' if direction==1 else 'short',v4_signal=sig,stop_px=sig['stop'],entry_ms=NOW-60_000)
                pos=dict(avgPx=100,markPx=100+2*direction)
                self.assertTrue(manage(e,{},pos,o))
                e.trail.assert_called_with({},pos,o,100+direction)
                o['stop_px']=100+direction
                self.assertFalse(manage(e,{},pos,o))
                pos['markPx']=100+.25*direction
                self.assertTrue(manage(e,{},pos,o))
                self.assertIn('보호 손절선 도달',e.close.call_args.args[1])
                o['entry_ms']=NOW-900_000
                pos['markPx']=100+1.5*direction
                self.assertTrue(manage(e,{},pos,o))
                self.assertIn('15분 만료',e.close.call_args.args[1])
        # Pre-time-table plans and new manual records must still use their own exits.
        historical=dict(direction='short',v4_signal={'monthly208':'two_wick','stop':101},stop_px=101,entry_ms=NOW)
        self.assertEqual(EARLY_RULES['two_wick'].target,2)
        self.assertTrue(manage(e,{},dict(avgPx=100,markPx=98),historical))
        self.assertIn('목표가 도달',e.close.call_args.args[1])
        o=dict(direction='long',v4_signal={'click716':True,'pc260':True,'stop':99},stop_px=99,entry_ms=NOW)
        pos=dict(avgPx=100,markPx=103)
        self.assertTrue(manage(e,{},pos,o))
        e.trail.assert_called_with({},pos,o,102)

    def test_record_previous_submitted_fill_once(self):
        data={}
        sig={'monthly208':'scalp_higher','signal_id':'previous','valid_from_ms':NOW}
        note_fill(data,sig)
        note_fill(data,sig)
        self.assertEqual(data['scalp_filled']['scalp_higher']['ids'],['previous'])

    def test_manual_button_reaches_the_same_admission_checks(self):
        sig=dict(click716=True,signal_id='click-id',leverage=5, symbol='BONK-USDT-SWAP', action='LONG')
        request=dict(op='entry',symbol=sig['symbol'],direction='LONG',request_id='btn',
                     deadline=time.monotonic()+5,issued_at=time.monotonic())
        events=[]
        e=object.__new__(RuleEngine)
        e.__dict__.update(click_pending716=request,journal=NS(data={'owned':None}),raw_snapshot={},log=Mock(),cfg={'signals':{},'risk':{}},
             events=NS(put=events.append),can_open_position=lambda:True,empty_slot=lambda:0,selected=lambda n:nullcontext(),
             records=lambda:[],pipeline=Mock(),api=NS(now_ms=lambda:NOW))
        fake_order=dict(client_id='offline',phase='protecting',symbol=sig['symbol'],v4_signal=sig)
        def accept_order(*_):
            e.journal.data['owned']=fake_order
            e.records=lambda:[fake_order]
        with patch('okx_click716.signal',return_value=sig), patch('okx_click716.gate',return_value={'allowed':True}), \
             patch('okx_autonomous.valid_leverage',side_effect=lambda s,c:valid(s)), \
             patch('okx_portfolio.PortfolioEngine.entry',side_effect=accept_order) as submit:
            self.assertTrue(click.poll(e))
        submit.assert_called_once_with(sig,None,0)
        self.assertEqual(events[-1][1]['status'],'submitted')
        self.assertIsNone(e.click_authorized_signal716)
        self.assertIsNone(e.click_pending716)


def check_installed_runtime():
    import pc_run
    pc_run.activate_package()
    import phone_pullback_size, phone_public_ws, phone_public_lanes, phone_performance
    import phone_trend_slot, phone_exit_details, phone_entry_feed, phone_manual_reduction
    import phone_risk_lifecycle, phone_position_details
    with tempfile.TemporaryDirectory() as directory:
        phone_pullback_size.install(P/'core')
        phone_public_ws.install()
        phone_public_lanes.install()
        metrics=phone_performance.install_before_engine(Path(directory))
        try:
            phone_trend_slot.install(P/'core')
            phone_exit_details.install(P/'core')
            phone_entry_feed.install()
            phone_manual_reduction.install(P/'core')
            phone_risk_lifecycle.install(P/'core')
            phone_position_details.install()
            from okx_autonomous import valid_leverage
            from okx_channel701 import check_entry
            from okx_pattern15 import management
            test=unittest.TestCase()
            manual={'click716':True,'pc260':True,'leverage':5,'action':'LONG','stop':99}
            for cfg in ({},{'risk':{'pc_three_slots':True}}):
                test.assertTrue(valid_leverage(manual,cfg))
                for name in HELD_RULES:
                    old=dict(manual,monthly208=name)
                    test.assertFalse(valid_leverage(old,cfg))
                    with test.assertRaises(BotError):
                        check_entry(NS(),old,100)
            snap={}
            pos={'markPx':103,'avgPx':100}
            engine=NS(cfg={'risk':{},'execution':{'rule_channel701':True}},
                      api=NS(now_ms=lambda:NOW),trail=Mock(),close=Mock())
            for sig in (manual,dict(manual,click716=False,pc250=True,pc211=True,monthly208='scalp_double',
                                    holding_rule={'max_hold_seconds':900})):
                owned=dict(v4_signal=sig,direction='long',stop_px=99,entry_ms=NOW)
                test.assertTrue(management(engine,snap,pos,owned))
                engine.trail.assert_called_with(snap,pos,owned,102)
        finally:
            metrics.parallel.close()


if __name__=='__main__':
    if sys.argv[1:]==['installed-runtime']:
        check_installed_runtime()
    else:
        unittest.main()
