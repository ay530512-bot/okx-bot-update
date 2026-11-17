"""Mobile pure computation. Core policy predicates remain pinned and unchanged.

This module has no engine, account, order client, subscription or journal.
It returns exactly the original positive packet, plus diagnostic explanations.
"""
import copy
from phone_frozen_bars import FrozenBars


def install(channel, cache, pins):
    from phone_entry_diagnostics import make_selector
    select = make_selector(pins)
    original_closed = channel.closed

    def validated(bars, hourly, cutoff):
        return select(original_closed(bars, cutoff), hourly)
    memo = cache.wrap(validated, 'signal.validated_selection')

    def packet(row, cfg, now, quote=None, swing_frame=None):
        from okx_band_flow import view
        from okx_pattern15 import summary, STEPS, leverage
        values = row.get('live_frames', {})
        bars = values.get('15m', [])
        aligned = type(now) is int and (bars._aligned15 if type(bars) is FrozenBars else
            all(type(r[0]) is int and r[0] % 900000 == 0 for r in bars))
        v, status, detail = memo(bars, values.get('1H'), now//900000*900000) if aligned else validated(bars, values.get('1H'), now)
        if not v:
            return dict(entry_setups=[], or_status=status, entry_diagnostic=detail)
        # Mutable copies only for positive packets. Never modify published bars.
        values = {f: b.thaw() if type(b) is FrozenBars else copy.deepcopy(b) for f, b in values.items()}
        b = original_closed(values.get('15m', []), now)
        frames = {}
        for f, step in STEPS.items():
            a = b if f == '15m' else [r for r in values.get(f, []) if r[0]+step <= now]
            if len(a) < 21:
                frames[f] = dict(analysis=dict(trend='unknown', reason='보조봉 자료 대기'), completed_ms=0)
                continue
            m = view(a, cfg)
            frames[f] = dict(analysis=summary(a), ma=m['ma'],
                bollinger={k: m[k] for k in ('mid', 'upper', 'lower')}, atr=m['atr'],
                recent=a[-24:], completed_ms=a[-1][0]+step)
        v['evidence704'] = channel.evidence(b, v, frames, now)
        frames['15m']['entry_setups'] = [v]
        return dict(symbol=row['symbol'], price=float((quote or {}).get('last') or v['reference']),
            asset_category=row.get('instrument', {}).get('instCategory', '1'),
            required_leverage=leverage(row['symbol']), or_status=status, frames=frames,
            entry_setups=[v], selection='V7.32 기존15m OR 두꼬리',
            policy='15m: 기존 규칙 OR 두꼬리·1H 확인; MA20 추격 제한 없음; 4H 진입 삭제',
            entry_diagnostic=detail)
    channel._phone_worker_packet = packet

