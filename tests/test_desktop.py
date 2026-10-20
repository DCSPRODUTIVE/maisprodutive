import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from configure_desktop import extract_profile, load_binary, read_pe_string, save_profile
from desktop import (DESKTOP_DEVICES, DESKTOP_HOST, DESKTOP_LOGIN, EXECUTABLE_SHA256,
                     DesktopAccount, DesktopClient, DesktopProfile, DesktopTransport,
                     build_login, load_profile, signed_device_query, windows_password_hash)
from server import Workbench
from yoosee import IntegrationError, probe


# Synthetic client identity and session. Never copy the extracted client values.
PROFILE = DesktopProfile("a" * 32, "b" * 64)
TOKEN = "1" * 96 + "00112233445566778899aabbccddeeff"


class FakeDesktopTransport:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return next(self.responses)


class DesktopProtocolTests(unittest.TestCase):
    def test_email_login_matches_observed_fields_and_lowercase_hash(self):
        body = build_login(PROFILE, "user@example.invalid", "password", unique_id="AA:BB:CC:DD:EE:FF")
        self.assertEqual(body["loginMode"], "email")
        self.assertEqual(body["email"], "user@example.invalid")
        self.assertNotIn("mobileArea", body)
        self.assertEqual(body["pwd"], "5f4dcc3b5aa765d61d8327deb882cf99")
        self.assertEqual(body["action"], "account")
        self.assertEqual(body["pkgName"], "Yoosee.PC")
        self.assertEqual(body["appName"], "Yoosee.PC")
        self.assertEqual(body["appVersion"], "10")
        self.assertEqual(body["apiVersion"], "10")
        self.assertEqual(body["terminalOS"], 1)
        self.assertEqual(body["language"], "ZH")
        self.assertNotIn("password", body.values())

    def test_mobile_login_has_separate_country_code(self):
        body = build_login(PROFILE, "11999999999", "password", "55", unique_id="test-device")
        self.assertEqual({k: body[k] for k in ("mobile", "mobileArea", "loginMode")},
                         {"mobile": "11999999999", "mobileArea": "55", "loginMode": "mobile"})
        self.assertNotIn("email", body)
        for phone, country in (("+5511999999999", "55"), ("11999999999", "+55"), ("123", [])):
            with self.assertRaises(IntegrationError):
                build_login(PROFILE, phone, "password", country)

    def test_hash_reproduces_windows_latin1_not_android_truncation(self):
        self.assertEqual(windows_password_hash("é"), hashlib.md5(b"\xe9").hexdigest())
        self.assertEqual(windows_password_hash("a😊b"), hashlib.md5(b"a??b").hexdigest())

    def test_invalid_input_causes_no_network_request(self):
        transport = FakeDesktopTransport()
        client = DesktopClient(PROFILE, transport)
        for user, password in ((None, "x"), ("x", None), ("", "x"), ("x", ""), ("x" * 321, "x")):
            with self.assertRaises(IntegrationError):
                client.login(user, password)
        self.assertEqual(transport.calls, [])

    def test_login_requires_explicit_success_and_access_session(self):
        for response in ({"code": 0}, {"data": {"accessId": "123", "accessToken": TOKEN}},
                         {"code": 0, "data": {"accessId": "123"}},
                         {"code": 42, "msg": "private-provider-message"}):
            transport = FakeDesktopTransport(response)
            client = DesktopClient(PROFILE, transport)
            client.account = DesktopAccount("previous", TOKEN)
            with self.assertRaises(IntegrationError) as error:
                client.login("user@example.invalid", "password")
            self.assertIsNone(client.account)
            self.assertEqual(len(transport.calls), 1)
            self.assertNotIn("private-provider-message", str(error.exception))

    def test_accepted_login_keeps_tokens_in_backend(self):
        transport = FakeDesktopTransport({"code": 0, "data": {"accessId": "123", "accessToken": TOKEN}})
        client = DesktopClient(PROFILE, transport)
        client.login("user@example.invalid", "password")
        self.assertEqual(client.account.access_id, "123")
        self.assertEqual(transport.calls[0][0], DESKTOP_LOGIN)
        self.assertNotIn("password", repr(client.__dict__))
        self.assertNotIn(TOKEN, repr(client.account))
        self.assertNotIn(PROFILE.app_token, repr(PROFILE))

    def test_device_signature_uses_decoded_tail_and_all_query_parameters(self):
        params, headers = signed_device_query(PROFILE, DesktopAccount("123", TOKEN), "99", nonce=7, timestamp=1000)
        self.assertEqual(params["accessToken"], TOKEN[:96])
        self.assertEqual(params["lastDeviceId"], "99")
        # An independently assembled canonical message from observed field names.
        expected = "\n".join([
            "accessToken:" + TOKEN[:96], "apiVersion:10", "appId:" + "a" * 32,
            "appName:Yoosee.PC", "appToken:" + "b" * 64, "appVersion:10",
            "host:openapi-iot.cloudlinks.cn", "language:ZH", "lastDeviceId:99",
            "pkgName:Yoosee.PC", "terminalOS:1", "x-iotvideo-accessid:123",
            "x-iotvideo-nonce:7", "x-iotvideo-timestamp:1000",
        ])
        signature = base64.b64encode(hmac.new(bytes.fromhex(TOKEN[-32:]), expected.encode(), hashlib.sha1).digest()).decode()
        self.assertEqual(headers["X-IotVideo-Signature"], signature)
        self.assertNotIn(TOKEN, json.dumps(params))
        self.assertNotIn(TOKEN[-32:], json.dumps(params))

    def test_unknown_token_cannot_expose_signing_key_as_query(self):
        for token in ("a" * 32, "x" * 128):
            with self.assertRaises(IntegrationError):
                signed_device_query(PROFILE, DesktopAccount("123", token), "0")

    def test_devices_use_signed_get_and_nested_pagination_without_secret_leaks(self):
        transport = FakeDesktopTransport(
            {"code": 0, "data": {"leftNum": 1, "deviceList": [{"devId": "1", "remarkName": "Loja", "secretKey": "camera-secret"}]}},
            {"code": 0, "data": {"leftNum": 0, "deviceList": [{"devId": "2", "remarkName": "Casa"}]}},
        )
        client = DesktopClient(PROFILE, transport)
        client.account = DesktopAccount("123", TOKEN)
        result = client.devices()
        self.assertEqual([d["id"] for d in result], ["1", "2"])
        self.assertEqual(transport.calls[1][1]["params"]["lastDeviceId"], "1")
        self.assertEqual(transport.calls[0][0], DESKTOP_DEVICES)
        self.assertIn("X-IotVideo-Signature", transport.calls[0][1]["headers"])
        self.assertNotIn("camera-secret", json.dumps(result))
        self.assertTrue(all(d["video"] == "unavailable" for d in result))

    def test_devices_reject_unknown_pagination_or_repeated_pages(self):
        responses = [
            [{"code": 0, "data": {"deviceList": []}}],
            [{"code": 0, "data": {"leftNum": 1, "deviceList": []}}],
            [{"code": 0, "data": {"leftNum": 1, "deviceList": [{"devId": "1"}]}}] * 2,
        ]
        for sequence in responses:
            client = DesktopClient(PROFILE, FakeDesktopTransport(*sequence))
            client.account = DesktopAccount("123", TOKEN)
            with self.assertRaises(IntegrationError):
                client.devices()

    def test_http_uses_json_body_for_login_and_does_not_disable_tls(self):
        transport = DesktopTransport()
        response = MagicMock()
        response.read.return_value = b'{"code":0}'
        transport.opener.open = MagicMock()
        transport.opener.open.return_value.__enter__.return_value = response
        body = build_login(PROFILE, "user@example.invalid", "password", unique_id="test-device")
        transport.request(DESKTOP_LOGIN, body=body)
        request = transport.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://" + DESKTOP_HOST + DESKTOP_LOGIN)
        self.assertNotIn("?", request.full_url)
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), body)
        self.assertEqual(request.get_header("Content-type"), "application/json; charset=utf-8")
        self.assertEqual(transport.opener.open.call_count, 1)

    def test_http_errors_never_expose_sensitive_urls(self):
        transport = DesktopTransport()
        transport.opener.open = MagicMock(side_effect=urllib.error.HTTPError(
            "https://host/?accessToken=secret-token", 403, "secret-message", None, None))
        with self.assertRaises(IntegrationError) as error:
            transport.request(DESKTOP_DEVICES, params={"accessToken": "secret-token"})
        self.assertNotIn("secret", str(error.exception))
        self.assertIn("403", str(error.exception))
        self.assertEqual(transport.opener.open.call_count, 1)


