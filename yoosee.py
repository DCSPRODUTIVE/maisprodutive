"""Experimental, read-only Yoosee cloud client based on the published Gwell SDK.

This implements the HTTP account layer, NOT the native P2P video transport.
No account credentials, device secrets, or cloud responses are written to disk.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request


HOSTS = (
    "api3.cloud-links.net", "api4.cloud-links.net",
    "api1.cloudlinks.cn", "api2.cloudlinks.cn",
)
LOGIN_PATH = "Users/LoginCheck.ashx"
DEVICES_PATH = "Relationship/LoadDeviceInfo.ashx"
MAX_RESPONSE = 2 * 1024 * 1024


class IntegrationError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True, repr=False)
class Config:
    app_id: str = ""
    app_token: str = ""
    package: str = "com.yoosee"
    version: str = "00.00.00.01"
    host: str = HOSTS[0]

    @classmethod
    def from_environment(cls):
        return cls(os.getenv("YOOSEE_APP_ID", ""), os.getenv("YOOSEE_APP_TOKEN", ""),
                   os.getenv("YOOSEE_PACKAGE", "com.yoosee"),
                   os.getenv("YOOSEE_APP_VERSION", "00.00.00.01"),
                   os.getenv("YOOSEE_API_HOST", HOSTS[0]))

    def __post_init__(self):
        if self.host not in HOSTS:
            raise IntegrationError("configuration", "Servidor fora da lista documentada pelo SDK.")
        if bool(self.app_id) != bool(self.app_token):
            raise IntegrationError("configuration", "Configuração SDK incompleta: YOOSEE_APP_ID e YOOSEE_APP_TOKEN devem ser configurados juntos, ou ambos removidos para o teste experimental da conta.")
        packed_version(self.version)

    @property
    def auth_mode(self) -> str:
        return "sdk" if self.app_id else "account-experimental"


def packed_version(version: str) -> str:
    parts = version.split(".")
    if len(parts) != 4 or any(not p.isascii() or not p.isdecimal() or int(p) > 255 for p in parts):
        raise IntegrationError("configuration", "A versão SDK deve ter quatro números entre 0 e 255.")
    n = 0
    for part in parts:
        n = (n << 8) | int(part)
    return str(n if n < 2**31 else n - 2**32)


def sdk_user_id(value: str) -> str:
    try:
        n = int(value)
        if not -(2**31) <= n < 2**31:
            raise ValueError
        return "0" + str(n & 0x7FFFFFFF)
    except (ValueError, TypeError):
        raise IntegrationError("protocol", "Identificador de conta incompatível com o SDK analisado.") from None


def login_username(value: str) -> str:
    # The SDK maps numeric account IDs beginning with zero to signed int32.
    if value.startswith("0") and value.isascii() and value.isdecimal():
        n = int(value)
        if n >= 2**31:
            raise IntegrationError("input", "Identificador numérico fora do formato esperado.")
        return str(n - 2**31)
    return value


def sdk_password_hash(password: str) -> str:
    # Historical MD5.getMD5ofStr calls getBytes() but passes String.length().
    # Reproduce the UTF-16 length / UTF-8 truncation, including non-ASCII input.
    java_length = len(password.encode("utf-16-le")) // 2
    raw = password.encode("utf-8")[:java_length]
    return hashlib.md5(raw, usedforsecurity=False).hexdigest().upper()


def assert_success(payload: dict):
    code = payload.get("error_code")
    if code in (None, ""):
        code = payload.get("code")
    # Never assume a response without an explicit success code was accepted.
    if str(code) != "0":
        safe_code = str(code) if re.fullmatch(r"[0-9A-Fa-f]{1,12}", str(code)) else "desconhecido"
        explanation = " O serviço informou parâmetros obrigatórios ausentes; isso não confirma erro na sua senha." if safe_code == "10901020" else ""
        raise IntegrationError("provider", "Yoosee não aceitou a operação (código " + safe_code + ")." + explanation)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Login hashes and sessions are query fields in this legacy SDK.
        # Never forward them to another destination or downgrade to HTTP.
        return None


class CloudTransport:
    def __init__(self):
        # Default TLS certificate and hostname verification remain enabled.
        self.opener = urllib.request.build_opener(NoRedirect())

    def post(self, host: str, path: str, params: dict) -> dict:
        if host not in HOSTS or path not in (LOGIN_PATH, DEVICES_PATH):
            raise IntegrationError("configuration", "Destino não permitido.")
        url = "https://" + host + "/" + path + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, data=b"", method="POST",
                                         headers={"Accept": "application/json", "User-Agent": "MaisProdutive-Research/0.1"})
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            # The original exception contains the full URL, so don't expose it.
            raise IntegrationError("http", f"Servidor retornou HTTP {exc.code}; detalhes sensíveis omitidos.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise IntegrationError("network", "Não foi possível conectar ao serviço Yoosee com TLS válido. Verifique a rede e os destinos permitidos.") from None
        if len(raw) > MAX_RESPONSE:
            raise IntegrationError("protocol", "Resposta excedeu o limite esperado.")
        try:
            result = json.loads(raw.decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            raise IntegrationError("protocol", "O serviço não retornou JSON compatível com o SDK.") from None
        if not isinstance(result, dict):
            raise IntegrationError("protocol", "Formato de resposta incompatível.")
        assert_success(result)
        return result


@dataclass(repr=False)
class Account:
    user_id: str
    session_id: str
    session_id2: str = ""
    verify_code1: str = ""
    verify_code2: str = ""


class YooseeClient:
    def __init__(self, config: Config, transport=None):
        self.config = config
        self.transport = transport or CloudTransport()
        self.account: Account | None = None
        self.anonymous_id = secrets.token_hex(16)

    def public_params(self) -> dict:
        params = {"Language": "pt-BR", "AppOS": "3", "AppName": self.config.package,
                  "AppVersion": packed_version(self.config.version), "PackageName": self.config.package,
                  "ApiVersion": "1"}
        if self.config.auth_mode == "sdk":
            params.update(AppID=self.config.app_id, AppToken=self.config.app_token)
        # Explicit experiment: omit unknown app credentials entirely. Do not invent,
        # extract or cycle tokens. The provider may reject this normal login request.
        return params

    def login(self, username: str, password: str):
        self.account = None
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
            raise IntegrationError("input", "Informe o login e a senha da sua conta Yoosee.")
        if len(username) > 320 or len(password) > 1024:
            raise IntegrationError("input", "Login ou senha excede o tamanho permitido.")
        # Uppercase MD5 is required by this historical SDK. HTTPS is mandatory.
        params = self.public_params() | {
            "User": login_username(username.strip()),
            "Pwd": sdk_password_hash(password),
            "VersionFlag": "1", "SessionID2": "1", "AnonymousId": self.anonymous_id,
        }
        result = self.transport.post(self.config.host, LOGIN_PATH, params)
        assert_success(result)
        modern = isinstance(result.get("data"), dict)
        data = result["data"] if modern else result
        user_id = data.get("userId" if modern else "UserID")
        session = data.get("sessionId" if modern else "SessionID")
        if user_id is None or not isinstance(session, (str, int)) or not str(session):
            raise IntegrationError("protocol", "Login sem os dados de sessão exigidos pelo SDK.")
        self.account = Account(sdk_user_id(str(user_id)), str(session),
                               str(data.get("sessionId2" if modern else "SessionID2", "")),
                               str(data.get("vcode1" if modern else "P2PVerifyCode1", "")),
                               str(data.get("vcode2" if modern else "P2PVerifyCode2", "")))

    def devices(self) -> list[dict]:
        if self.account is None:
            raise IntegrationError("authentication", "Entre na conta antes de consultar as câmeras.")
        devices, seen = [], set()
        cursor = "0"
        # Bounded pagination: never silently truncate or loop on a repeated page.
        for _ in range(100):
            params = self.public_params() | {
                "UserID": self.account.user_id, "SessionID": self.account.session_id,
                "PreDeviceID": cursor, "RequestCount": 20, "MyUpgradeFlag": 0,
                "UpgCheckList": "", "NotReturnDeleted": 1,
            }
            result = self.transport.post(self.config.host, DEVICES_PATH, params)
            assert_success(result)
            data = result.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("deviceList"), list):
                raise IntegrationError("protocol", "Lista de câmeras incompatível com o SDK analisado.")
            rows = data["deviceList"]
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("devId"), (str, int)) or not str(row["devId"]):
                    raise IntegrationError("protocol", "Câmera sem identificador válido.")
                device_id = str(row["devId"])
                if device_id in seen:
                    raise IntegrationError("protocol", "Paginação repetida; consulta interrompida.")
                seen.add(device_id)
                # Allowlist only: secretKey, tokens and passwords never leave backend.
                devices.append({"id": device_id, "name": str(row.get("remarkName") or "Câmera"),
                                "video": "unavailable", "reason": "Transporte P2P ainda não implementado."})
            left = result.get("leftNum")
            if left is not None:
                try:
                    remaining = int(left)
                except (TypeError, ValueError):
                    raise IntegrationError("protocol", "Paginação incompatível.") from None
                if remaining < 0:
                    raise IntegrationError("protocol", "Paginação incompatível.")
                if remaining == 0:
                    return devices
                if not rows:
                    raise IntegrationError("protocol", "Paginação sem progresso.")
            elif len(rows) < 20:
                return devices
            if not rows:
                return devices
            cursor = str(rows[-1]["devId"])
        raise IntegrationError("protocol", "Consulta excedeu o limite de páginas.")


def probe(*, desktop=False) -> list[dict]:
    """Read-only service reachability; no credentials or login attempts."""
    opener = urllib.request.build_opener(NoRedirect())
    results = []
    if desktop:
        from desktop import DESKTOP_HOST, DESKTOP_LOGIN
        destinations = [(DESKTOP_HOST, DESKTOP_LOGIN.lstrip("/"))]
    else:
        destinations = [(host, LOGIN_PATH) for host in HOSTS]
    for host, path in destinations:
        observation = {"host": host, "authentication_tested": False,
                       "protocol_response": False}
        try:
            # An HTML landing page does not establish that the API exists.
            # GET without any parameters is a credential-free endpoint check.
            with opener.open("https://" + host + "/" + path, timeout=8) as response:
                observation.update(http=response.status, reachable=True)
                raw = response.read(8193)
                try:
                    payload = json.loads(raw.decode("utf-8-sig")) if len(raw) <= 8192 else None
                except (ValueError, UnicodeError):
                    payload = None
                if isinstance(payload, dict):
                    code = str(payload.get("code" if desktop else "error_code", ""))
                    if re.fullmatch(r"[0-9A-Fa-f]{1,12}", code):
                        observation.update(protocol_response=True, provider_code=code)
        except urllib.error.HTTPError as exc:
            observation.update(http=exc.code, reachable=True)
        except (urllib.error.URLError, OSError, TimeoutError):
            observation.update(reachable=False, reason="proxy, rede ou TLS")
        results.append(observation)
    return results


def main():
    parser = argparse.ArgumentParser(description="Diagnóstico experimental Yoosee, sem VPN")
    parser.add_argument("command", choices=("probe", "devices"))
    args = parser.parse_args()
    try:
        if args.command == "probe":
            results = probe()
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 0 if any(r["reachable"] for r in results) else 1
        client = YooseeClient(Config.from_environment())
        client.login(os.getenv("YOOSEE_USERNAME", ""), os.getenv("YOOSEE_PASSWORD", ""))
        print(json.dumps(client.devices(), ensure_ascii=False, indent=2))
        return 0
    except IntegrationError as exc:
        print(json.dumps({"error": exc.kind, "message": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
