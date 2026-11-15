"""Expose bounded read-only run diagnostics on the existing authenticated UI."""
import time
from phone_connection_trace import snapshot


def attach(engine, timer):
    report, summary = timer.report, timer.make_summary
    def health_report():
        d = report()
        try:
            value = snapshot(engine)
            public, account, state = value['public'], value['account'], value['engine']
            transport = public.get('transport', {})
            last = transport.get('last_disconnect') or {}
            d['runtime_health'] = dict(observed_at=time.time(),
                elapsed_s=d.get('elapsed_s'), public_connected=public.get('connected'),
                account_connected=account.get('connected'), account_fresh=account.get('fresh_at_observation'),
                account_age_s=account.get('last_equity_receive_age_s'),
                recovering=state.get('recovering'), entry_enabled=state.get('entry_enabled'),
                entry_cancelled=state.get('entry_cancelled'), user_paused=state.get('user_paused'),
                disconnect_count=transport.get('disconnect_count'),
                last_disconnect_at=last.get('observed_at'), last_disconnect_cause=last.get('cause'),
                entry=dict(getattr(engine,'phone_entry_diagnostic',{})))
        except Exception:
            d['runtime_health'] = dict(observed_at=time.time(),unavailable=True)
        return d
    def health_summary(d):
        result = summary(d)
        result['runtime_health'] = d.get('runtime_health')
        return result
    timer.report, timer.make_summary = health_report, health_summary
