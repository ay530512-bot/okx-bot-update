import http.client
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from http.server import ThreadingHTTPServer
import phone_account as app

KEYS=dict(OKX_API_KEY="dummy-key",OKX_SECRET_KEY="dummy-secret",OKX_PASSPHRASE="dummy-pass")


class BoundaryTests(unittest.TestCase):
    def test_transport_blocks_all_non_get_and_foreign_destinations_before_network(self):
        transport=Mock(); s=app.GetOnlySession(transport)
        attempts=[("POST","https://openapi.okx.com/api/v5/trade/order",{}),
                  ("GET","https://other.example/api/v5/account/config",{}),
                  ("GET","http://openapi.okx.com/api/v5/account/config",{}),
                  ("GET","https://openapi.okx.com/api/v5/account/config",dict(data="secret")),
                  ("GET","https://openapi.okx.com/api/v5/account/config",dict(json={})),
                  ("GET","https://openapi.okx.com/api/v5/trade/cancel-order",{})]
        # Even an empty JSON object must be refused (a caller must send no body).
        for method,url,kw in attempts:
            with self.subTest(method=method,url=url,kw=kw),self.assertRaises(PermissionError):
                s.request(method,url,**kw)
        transport.request.assert_not_called()

    def test_redirect_never_followed(self):
        transport=Mock();transport.request.return_value.status_code=302
        with self.assertRaises(PermissionError):
            app.GetOnlySession(transport).request("GET","https://openapi.okx.com/api/v5/public/time")
        self.assertFalse(transport.request.call_args.kwargs["allow_redirects"])

    def test_exact_public_endpoint_accepted(self):
        transport=Mock();transport.request.return_value.status_code=200
        self.assertIs(app.GetOnlySession(transport).request("GET","https://openapi.okx.com/api/v5/public/time"),transport.request.return_value)

    def test_bad_fields_and_header_injection(self):
        for data in (dict(KEYS,TRADING_EXCHANGE="binance"),dict(KEYS,OKX_API_KEY="abc\n"),dict(KEYS,OKX_SECRET_KEY="")):
            with self.assertRaises(ValueError):app.validate_keys(data)

    def test_error_never_echoes_raw_secret(self):
        error=app.public_error(Exception("secret-credential-text 50110"))
        self.assertNotIn("secret-credential-text",json.dumps(error))
        self.assertEqual(error["code"],"50110")

    def test_private_file_mode_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"key.json";app.save_json(p,KEYS)
            self.assertEqual(p.stat().st_mode & 0o777,0o600)
            q=Path(folder)/"link";q.symlink_to(p)
            with self.assertRaises(ValueError):app.save_json(q,{})
            self.assertEqual(json.loads(p.read_text()),KEYS)

    def test_account_report_does_not_copy_secrets_or_uid(self):
        with tempfile.TemporaryDirectory() as folder:
            api=Mock();api.snapshot.return_value=dict(config=dict(acctLv="2",posMode="long_short_mode",uid="PRIVATE-UID"),equity="100",available="70",positions=[dict(pos="0"),dict(pos="2")],orders=[])
            api.pending_algos.return_value=[dict(algoId="PRIVATE-ORDER-ID")]
            s=app.Service(folder,"config-hash",client_factory=lambda k:api)
            s.store_keys(KEYS);s.check_once()
            snap=s.snapshot();report=(Path(folder)/"account-check.json").read_text()
            self.assertEqual(snap["account"]["positions"],1)
            self.assertEqual(snap["account"]["conditional_orders"],1)
            self.assertFalse(snap["runtime_handover_complete"])
            for private in ("dummy-key","dummy-secret","dummy-pass","PRIVATE-UID","PRIVATE-ORDER-ID","equity_usdt"):
                self.assertNotIn(private,report)

    def test_bad_account_mode_not_marked_compatible(self):
        api=Mock();api.snapshot.return_value=dict(config=dict(acctLv="3",posMode="net_mode"),equity="100",available="100",positions=[],orders=[]);api.pending_algos.return_value=[]
        result=app.check_account(api)
        self.assertFalse(result["mode_compatible"])
        self.assertTrue(result["flat_at_observation"])

    def test_code_expiry_rate_limit_and_non_ascii(self):
        with tempfile.TemporaryDirectory() as folder:
            s=app.Service(folder,"h")
            self.assertEqual(s.login("한글")[1],401)
            for _ in range(4):self.assertEqual(s.login("no")[1],401)
            self.assertEqual(s.login(s.login_code)[1],429)
            s.attempts.clear();s.login_deadline=0
            self.assertEqual(s.login(s.login_code)[1],401)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.service=app.Service(self.tmp.name,"config-hash")
        self.server=ThreadingHTTPServer(("127.0.0.1",0),app.handler(self.service))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.host="127.0.0.1:"+str(self.server.server_address[1]);self.cookie=""

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def request(self,path,body=None,extra=None):
        c=http.client.HTTPConnection("127.0.0.1",self.server.server_address[1],timeout=3)
        headers={"Host":self.host,"Origin":"http://"+self.host,"Cookie":self.cookie,"Content-Type":"application/json"}
        headers.update(extra or {})
        c.request("GET" if body is None else "POST",path,body=None if body is None else json.dumps(body),headers=headers)
        r=c.getresponse();raw=r.read();status=r.status;cookie=r.getheader("Set-Cookie");c.close()
        return status,raw,cookie

    def login(self):
        status,_,cookie=self.request("/login",dict(code=self.service.login_code))
        self.assertEqual(status,200);self.cookie=cookie.split(";")[0]

    def test_no_auth_cannot_read_or_store(self):
        self.assertEqual(self.request("/status")[0],401)
        self.assertEqual(self.request("/keys",KEYS)[0],401)
        self.assertFalse(self.service.keys_path.exists())

    def test_cross_origin_and_dns_rebinding_blocked(self):
        self.login()
        self.assertEqual(self.request("/keys",KEYS,{"Origin":"https://evil.example"})[0],403)
        self.assertEqual(self.request("/status",extra={"Host":"evil.example"})[0],403)
        self.assertFalse(self.service.keys_path.exists())

    def test_authenticated_flow_keeps_secrets_out_of_responses(self):
        self.login()
        self.assertEqual(self.request("/keys",KEYS)[0],202)
        status,raw,_=self.request("/status");self.assertEqual(status,200)
        for secret in KEYS.values():self.assertNotIn(secret.encode(),raw)
        self.assertEqual(json.loads(self.service.keys_path.read_text()),KEYS)
        self.assertFalse(json.loads(raw)["orders_enabled"])

    def test_no_start_order_or_close_routes(self):
        self.login()
        for path in ("/start","/api/control/confirm","/api/control/entry","/api/control/close_all","/trade/order"):
            self.assertEqual(self.request(path,{})[0],405)

    def test_logout_invalidates_session(self):
        self.login();self.assertEqual(self.request("/logout",{})[0],200)
        self.assertEqual(self.request("/status")[0],401)

    def test_static_pages_work_without_credentials(self):
        for path in ("/","/app.js","/style.css"):
            self.assertEqual(self.request(path)[0],200)


if __name__=="__main__":unittest.main()
