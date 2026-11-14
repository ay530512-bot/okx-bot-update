# 1.1.9 public market WS heartbeat fix (review branch)

Observed 2026-11-15 Fold3 trace: PublicHeartbeatTimeout during continuous incoming frames (frame_age_s approximately 0), account WS still connected. Original phone_v118 code sent text ping every 20s even when messages were flowing. This branch proposes idle-only ping: transmit after 20 seconds without any incoming frame, retain the 20s timeout for genuine silence, clear pending heartbeat when the peer resumes sending valid frames. Original quote freshness and trading/exit code are unchanged.

Primary source: https://www.okx.com/docs-v5/en/ WebSocket Connect guidance ("If no new message is received within N seconds, send the String ping", N less than 30).

To test: python -m unittest discover -s android/phone_v119 -p 'test_*.py' -v

IMPORTANT: this source-only review branch does NOT change android/phone_latest.json, does NOT publish a new signed/verified phone release, and does NOT install onto Fold3. The existing 1.1.8 trade bot, Github releases, core and stop protection remain unchanged. Before official release, run complete pinned-core regression and device tests and produce a compatible v17+ installer with safe handover / rollback. The separate download bundle distributed through the chat includes a guarded one-shot staging installer; its real-device startup has not yet been verified.
