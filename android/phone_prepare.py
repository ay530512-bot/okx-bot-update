#!/usr/bin/env python3
"""Stage the audited Q2X source and check imports/public WS; never start trading."""
import argparse
import hashlib
import importlib.abc
import importlib.metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
import zipfile

VERSION = "phone-prepare-1"
BASE_COMMIT = "46b086ba15b54794777b408613fd5cefb892663d"
ARCHIVE_URL = ("https://raw.githubusercontent.com/ay530512-bot/okx-bot-update/"
               + BASE_COMMIT + "/release-input/OKX_PROGRAM_UPDATE.zip")
ARCHIVE_SHA256 = "6b2a0a90f02cca914ffc5cc0996555e8c1435b7a61618575ee94ee2ebdc2dad1"
PACKAGES = ("requests==2.34.2", "python-dotenv==1.2.4", "websocket-client==1.9.2")
SYMBOL = "AAVE-USDT-SWAP"
REQUIRED_CHANNELS = ("tickers", "books5", "mark-price")


def save(path, data):
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def checked_members(raw, expected_hash=ARCHIVE_SHA256):
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("download hash mismatch")
    members = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if len(z.infolist()) > 300 or sum(i.file_size for i in z.infolist()) > 8_000_000:
            raise ValueError("archive size limit")
        for item in z.infolist():
            p = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            supported_path = len(p.parts) == 1 or (len(p.parts) == 2 and p.parts[0] == "mobile_assets")
            if (p.is_absolute() or not supported_path or ".." in p.parts or str(p) != item.filename
                    or "\\" in item.filename or item.is_dir()
                    or stat.S_ISLNK(mode) or item.filename in members):
                raise ValueError("unsafe archive member")
            members[item.filename] = z.read(item)
    for name in ("okx_v5.py", "okx_stream.py", "okx_mobile.py", "release_info.json"):
        if name not in members:
            raise ValueError("incomplete source archive")
    release = json.loads(members["release_info.json"])
    if release.get("version") != "7.32-Q2X" or release.get("sequence") != 7320224:
        raise ValueError("unexpected source version")
    return members


def stage_source(raw, target, expected_hash=ARCHIVE_SHA256):
    members = checked_members(raw, expected_hash)
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            raise ValueError("unexpected existing source path")
        for name, data in members.items():
            p = target / name
            if p.is_symlink() or not p.is_file() or p.read_bytes() != data:
                raise ValueError("existing source differs; not overwritten")
        for p in target.rglob("*"):
            relative = p.relative_to(target)
            if p.is_symlink() or (p.is_file() and "__pycache__" not in relative.parts
                                 and relative.as_posix() not in members):
                raise ValueError("existing source has extra files; not overwritten")
        return len(members)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".source-", dir=target.parent))
    try:
        for name, data in members.items():
            (temp / name).parent.mkdir(parents=True, exist_ok=True)
            (temp / name).write_bytes(data)
        temp.rename(target)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return len(members)


