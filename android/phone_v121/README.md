# OKX Ai trade 1.2.1 — candidate calculation latency

Phone-only update from 1.2.0 / host-v18 to host-v19. Original Q2X source, configuration,
OR/two-wick selection, quarter-size pullback longs, protection and final admission stay intact.

Candidate scans now build auxiliary indicator/UI frames only when select() returns an entry.
No-signal/conflict handling still runs. Direct packet consumers still receive complete frames.
Aligned closed-bar validation is memoized only inside optimized candidate packet scopes;
full input bytes and time buckets invalidate corrections/new candles. No errors are cached.
Final entry checks and position management bypass this memoization. Added timing for packet
body and closed-bar validation. Update checks gain a random query to avoid old manifest caches.

No websocket transport/reconnect or stale-data admission changes. Internet/server disconnects
cannot be prevented by this release; recent WebSocketConnectionClosedException root cause is
not established. This patch addresses measured computation latency, not a demonstrated network fix.

Validation: exact pinned Q2X differential comparison on 81 synthetic/fixture symbols and five
clock offsets, positive signals, 90-second expiration, corrected history and quote refresh.
Measured workstation run: 0.780839 s original, 0.250158 s optimized, not Fold or exchange latency.
15 existing handover checks, 8 transaction checks, 5 sizing checks passed. New installer is
staged offline; live phone/account speed and installation remain unverified until user installs.
No live orders were placed by these tests. Existing safe handover may defer installation.
