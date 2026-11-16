"""Local TLS feeds + 290-symbol computation + complete simulated entry.

No live account, credentials or exchange request. Production readers, four
calculation workers, coordinator, admission, reconciliation and SL checks run
concurrently. The account, candle inputs, network peer and fills are simulated.
"""
import copy
import hashlib
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

# Keep the native connector only for the explicitly scoped loopback peer.
native_connect = socket.socket.connect
from execution_harness import D, HOST, Harness, NETWORK_ATTEMPTS, trend
from test_morning import fixture as morning_fixture
from soak_transport import Server
import phone_public_ws as transport
import phone_morning_short as morning

FIXTURES = json.loads((D/'fixtures.json').read_text())['fixtures']
FIXTURES['morning_top1_SHORT'] = morning_fixture()


def expanded(rows):
    out = copy.deepcopy(rows)
    source = rows[0]['live_frames']
    listing=source['15m'][-1][0]//3600000*3600000-2*3600000
    out.append(dict(symbol='NEWLIST-USDT-SWAP',live_frames={
        f:[copy.deepcopy(b) for b in bars if b[0]>=listing] for f,bars in source.items()}))
    for i in range(290-len(out)):
        price = 1+i*.001
        frames = {f:[[b[0], price, price*1.0001, price*.9999, price, 100]
                     for b in bars] for f, bars in source.items()}
        out.append(dict(symbol=f'LOAD{i:03}-USDT-SWAP', live_frames=frames))
    return out


