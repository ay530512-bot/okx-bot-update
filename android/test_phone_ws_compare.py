"""Offline checks with the actual websocket-client frame parser and fake peers."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import websocket
import phone_ws_compare as diag


class Clock:
    value = 0.0
    def __call__(self):
        return self.value


class ComparisonTests(unittest.TestCase):
    def test_partial_frame_survives_socket_timeout_in_library(self):
        # Original one-second recv timeout alone does not discard buffered bytes.
        pieces = iter([b'\x81\x05', b'he', websocket.WebSocketTimeoutException(), b'llo'])
        def receive(n):
            item = next(pieces)
            if isinstance(item, Exception):
                raise item
            return item
        buf = websocket._abnf.frame_buffer(receive, False)
        with self.assertRaises(websocket.WebSocketTimeoutException):
            buf.recv_frame()
        self.assertEqual(buf.recv_frame().data, b'hello')

    def test_close_code_recorded_before_ack_and_reason_redacted(self):
        metrics = {}
        frame = websocket.ABNF(fin=1, opcode=8, mask_value=0,
                               data=struct.pack('!H', 1008)+b'rate limit TOKEN_SECRET')
        cls = diag.observer_class(websocket, metrics)
        with patch.object(websocket.WebSocket, 'recv_frame', return_value=frame):
            self.assertIs(cls().recv_frame(), frame)
        self.assertEqual(metrics['close_code'], 1008)
        self.assertEqual(metrics['close_reason_category'], 'rate_limit')
        self.assertNotIn('TOKEN_SECRET', str(metrics))

    def test_ping_and_data_tally_without_orders(self):
        clock = Clock()
        sent = []
        class Peer:
            def send(self, message):
                sent.append(message)
            def recv(self):
                clock.value += 10
                if clock.value == 10:
                    raise websocket.WebSocketTimeoutException()
                if clock.value == 20:
                    return json.dumps({'arg': {'channel': 'tickers'}, 'data': [{'ts': '42'}]})
                return 'pong'
        result = {}
        diag.observe_session(Peer(), result, 31, websocket, clock)
        request = json.loads(sent[0])
        self.assertEqual(request['op'], 'subscribe')
        self.assertEqual({x['instId'] for x in request['args']}, {'AAVE-USDT-SWAP'})
        self.assertEqual(sent[1:], ['ping'])
        self.assertEqual(result['messages_by_channel'], {'tickers': 1})
        self.assertEqual(result['ended_by'], 'diagnostic_duration')

    def test_broken_pipe_does_not_get_called_login_or_account_error(self):
        clock = Clock()
        class Peer:
            def send(self, message):
                if message == 'ping':
                    raise BrokenPipeError('PRIVATE_TOKEN')
            def recv(self):
                clock.value += 21
                raise websocket.WebSocketTimeoutException()
        result = {}
        with self.assertRaises(BrokenPipeError):
            diag.observe_session(Peer(), result, 50, websocket, clock)
        self.assertEqual(result['stage'], 'send_ping')
        self.assertNotIn('PRIVATE_TOKEN', str(result))

    def test_original_ping_policy_is_observation_not_fake_recovery(self):
        clock = Clock()
        class Silent:
            def send(self, message):
                pass
            def recv(self):
                clock.value += 1
                raise websocket.WebSocketTimeoutException()
        result = {}
        diag.observe_session(Silent(), result, 45, websocket, clock)
        self.assertEqual(result['text_ping_sent'], 2)
        self.assertEqual(result['text_pong_received'], 0)
        self.assertEqual(result['pending_text_pong_age_s'], 25)

    def test_error_frame_code_only(self):
        class Peer:
            def send(self, message):
                pass
            def recv(self):
                return '{"event":"error","code":"60014","msg":"SECRET"}'
        result = {}
        diag.observe_session(Peer(), result, float('inf'), websocket)
        self.assertEqual(result['ended_by'], 'server_error')
        self.assertEqual(result['server_codes'], ['60014'])
        self.assertNotIn('SECRET', str(result))

    def test_log_window_channels_and_private_text(self):
        start = diag.datetime(2026, 11, 13, 15, 30, tzinfo=diag.KST)
        end = start+diag.timedelta(minutes=5)
        text = '\n'.join(['11-13 15:29:59 공개 WS: BrokenPipeError OLD_SECRET',
                          '11-13 15:31:00 공개 WS: BrokenPipeError / 계정 WS: 수신 확인 PRIVATE_KEY',
                          '11-13 15:32:00 BrokenPipeError source_unknown TOKEN',
                          '11-13 15:36:00 계정 WS: BrokenPipeError FUTURE'])
        rows = diag.engine_events(text, start, end)
        self.assertEqual(len(rows), 2)
        self.assertIn('공개 WS 오류 확인', rows[0]['signals'])
        self.assertNotIn('공개 WS 오류 확인', rows[1]['signals'])
        for value in ('PRIVATE_KEY', 'TOKEN', 'OLD_SECRET', 'FUTURE'):
            self.assertNotIn(value, str(rows))

    def test_symlink_and_path_escape_are_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home/'bot'; root.mkdir()
            secret = home/'credentials'; secret.write_text('PRIVATE')
            (root/'host.log').symlink_to(secret)
            self.assertEqual(diag.tail(root, 'host.log'), '')
            self.assertEqual(diag.tail(root, '../credentials'), '')

    def test_tls_verified_and_fixed_public_endpoint(self):
        raw = SimpleNamespace(settimeout=lambda n: None, connect=lambda addr: None, close=lambda: None)
        wrapped = SimpleNamespace(close=lambda: None)
        peer = SimpleNamespace(settimeout=lambda n: None)
        context = SimpleNamespace(wrap_socket=lambda sock, server_hostname: wrapped)
        with patch.object(diag.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('192.0.2.1', 443))]), \
             patch.object(diag.socket, 'socket', return_value=raw), \
             patch.object(diag.ssl, 'create_default_context', return_value=context) as tls, \
             patch.object(websocket, 'create_connection', return_value=peer) as connect:
            self.assertIs(diag.public_connect(websocket, object), peer)
        tls.assert_called_once_with()
        self.assertEqual(connect.call_args.args, (diag.URL,))
        self.assertEqual(connect.call_args.kwargs['redirect_limit'], 0)
        self.assertIs(connect.call_args.kwargs['socket'], wrapped)

    def test_parent_preserves_bot_files_and_only_saves_report(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory); root = home/'okx-phone'; root.mkdir()
            state = root/'phone_service_status.json'
            state.write_text('{"host_pid":6820,"state":"running","mode":"run","apiKey":"SECRET"}')
            before = state.read_bytes()
            class Child:
                returncode = 0
                def poll(self):
                    return 0
            def spawn(args, **kwargs):
                self.assertIn('--worker', args)
                kwargs['stdout'].write(b'{"attempts":[]}')
                return Child()
            with patch.object(diag.Path, 'home', return_value=home), \
                 patch.object(diag.subprocess, 'Popen', side_effect=spawn), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = diag.run(root, 1)
            self.assertEqual(state.read_bytes(), before)
            self.assertEqual(list(root.iterdir()), [state])
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertEqual((home/'OKX_PHONE_WS_COMPARE_RESULT.json').stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
