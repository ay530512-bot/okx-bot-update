"""Keep every quote and mark callback; avoid rebuilding unchanged OHLC tuples."""
import ast
import hashlib
import inspect
from types import FunctionType


def install(pins):
    import okx_stream
    cls = okx_stream.MarketStream
    if getattr(cls, '_phone_feed_fast', False):
        return
    path = inspect.getsourcefile(okx_stream)
    with open(path, 'rb') as handle:
        raw = handle.read()
    if hashlib.sha256(raw).hexdigest() != pins['files']['okx_stream.py']:
        raise ValueError('public feed source hash mismatch')
    tree = ast.parse(raw)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MarketStream')
    node = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == 'feed')
    before = 'self.band_prices[key] = (start, max(previous[1], price), min(previous[2], price), price, self.generation)'
    class SkipIdentical(ast.NodeTransformer):
        count = 0
        def visit_Assign(self, item):
            if ast.unparse(item) != before:
                return item
            self.count += 1
            # Prices are finite and positive here; preserve tie selection while
            # avoiding two Python function calls on every changed-price bar.
            assign = ast.parse('self.band_prices[key] = (start, '
                               'previous[1] if previous[1] >= price else price, '
                               'previous[2] if previous[2] <= price else price, '
                               'price, self.generation)').body[0]
            return ast.If(test=ast.parse('previous[3] != price', mode='eval').body,
                          body=[assign], orelse=[])
    transform = SkipIdentical()
    node = transform.visit(node)
    if transform.count != 1:
        raise ValueError('public feed patch anchor mismatch')
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 path+'<phone125>', 'exec'), namespace)
    cls.feed = FunctionType(namespace['feed'].__code__, okx_stream.__dict__, 'feed')
    cls._phone_feed_fast = True