class NoTk(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "tkinter" or name.startswith("tkinter."):
            raise ImportError("desktop GUI is not allowed in phone import check")


def import_check(source):
    # Import definitions only. No RuleEngine, AccountStream or mobile server instance.
    sys.path.insert(0, str(source))
    block_tk = NoTk()
    sys.meta_path.insert(0, block_tk)
    connect, create = socket.socket.connect, socket.create_connection
    def denied(*args, **kwargs):
        raise RuntimeError("network during import is forbidden")
    socket.socket.connect = denied
    socket.create_connection = denied
    try:
        for name in ("requests", "dotenv", "websocket", "okx_v5", "okx_stream", "okx_mobile"):
            __import__(name)
    finally:
        socket.socket.connect, socket.create_connection = connect, create
        sys.meta_path.remove(block_tk)
    return ["okx_v5", "okx_stream", "okx_mobile"]


def uptime():
    return time.clock_gettime(time.CLOCK_BOOTTIME) if hasattr(time, "CLOCK_BOOTTIME") else time.monotonic()


def sample_stream(stream, duration=60, clock=uptime, wall=time.time, sleep=time.sleep):
    updates = {ch: set() for ch in REQUIRED_CHANNELS}
    connected_once = False
    disconnect_seen = False
    max_gap = 0.0
    started = prev = clock()
    prev_wall = wall()
    final_fresh = {}
    while clock() - started < duration:
        sleep(0.5)
        now, now_wall = clock(), wall()
        max_gap = max(max_gap, now - prev, now_wall - prev_wall)
        prev, prev_wall = now, now_wall
        if stream.connected:
            connected_once = True
        elif connected_once:
            disconnect_seen = True
        for ch in REQUIRED_CHANNELS:
            row = stream.read(SYMBOL, ch, max_age=10, now_ms=int(now_wall * 1000))
            final_fresh[ch] = row is not None
            if row is not None:
                updates[ch].add(str(row["ts"]))
    good = (connected_once and not disconnect_seen and max_gap <= 5
            and all(final_fresh.values()) and all(len(v) >= 2 for v in updates.values()))
    return dict(ok=good, elapsed_seconds=round(clock() - started, 3),
                max_loop_gap_seconds=round(max_gap, 3), connected_once=connected_once,
                disconnect_seen=disconnect_seen, final_fresh=final_fresh,
                distinct_updates={k: len(v) for k, v in updates.items()})


def worker(root):
    report = dict(version=VERSION, source_commit=BASE_COMMIT, source_sha256=ARCHIVE_SHA256,
                  private_api=False, orders_sent=False, trading_engine_started=False,
                  status="checking", python=sys.version.split()[0])
    result_path = root / "runtime-check.json"
    save(result_path, report)
    report["imports"] = import_check(root / "q2x-source")
    report["packages"] = {p.split("==")[0]: importlib.metadata.version(p.split("==")[0]) for p in PACKAGES}
    print("현재 Q2X 코드 불러오기: 정상 (PC 창 필요 없음)", flush=True)
    from okx_stream import MarketStream
    stream = MarketStream()
    stream.watch([SYMBOL])
    print("실시간 공개 시세를 60초간 점검합니다. API 키/주문 없이 진행합니다.", flush=True)
    stream.start()
    try:
        report["websocket"] = sample_stream(stream)
        report["status"] = "public_runtime_check_passed" if report["websocket"]["ok"] else "needs_attention"
    finally:
        stream.stop()
    save(result_path, report)
    print("\n=== 폰 실행 준비 결과 ===")
    print("코드 준비: Q2X / 불러오기 정상")
    print("실시간 시세:", "정상" if report["websocket"]["ok"] else "추가 확인 필요")
    print("수신 횟수:", json.dumps(report["websocket"]["distinct_updates"]))
    print("점검 중 연결 끊김:", "있음" if report["websocket"]["disconnect_seen"] else "관측 안 됨")
    print("기존 PC 프로그램/계정/주문은 변경하지 않았습니다.")
    print("미완료: 계정 설정 이관, 폰 실행 화면·외부 접속, 실거래 관리 및 장시간 검증")
    print("결과 저장: ~/okx-phone-stage/runtime-check.json")
    return 0 if report["websocket"]["ok"] else 1


def prepare(root):
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer required")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    print("1/3 · 검증된 Q2X 코드 내려받기", flush=True)
    with urlopen(Request(ARCHIVE_URL, headers={"User-Agent": VERSION}), timeout=30) as r:
        raw = r.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("download size limit")
    count = stage_source(raw, root / "q2x-source")
    print(f"SHA-256 일치 / {count}개 파일 준비 완료", flush=True)
    print("2/3 · 실행에 필요한 Python 패키지 설치", flush=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                    "--only-binary=:all:", "--index-url", "https://pypi.org/simple", *PACKAGES], check=True)
    (root / "phone_prepare.py").write_bytes(Path(__file__).read_bytes())
    print("3/3 · 코드 불러오기 / 실시간 시세 점검", flush=True)
    completed = subprocess.run([sys.executable, "-B", str(root / "phone_prepare.py"), "--worker"])
    return completed.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path.home() / "okx-phone-stage"
    try:
        return worker(root) if args.worker else prepare(root)
    except KeyboardInterrupt:
        print("점검을 중단했습니다. 실거래는 시작하지 않았습니다.")
        return 130
    except Exception as exc:
        # No credential-bearing raw exception text or environment dump.
        print("실행 준비 미완료 · 오류 종류:", type(exc).__name__)
        print("이 화면을 알려주세요. 기존 PC는 계속 사용하세요.")
        if isinstance(exc, subprocess.CalledProcessError):
            print("패키지 설치/점검이 실패했습니다. 위 오류 문구를 확인하세요.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
