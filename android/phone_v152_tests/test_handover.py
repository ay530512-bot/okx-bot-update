"""Offline position handover tests; test API exposes GETs only."""
import copy
import hashlib
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import phone_handover as h
import phone_button_upgrade as u


def fixtures(requested=True):
    account = hashlib.sha256(b'fixture-account').hexdigest()
    c = dict(schema=1, requested=requested, account=account, exchange='okx',
             policy_hash='unchanged', budget=2,
             history=[dict(ms=1, event='started', reason='original intent')])
    owned = dict(symbol='X-USDT-SWAP', direction='long', quantity='2', avg_px='100',
                 phase='active', algo_client_id='sl-a', stop_px='95',
                 partial_used=True, peak_roe=.4, entry_ms=1000, client_id='entry-a')
    journal = dict(version=1, account=account, owned=owned, extra_owned=None,
                   additional_owned=[], entry_continuity732=c,
                   seen_signals=['already-traded'], day={'base':'300'})
    snapshot = dict(config={'uid':'fixture-account','acctLv':'2','posMode':'long_short_mode'},
                    positions=[dict(instId='X-USDT-SWAP',posSide='long',mgnMode='isolated',
                                    pos='2',avgPx='100',markPx='103')], orders=[])
    algo = dict(instId='X-USDT-SWAP',posSide='long',side='sell',tdMode='isolated',
                algoId='exchange-sl-a',algoClOrdId='sl-a',state='live',slTriggerPxType='mark',
                slOrdPx='-1',slTriggerPx='95',sz='2',closeFraction='')
    return journal, snapshot, [algo]


class ReadAPI:
    def __init__(self, snap, algos):
        self.snap, self.algos = snap, algos
        self.calls = []
        self.callback = None
    def snapshot(self):
        self.calls.append('GET snapshot')
        if self.callback:
            callback, self.callback = self.callback, None
            callback()
        return copy.deepcopy(self.snap)
    def pending_algos(self, full=False):
        assert full
        self.calls.append('GET algos')
        return copy.deepcopy(self.algos)


class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'host-v17').mkdir()
        (self.root/'runtime-q2x').mkdir()
        self.j, self.snap, self.algos = fixtures()
        self.path = self.root/'runtime-q2x/bot_state.json'
        self.api = ReadAPI(self.snap, self.algos)
        self.e = SimpleNamespace(journal=SimpleNamespace(data=self.j), api=self.api,
            handle=Mock(), send=Mock(), commands=queue.Queue(), events=queue.Queue(),
            risk_queue=queue.Queue(), queued_risks=set(), entry_cancel=threading.Event(),
            stop_event=threading.Event(), command_wake=threading.Event(), enabled=True,
            preview=False, user_paused=False, run_requested=True, resume_pending=False,
            invalidate=Mock(), log=Mock())
        self.e.journal.save = lambda: h.save_json(self.path, self.e.journal.data)
        self.e.journal.save()
        self.request = dict(protocol=1,nonce='a'*32,created_at=time.time(),host_pid=os.getpid(),
            host_token=h.process_token(os.getpid()),installer_pid=os.getpid(),
            installer_token=h.process_token(os.getpid()),target=str(self.root/'host-v17'))
        h.save_json(self.root/h.REQUEST, self.request)
        self.adapter = h.install(self.e, self.root)
        self.watchdog = patch.object(h, 'start_watchdog').start()
        self.addCleanup(patch.stopall)
    def tearDown(self):
        self.temp.cleanup()
    def run_handover(self):
        self.e.handle('phone_update_handover', {'request':self.request})
        return h.load(self.root/h.ACK)
    def test_owned_partial_history_unchanged_and_only_gets(self):
        original = copy.deepcopy(self.j)
        ack = self.run_handover()
        self.assertEqual(ack['phase'], 'released')
        self.assertTrue(ack['requested'])
        self.assertEqual(self.j, original)
        self.assertEqual(h.load(self.path), original)
        self.assertTrue(self.e.stop_event.is_set())
        self.assertFalse(self.e.enabled)
        self.assertEqual(self.api.calls, ['GET snapshot','GET algos']*2)
        self.watchdog.assert_called_once()
    def test_previously_paused_stays_paused(self):
        self.e.run_requested = False
        self.j['entry_continuity732']['requested'] = False
        self.assertFalse(self.run_handover()['requested'])
        self.assertFalse(self.j['entry_continuity732']['requested'])
    def test_missing_stop_keeps_manager_and_recovery_gate(self):
        self.api.algos.clear()
        ack = self.run_handover()
        self.assertEqual(ack['phase'], 'deferred')
        self.assertFalse(self.e.stop_event.is_set())
        self.assertTrue(self.e.resume_pending)
        self.assertTrue(self.e.recovering)
        self.assertFalse(self.e.enabled)
    def test_active_order_or_partial_fill_defers_without_shutdown(self):
        for key in ('pending_add','market_fill_check_pending','close_requested','cleanup_legs'):
            with self.subTest(key=key):
                self.j['owned'][key] = True
                self.assertEqual(self.run_handover()['phase'],'deferred')
                self.assertFalse(self.e.stop_event.is_set())
                del self.j['owned'][key]
        self.api.snap['orders'] = [{}]
        self.assertEqual(self.run_handover()['phase'],'deferred')
    def test_operator_command_arriving_during_get_aborts_handover(self):
        self.api.callback = lambda:self.e.commands.put(('pause',{}))
        self.assertEqual(self.run_handover()['phase'],'deferred')
        self.assertFalse(self.e.stop_event.is_set())
        self.assertEqual(self.e.commands.get()[0],'pause')
    def test_protection_trigger_arriving_during_get_aborts(self):
        self.api.callback = lambda:self.e.risk_queue.put('SL')
        self.assertEqual(self.run_handover()['phase'],'deferred')
        self.assertFalse(self.e.stop_event.is_set())
    def test_late_stop_wins_after_commit_and_never_executes_close(self):
        ack = self.run_handover()
        self.e.send('mobile_control',op='close_all',request_id='test',owner='test')
        self.assertEqual(h.load(self.root/h.CANCEL)['nonce'],ack['nonce'])
        u.apply_late_stop(self.root,ack)
        self.assertFalse(h.load(self.path)['entry_continuity732']['requested'])
        self.assertEqual(h.load(self.path)['owned'],self.j['owned'])
        self.adapter.original_send.assert_not_called()
    def test_expired_cancelled_or_wrong_pid_request_never_stops(self):
        for change in ({'created_at':time.time()-91},{'host_pid':1},{'installer_token':'wrong'},
                       {'target':'/tmp/not-owned'}):
            r = dict(self.request,**change)
            h.save_json(self.root/h.REQUEST,r)
            self.assertFalse(h.valid_request(self.root,r))
        (self.root/h.REQUEST).unlink()
        self.assertFalse(h.valid_request(self.root,self.request))
    def test_cancel_during_reads_prevents_late_commit(self):
        self.api.callback = lambda:(self.root/h.REQUEST).unlink()
        self.assertEqual(self.run_handover()['phase'],'deferred')
        self.assertFalse(self.e.stop_event.is_set())
    def test_api_failure_does_not_change_journal_or_stop_manager(self):
        self.api.callback = Mock(side_effect=OSError('HTTP timeout'))
        original = copy.deepcopy(self.j)
        self.assertEqual(self.run_handover()['phase'],'deferred')
        self.assertEqual(self.j,original)
        self.assertFalse(self.e.stop_event.is_set())
    def test_no_watchdog_means_no_handover(self):
        self.watchdog.side_effect = OSError('spawn failed')
        self.assertEqual(self.run_handover()['phase'], 'deferred')
        self.assertFalse(self.e.stop_event.is_set())


