import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from server import Workbench
from yoosee import (Account, CloudTransport, Config, DEVICES_PATH, IntegrationError,
                    LOGIN_PATH, NoRedirect, YooseeClient, packed_version,
                    sdk_password_hash, login_username)
from yoosee import probe


class FakeTransport:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, host, path, params):
        self.calls.append((host, path, params.copy()))
        return next(self.responses)


def accepted():
    # Synthetic fixture derived from the SDK field declarations; not a live response.
    return {"error_code": "0", "UserID": "-2147483525", "SessionID": "101",
            "SessionID2": "102", "P2PVerifyCode1": "103", "P2PVerifyCode2": "104"}


class ProtocolTests(unittest.TestCase):
    def config(self):
        return Config("test-app-id", "test-app-token")

    def test_login_matches_sdk_and_does_not_keep_password(self):
        transport = FakeTransport(accepted())
        client = YooseeClient(self.config(), transport)
        client.login("name@example.invalid", "password")
        _, path, params = transport.calls[0]
        self.assertEqual(path, LOGIN_PATH)
        self.assertEqual(params["Pwd"], "5F4DCC3B5AA765D61D8327DEB882CF99")
        self.assertEqual(params["AppVersion"], "1")
        self.assertEqual(client.account.user_id, "0123")
        self.assertNotIn("password", repr(client.__dict__))
        self.assertNotIn("101", repr(client.account))

    def test_account_only_login_omits_app_credentials_and_sends_once(self):
        transport = FakeTransport(accepted())
        client = YooseeClient(Config(), transport)
        client.login("name@example.invalid", "password")
        self.assertEqual(len(transport.calls), 1)
        self.assertNotIn("AppID", transport.calls[0][2])
        self.assertNotIn("AppToken", transport.calls[0][2])
        self.assertEqual(transport.calls[0][2]["User"], "name@example.invalid")
        self.assertEqual(transport.calls[0][2]["Pwd"], "5F4DCC3B5AA765D61D8327DEB882CF99")
        self.assertEqual(client.account.user_id, "0123")

    def test_account_only_rejection_does_not_retry_or_create_session(self):
        transport = FakeTransport({"error_code": "10901020", "error": "raw-provider-private-data"})
        client = YooseeClient(Config(), transport)
        with self.assertRaises(IntegrationError) as error:
            client.login("name@example.invalid", "password")
        self.assertIsNone(client.account)
        self.assertEqual(len(transport.calls), 1)
        self.assertIn("10901020", str(error.exception))
        self.assertNotIn("raw-provider-private-data", str(error.exception))

    def test_configuration_allows_account_experiment_but_rejects_partial_sdk(self):
        with patch.dict(os.environ, {"YOOSEE_APP_ID": "", "YOOSEE_APP_TOKEN": ""}):
            self.assertEqual(Config.from_environment().auth_mode, "account-experimental")
        for app_id, token in (("only-id", ""), ("", "only-token")):
            with self.assertRaises(IntegrationError):
                Config(app_id, token)
        self.assertEqual(Config("test-id", "test-token").auth_mode, "sdk")

    def test_legacy_md5_non_ascii_truncation(self):
        # 'é' is 2 UTF-8 bytes but one Java character; SDK hashes just 0xc3.
        import hashlib
        self.assertEqual(sdk_password_hash("é"), hashlib.md5(b"\xc3").hexdigest().upper())

    def test_modern_login_response(self):
        transport = FakeTransport({"code": 0, "data": {"userId": "123", "sessionId": "101",
                                                         "sessionId2": "102", "vcode1": "103", "vcode2": "104"}})
        client = YooseeClient(self.config(), transport)
        client.login("0123", "test")
        self.assertEqual(transport.calls[0][2]["User"], "-2147483525")
        self.assertEqual(client.account.user_id, "0123")

    def test_failure_clears_previous_session_and_hides_provider_message(self):
        transport = FakeTransport({"error_code": "10901001", "error": "secret-response"})
        client = YooseeClient(self.config(), transport)
        client.account = Account("0123", "sensitive-session")
        with self.assertRaises(IntegrationError) as context:
            client.login("user", "pass")
        self.assertIsNone(client.account)
        self.assertNotIn("secret-response", str(context.exception))

    def test_unknown_success_schema_is_rejected(self):
        for response in ({"UserID": "123", "SessionID": "101"}, {"code": 0}, {"code": 0, "SessionID": "101", "UserID": "x"}):
            with self.subTest(response=response), self.assertRaises(IntegrationError):
                YooseeClient(self.config(), FakeTransport(response)).login("user", "pass")

    def test_device_pagination_and_secret_redaction(self):
        transport = FakeTransport(
            {"code": 0, "leftNum": 1, "data": {"deviceList": [{"devId": "10", "remarkName": "Loja", "secretKey": "never-expose"}]}},
            {"code": 0, "leftNum": 0, "data": {"deviceList": [{"devId": "20", "remarkName": "Casa", "secretKey": "never-expose"}]}},
        )
        client = YooseeClient(self.config(), transport)
        client.account = Account("0123", "session-secret")
        devices = client.devices()
        self.assertEqual([d["id"] for d in devices], ["10", "20"])
        self.assertEqual(transport.calls[1][2]["PreDeviceID"], "10")
        self.assertNotIn("secret", json.dumps(devices))
        self.assertTrue(all(d["video"] == "unavailable" for d in devices))

    def test_device_failure_does_not_look_like_empty_success(self):
        for response in ({"code": 1}, {"code": 0, "data": {}}, {"code": 0, "leftNum": 1, "data": {"deviceList": []}}):
            client = YooseeClient(self.config(), FakeTransport(response))
            client.account = Account("0123", "session")
            with self.subTest(response=response), self.assertRaises(IntegrationError):
                client.devices()

    def test_repeated_page_is_rejected(self):
        page = {"code": 0, "leftNum": 1, "data": {"deviceList": [{"devId": "10"}]}}
        client = YooseeClient(self.config(), FakeTransport(page, page))
        client.account = Account("0123", "session")
        with self.assertRaises(IntegrationError):
            client.devices()

    def test_queries_require_authentication(self):
        with self.assertRaises(IntegrationError):
            YooseeClient(self.config()).devices()

    def test_invalid_login_never_calls_network(self):
        transport = FakeTransport()
        client = YooseeClient(self.config(), transport)
        for username, password in (("", "x"), ("x", ""), (None, None), ("x", ["y"])):
            with self.assertRaises(IntegrationError):
                client.login(username, password)
        self.assertEqual(transport.calls, [])

    def test_sdk_version_and_numeric_user_id(self):
        self.assertEqual(packed_version("01.02.03.04"), "16909060")
        self.assertEqual(packed_version("255.255.255.255"), "-1")
        self.assertEqual(login_username("0123"), "-2147483525")
        self.assertEqual(login_username("mail@example.invalid"), "mail@example.invalid")
        for version in ("1.2", "256.0.0.0", "x.0.0.0", "-1.0.0.0"):
            with self.assertRaises(IntegrationError):
                packed_version(version)

    def test_arbitrary_cloud_hosts_are_rejected(self):
        with self.assertRaises(IntegrationError):
            Config("a", "b", host="attacker.invalid")
        with self.assertRaises(IntegrationError):
            CloudTransport().post("attacker.invalid", LOGIN_PATH, {})

    def test_redirects_never_forward_credentials(self):
        handler = NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "http://attacker.invalid"))

    def test_transport_errors_do_not_expose_url(self):
        transport = CloudTransport()
        transport.opener.open = lambda *a, **k: (_ for _ in ()).throw(
            urllib.error.HTTPError("https://host/?Pwd=sensitive-hash", 403, "secret", None, None))
        with self.assertRaises(IntegrationError) as error:
            transport.post(self.config().host, LOGIN_PATH, {"Pwd": "sensitive-hash"})
        self.assertNotIn("sensitive", str(error.exception))
        self.assertIn("403", str(error.exception))

    def test_probe_checks_api_without_authentication(self):
        from unittest.mock import MagicMock
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"error_code":"10901020","error":"missing params"}'
        with patch("yoosee.urllib.request.build_opener", return_value=opener):
            observations = probe()
        self.assertTrue(all(row["protocol_response"] for row in observations))
        self.assertTrue(all(not row["authentication_tested"] for row in observations))
        for call in opener.open.call_args_list:
            url = call.args[0]
            self.assertTrue(url.endswith("/Users/LoginCheck.ashx"))
            self.assertNotIn("?", url)

    def test_probe_does_not_confuse_html_with_api(self):
        from unittest.mock import MagicMock
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'<html>API landing page</html>'
        with patch("yoosee.urllib.request.build_opener", return_value=opener):
            observations = probe()
        self.assertTrue(all(row["reachable"] for row in observations))
        self.assertTrue(all(not row["protocol_response"] for row in observations))


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Workbench(("127.0.0.1", 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, body=None, headers=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers or {})
        try:
            response = urllib.request.urlopen(req, timeout=3)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read()

    def session(self):
        code, headers, raw = self.request("/api/status")
        self.assertEqual(code, 200)
        status = json.loads(raw)
        return {"Cookie": headers["Set-Cookie"].split(";")[0], "Origin": self.base,
                "Content-Type": "application/json", "X-CSRF-Token": status["csrf"]}

    def test_real_http_assets_and_health(self):
        for path, expected in (("/", b"Yoosee"), ("/app.js", b"textContent"), ("/style.css", b"color")):
            code, headers, raw = self.request(path)
            self.assertEqual(code, 200)
            self.assertIn(expected, raw)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertFalse(json.loads(self.request("/api/health")[2])["video_available"])

    def test_login_blocks_cross_origin_and_missing_csrf(self):
        headers = self.session()
        self.assertEqual(self.request("/api/login", {}, headers | {"Origin": "http://attacker.invalid"})[0], 403)
        self.assertEqual(self.request("/api/login", {}, headers | {"X-CSRF-Token": "bad"})[0], 403)

    def test_partial_sdk_configuration_is_explicit(self):
        headers = self.session()
        with patch.dict(os.environ, {"YOOSEE_APP_ID": "partial-test-id", "YOOSEE_APP_TOKEN": ""}):
            code, _, raw = self.request("/api/login", {"username": "example", "password": "not-a-real-password"}, headers)
        self.assertEqual(code, 422)
        self.assertIn("YOOSEE_APP_ID", raw.decode())
        self.assertNotIn("not-a-real-password", raw.decode())

    def test_browser_account_only_login_without_environment_keys(self):
        headers = self.session()
        transport = FakeTransport(accepted())
        with patch.dict(os.environ, {"YOOSEE_APP_ID": "", "YOOSEE_APP_TOKEN": ""}), patch(
                "server.YooseeClient", side_effect=lambda config: YooseeClient(config, transport)):
            code, _, raw = self.request("/api/login", {"username": "test@example.invalid", "password": "not-real"}, headers)
            self.assertEqual(code, 200)
            self.assertNotIn("not-real", raw.decode())
            status = json.loads(self.request("/api/status", headers={"Cookie": headers["Cookie"]})[2])
            self.assertTrue(status["authenticated"])
            self.assertEqual(status["auth_mode"], "account-experimental")
        self.assertEqual(len(transport.calls), 1)
        self.assertNotIn("AppID", transport.calls[0][2])

    def test_browser_rejected_account_only_login_keeps_account_disconnected(self):
        headers = self.session()
        transport = FakeTransport({"error_code": "10901020", "error": "not-for-the-browser"})
        with patch.dict(os.environ, {"YOOSEE_APP_ID": "", "YOOSEE_APP_TOKEN": ""}), patch(
                "server.YooseeClient", side_effect=lambda config: YooseeClient(config, transport)):
            code, _, raw = self.request("/api/login", {"username": "test@example.invalid", "password": "not-real"}, headers)
            self.assertEqual(code, 422)
            self.assertIn("10901020", raw.decode())
            self.assertNotIn("not-for-the-browser", raw.decode())
            self.assertNotIn("not-real", raw.decode())
            status = json.loads(self.request("/api/status", headers={"Cookie": headers["Cookie"]})[2])
            self.assertFalse(status["authenticated"])
            self.assertEqual(self.request("/api/devices", {}, headers)[0], 422)
        self.assertEqual(len(transport.calls), 1)

    def test_browser_can_probe_without_sdk_or_account_credentials(self):
        headers = self.session()
        observations = [{"host": "api3.cloud-links.net", "reachable": True,
                         "protocol_response": True, "authentication_tested": False}]
        with patch("server.probe", return_value=observations) as mock_probe, patch(
                "server.Config.from_environment", side_effect=AssertionError("Probe must not require credentials")):
            code, _, raw = self.request("/api/connectivity", {}, headers)
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(raw)["observations"], observations)
            self.assertEqual(self.request("/api/connectivity", {}, headers)[0], 429)
            mock_probe.assert_called_once_with()

    def test_browser_probe_rejects_submitted_credentials_and_missing_csrf(self):
        headers = self.session()
        with patch("server.probe") as mock_probe:
            self.assertEqual(self.request("/api/connectivity", {"password": "secret"}, headers)[0], 400)
            self.assertEqual(self.request("/api/connectivity", {}, headers | {"X-CSRF-Token": "bad"})[0], 403)
            mock_probe.assert_not_called()

    def test_browser_login_list_logout_with_synthetic_provider(self):
        headers = self.session()
        with patch("server.Config.from_environment", return_value=Config("a", "b")), patch("server.YooseeClient") as factory:
            factory.return_value.devices.return_value = [{"id": "10", "name": "Loja", "video": "unavailable"}]
            self.assertEqual(self.request("/api/login", {"username": "test", "password": "secret"}, headers)[0], 200)
            factory.return_value.login.assert_called_once_with("test", "secret")
            code, _, raw = self.request("/api/devices", {}, headers)
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(raw)["devices"][0]["id"], "10")
            self.assertNotIn("secret", raw.decode())
            # Another browser session cannot access the first browser's cloud client.
            self.assertEqual(self.request("/api/devices", {}, self.session())[0], 422)
            self.assertEqual(self.request("/api/logout", {}, headers)[0], 200)
            self.assertEqual(self.request("/api/devices", {}, headers)[0], 403)

    def test_unknown_path_and_dns_rebinding_host_rejected(self):
        self.assertEqual(self.request("/.env")[0], 404)
        self.assertEqual(self.request("/api/status", headers={"Host": "attacker.invalid"})[0], 403)


if __name__ == "__main__":
    unittest.main()
