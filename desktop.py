"""Experimental HTTP protocol recovered from the user-provided Windows client.

The HTTP module does not execute Windows code. Client parameters are imported locally; account
credentials and access tokens never go into the profile or browser responses.
"""
from dataclasses import dataclass
from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from yoosee import IntegrationError, NoRedirect, MAX_RESPONSE, assert_success

DESKTOP_HOST = "openapi-iot.cloudlinks.cn"
DESKTOP_LOGIN = "/openapi/app/user/login/account"
DESKTOP_DEVICES = "/openapi/app/user/device/listDevice"
INSTALLER_SHA256 = "0f0a6901fe4aefdc1d77dc0d3e1182df61711165f677811f394f280ee42e6d21"
EXECUTABLE_SHA256 = "8720a7c99022cf51fb53b80e91ae151e4e45c8992cbe83b839c57a782c0b323a"


def profile_path():
    return Path(os.getenv("YOOSEE_DESKTOP_PROFILE") or Path(__file__).parent / ".local" / "yoosee-desktop.json")


@dataclass(frozen=True, repr=False)
class DesktopProfile:
    app_id: str
    app_token: str

    def __post_init__(self):
        if not re.fullmatch(r"[0-9a-fA-F]{32}", self.app_id) or not re.fullmatch(r"[0-9a-fA-F]{64}", self.app_token):
            raise IntegrationError("configuration", "Perfil Windows inválido; importe novamente o instalador compatível.")

    @property
    def auth_mode(self):
        return "windows-experimental"

    def params(self):
        # Verified in WebApiModel's constructor and UserMobileLogin.
        return {"language": "ZH", "pkgName": "Yoosee.PC", "terminalOS": 1,
                "appVersion": "10", "apiVersion": "10", "appName": "Yoosee.PC",
                "appId": self.app_id, "appToken": self.app_token}


def load_profile(path=None):
    try:
        p = Path(path) if path is not None else profile_path()
        if p.stat().st_size > 8192:
            raise ValueError
        data = json.loads(p.read_text())
        if not isinstance(data, dict) or data.get("schema") != 1 or data.get("source_sha256") != EXECUTABLE_SHA256:
            raise ValueError
        return DesktopProfile(data["app_id"], data["app_token"])
    except (OSError, ValueError, KeyError, TypeError):
        raise IntegrationError("configuration", "Não foi possível ler o perfil Windows. Execute configure_desktop.py com o instalador 1.0.0.8.") from None


def windows_password_hash(password):
    # Qt fromAscii_helper uses UTF-8; toLatin1 substitutes unrepresentable chars
    # with '?' per UTF-16 code unit. Preserve this historical Windows behavior.
    converted = bytearray()
    for char in password:
        code = ord(char)
        converted.extend(bytes([code]) if code <= 255 else b"??" if code > 65535 else b"?")
    return hashlib.md5(converted, usedforsecurity=False).hexdigest()


def device_identity():
    node = uuid.getnode()
    return ":".join(f"{(node >> shift) & 255:02X}" for shift in range(40, -1, -8))


def build_login(profile, username, password, country_code="55", unique_id=None):
    if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
        raise IntegrationError("input", "Informe seu e-mail ou telefone e a senha da conta Yoosee.")
    if len(username) > 320 or len(password) > 1024:
        raise IntegrationError("input", "Login ou senha excede o tamanho permitido.")
    username = username.strip()
    data = profile.params() | {"action": "account", "uniqueId": unique_id or device_identity(),
                               "pwd": windows_password_hash(password)}
    if "@" in username:
        data.update(loginMode="email", email=username)
    else:
        if not username.isascii() or not username.isdigit():
            raise IntegrationError("input", "Para telefone, informe apenas os números com DDD; selecione o código do país separadamente.")
        if not isinstance(country_code, str) or not re.fullmatch(r"[1-9][0-9]{0,3}", country_code):
            raise IntegrationError("input", "Código de país inválido; para Brasil use 55.")
        data.update(loginMode="mobile", mobile=username, mobileArea=country_code)
    return data


