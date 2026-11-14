"""Phone 1.2.0: quarter-size only a selected automatic 7.32 pullback long.

Keeps Q2X's pinned original files, order proof, shared equity, reserve, leverage,
lot rounding, depth checks and deterministic final recomputation. No I/O to the
exchange, config changes, or changes to positions already open.
"""
import ast
from functools import wraps
import hashlib
from pathlib import Path
from types import FunctionType

RISK_SOURCE_SHA256 = '49fb7681b2ddbd894f40f1ea9e4985eeaec6c868568fb1fd37c2ffb95a37bd1d'
ORIGINAL_TARGET = '    target = equity / 4\n'
SMALL_TARGET = '    target = equity / 16\n'


def reduced(signal, direction):
    if (direction != 'long' or signal.get('action') != 'LONG'
            or not signal.get('rule_channel701')
            or any(signal.get(k) for k in ('click716', 'user_chat_order', 'selected_ai_order'))):
        return False
    proof = (signal.get('decision_record') or {}).get('volume_wick_proof') or {}
    return proof.get('route721') == 'trend_pullback' and proof.get('action') == 'LONG'


def install(source):
    import okx_risk732 as policy

    path = Path(source) / 'okx_risk732.py'
    if (path.is_symlink() or not path.is_file()
            or Path(policy.__file__).resolve() != path.resolve()):
        raise ValueError('눌림목 주문량 규칙 · Q2X 원본 경로 불일치')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RISK_SOURCE_SHA256:
        raise ValueError('눌림목 주문량 규칙 · Q2X 원본 해시 불일치')

    original = policy.cap_plan
    if getattr(original, 'phone_pullback_quarter_v120', False):
        return
    text = raw.decode('utf-8')
    matches = [node for node in ast.parse(text).body
               if isinstance(node, ast.FunctionDef) and node.name == 'cap_plan']
    if len(matches) != 1:
        raise ValueError('눌림목 주문량 규칙 · Q2X 수량 함수 불일치')
    node = matches[0]
    cap_source = ''.join(text.splitlines(keepends=True)[node.lineno-1:node.end_lineno])
    if (original.__code__.co_firstlineno != node.lineno
            or cap_source.count(ORIGINAL_TARGET) != 1
            or cap_source.count('시드 1/4') != 3):
        raise ValueError('눌림목 주문량 규칙 · Q2X 증거금 계산 불일치')
    cap_source = cap_source.replace(ORIGINAL_TARGET, SMALL_TARGET, 1)
    cap_source = cap_source.replace('시드 1/4', '눌림목 롱 증거금')
    namespace = {}
    exec(compile('\n'*(node.lineno-1)+cap_source, str(path), 'exec'), namespace)
    small = FunctionType(namespace['cap_plan'].__code__, policy.__dict__, 'cap_plan')

    @wraps(original)
    def cap_plan(e, plan, i, s, direction, snapshot, fee):
        if not reduced(s, direction):
            return original(e, plan, i, s, direction, snapshot, fee)
        result = small(e, plan, i, s, direction, snapshot, fee)
        result['risk732']['target_multiplier'] = '0.25'
        return result

    cap_plan.phone_pullback_quarter_v120 = True
    policy.cap_plan = cap_plan