def exercise(name, fixture, server_context, client_context):
    f = copy.deepcopy(fixture)
    f['rows'] = expanded(f['rows'])
    if 'arming_rows' in f:
        f['arming_rows'] = expanded(f['arming_rows'])
    h = Harness(f, 4)
    def listing_metadata():
        row=h.api.rows['NEWLIST-USDT-SWAP']
        listing=min(b[0] for b in row['live_frames']['15m'])
        row['instrument'].update(instType='SWAP',listTime=str(int(listing)))
    listing_metadata()
    e, stream = h.e, h.e.stream
    monitor = stream._phone_monitor_stream
    stream.data.clear()
    stream.active_pairs.clear()
    stream.symbols.clear()
    stream.connected = False
    stream.generation = 0
    stream.watch(['AAVE-USDT-SWAP'])
    stream.monitor(list(h.api.rows))
    started = time.monotonic()
    clock_origin = started
    base_ms = h.api.now
    switched = 'arming_rows' not in f
    stamps = {}
    ticks = []
    ready_while_monitor_down = 0
    max_cached = 0
    prefill_requests = 0

    def quote(symbol, channel):
        # Hold one required channel until both sockets have recovered. A
        # pending candidate must survive this; the guard itself stays enabled.
        if channel == 'trades' and time.monotonic()-started < 10:
            return None
        if symbol in h.api.rows:
            q = h.api.quote(symbol)
            return h.api.book(symbol) if channel == 'books5' else dict(q, px=q['last'], markPx=q['last'])
        return dict(ts=str(h.api.now), last='2', markPx='2', px='2',
                    bidPx='1.9999', askPx='2.0001',
                    bids=[['1.9999','1000000','0','1']], asks=[['2.0001','1000000','0','1']])

    server = Server(server_context, quote_provider=quote,
                    fault_targets={'monitor':[1,7], 'execution':[3]})

    def local_dns(host, port, *args, **kwargs):
        assert host == 'ws.okx.com' and port == 443
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', server.port))]

    def local_connect(sock, address):
        assert address == ('127.0.0.1', server.port), 'non-loopback network forbidden'
        return native_connect(sock, address)

    try:
        with patch.object(socket.socket, 'connect', local_connect), \
             patch.object(transport.socket, 'getaddrinfo', side_effect=local_dns), \
             patch.object(transport.ssl, 'create_default_context', return_value=client_context):
            stream.start()
            while time.monotonic()-started < 18:
                h.api.now = base_ms+int((time.monotonic()-clock_origin)*1000)
                e.account_stream.received = time.monotonic()
                t = time.monotonic()
                e.tick()
                ticks.append(time.monotonic()-t)
                max_cached = max(max_cached, len(h.manager.packets))
                if not switched and e.journal.data.get(trend.STATE, {}).get('arm'):
                    h.feed(f['rows'], f['now'], quotes=False)
                    listing_metadata()
                    base_ms = f['now']
                    clock_origin = time.monotonic()
                    switched = True
                pending = list(getattr(e, 'channel_pending', {}).values())
                for state in (trend.STATE, morning.STATE):
                    s = e.journal.data.get(state, {}).get('pending')
                    if s:
                        pending.append(s)
                if pending:
                    stamps.setdefault('candidate_s', round(time.monotonic()-started, 3))
                if time.monotonic()-started < 10:
                    assert not h.api.opening_posts(), 'entry with required trades missing'
                for order in e.records():
                    if order['phase'] == 'submitted':
                        stamps.setdefault('order_s', round(time.monotonic()-started, 3))
                        assert not order.get('protection_verified')
                        if not h.api.positions:
                            prefill_requests = len(h.api.opening_posts())
                            h.api.fill(order['client_id'])
                    if order['phase'] == 'active':
                        assert order['protection_verified']
                        stamps.setdefault('protected_s', round(time.monotonic()-started, 3))
                    ready_while_monitor_down += int(not monitor.connected and
                        stream.ready(order['symbol'], e.cfg, h.api.now))
                time.sleep(.1)
            assert switched
            assert len(h.api.opening_posts()) == prefill_requests == 1
            assert len(e.records()) == 1
            order = e.records()[0]
            assert order['phase'] == 'active' and order['protection_verified']
            actual = order['v4_signal']['decision_record']['volume_wick_proof']['route721']
            expected = morning.ROUTE if name == 'morning_top1_SHORT' else name.rsplit('_',1)[0]
            assert actual == expected, (actual, expected)
            assert max_cached == 290, max_cached
            assert server.faults == {'monitor':2, 'execution':1}, server.faults
            assert transport.diagnostics(stream)['disconnect_count'] == 1
            assert transport.diagnostics(monitor)['disconnect_count'] == 2
            assert not server.errors, server.errors
            assert not NETWORK_ATTEMPTS, NETWORK_ATTEMPTS
            report = dict(rule=name, monitored_symbols=290, computed_symbols=max_cached,
                calculation_workers=4, elapsed_s=round(time.monotonic()-started,3),
                events=stamps, engine_ticks=len(ticks), max_tick_s=round(max(ticks),4),
                mean_tick_s=round(sum(ticks)/len(ticks),4), sent=dict(server.sent),
                injected_eof=dict(server.faults), opening_requests=1,
                phase=order['phase'], protection_verified=order['protection_verified'],
                execution_disconnects=transport.diagnostics(stream)['disconnect_count'],
                monitor_disconnects=transport.diagnostics(monitor)['disconnect_count'],
                unexpected_disconnects=0, server_errors=list(server.errors))
            report['baseline_ineligible_count']=getattr(e,'phone_trend_inputs',{}).get('baseline_ineligible_count')
            if name in ('top1_15kst_dip130_LONG','morning_top1_SHORT'):
                assert report['baseline_ineligible_count']==1,report
            stream.stop()
            stream._phone_reader.join(3)
            monitor._phone_reader.join(3)
            return report
    finally:
        stream.stop()
        if hasattr(stream, '_phone_reader'):
            stream._phone_reader.join(3)
            monitor._phone_reader.join(3)
        server.close()
        h.close()


def main():
    results = []
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        key, cert = Path(tmp)/'key.pem', Path(tmp)/'cert.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes',
            '-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=ws.okx.com',
            '-addext','subjectAltName=DNS:ws.okx.com'], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert, key)
        client_context = ssl.create_default_context(cafile=str(cert))
        assert client_context.check_hostname and client_context.verify_mode == ssl.CERT_REQUIRED
        for name, fixture in FIXTURES.items():
            try:
                result = exercise(name, fixture, server_context, client_context)
                results.append(result)
                print(json.dumps(result), flush=True)
            except Exception:
                import traceback
                failures.append(dict(rule=name, error=traceback.format_exc()))
                print(failures[-1]['error'], flush=True)
    report = dict(version='1.5.4', local_tls_only=True,
        actual_phone_tested=False, actual_exchange_order_requests=0,
        rules_passed=len(results), failures=failures, results=results,
        runtime_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HOST.iterdir()) if p.is_file()},
        scope='Synthetic 290-symbol universe; real local TLS streams and calculation subprocesses; simulated exchange/account/fills; no phone or live OKX timing claim.')
    (D/'loaded_entry_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    assert len(results) == 8 and not failures, failures


if __name__ == '__main__':
    main()
