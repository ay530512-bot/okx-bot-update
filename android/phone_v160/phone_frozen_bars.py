"""Immutable published candle inputs. No clocks, quotes or order verdicts cached."""
import copy
import functools
import hashlib
import inspect
import pickle
import math


class FrozenBars(tuple):
    def __new__(cls, rows):
        # Copy every nested row, preserving numeric types and exact values.
        values = tuple(tuple(row) for row in rows)
        if any(type(x) not in (int, float) or not math.isfinite(x)
               for row in values for x in row):
            raise ValueError('unsupported immutable candle input')
        result = tuple.__new__(cls, values)
        object.__setattr__(result, '_encoded', pickle.dumps(result.thaw(), protocol=5))
        object.__setattr__(result, '_aligned15', all(row and type(row[0]) is int
                                                  and row[0] % 900000 == 0 for row in values))
        return result

    def __setattr__(self, name, value):
        raise TypeError('immutable candle snapshot')

    def __delattr__(self, name):
        raise TypeError('immutable candle snapshot')

    def thaw(self):
        return [list(row) for row in self]

    def __deepcopy__(self, memo):
        # Legacy chart/candidate consumers expect an editable independent list.
        value = self.thaw()
        memo[id(self)] = value
        return value

    def __reduce__(self):
        return (list, (self.thaw(),))


def freeze(rows):
    if type(rows) is FrozenBars:
        return rows
    if type(rows) not in (list, tuple) or any(type(row) not in (list, tuple) for row in rows):
        return rows
    try:
        return FrozenBars(rows)
    except (ValueError, TypeError, OverflowError):
        # Invalid/unusual data follows all original validation, without a fast key.
        return rows


def install(module, pins):
    path = inspect.getsourcefile(module)
    with open(path, 'rb') as source:
        if hashlib.sha256(source.read()).hexdigest() != pins['files']['okx_band_flow.py']:
            raise ValueError('immutable candle producer source hash mismatch')
    original = module.merge_completed
    if getattr(original, '_phone_frozen_bars', False):
        return

    @functools.wraps(original)
    def merged(*args, **kwargs):
        return freeze(original(*args, **kwargs))
    merged._phone_frozen_bars = True
    module.merge_completed = merged
