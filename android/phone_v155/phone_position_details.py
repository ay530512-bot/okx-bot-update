"""Read-only entry evidence from the persisted decision; no strategy inference."""
import math

NAMES = {'trend_pullback': '눌림목', 'exhaustion724': '확정반전',
         'double_wick': '두꼬리', 'top1_15kst_dip130': '상승률 1위 추세 롱',
         'top1_morning_failed_rebound150': '오전 상승률 1위 숏'}


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def describe(record):
    s = record.get('v4_signal') or {}
    proof = (s.get('decision_record') or {}).get('volume_wick_proof') or {}
    route = proof.get('route721')
    side = record.get('direction')
    out = dict(rule=NAMES.get(route, '진입 규칙 기록 없음'), route=route if route in NAMES else None,
               summary='저장된 조건 기록 없음', evidence=[], entry_ms=record.get('entry_ms'),
               confirmed_ms=s.get('valid_from_ms'), frame=s.get('setup_frame'),
               source='persisted_entry_decision')
    if not proof or side not in ('long', 'short') or proof.get('action') != side.upper():
        out.update(rule='진입 규칙 기록 없음', route=None)
        return out
    rows = out['evidence']
    def value(label, v, style='number'):
        n = number(v)
        if n is not None:
            text = f'{n*100:.1f}%' if style == 'pct' else f'{n:.2f}배' if style == 'ratio' else f'{n:.8g}'
            rows.append(dict(label=label, value=text))
    c = proof.get('confirmation721') or {}
    if route == 'trend_pullback':
        touched = [str(x) for x in proof.get('ma_touched721', []) if type(x) is int and 0 < x <= 1000]
        out['summary'] = ('하락' if side == 'short' else '상승')+' 추세 · 이평선 재확인 후 완료봉 진입'
        if touched: rows.append(dict(label='재확인 이평선', value=' / '.join('MA'+x for x in touched)))
    elif route == 'exhaustion724':
        out['summary'] = ('확장봉 후 음봉·윗꼬리·RSI 하락 확인' if side == 'short'
                          else '확장봉 후 양봉·아랫꼬리·RSI 상승 확인')
        value('확인봉 꼬리', c.get('wick_fraction'), 'pct')
        value('종가 강도', c.get('close_strength'), 'pct')
        value('확인봉 RSI', c.get('rsi14'))
    elif route == 'double_wick':
        detail = proof.get('pattern_details') or {}
        out['summary'] = '연속 윗꼬리 · 고점 미돌파 확인' if side == 'short' else '연속 아랫꼬리 · 저점 미갱신 확인'
        for i, v in enumerate((detail.get('wicks') or [])[:2]): value(f'{i+1}차 꼬리 비율', v, 'pct')
        if side == 'short':
            value('직전 고점', detail.get('prior_high')); value('확인봉 고점', detail.get('second_high'))
        else:
            value('직전 저점', detail.get('prior_low')); value('확인봉 저점', detail.get('second_low'))
    elif route == 'top1_15kst_dip130':
        out['summary'] = '완료1시간봉 상승률 1위 · 돌파 후 눌림 확인'
        value('눌림 기준가', proof.get('dip_level')); value('돌파 기준가', proof.get('channel_high'))
    elif route == 'top1_morning_failed_rebound150':
        out['summary'] = '완료1시간봉 상승률 1위 · 큰 눌림 후 반등 실패'
        value('고점 대비 눌림', proof.get('pullback_pct'), 'pct')
        value('직전 고점', proof.get('peak')); value('반등 고점', proof.get('rebound_high'))
    value('거래량 배수', c.get('volume_ratio', proof.get('context_volume')), 'ratio')
    value('1시간 추세효율', proof.get('hourly_efficiency724', proof.get('context_er')))
    value('진입 기준가', s.get('entry_reference', proof.get('reference')))
    value('최초 손절가', proof.get('structural_stop'))
    return out


def install():
    import okx_dashboard_data as dashboard
    original = dashboard.dashboard_snapshot
    if getattr(original, '_phone_entry_details', False): return
    def snapshot(snapshot, records, *args, **kwargs):
        out = original(snapshot, records, *args, **kwargs)
        by_key = {(r['symbol'], r['direction']): r for r in records}
        for row in out['positions']:
            record = by_key.get((row['symbol'], row['direction']))
            try:
                row['entry_details'] = describe(record) if record is not None else dict(
                    rule='수동 진입', summary='자동 규칙 적용 없음', evidence=[], source='manual')
            except (TypeError,ValueError,AttributeError,KeyError,OverflowError):
                row['entry_details'] = dict(rule='진입 규칙 기록 확인 필요',
                    summary='저장된 조건을 읽지 못했습니다.', evidence=[], source='unavailable')
        return out
    snapshot._phone_entry_details = True
    dashboard.dashboard_snapshot = snapshot