class Reconciliation(unittest.TestCase):
    def test_multislot_and_multileg_preservation(self):
        j,s,a=fixtures()
        j['extra_owned']=dict(j['owned'],symbol='Y-USDT-SWAP',direction='short',algo_client_id='sl-b')
        s['positions'].append(dict(s['positions'][0],instId='Y-USDT-SWAP',posSide='short'))
        a.append(dict(a[0],instId='Y-USDT-SWAP',posSide='short',side='buy',algoClOrdId='sl-b',algoId='b'))
        self.assertIsInstance(h.validate_protected(j,s,a),str)
        j['owned']['legs']=[dict(algo_client_id='sl-a',quantity='1',stop_px='95'),
                            dict(algo_client_id='sl-c',quantity='1',stop_px='96')]
        a[0]['sz']='1'
        a.append(dict(a[0],algoClOrdId='sl-c',algoId='c',slTriggerPx='96'))
        self.assertIsInstance(h.validate_protected(j,s,a),str)
        a[0]['closeFraction']='1'
        with self.assertRaises(ValueError):h.validate_protected(j,s,a)
    def test_wrong_stop_side_size_account_duplicates_and_unknown_positions(self):
        for delta in ({'sz':'1'},{'slTriggerPx':'94'},{'side':'buy'}, {'state':'canceled'},
                      {'slTriggerPxType':'last'}, {'slOrdPx':'90'}, {'tdMode':'cross'},
                      {'slTriggerPx':'NaN'}):
            j,s,a=fixtures();a[0].update(delta)
            with self.subTest(delta=delta),self.assertRaises(ValueError):h.validate_protected(j,s,a)
        j,s,a=fixtures();a.append(copy.deepcopy(a[0]))
        with self.assertRaises(ValueError):h.validate_protected(j,s,a)
        j,s,a=fixtures();s['positions'].append(dict(s['positions'][0],instId='manual'))
        with self.assertRaises(ValueError):h.validate_protected(j,s,a)
        j,s,a=fixtures();s['config']['uid']='other'
        with self.assertRaises(ValueError):h.validate_protected(j,s,a)
    def test_legacy_restore_only_our_exact_pause_sequence(self):
        before,_,_=fixtures()
        for signals in (1,2):
            after=copy.deepcopy(before);c=after['entry_continuity732'];c['requested']=False
            c['history'] += [dict(ms=2+i,event='operator_stop',reason='사용자가 신규 진입 중지') for i in range(signals)]
            c['history'].append(dict(ms=5,event='operator_stop',reason='사용자가 프로그램 종료'))
            self.assertTrue(u.legacy_resume_allowed(before,after,signals))
            extra=copy.deepcopy(after)
            extra['entry_continuity732']['history'].insert(-1,dict(ms=4,event='operator_stop',reason='사용자가 신규 진입 중지'))
            self.assertFalse(u.legacy_resume_allowed(before,extra,signals))
            before_paused=copy.deepcopy(before);before_paused['entry_continuity732']['requested']=False
            self.assertFalse(u.legacy_resume_allowed(before_paused,after,signals))


if __name__ == '__main__':
    unittest.main()