class ProfileTests(unittest.TestCase):
    def test_profile_is_private_repeatable_and_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "profile.json"
            self.assertTrue(save_profile(PROFILE, target))
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(load_profile(target).app_id, PROFILE.app_id)
            self.assertFalse(save_profile(PROFILE, target))
            self.assertRaises(IntegrationError, save_profile, DesktopProfile("c" * 32, "d" * 64), target)
            self.assertEqual(load_profile(target).app_id, PROFILE.app_id)

    def test_unknown_or_truncated_pe_is_never_imported(self):
        for binary in (b"", b"MZ" + b"\0" * 80, b"not-an-executable"):
            with self.assertRaises(IntegrationError):
                extract_profile(binary)
            with self.assertRaises(IntegrationError):
                read_pe_string(binary, 0x5BB5A8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unrelated.exe"
            path.write_bytes(b"MZ-unrelated")
            with patch("configure_desktop.subprocess.run") as run, self.assertRaises(IntegrationError):
                load_binary(path)
            run.assert_not_called()

    def test_profile_does_not_accept_other_sources_or_credentials_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"schema": 1, "source_sha256": "unknown", "app_id": "a" * 32, "app_token": "b" * 64}))
            with self.assertRaises(IntegrationError):
                load_profile(path)
        with self.assertRaises(IntegrationError):
            DesktopProfile("bad", "bad")


