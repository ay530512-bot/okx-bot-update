"""Bounded, read-only export of already recorded diagnostics. No API access."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

KEYS = set('''scan_watch last_scan_age_s run_requested similarity reference_symbol action observed_ms candidates threshold score chart indicators volume relative_volume passed risk_work pending_risks queued_risk_events retired_callbacks resume_reason
latest_quote_lag_s clock_sample_age_s observer_gap_s trimmed_events monitor pong_rtt_s lane acknowledged execution_disconnect_count monitor_disconnect_count monitor_connected format saved_at program_version runtime_health observed_at elapsed_s
public_connected account_connected account_fresh account_age_s recovering entry_enabled
entry_cancelled user_paused disconnect_count last_disconnect_at last_disconnect_cause
disconnect_history generation error stage close_code cause server_notice code
connection_uptime_s frame_age_s pong_age_s pending_ping_age_s signal_journey
unique_observed first_seen_expired retained rows errors symbol action confirmation_ms
valid_from_ms expires_ms first_seen_ms first_delay_s ever_valid admission_count
last_seen_ms admission_at_ms first_market_wait_ms last_market_wait_ms first_market_ready_ms
last_rejected_ms timing input_published_ms computation_submitted_ms computation_published_ms
rank_inputs_captured_ms compute_s route rejection last_market channels connected
request_wait_s ready subscribed wanted receive_age_s exchange_age_s limit_s
wanted_age_s request_sent_age_s last_gate expired stage_label tickers trades books5 mark-price
entry reasons waiting remaining_s routes trend_pullback confirmed_reversal double_wick
pass_count wait_count inactive_count data_wait_count examples status reason data_issue or_status
completed15_count completed1h_count completed15_ms completed1h_ms duration_s pending result
live_rank leader quotes_ready missing_quotes basis phase quote_ms ranking_basis rank_observed_ms
architecture trend_status trend_inputs trend_rank trend_rank_checked_ms trend_armed_symbol
morning_status morning_rank morning_rank_checked_ms gain rank hour day missing_hourly_details source universe scan_rows eligible hourly_ready
missing_hourly baseline_ineligible_count baseline_ineligible listing_ms reference_ms entry_observation_totals scans candidate_returns history_write_errors
recent_performance count mean_s p95_s resources threads cpu_one_core_pct rss_mib peak_rss_mib
parallel requested effective workers_alive last_error last_scan_s aggregate_cpu_one_core_pct
aggregate_rss_mib calculating batch_age_s completed_batches discarded_batches cached_symbols
nonblocking last_admission at type category location details symbol now_ms failed market
recent_ticks mode seconds metrics group label calls total_s self_s max_s last_s
exception_counts first_at last_at recent_admission_exceptions version run_id health admission
history historical_signals connection_trace latest events public account engine transport
frames text_pings text_pongs max_frame_gap_s subscription_frames last_subscription_bytes
last_disconnect samples dropped_observations write_errors max_observer_gap_s engine_tick
active_age_s last_duration_s max_duration_s time_kst kind reason_kind observed_triggers
lock_busy error_code subscription_pairs execution_symbols monitor_symbols
last_market_receive_age_s equity_seen last_equity_receive_age_s fresh_at_observation
connection_key good_snapshots export_errors history_rows file note'''.split())


def safe(value, parent='', depth=0):
    if depth > 15:
        return None
    if isinstance(value, dict):
        if parent in ('reasons', 'exception_counts'):
            return {str(k)[:120]: safe(v, str(k), depth+1)
                    for k, v in list(value.items())[:80]}
        return {k: safe(v, k, depth+1) for k, v in value.items() if k in KEYS}
    if isinstance(value, list):
        return [safe(v, parent, depth+1) for v in value[-1024:]]
    if value is None or type(value) is bool:
        return value
    if type(value) in (int, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:500]
    return None


def read_local(root, name, limit):
    path = Path(root)/name
    if path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('diagnostic size or link')
    return path.read_text(encoding='utf-8')


def export(root, summary):
    p = summary or {}
    h = p.get('runtime_health') or {}
    data = safe(dict(format='okx-phone-diagnostic-2',
        saved_at=datetime.now(timezone.utc).isoformat(), program_version=h.get('program_version'),
        runtime_health=h, recent_performance=p.get('recent'), resources=p.get('resources'),
        parallel=p.get('parallel'), last_admission=p.get('last_admission')))
    problems = []
    try:
        update=json.loads(read_local(root,'phone_update_result.json',16384))
        data['update_result']={k:update.get(k) for k in ('version','phase','observed_at','message')}
    except (OSError,ValueError,TypeError):
        pass
    for name, key, limit in (('phone_connection_trace.json', 'connection_trace', 262144),
                             ('phone_performance.json', None, 1048576)):
        try:
            recorded = json.loads(read_local(root, name, limit))
            if not isinstance(recorded, dict):
                raise ValueError('diagnostic object required')
            if key:
                data[key] = safe(recorded)
            else:
                for k in ('metrics', 'exception_counts', 'recent_admission_exceptions', 'recent_ticks'):
                    data[k] = safe(recorded.get(k), k)
        except (OSError, ValueError, TypeError):
            problems.append(dict(file=name, note='읽기 실패 또는 기록 없음'))
    history = []
    for name in ('phone_entry_history.previous.jsonl', 'phone_entry_history.jsonl'):
        try:
            text = read_local(root, name, 3*1024*1024)
            for line in text.splitlines()[-500:]:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict) and row.get('version') == 'phone-entry-history-1':
                        history.append(safe(row))
                except (ValueError, TypeError):
                    problems.append(dict(file=name, note='미완성 기록 행 제외'))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            problems.append(dict(file=name, note='읽기 실패 또는 크기 제한'))
    history.sort(key=lambda x: x.get('observed_at') or 0)
    data['history'] = history[-240:]
    data['history_rows'] = len(data['history'])
    # Observations survive run boundaries for analysis only. Never restore them
    # to the trading journal, pending signals, or processed-signal state.
    signals = {}
    for row in data['history']:
        health = row.get('health') or {}
        if not isinstance(health, dict):
            continue
        for signal in (health.get('signal_journey') or {}).get('rows', []):
            if not isinstance(signal, dict):
                continue
            key = (row.get('run_id'), signal.get('symbol'), signal.get('action'), signal.get('confirmation_ms'))
            signals[key] = dict(signal, run_id=row.get('run_id'), observed_at=row.get('observed_at'))
    data['historical_signals'] = list(signals.values())[-1024:]
    data['export_errors'] = problems[-12:]
    return data
