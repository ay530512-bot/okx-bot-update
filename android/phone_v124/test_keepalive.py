"""Regress pre-1.1.7 keepalive cadence without restoring live-feed false resets."""
import unittest
from unittest.mock import patch
from test_public_ws import stream
import phone_public_ws as fix


class Keepalive(unittest.TestCase):
    def test_busy_stream_still_sends_at_20_seconds(self):
        s=stream();s.last_ping=100
        fix.diagnostics(s)['frame_at']=119.999
        with patch('time.monotonic',return_value=119.999):fix.ping_if_due(s,s.ws)
        self.assertEqual(s.ws.sent,[])
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,s.ws)
        self.assertEqual(s.ws.sent,['ping'])

    def test_market_frames_prevent_old_false_timeout(self):
        s=stream();s.last_ping=100
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,s.ws)
        fix.diagnostics(s)['frame_at']=139.999
        with patch('time.monotonic',return_value=140):fix.ping_if_due(s,s.ws)
        self.assertEqual(s.ws.sent,['ping','ping'])
        self.assertEqual(s.generation,1);self.assertTrue(s.connected)

    def test_missing_all_inbound_times_out(self):
        s=stream();s.last_ping=100
        fix.diagnostics(s)['frame_at']=101
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,s.ws)
        with patch('time.monotonic',return_value=140):
            with self.assertRaises(fix.PublicHeartbeatTimeout):fix.ping_if_due(s,s.ws)

    def test_no_flood_one_pending_ping(self):
        s=stream();s.last_ping=100
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,s.ws)
        for now in (120.1,121,125,139.9):
            with patch('time.monotonic',return_value=now):fix.ping_if_due(s,s.ws)
        self.assertEqual(s.ws.sent,['ping'])

    def test_stale_socket_never_pings(self):
        s=stream();old=s.ws;s.ws=object()
        with patch('time.monotonic',return_value=120):fix.ping_if_due(s,old)
        self.assertEqual(old.sent,[])


if __name__=='__main__':unittest.main()
