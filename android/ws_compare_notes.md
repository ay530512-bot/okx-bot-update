# Public WebSocket comparison 1

This is an observation tool, not a trading-program update or a connection fix.
It uses the installed websocket-client package without upgrading dependencies.

## Why another observation is needed

The bounded delay-check logs show connection-closed/broken-pipe errors and
recovery phases despite a stable host process. They do not record a server close
code, the failing send/receive stage, actual screen state, or the public socket's
receive-loop timing. A successful public REST time request cannot establish
WebSocket health. An omitted probe cannot establish HTTP success either.

The original public stream sends text `ping` every 20 seconds. It does not enforce
a text-pong deadline; this is an observable weakness, not a demonstrated cause of
the reported peer disconnects. An offline test using websocket-client 1.9.0
confirmed that a timeout in a partially received frame retains the bytes and
resumes correctly; do not claim that the original one-second timeout alone
corrupts a frame. The version on the phone is reported by the comparison tool.

## Operation

Run `python -B phone_ws_compare.py`. Keep charging, Wi-Fi and the Termux screen on
for this comparison. Screen state is operator-controlled and is **not measured**.
Default observation time is 300 seconds, plus up to 30 seconds for bounded cleanup.

- Creates one public IPv4/verified-TLS connection to the same Q2X public endpoint.
- Subscribes to the four existing public channels for AAVE-USDT-SWAP only.
- Retains the original 20-second text-ping policy for comparison. It observes
  missing pong replies; it does not claim to have repaired the heartbeat policy.
- Records channel message counts, ping/pong counts, socket receive gaps, failure
  stage, numeric close code, and an allowlisted close-reason category. Raw peer
  messages, prices, exception messages and log lines are not printed.
- Correlates sanitized existing bot log entries only within the test window.
- Records service PID/restart changes without sending that process signals.
- No bot or credential imports, REST queries, login, orders, bot restarts or
  setting changes. Termination at deadline affects only the new diagnostic child.
- Saves only `~/OKX_PHONE_WS_COMPARE_RESULT.json`, with mode 0600.

## Interpretation limits

A healthy low-volume comparison does not prove that the bot's larger subscription
load is healthy. Simultaneous failures would support investigating shared network
or device conditions, but do not prove Wi-Fi is the cause. Bot-only failures would
support investigating its receive path/load, but do not prove a code defect.
The comparison's close code is not the bot socket's close code. Observer scheduling
gaps are not measurements of the trading engine. Existing freshness, position
reconciliation and protective-order checks must remain in place.

## Primary references checked

- OKX API guide, WebSocket connection/heartbeat guidance:
  https://www.okx.com/docs-v5/en/#overview-websocket
- websocket-client official frame-buffer implementation v1.9.0:
  https://github.com/websocket-client/websocket-client/blob/v1.9.0/websocket/_abnf.py
- websocket-client official receive/close implementation:
  https://websocket-client.readthedocs.io/en/latest/_modules/websocket/_core.html

The original Q2X source and the installed shared-clock v1 are unchanged.
