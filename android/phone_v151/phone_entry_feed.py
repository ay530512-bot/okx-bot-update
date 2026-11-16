"""Retain valid admission subscriptions; explain unchanged admission guards.
No order writes, REST fallback, freshness extension, or signal retries here.
"""
import functools
import time


def quote_details(e, symbol):
    stream = e.stream
    now = e.api.now_ms()
    result = dict(symbol=symbol, observed_ms=now, connected=bool(stream.connected),
                  generation=stream.generation, channels={})
    with stream.lock:
        from phone_public_ws import subscription_wait
        mono=time.monotonic()
        priority=symbol in getattr(stream,'_phone_priority_symbols',())
        needs_send=any(s==symbol for s,ch in stream.pairs()-stream.active_pairs)
        result['request_wait_s']=round(subscription_wait(stream,priority,mono),3) if needs_send and stream.connected else 0
        for ch in stream.CHANNELS:
            age = e.cfg['liquidity']['ws_max_age_seconds']
            if ch == 'trades':
                age = e.cfg['liquidity'].get('trade_max_age_seconds', age)
            item = stream.data.get((symbol, ch))
            row = dict(ready=stream.read(symbol, ch, age, now) is not None,
                       subscribed=bool(stream.connected and (symbol, ch) in stream.active_pairs),
                       wanted=symbol in stream.symbols, limit_s=age)
            sent=getattr(stream,'_phone_sent_at',{}).get((symbol,ch))
            sent=sent[1] if sent and sent[0]==stream.generation and stream.connected else None
            wanted=getattr(stream,'_phone_desired_since',{}).get((symbol,ch))
            row['request_sent_age_s']=round(mono-sent,3) if sent is not None else None
            row['wanted_age_s']=round(mono-wanted,3) if wanted is not None else None
            if item:
                row.update(receive_age_s=round(time.monotonic()-item[1], 3),
                           exchange_age_s=round((now-int(item[0]['ts']))/1000, 3),
                           same_generation=item[2] == stream.generation)
            result['channels'][ch] = row
    return result


def install():
    import okx_risk732 as risk
    from okx_core import BotError, dec
    if getattr(risk, '_phone_entry_feed136', False):
        return
    for name in ('prepare_plan', 'submit_check'):
        original = getattr(risk, name)
        def wrap(fn):
            @functools.wraps(fn)
            def checked(e, plan, i, *args, **kwargs):
                try:
                    return fn(e, plan, i, *args, **kwargs)
                except BotError as exc:
                    if str(exc) not in ('V732 실시간 시세 확인 대기', 'V732 주문 직전 시세 지연'):
                        raise
                    try:
                        detail = quote_details(e, i['instId'])
                        missing = [ch+(' 미수신' if 'receive_age_s' not in v else
                            ' 수신'+str(v['receive_age_s'])+'초/거래소'+str(v['exchange_age_s'])+'초')
                            for ch, v in detail['channels'].items() if not v['ready']]
                    except Exception:
                        raise exc
                    error = BotError(str(exc)+' / '+i['instId']+' / '+', '.join(missing))
                    error.phone_admission_detail = detail
                    raise error from exc
            return checked
        setattr(risk, name, wrap(original))
    original_liquidity = risk.check_liquidity
    @functools.wraps(original_liquidity)
    def liquidity(check):
        try:
            return original_liquidity(check)
        except BotError as exc:
            detail = dict(spread_pct=str(dec(check['spread'])*100),
                slippage_pct=str(dec(check['slippage'])*100),
                spread_limit_pct=str(dec(risk.DEFAULTS['max_spread'])*100),
                slippage_limit_pct=str(dec(risk.DEFAULTS['max_slippage'])*100))
            error = BotError(str(exc)+' / 실제 스프레드 '+detail['spread_pct']+
                '% · 예상 슬리피지 '+detail['slippage_pct']+'%')
            error.phone_admission_detail = detail
            raise error from exc
    risk.check_liquidity = liquidity
    risk._phone_entry_feed136 = True
