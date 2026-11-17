"""Retired 1.7.0 EMA entry identity, kept for existing position management.

1.7.1 never emits or admits this entry. Existing owned records keep their
original reserved-slot trailing protection and morning-switch management.
"""
STATE = 'phone_ema_support170'
ROUTE = 'top1_ema20_support170'


def is_signal(s):
    return bool(s and s.get('pattern') == ROUTE)


def scan(e):
    e.phone_support_status = '추가 EMA20 신규 진입 제거됨'
    e.phone_support_diagnostic = {}
    return None


def validate_entry(e, s, price):
    from okx_core import BotError
    raise BotError('제거된 EMA20 추가 진입 신호 · 신규 주문 차단')