class DesktopBrowserTests(unittest.TestCase):
    def test_probe_targets_windows_endpoint_without_credentials(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b'{"code":10901020}'
        with patch("yoosee.urllib.request.build_opener", return_value=opener):
            observations = probe(desktop=True)
        opener.open.assert_called_once_with("https://" + DESKTOP_HOST + DESKTOP_LOGIN, timeout=8)
        self.assertEqual(len(observations), 1)
        self.assertTrue(observations[0]["protocol_response"])
        self.assertFalse(observations[0]["authentication_tested"])

    def test_imported_profile_selects_windows_only_and_hides_session_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "profile.json"
            save_profile(PROFILE, target)
            transport = FakeDesktopTransport({"code": 0, "data": {"accessId": "123", "accessToken": TOKEN}},
                                             {"code": 0, "data": {"deviceList": [{"devId": "owned", "remarkName": "Camera"}], "leftNum": 0}})
            with patch.dict(os.environ, {"YOOSEE_DESKTOP_PROFILE": str(target)}):
                server = Workbench(("127.0.0.1", 0))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_port}"
                try:
                    with urllib.request.urlopen(base + "/api/status", timeout=3) as r:
                        status = json.load(r)
                        cookie = r.headers["Set-Cookie"].split(";")[0]
                    self.assertEqual(status["auth_mode"], "windows-experimental")
                    headers = {"Cookie": cookie, "Origin": base, "X-CSRF-Token": status["csrf"], "Content-Type": "application/json"}
                    with patch("server.probe", return_value=[]) as network_probe:
                        request = urllib.request.Request(base + "/api/connectivity", data=b"{}", headers=headers)
                        with urllib.request.urlopen(request, timeout=3) as r:
                            self.assertEqual(r.status, 200)
                        network_probe.assert_called_once_with(desktop=True)
                    request = urllib.request.Request(base + "/api/login", data=json.dumps(
                        {"username": "11999999999", "password": "test-only", "country_code": "55"}).encode(), headers=headers)
                    with patch("server.DesktopClient", side_effect=lambda config: DesktopClient(config, transport)), patch("server.YooseeClient") as legacy:
                        with urllib.request.urlopen(request, timeout=3) as r:
                            raw = r.read()
                            self.assertEqual(r.status, 200)
                        legacy.assert_not_called()
                    self.assertEqual(len(transport.calls), 1)
                    self.assertEqual(transport.calls[0][1]["body"]["mobileArea"], "55")
                    with patch("video.capture", return_value={"image": "data:image/jpeg;base64,test", "message": "Captura pontual"}) as capture:
                        request = urllib.request.Request(base + "/api/video/snapshot", data=b'{"device_id":"owned"}', headers=headers)
                        with self.assertRaises(urllib.error.HTTPError) as rejected:
                            urllib.request.urlopen(request, timeout=3)
                        self.assertEqual(rejected.exception.code, 422)
                        capture.assert_not_called()
                        with urllib.request.urlopen(urllib.request.Request(base + "/api/devices", data=b'{}', headers=headers), timeout=3) as r:
                            self.assertEqual(r.status, 200)
                        with urllib.request.urlopen(request, timeout=3) as r:
                            raw += r.read()
                        capture.assert_called_once()
                        for _ in range(8):
                            server.video_guard.acquire()
                        try:
                            with self.assertRaises(urllib.error.HTTPError) as busy:
                                urllib.request.urlopen(request, timeout=3)
                            self.assertEqual(busy.exception.code, 422)
                            self.assertEqual(capture.call_count, 1)
                        finally:
                            for _ in range(8):
                                server.video_guard.release()
                    with urllib.request.urlopen(urllib.request.Request(base + "/api/status", headers={"Cookie": cookie}), timeout=3) as r:
                        raw += r.read()
                    self.assertNotIn(TOKEN.encode(), raw)
                    self.assertNotIn(PROFILE.app_token.encode(), raw)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()

    def test_invalid_desktop_profile_does_not_fall_back_to_legacy(self):
        from server import current_config
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text("not-json")
            with patch.dict(os.environ, {"YOOSEE_DESKTOP_PROFILE": str(path)}), patch("server.Config.from_environment") as legacy:
                with self.assertRaises(IntegrationError):
                    current_config()
                legacy.assert_not_called()
