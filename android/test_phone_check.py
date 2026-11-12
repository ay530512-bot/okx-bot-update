import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import phone_check as check


def good_data(path):
    if path == check.TIME_PATH:
        return [{"ts": "1000000"}]
    return [["1000000", "10", "12", "9", "11", "4", "4", "44", "1"]]


class PreflightTests(unittest.TestCase):
    def test_public_success(self):
        result = check.public_checks(good_data, lambda: 1000)
        self.assertTrue(all(x["ok"] for x in result.values()))

    def test_wrong_clock(self):
        result = check.public_checks(good_data, lambda: 1020)
        self.assertFalse(result["server_time"]["ok"])

    def test_invalid_candle(self):
        def bad(path):
            data = good_data(path)
            if path == check.CANDLE_PATH:
                data[0][2] = "1"
            return data
        self.assertFalse(check.public_checks(bad, lambda: 1000)["candles"]["ok"])

    def test_nan_clock(self):
        self.assertFalse(check.public_checks(lambda _: [{"ts": "NaN"}], lambda: 1000)["server_time"]["ok"])

    def test_private_endpoint_rejected_before_network(self):
        with patch.object(check, "urlopen") as network:
            with self.assertRaises(ValueError):
                check.read_public("/api/v5/account/balance")
            network.assert_not_called()

    def test_http_error_redacted(self):
        def forbidden(_):
            raise HTTPError("https://private.invalid/secret", 403, "sensitive", {}, None)
        result = check.public_checks(forbidden)
        self.assertEqual(result["candles"]["http_status"], 403)
        self.assertNotIn("secret", json.dumps(result))

    def test_sleep_gap_includes_suspension_and_clock_change(self):
        self.assertEqual(check.heartbeat_gap(0, 1, 10, 71), 61)
        self.assertEqual(check.heartbeat_gap(0, 61, 10, 11), 61)
        self.assertEqual(check.heartbeat_gap(0, 1, 10, 9), 1)

    def test_report_persists_running_and_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            check.save_report(path, {"status": "running"})
            self.assertEqual(json.loads(path.read_text())["status"], "running")
            check.save_report(path, {"status": "short_check_passed"})
            self.assertEqual(json.loads(path.read_text())["status"], "short_check_passed")
            self.assertFalse(path.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()
