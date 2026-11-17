"""Expose bounded read-only run diagnostics on the existing authenticated UI."""
import time
from phone_connection_trace import snapshot


def attach(engine, timer):
    report, summary = timer.report, timer.make_summary
    from phone_entry_diagnostics import History
    history = History(timer.root)
    def health_report():
        d = report()
        try:
            value = snapshot(engine)
            public, account, state = value['public'], value['account'], value['engine']
            transport = public.get('transport', {})
            monitor = public.get('monitor', {})
            disconnects = [dict(x, lane=lane) for lane, values in (
                ('execution', transport.get('disconnect_history', [])),
                ('monitor', monitor.get('disconnect_history', []))) for x in values]
            disconnects.sort(key=lambda x: x.get('observed_at') or 0)
            last = disconnects[-1] if disconnects else (transport.get('last_disconnect') or {})
            d['runtime_health'] = dict(observed_at=time.time(),
                elapsed_s=d.get('elapsed_s'), public_connected=public.get('connected'),
                account_connected=account.get('connected'), account_fresh=account.get('fresh_at_observation'),
                account_age_s=account.get('last_equity_receive_age_s'),
                recovering=state.get('recovering'), entry_enabled=state.get('entry_enabled'),
                entry_cancelled=state.get('entry_cancelled'), user_paused=state.get('user_paused'),
                risk_work=__import__('phone_risk_lifecycle').diagnostics(engine),
                scan_watch=__import__('phone_risk_lifecycle').scan_watch(engine),
                disconnect_count=(transport.get('disconnect_count') or 0)+(monitor.get('disconnect_count') or 0),
                execution_disconnect_count=transport.get('disconnect_count'),
                monitor_disconnect_count=monitor.get('disconnect_count'),
                monitor_connected=monitor.get('connected'),
                last_disconnect_at=last.get('observed_at'), last_disconnect_cause=last.get('cause'),
                disconnect_history=disconnects[-8:],
                signal_journey=engine._phone_journey137.report(engine.api.now_ms()) if hasattr(engine, '_phone_journey137') else None,
                entry=dict(getattr(engine,'phone_entry_diagnostic',{})),
                trend_status=getattr(engine,'phone_trend_status','추세 검사 대기'),
                morning_status=getattr(engine,'phone_morning_status','오전 숏 검사 대기'),
                morning_rank=dict((engine.journal.data.get('phone_morning150',{}).get('rank') or {})),
                morning_rank_checked_ms=engine.journal.data.get('phone_morning150',{}).get('last',0),
                trend_inputs=dict(getattr(engine,'phone_trend_inputs',{})),
                live_rank={k:v for k,v in __import__('phone_live_rank').snapshot(engine).items() if k != 'rows'},
                trend_rank=dict((engine.journal.data.get('phone_trend130',{}).get('rank') or {})),
                trend_rank_checked_ms=engine.journal.data.get('phone_trend130',{}).get('last',0),
                trend_armed_symbol=(engine.journal.data.get('phone_trend130',{}).get('arm') or {}).get('symbol'),
                entry_observation_totals=dict(getattr(engine,'phone_entry_totals',{})),
                program_version='1.6.11')
            history.observe(d['runtime_health'],d)
            d['runtime_health']['history_write_errors']=history.errors
        except Exception:
            d['runtime_health'] = dict(observed_at=time.time(),unavailable=True)
        return d
    def health_summary(d):
        result = summary(d)
        result['runtime_health'] = d.get('runtime_health')
        return result
    timer.report, timer.make_summary = health_report, health_summary
