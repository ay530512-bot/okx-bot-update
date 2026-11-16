#!/usr/bin/env python3
"""Phone-local account setup. This process contains no trading-engine startup.

Only an allowlist of OKX GET endpoints is reachable, including at HTTP transport.
Credentials remain in Termux private storage, never in a report or public repo.
"""
import argparse
import copy
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
from collections import deque
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "phone-account-1"
PORT = 8767
SOURCE_VERSION = "7.32-Q2X"
READS = {
    "/api/v5/public/time": False,
    "/api/v5/account/config": True,
    "/api/v5/account/balance": True,
    "/api/v5/account/positions": True,
    "/api/v5/trade/orders-pending": True,
    "/api/v5/trade/orders-algo-pending": True,
}
SECRET_FIELDS = ("OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE")


def atomic_private(path, raw):
    """Atomic private write, without following a pre-existing target symlink."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("symbolic link is not allowed")
    fd, name = tempfile.mkstemp(prefix=".phone-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_json(path, data):
    atomic_private(path, json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode())


def validate_keys(data):
    if not isinstance(data, dict) or set(data) != set(SECRET_FIELDS):
        raise ValueError("세 가지 API 항목을 입력하세요.")
    if any(not isinstance(v, str) or not 1 <= len(v) <= 256 or
           any(ord(c) < 32 or ord(c) > 126 for c in v) for v in data.values()):
        raise ValueError("API 입력값의 길이 또는 문자를 확인하세요.")
    return dict(data)


class GetOnlySession:
    """Second gate: refuse POST, alternate hosts, redirects and bodies."""
    def __init__(self, session):
        self.inner = session

    def request(self, method, url, **kwargs):
        parsed = urlsplit(url)
        if (method != "GET" or parsed.scheme != "https" or
                parsed.netloc != "openapi.okx.com" or parsed.path not in READS or
                parsed.fragment or kwargs.get("data") is not None or kwargs.get("json") is not None):
            raise PermissionError("계정 조회 모드에서 허용되지 않은 요청입니다.")
        kwargs["allow_redirects"] = False
        response = self.inner.request(method, url, **kwargs)
        if 300 <= response.status_code < 400:
            raise PermissionError("조회 서버의 주소 변경 응답을 차단했습니다.")
        return response

    def close(self):
        self.inner.close()


def readonly_client(keys):
    from okx_core import OKX
    class ReadOnlyOKX(OKX):
        def request(self, method, path, params=None, body=None, private=True):
            if (method != "GET" or path not in READS or
                    private is not READS[path] or body is not None):
                raise PermissionError("계정 조회 모드: 주문·취소·설정 변경 차단")
            return super().request(method, path, params=params, private=private)
    api = ReadOnlyOKX(dict(validate_keys(keys), TRADING_EXCHANGE="okx"))
    api.session = GetOnlySession(api.session)
    api.read_efficiency = False  # No shared cache: each displayed check is a fresh GET.
    return api


def finite(value):
    n = float(value)
    if not math.isfinite(n):
        raise ValueError("non-finite account value")
    return n


def check_account(api):
    snap = api.snapshot()
    algos = api.pending_algos(full=True)
    positions = [p for p in snap["positions"] if finite(p.get("pos", "0")) != 0]
    config = snap["config"]
    compatible = str(config.get("acctLv")) == "2" and config.get("posMode") == "long_short_mode"
    return dict(status="connected", checked_ms=int(time.time()*1000),
                equity_usdt=str(snap["equity"]), available_usdt=str(snap["available"]),
                account_mode=str(config.get("acctLv", "")), position_mode=config.get("posMode", ""),
                mode_compatible=compatible, positions=len(positions),
                open_orders=len(snap["orders"]), conditional_orders=len(algos),
                # A flat snapshot is not proof that the PC is stopped or handover is safe.
                flat_at_observation=not positions and not snap["orders"] and not algos,
                message="계정 조회 완료 · 매매는 PC가 계속 담당합니다." if compatible else
                        "계정 연결은 확인됐지만 계정 모드가 현재 프로그램과 다릅니다. 설정은 변경하지 않았습니다.")


def public_error(exc):
    # Never echo a raw exception (a server/library can include credentials).
    match = re.search(r"\b(50110|50113|50123|50114|50111|50105|50102|50011|50040)\b", str(exc))
    code = match.group(1) if match else None
    message = {
        "50110": "API 허용 IP와 폰의 현재 인터넷 연결을 확인하세요.",
        "50113": "API Secret Key와 입력값을 확인하세요.",
        "50123": "API 권한을 확인하세요. 이 화면은 조회만 요청합니다.",
        "50114": "API 인증 정보를 확인하세요.",
        "50111": "API Key를 확인하세요.",
        "50105": "API Passphrase를 확인하세요.",
        "50102": "폰 날짜·시간 자동 설정을 확인하세요.",
        "50011": "조회 제한입니다. 잠시 후 다시 확인하세요.",
        "50040": "조회 제한입니다. 잠시 후 다시 확인하세요.",
    }.get(code, "계정 조회를 완료하지 못했습니다. 인터넷 연결과 입력값을 확인하세요.")
    return dict(status="error", code=code, message=message)


class Service:
    def __init__(self, root, config_sha, client_factory=readonly_client):
        self.root = Path(root)
        self.config_sha = config_sha
        self.client_factory = client_factory
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.wake = threading.Event()
        self.attempts = deque()
        self.sessions = {}
        self.login_code = str(secrets.randbelow(10**10)).zfill(10)
        self.login_deadline = time.monotonic()+1800
        self.keys_path = self.root/"phone_credentials.json"
        self.checking = False
        self.result = dict(status="not_configured", message="폰에 API 정보를 입력하세요.")
        self.report = dict(version=VERSION, source_version=SOURCE_VERSION, config_sha256=config_sha,
                           mode="read_only", orders_enabled=False, trading_engine_started=False,
                           external_access=False, runtime_handover_complete=False)

    def auth(self, cookie):
        try:
            token = SimpleCookie(cookie)["phone_session"].value
        except Exception:
            return False
        with self.lock:
            return self.sessions.get(token, 0) > time.monotonic()

    def login(self, code):
        with self.lock:
            now = time.monotonic()
            while self.attempts and self.attempts[0] < now-60:
                self.attempts.popleft()
            if len(self.attempts) >= 5:
                return None, 429
            self.attempts.append(now)
            if not isinstance(code, str) or not re.fullmatch(r"[0-9]{10}",code) or now > self.login_deadline or not hmac.compare_digest(code, self.login_code):
                return None, 401
            self.sessions = {k:v for k,v in self.sessions.items() if v > now}
            if len(self.sessions) >= 8:
                return None, 429
            token = secrets.token_urlsafe(32)
            self.sessions[token] = now+7200
            return token, 200

    def store_keys(self, body):
        keys = validate_keys(body)
        with self.lock:
            if self.checking:
                raise ValueError("계정 조회 중입니다. 완료 후 다시 시도하세요.")
            save_json(self.keys_path, keys)
            self.result = dict(status="waiting", message="API 정보 저장 완료 · 계정 조회 대기")
            self.wake.set()

    def snapshot(self):
        with self.lock:
            return dict(self.report, credentials_saved=self.keys_path.is_file(),
                        checking=self.checking, account=copy.deepcopy(self.result))

    def check_once(self):
        with self.lock:
            if not self.keys_path.is_file() or self.checking:
                return
            self.checking = True
        api = None
        try:
            if self.keys_path.is_symlink():
                raise ValueError("credentials symlink")
            api = self.client_factory(validate_keys(json.loads(self.keys_path.read_text())))
            result = check_account(api)
        except Exception as exc:
            result = public_error(exc)
        finally:
            if api is not None:
                api.session.close()
        with self.lock:
            self.result = result
            self.checking = False
            # Persist health/counters only, not balance, keys, account identifiers or raw errors.
            safe = dict(self.report, checked_ms=result.get("checked_ms"), status=result["status"],
                        mode_compatible=result.get("mode_compatible"), positions=result.get("positions"),
                        open_orders=result.get("open_orders"), conditional_orders=result.get("conditional_orders"),
                        error_code=result.get("code"))
            save_json(self.root/"account-check.json", safe)

    def worker(self):
        while not self.closed.is_set():
            self.wake.wait(30)
            self.wake.clear()
            if self.closed.is_set():
                break
            self.check_once()


HTML = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OKX 폰 연결</title><link rel="stylesheet" href="/style.css"><main><header><small>PHONE · Q2X</small><h1>OKX 폰 연결</h1><span class="badge">계정 조회 전용</span></header><section id="login"><h2>폰에서 연결하기</h2><p>Termux에 표시된 10자리 접속 코드를 입력하세요.</p><form id="loginForm"><input name="code" type="password" inputmode="numeric" autocomplete="off" placeholder="접속 코드" maxlength="10" required><button>연결</button></form></section><div id="app" hidden><section><h2>설정 준비 완료</h2><p>7.32-Q2X · 15분봉 긴꼬리 수익 보호 포함</p><p>보내준 매매 설정을 변경 없이 보관했습니다.</p><p class="muted" id="hash"></p></section><section><h2>계정 연결</h2><p id="saved">OKX API 정보를 이 폰에만 저장합니다.</p><form id="keysForm"><label>API Key<input name="OKX_API_KEY" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" required></label><label>Secret Key<input name="OKX_SECRET_KEY" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" required></label><label>Passphrase<input name="OKX_PASSPHRASE" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" required></label><button id="save">저장하고 계정 확인</button></form></section><section><h2>연결 상태</h2><p id="state">확인 대기</p><dl id="values"></dl><button id="refresh" class="secondary">다시 확인</button></section><section class="notice"><h2>PC에서 계속 운용 중</h2><p>이 화면에서는 주문·청산·SL 변경을 실행하지 않습니다. 폰 실거래 전환과 외부 접속은 아직 완료되지 않았습니다.</p><p>PC 프로그램은 이전 완료 전까지 유지하세요.</p></section><button id="logout" class="secondary">화면 잠그기</button></div><p id="error" role="alert"></p></main><script src="/app.js"></script></html>'''
CSS = '''*{box-sizing:border-box}body{margin:0;background:#000;color:#f5f5f5;font-family:system-ui,sans-serif}main{max-width:620px;margin:auto;padding:28px 18px 60px}header{padding:18px 4px 28px}small,.muted{color:#999}h1{font-size:32px;margin:10px 0 18px}h2{font-size:20px;margin:0 0 16px}section{background:#1c1c1c;border-radius:24px;padding:22px;margin-bottom:16px}p{line-height:1.6}input{width:100%;border:1px solid #444;background:#292929;color:#fff;padding:16px;border-radius:14px;font-size:16px;margin:8px 0 18px}button{border:0;background:#c7fc4a;color:#111;border-radius:28px;padding:16px 22px;font-size:16px;font-weight:700;width:100%;cursor:pointer}button:disabled{opacity:.45}.secondary{background:#303030;color:#eee}.badge{display:inline-block;color:#c7fc4a;background:#26310b;border-radius:20px;padding:7px 13px}.notice{border:1px solid #514523}dt{color:#999;font-size:14px;margin-top:18px}dd{margin:4px 0;font-size:22px;overflow-wrap:anywhere}#error{color:#ff839d}#hash{font-size:12px;overflow-wrap:anywhere}[hidden]{display:none!important}'''
JS = '''const $=s=>document.querySelector(s);let busy=false;async function request(path,data){const r=await fetch(path,{method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const j=await r.json();if(!r.ok){if(r.status===401){$('#app').hidden=true;$('#login').hidden=false;}throw Error(j.error||'연결 확인이 필요합니다.');}return j;}function error(e){$('#error').textContent=e.message;}async function status(){if(busy)return;busy=true;try{const j=await request('/status');$('#login').hidden=true;$('#app').hidden=false;$('#hash').textContent='설정 확인: '+j.config_sha256.slice(0,16);$('#saved').textContent=j.credentials_saved?'API 정보가 이 폰에 저장돼 있습니다. 변경할 때만 다시 입력하세요.':'OKX API 정보를 이 폰에만 저장합니다.';$('#save').disabled=j.checking;$('#refresh').disabled=j.checking;const a=j.account;$('#state').textContent=j.checking?'계정 조회 중…':a.message;const v=$('#values');v.replaceChildren();if(a.status==='connected'){for(const [k,x] of [['평가자산 (USDT)',a.equity_usdt],['가용잔고 (USDT)',a.available_usdt],['보유 포지션',a.positions],['미체결 / 조건주문',a.open_orders+' / '+a.conditional_orders],['계정 모드',a.mode_compatible?'호환 확인':'확인 필요'],['조회 시각',new Date(a.checked_ms).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' KST']]){const t=document.createElement('dt'),d=document.createElement('dd');t.textContent=k;d.textContent=x;v.append(t,d);}}}catch(e){if(!$('#app').hidden)error(e);}finally{busy=false;}}$('#loginForm').onsubmit=async e=>{e.preventDefault();try{await request('/login',Object.fromEntries(new FormData(e.target)));e.target.reset();$('#error').textContent='';await status();}catch(x){error(x);}};$('#keysForm').onsubmit=async e=>{e.preventDefault();$('#save').disabled=true;try{await request('/keys',Object.fromEntries(new FormData(e.target)));e.target.reset();$('#error').textContent='';await status();}catch(x){error(x);}finally{$('#save').disabled=false;}};$('#refresh').onclick=async()=>{try{await request('/refresh',{});await status();}catch(e){error(e);}};$('#logout').onclick=async()=>{try{await request('/logout',{});$('#app').hidden=true;$('#login').hidden=false;$('#values').replaceChildren();}catch(e){error(e);}};setInterval(status,5000);status();'''


def handler(service):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PhoneLocal"
        sys_version = ""
        def log_message(self, *args):
            pass
        def setup(self):
            super().setup()
            self.connection.settimeout(5)
        def reply(self, status, value, content_type="application/json; charset=utf-8", cookie=None):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            for key,val in {"Content-Type":content_type, "Content-Length":str(len(raw)), "Cache-Control":"no-store",
                            "Referrer-Policy":"no-referrer", "X-Frame-Options":"DENY", "X-Content-Type-Options":"nosniff",
                            "Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"}.items():
                self.send_header(key,val)
            if cookie:
                self.send_header("Set-Cookie",cookie)
            self.end_headers()
            self.wfile.write(raw)
        def host_ok(self):
            expected = "127.0.0.1:"+str(self.server.server_address[1])
            if self.headers.get("Host") != expected:
                self.reply(403,dict(error="Termux에 표시된 주소로 접속하세요."))
                return False
            return True
        def authorized(self):
            if not service.auth(self.headers.get("Cookie", "")):
                self.reply(401,dict(error="접속 코드를 입력하세요."))
                return False
            return True
        def do_GET(self):
            if not self.host_ok():
                return
            static = {"/":(HTML,"text/html"), "/app.js":(JS,"text/javascript"), "/style.css":(CSS,"text/css")}
            if self.path in static:
                text, kind = static[self.path]
                self.reply(200,text.encode(),kind+"; charset=utf-8")
            elif self.path == "/status" and self.authorized():
                self.reply(200,service.snapshot())
            elif self.path != "/status":
                self.reply(404,dict(error="없는 페이지입니다."))
        def do_POST(self):
            if not self.host_ok():
                return
            if self.headers.get("Origin") != "http://"+self.headers["Host"]:
                self.reply(403,dict(error="같은 폰의 연결 화면에서 요청하세요."));return
            if self.path not in ("/login","/keys","/refresh","/logout"):
                self.reply(405,dict(error="조회 전용입니다. 주문 기능이 없습니다."));return
            try:
                size = int(self.headers.get("Content-Length","0"))
                if (not 0 < size <= 2048 or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
                        or self.headers.get("Transfer-Encoding")):
                    raise ValueError()
                body = json.loads(self.rfile.read(size))
                if not isinstance(body,dict):
                    raise ValueError()
            except (ValueError, TypeError):
                self.reply(400,dict(error="입력 형식을 확인하세요."));return
            suffix = "; Path=/; HttpOnly; SameSite=Strict"
            if self.path == "/login":
                token, status = service.login(body.get("code"))
                self.reply(status,dict(ok=True) if token else dict(error="접속 코드 또는 시도 횟수를 확인하세요."),
                           cookie="phone_session="+token+suffix if token else None)
                return
            if not self.authorized():
                return
            if self.path == "/logout":
                token=SimpleCookie(self.headers["Cookie"])["phone_session"].value
                with service.lock:
                    service.sessions.pop(token,None)
                self.reply(200,dict(ok=True),cookie="phone_session=; Max-Age=0"+suffix)
            elif self.path == "/refresh":
                service.wake.set();self.reply(202,dict(ok=True))
            else:
                try:
                    service.store_keys(body)
                except ValueError as exc:
                    self.reply(400,dict(error=str(exc)));return
                except OSError:
                    self.reply(500,dict(error="폰 내부 저장 공간을 확인하세요."));return
                self.reply(202,dict(ok=True))
    return Handler


def validate_config(root, expected_sha):
    path = root/"strategy_config.json"
    if path.is_symlink():
        raise ValueError("config symlink")
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_sha:
        raise ValueError("설정 파일이 준비한 원본과 다릅니다.")
    cfg=json.loads(raw.decode("utf-8-sig"))
    from okx_pattern15 import validate_config as validate
    before=copy.deepcopy(cfg)
    validate(cfg)
    if before!=cfg:
        raise ValueError("설정 검사가 파일 값을 변경하려 했습니다.")
    if not cfg.get("execution",{}).get("rule_channel701"):
        raise ValueError("expected Q2X route")


def main(root=None):
    root=Path(root or Path(__file__).resolve().parent)
    os.umask(0o077)
    meta=json.loads((root/"phone_installation.json").read_text())
    source=Path(meta["source_path"])
    # Verify every pinned source file before importing any exchange code.
    for relative, expected in meta["source_files"].items():
        p=source/relative
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError("Q2X 소스가 바뀌었습니다. 재설치 전에 확인이 필요합니다.")
    sys.path.insert(0,str(source))
    validate_config(root,meta["config_sha256"])
    service=Service(root,meta["config_sha256"])
    server=ThreadingHTTPServer(("127.0.0.1",PORT),handler(service))
    server.daemon_threads=True
    worker=threading.Thread(target=service.worker,daemon=True,name="phone-account-read-only")
    worker.start()
    print("\n설정 원본 일치 / Q2X 검사 통과",flush=True)
    print("이 폰의 Chrome에서 http://127.0.0.1:8767 을 여세요.",flush=True)
    print("접속 코드:",service.login_code,flush=True)
    print("API 정보는 브라우저 입력칸에만 입력하세요. 이 화면은 주문하지 않습니다.",flush=True)
    print("종료: Ctrl+C / 아직 PC를 끄지 마세요.",flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        print("폰 조회 화면을 종료했습니다. PC 및 주문은 변경하지 않았습니다.")
    finally:
        service.closed.set();service.wake.set();server.server_close();worker.join(timeout=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("폰 연결 화면 시작 실패:",type(exc).__name__)
        print("기존 파일은 삭제하지 말고 이 오류 종류를 알려주세요.")
        sys.exit(1)
