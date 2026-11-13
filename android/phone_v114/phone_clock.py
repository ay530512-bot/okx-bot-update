"""Share OKX server-time reads across disposable scan clients in one process.

No order retry, strategy change, local-wall-clock fallback or stale-data bypass.
The verified Q2X source files remain byte-for-byte unchanged.
"""
import threading
import time

VERSION = 'phone-shared-clock-1'


class SharedClock:
    def __init__(self, error_type, monotonic=time.monotonic, ttl=60.0):
        self.error_type = error_type
        self.monotonic = monotonic
        self.ttl = ttl
        self.lock = threading.Lock()
        self.sample = None
        self.retry_at = 0.0
        self.failures = 0

    def sync(self, api):
        # Single flight includes the failure path: waiting callers share the
        # cooldown rather than making the same failed request one by one.
        with self.lock:
            now = self.monotonic()
            if now < self.retry_at:
                raise self.error_type('서버 시각 조회 재시도 대기 · 다음 검사에서 확인합니다.')
            if self.sample is None or now - self.sample[2] >= self.ttl:
                try:
                    data = api.request('GET', '/api/v5/public/time', private=False)
                    timestamp = str(data[0]['ts'])
                    if not timestamp.isascii() or not timestamp.isdigit() or int(timestamp) <= 0:
                        raise ValueError('invalid server timestamp')
                    observed = self.monotonic()
                    self.sample = (int(timestamp), observed, observed)
                    self.failures = 0
                    self.retry_at = 0.0
                except Exception:
                    self.failures = min(self.failures + 1, 5)
                    self.retry_at = self.monotonic() + min(30.0, 2.0 ** self.failures)
                    # Do not mutate the caller's last valid clock on failure.
                    raise
            # Preserve the sample's age: borrowing it does not refresh synced.
            api.server_ms, api.anchor, api.synced = self.sample


def install():
    from okx_core import OKX, Rejected
    if getattr(OKX.sync, '_phone_shared_clock_version', None) == VERSION:
        return OKX.sync._phone_shared_clock
    shared = SharedClock(Rejected)

    def sync(api):
        return shared.sync(api)

    sync._phone_shared_clock_version = VERSION
    sync._phone_shared_clock = shared
    OKX.sync = sync
    return shared
