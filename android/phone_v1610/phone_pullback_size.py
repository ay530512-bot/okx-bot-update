"""Phone 1.2.7: use the pinned original quarter allocation for every route.

The former pullback-long sixteenth overlay is deliberately not installed.
Existing positions, risk guards, and exchange configuration are untouched.
The updater starts a fresh interpreter before this validation runs.
"""
import hashlib
from pathlib import Path

RISK_SOURCE_SHA256 = '49fb7681b2ddbd894f40f1ea9e4985eeaec6c868568fb1fd37c2ffb95a37bd1d'


def install(source):
    import okx_risk732 as policy
    path = Path(source) / 'okx_risk732.py'
    if (path.is_symlink() or not path.is_file()
            or Path(policy.__file__).resolve() != path.resolve()):
        raise ValueError('기본 1/4 주문량 규칙 · Q2X 원본 경로 불일치')
    if hashlib.sha256(path.read_bytes()).hexdigest() != RISK_SOURCE_SHA256:
        raise ValueError('기본 1/4 주문량 규칙 · Q2X 원본 해시 불일치')
    if getattr(policy.cap_plan, 'phone_pullback_quarter_v120', False):
        raise ValueError('이전 1/16 주문량 규칙이 남아 있습니다. 새 실행기로 재시작 필요')
    if Path(policy.cap_plan.__code__.co_filename).resolve() != path.resolve():
        raise ValueError('기본 1/4 주문량 함수 경로 불일치')
    # Retain the original function object, including reserve/lot/depth checks.
