#!/usr/bin/env python3
"""Fold3/Termux preflight only: public GETs, no credentials, no trading."""
import argparse
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VERSION = "phone-check-1"
BASE = "https://openapi.okx.com"
TIME_PATH = "/api/v5/public/time"
CANDLE_PATH = "/api/v5/market/candles?instId=AAVE-USDT-SWAP&bar=15m&limit=3"
MAX_GAP = 5.0


def read_public(path):
    if path not in (TIME_PATH, CANDLE_PATH):
        raise ValueError("public endpoint not allowed")
    req = Request(BASE + path, headers={"User-Agent": VERSION}, method="GET")
    with urlopen(req, timeout=12) as response:
        data = response.read(131073)
    if len(data) > 131072:
        raise ValueError("oversize response")
    result = json.loads(data)
    if not isinstance(result, dict) or result.get("code") != "0":
        raise ValueError("exchange response unsuccessful")
    if not isinstance(result.get("data"), list) or not result["data"]:
        raise ValueError("empty exchange response")
    return result["data"]


def public_checks(fetch=read_public, wall=time.time):
    results = {}
    for name, path in (("server_time", TIME_PATH), ("candles", CANDLE_PATH)):
        try:
            before = wall()
            data = fetch(path)
            after = wall()
            if name == "server_time":
                server = float(data[0]["ts"]) / 1000
                offset = server - (before + after) / 2
                if not math.isfinite(offset):
                    raise ValueError("invalid server clock")
                results[name] = {"ok": abs(offset) <= 5,
                                 "clock_offset_seconds": round(offset, 3),
                                 "round_trip_seconds": round(after - before, 3)}
            else:
                row = data[0]
                if len(row) < 9 or row[8] not in ("0", "1"):
                    raise ValueError("unexpected candle schema")
                o, h, low, c = map(float, row[1:5])
                if not all(math.isfinite(x) and x > 0 for x in (o, h, low, c)):
                    raise ValueError("invalid prices")
                if not low <= min(o, c) <= max(o, c) <= h:
                    raise ValueError("invalid price range")
                results[name] = {"ok": True, "rows": len(data)}
        except Exception as exc:
            # Do not print raw exception URLs, response bodies or local paths.
            detail = {"ok": False, "error_type": type(exc).__name__}
            if isinstance(exc, HTTPError):
                detail["http_status"] = exc.code
            results[name] = detail
    return results


def uptime():
    # Linux BOOTTIME includes device suspension, unlike CLOCK_MONOTONIC.
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    return time.monotonic()


def heartbeat_gap(prev_up, now_up, prev_wall, now_wall):
    return max(0, now_up - prev_up, now_wall - prev_wall)


def save_report(path, report):
    temp = path.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=180)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 86400:
        parser.error("--seconds must be 10..86400")
    folder = Path.home() / "okx-phone-check"
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / "result.json"
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("status") == "running":
                print("이전 점검이 끝나지 않았습니다. 종료/앱 중단 여부를 확인하세요.")
            save_report(folder / "previous-result.json", old)
        except (OSError, ValueError):
            print("이전 점검 결과를 읽지 못했습니다.")
    report = {
        "version": VERSION,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(), "architecture": platform.machine(),
        "scope": "public-network-and-short-heartbeat-only",
        "screen_off_verified": False,
        "screen_off_note": "User must confirm; not detected automatically",
        "boottime_clock": hasattr(time, "CLOCK_BOOTTIME"),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requested_seconds": args.seconds, "status": "running",
        "elapsed_seconds": 0, "max_gap_seconds": 0, "gap_over_5s_count": 0,
    }
    save_report(path, report)
    print("OKX 폰 사전 점검 · API 키/주문/계좌 접속 없음", flush=True)
    report["public_before"] = public_checks()
    save_report(path, report)
    print("첫 공개 접속:", json.dumps(report["public_before"], ensure_ascii=False), flush=True)
    print(f"이제 화면을 꺼주세요. {args.seconds}초 뒤 켜고 결과를 확인하세요.", flush=True)
    start = prev_up = uptime()
    prev_wall = time.time()
    try:
        while True:
            time.sleep(1)
            now_up, now_wall = uptime(), time.time()
            gap = heartbeat_gap(prev_up, now_up, prev_wall, now_wall)
            report["max_gap_seconds"] = round(max(report["max_gap_seconds"], gap), 3)
            report["gap_over_5s_count"] += int(gap > MAX_GAP)
            report["elapsed_seconds"] = round(now_up - start, 3)
            save_report(path, report)
            prev_up, prev_wall = now_up, now_wall
            if now_up - start >= args.seconds:
                break
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        save_report(path, report)
        print("중단됨 · 실거래 준비 완료가 아닙니다.")
        return 2
    report["public_after"] = public_checks()
    public_ok = all(item["ok"] for phase in ("public_before", "public_after")
                    for item in report[phase].values())
    ok = public_ok and report["gap_over_5s_count"] == 0
    report["status"] = "short_check_passed" if ok else "needs_attention"
    save_report(path, report)
    print("\n=== 폰 점검 결과 ===")
    print("판정:", "짧은 기초점검 통과" if ok else "추가 확인 필요")
    print(f"실행: {report['elapsed_seconds']}초 / 최대 멈춤 간격: {report['max_gap_seconds']}초")
    print("공개 API:", "정상" if public_ok else "실패/시간 오차 있음")
    if not public_ok:
        print(json.dumps({k: report[k] for k in ("public_before", "public_after")}, ensure_ascii=False))
    print("화면 꺼짐은 직접 확인해야 합니다. 24시간 안정성/실거래/원격접속은 아직 미검증입니다.")
    print("결과 저장: ~/okx-phone-check/result.json")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