class DesktopTransport:
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, *, body=None, params=None, headers=None):
        if path not in (DESKTOP_LOGIN, DESKTOP_DEVICES):
            raise IntegrationError("configuration", "Destino não permitido para o protocolo Windows.")
        if (path == DESKTOP_LOGIN and (body is None or params is not None)) or (path == DESKTOP_DEVICES and (params is None or body is not None)):
            raise IntegrationError("configuration", "Método incompatível com o protocolo Windows.")
        url = "https://" + DESKTOP_HOST + path
        request_headers = {"Accept": "application/json", "User-Agent": "MaisProdutive-Research/0.2"}
        request_headers.update(headers or {})
        if params is not None:
            url += "?" + urllib.parse.urlencode(params)
            raw = None
            request_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
        else:
            raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(url, data=raw, headers=request_headers, method="POST" if body is not None else "GET")
        try:
            with self.opener.open(request, timeout=20) as response:
                result = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            raise IntegrationError("http", f"API Windows respondeu HTTP {exc.code}. Detalhes de credenciais omitidos.") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise IntegrationError("network", "Não foi possível conectar à API Windows da Yoosee com TLS válido.") from None
        if len(result) > MAX_RESPONSE:
            raise IntegrationError("protocol", "Resposta excedeu o limite esperado.")
        try:
            payload = json.loads(result.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            raise IntegrationError("protocol", "API Windows não retornou JSON compatível.") from None
        assert_success(payload)
        return payload


@dataclass(repr=False)
class DesktopAccount:
    access_id: str
    access_token: str


def signed_device_query(profile, account, cursor, *, nonce=None, timestamp=None):
    token = account.access_token
    if len(token) < 128 or not re.fullmatch(r"[0-9a-fA-F]{32}", token[-32:]):
        raise IntegrationError("protocol", "Token retornado não é compatível com a assinatura do cliente Windows analisado.")
    params = {k: str(v) for k, v in profile.params().items()} | {
        "lastDeviceId": str(cursor), "accessToken": token[:96],
    }
    signing = params | {"x-iotvideo-accessid": account.access_id,
                        "x-iotvideo-nonce": str(nonce if nonce is not None else secrets.randbelow(1000)),
                        "x-iotvideo-timestamp": str(timestamp if timestamp is not None else int(time.time())),
                        "host": DESKTOP_HOST}
    canonical = "\n".join(key + ":" + signing[key] for key in sorted(signing))
    signature = base64.b64encode(hmac.new(bytes.fromhex(token[-32:]), canonical.encode("utf-8"), hashlib.sha1).digest()).decode()
    headers = {"X-IotVideo-AccessID": account.access_id,
               "X-IotVideo-Nonce": signing["x-iotvideo-nonce"],
               "X-IotVideo-Timestamp": signing["x-iotvideo-timestamp"],
               "X-IotVideo-Signature": signature}
    return params, headers


class DesktopClient:
    def __init__(self, config, transport=None):
        self.config = config
        self.transport = transport or DesktopTransport()
        self.account = None
        self.device_ids = set()

    def login(self, username, password, country_code="55"):
        self.account = None
        self.device_ids.clear()
        response = self.transport.request(DESKTOP_LOGIN, body=build_login(self.config, username, password, country_code))
        assert_success(response)
        data = response.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("accessId"), (str, int)) or not str(data["accessId"]) or not isinstance(data.get("accessToken"), str) or len(data["accessToken"]) < 32:
            raise IntegrationError("protocol", "Login retornou sucesso sem os dados de acesso esperados pelo cliente Windows.")
        self.account = DesktopAccount(str(data["accessId"]), data["accessToken"])

    def devices(self):
        self.device_ids.clear()
        if self.account is None:
            raise IntegrationError("authentication", "Entre na conta antes de consultar as câmeras.")
        devices, seen, cursor = [], set(), "0"
        for _ in range(100):
            params, headers = signed_device_query(self.config, self.account, cursor)
            response = self.transport.request(DESKTOP_DEVICES, params=params, headers=headers)
            assert_success(response)
            data = response.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("deviceList"), list):
                raise IntegrationError("protocol", "Resposta de câmeras incompatível com a API Windows.")
            rows = data["deviceList"]
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("devId"), (str, int)) or not str(row["devId"]):
                    raise IntegrationError("protocol", "Câmera sem identificador válido.")
                device_id = str(row["devId"])
                if device_id in seen:
                    raise IntegrationError("protocol", "Paginação de câmeras repetida; consulta interrompida.")
                seen.add(device_id)
                devices.append({"id": device_id, "name": str(row.get("remarkName") or "Câmera"),
                                "video": "unavailable", "reason": "Vídeo P2P ainda não implementado."})
            # This client reads leftNum INSIDE data, unlike the legacy SDK.
            remaining = data.get("leftNum")
            if not isinstance(remaining, int) or isinstance(remaining, bool) or remaining < 0:
                raise IntegrationError("protocol", "Paginação da API Windows incompatível.")
            if remaining == 0:
                self.device_ids = seen
                return devices
            if not rows:
                raise IntegrationError("protocol", "Paginação de câmeras sem progresso.")
            cursor = str(rows[-1]["devId"])
        raise IntegrationError("protocol", "Consulta excedeu o limite de páginas.")

    def snapshot(self, device_id):
        self.require_device(device_id)
        from video import capture
        return capture(self.account, device_id)

    def require_device(self, device_id):
        if self.account is None:
            raise IntegrationError("authentication", "Entre na conta primeiro.")
        if not isinstance(device_id, str) or device_id not in self.device_ids:
            raise IntegrationError("input", "Consulte as câmeras da sua conta e selecione uma delas.")
