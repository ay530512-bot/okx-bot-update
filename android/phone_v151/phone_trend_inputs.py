"""Read confirmed inputs, independently of unrelated scan progress.

No fetches or order operations. The existing rank_rows/completed validators
still require every eligible symbol's synchronized closed hour, and the
selected symbol's latest closed 15m candle. A partial ranking is never used.
"""
import copy


def ranked_rows(engine, result, t):
    from phone_trend_slot import permitted, completed, HOUR
    universe = engine.universe
    market = getattr(universe, 'full_market', None)
    if market is None:
        # Non-mobile test/reference adapters retain the original complete scan.
        rows = result.get('rows', [])
        if len(rows) != result.get('universe') or result.get('filter_counts', {}).get('data_error', 0):
            raise ValueError('전체 종목 자료 완성 대기')
        return [r for r in rows if permitted(r, engine.cfg)]
    with universe.lock:
        instruments = dict(market.instruments)
        cache = getattr(market, 'band_cache', {})
        # Producer replaces immutable histories. Copy references under its lock.
        inputs = {s: {f: cache.get((s, f)) for f in ('15m', '1H')}
                  for s in instruments}
        paused = getattr(universe, 'search_paused', None)
        paused = paused.is_set() if paused is not None else False
    now = engine.api.now_ms()
    detail = dict(observed_ms=now, source='confirmed_frame_cache',
                  universe=len(instruments), scan_rows=len(result.get('rows', [])),
                  eligible=0, hourly_ready=0, missing_hourly=[], missing_hourly_details=[], ready=False)
    engine.phone_trend_inputs = detail
    if paused:
        raise ValueError('전체 종목 자료 수집 중지')
    if not instruments or len(instruments) != result.get('universe'):
        raise ValueError('전체 종목 목록 갱신 대기')
    rows = []
    for symbol, instrument in instruments.items():
        row = dict(symbol=symbol, instrument=dict(instrument))
        if not permitted(row, engine.cfg):
            continue
        detail['eligible'] += 1
        frames = {}
        for frame, cached in inputs[symbol].items():
            bars = cached[1] if isinstance(cached, tuple) and len(cached) == 2 else []
            # FrozenBars is an immutable tuple; mutable fixtures are isolated.
            frames[frame] = bars if isinstance(bars, tuple) else copy.deepcopy(bars)
        row.update(live_frames=frames, observed_ms=None, cache_read_ms=now)
        rows.append(row)
        try:
            hourly = completed(frames['1H'], t, HOUR, 1)
            day = t // 86400000 * 86400000
            if not any(int(b[0]) == day for b in hourly):
                raise ValueError('09시 기준봉 대기')
            detail['hourly_ready'] += 1
        except (ValueError, TypeError, KeyError, IndexError, OverflowError) as error:
            if len(detail['missing_hourly']) < 8:
                detail['missing_hourly'].append(symbol)
                detail['missing_hourly_details'].append(dict(symbol=symbol,
                    reason='1시간봉 미수신' if not frames['1H'] else str(error),
                    completed1h_count=len(frames['1H'])))
    detail['ready'] = bool(rows) and detail['hourly_ready'] == len(rows)
    if not detail['ready']:
        raise ValueError('순위용 완료1시간봉 대기: '+str(detail['hourly_ready'])+'/'+str(len(rows)))
    # Ranking still validates the data itself, including the prior hour when
    # t falls exactly on an hourly boundary. This is coverage, not approval.
    return rows
