"""Offline tests only. No real OKX connection or live order."""
import threading
import unittest
from unittest.mock import patch
import phone_public_ws as m
class Socket:
    def __init__(self): self.sent=[]
    def send(self,msg):self.sent.append(msg)
class Stream:
    def __init__(self):
        self.lock=threading.RLock();self.ws=Socket();self.connected=True
        self.generation=1;self.last_ping=0.0
class Idle(unittest.TestCase):
    def call(self,s,t):
        with patch.object(m.time,'monotonic',return_value=t):
            m.ping_if_due(s,s.ws)
    def test_continuous_frames_no_ping(self):
        s=Stream();d=m.diagnostics(s)
        for t in (10,20,40,60,80):
            d['frame_at']=t;self.call(s,t)
        self.assertEqual(s.ws.sent,[])
    def test_silence_pings_then_times_out(self):
        s=Stream();self.call(s,20);self.assertEqual(s.ws.sent,['ping'])
        with self.assertRaises(m.PublicHeartbeatTimeout):self.call(s,40)
    def test_inbound_resume_cancels_pending(self):
        s=Stream();self.call(s,20)
        d=m.diagnostics(s);d['frame_at']=21
        self.call(s,40);self.assertEqual(s.ws.sent,['ping'])
        self.assertIsNone(d['pending_ping_at'])
    def test_timely_pong_cancels_pending(self):
        s=Stream();self.call(s,20)
        d=m.diagnostics(s);d['pending_ping_at']=None;d['frame_at']=24
        self.call(s,30);self.assertEqual(s.ws.sent,['ping'])
    def test_old_generation_no_commit(self):
        s=Stream();s.ws.send=lambda _:setattr(s,'generation',2)
        self.call(s,20);self.assertIsNone(m.diagnostics(s)['pending_ping_at'])
if __name__=='__main__':unittest.main(verbosity=2)
