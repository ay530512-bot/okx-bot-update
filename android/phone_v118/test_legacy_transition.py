"""One-time bootstrap retains the old manager until its own natural close."""
import copy
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import Mock, patch
import phone_button_upgrade as u
import phone_handover as h
from test_handover import fixtures


class Legacy(unittest.TestCase):
    def simulate(self, requested=True, additional_stop=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'runtime-q2x').mkdir()
            old=root/'host-v15';old.mkdir()
            j,_,_=fixtures(requested)
            original=copy.deepcopy(j['owned'])
            h.save_json(u.journal_path(root),j)
            pid=os.getpid()
            h.save_json(root/'phone_service_status.json',{'host_pid':pid})
            state={'alive':True,'signals':0,'sleeps':0,'natural_closed':False}
            def event(reason):
                j['entry_continuity732']['history'].append(dict(ms=100+len(j['entry_continuity732']['history']),
                    event='operator_stop',reason=reason))
            def send_signal(given,sig):
                self.assertEqual((given,sig),(pid,signal.SIGTERM))
                state['signals']+=1
                j['entry_continuity732']['requested']=False
                event('사용자가 신규 진입 중지')
                if not j['owned']:
                    self.assertTrue(state['natural_closed'])
                    event('사용자가 프로그램 종료');state['alive']=False
                h.save_json(u.journal_path(root),j)
            def wait(seconds):
                state['sleeps']+=1
                if state['sleeps']==1:
                    self.assertEqual(j['owned'],original)
                if state['sleeps']==2:
                    # The pre-existing strategy, not updater, closes its trade.
                    j['owned']=None;state['natural_closed']=True
                    if additional_stop:event('사용자가 신규 진입 중지')
                    h.save_json(u.journal_path(root),j)
            original_read=Path.read_bytes
            def read_bytes(path):
                if path==Path('/proc')/str(pid)/'cmdline':
                    return str(old/'phone_host.py').encode()+b'\0'
                return original_read(path)
            with (patch.object(u.Path,'read_bytes',read_bytes),
                  patch.object(u,'process_token',side_effect=lambda _: 'host-token' if state['alive'] else None),
                  patch.object(u.os,'kill',side_effect=send_signal) as sig,
                  patch.object(u.time,'sleep',side_effect=wait),
                  patch.object(u,'wait_released'),
                  patch.object(u,'inspect_account',return_value='account'),
                  patch.object(u,'read_flat_account',return_value='account')):
                ack=u.legacy_transition(root,old,{pid:'host-token'},Mock(),{})
            self.assertEqual(sig.call_count,2)
            self.assertTrue(state['natural_closed'])
            return ack,h.load(u.journal_path(root))
    def test_active_intent_restored_after_natural_close_without_manual_pause(self):
        ack,j=self.simulate()
        self.assertTrue(ack['requested'])
        self.assertTrue(j['entry_continuity732']['requested'])
    def test_previously_paused_does_not_become_live(self):
        ack,j=self.simulate(requested=False)
        self.assertFalse(ack['requested'])
    def test_operator_stop_during_wait_prevents_auto_resume(self):
        ack,j=self.simulate(additional_stop=True)
        self.assertFalse(ack['requested'])


if __name__=='__main__':unittest.main()
