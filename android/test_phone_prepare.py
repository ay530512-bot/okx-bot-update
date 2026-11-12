import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import phone_prepare as p


def archive(extra=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name in ("okx_v5.py", "okx_stream.py", "okx_mobile.py"):
            z.writestr(name, "# test definition only\n")
        z.writestr("release_info.json", json.dumps(dict(version="7.32-Q2X", sequence=7320224)))
        if extra:
            z.writestr(*extra)
    raw = out.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


class SourceTests(unittest.TestCase):
    def test_valid_archive_and_idempotent_stage(self):
        raw, sha = archive()
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "source"
            self.assertEqual(p.stage_source(raw, target, sha), 4)
            self.assertEqual(p.stage_source(raw, target, sha), 4)

    def test_wrong_hash_rejected(self):
        raw, _ = archive()
        with self.assertRaises(ValueError):
            p.checked_members(raw, "0" * 64)

    def test_bundled_mobile_assets_preserved(self):
        raw, sha = archive(("mobile_assets/app.js", "const demo = true;"))
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "source"
            self.assertEqual(p.stage_source(raw, target, sha), 5)
            self.assertEqual(p.stage_source(raw, target, sha), 5)
            self.assertEqual((target / "mobile_assets/app.js").read_text(), "const demo = true;")

    def test_traversal_and_absolute_rejected(self):
        for name in ("../outside.py", "/outside.py", "a/b.py", "a\\b.py"):
            raw, sha = archive((name, "bad"))
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.checked_members(raw, sha)

    def test_changed_existing_source_not_overwritten(self):
        raw, sha = archive()
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "source"
            p.stage_source(raw, target, sha)
            (target / "okx_v5.py").write_text("existing")
            with self.assertRaises(ValueError):
                p.stage_source(raw, target, sha)
            self.assertEqual((target / "okx_v5.py").read_text(), "existing")

    def test_extra_file_refused(self):
        raw, sha = archive()
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "source"
            p.stage_source(raw, target, sha)
            (target / "requests.py").write_text("shadow module")
            with self.assertRaises(ValueError):
                p.stage_source(raw, target, sha)

    def test_tk_import_rejected(self):
        with self.assertRaises(ImportError):
            p.NoTk().find_spec("tkinter")


class FakeClock:
    def __init__(self): self.t = 0
    def now(self): return self.t
    def sleep(self, delay): self.t += delay


class FakeStream:
    connected = True
    def __init__(self, clock, missing=False): self.clock, self.missing = clock, missing
    def read(self, symbol, ch, **kwargs):
        return None if self.missing and ch == "mark-price" else {"ts": int(self.clock.t * 1000)}


class SamplingTests(unittest.TestCase):
    def test_live_updates_pass(self):
        c = FakeClock()
        result = p.sample_stream(FakeStream(c), 4, c.now, c.now, c.sleep)
        self.assertTrue(result["ok"])
        self.assertEqual(result["distinct_updates"]["mark-price"], 8)

    def test_missing_mark_fails(self):
        c = FakeClock()
        self.assertFalse(p.sample_stream(FakeStream(c, True), 4, c.now, c.now, c.sleep)["ok"])

    def test_paused_execution_fails(self):
        c = FakeClock()
        def paused(delay): c.t += 6
        self.assertFalse(p.sample_stream(FakeStream(c), 12, c.now, c.now, paused)["ok"])

    def test_disconnect_recorded(self):
        c = FakeClock()
        s = FakeStream(c)
        def disconnect(delay):
            c.sleep(delay)
            s.connected = c.t < 2
        result = p.sample_stream(s, 4, c.now, c.now, disconnect)
        self.assertFalse(result["ok"])
        self.assertTrue(result["disconnect_seen"])


if __name__ == "__main__":
    unittest.main()
