"""Local browser workbench. Remote hosting and P2P video are not implemented."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import argparse
import json
from pathlib import Path
import secrets
import threading
import time

from yoosee import Config, IntegrationError, YooseeClient, probe

ROOT = Path(__file__).parent
SESSION_TTL = 20 * 60


class Workbench(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        if address[0] not in ("127.0.0.1", "localhost"):
            raise ValueError("Use loopback; hospedagem pública exige autenticação e HTTPS adicionais.")
        super().__init__(address, Handler)
        self.sessions = {}
        self.guard = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Don't log submitted data, sessions or provider URLs.

    def send(self, status, data, content_type="application/json; charset=utf-8", cookie=None):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in (f"localhost:{port}", f"127.0.0.1:{port}")

    def session(self, create=False):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except Exception:
            return None, None
        sid = cookies["workbench"].value if "workbench" in cookies else None
        with self.server.guard:
            now = time.monotonic()
            for key, state in list(self.server.sessions.items()):
                if state["expires"] <= now:
                    del self.server.sessions[key]
            state = self.server.sessions.get(sid)
            if state:
                return state, None
            if not create or len(self.server.sessions) >= 16:
                return None, None
            sid = secrets.token_urlsafe(32)
            state = {"csrf": secrets.token_urlsafe(32), "client": None, "devices": [],
                     "expires": now + SESSION_TTL, "last_login": 0,
                     "last_probe": 0, "lock": threading.Lock()}
            self.server.sessions[sid] = state
            return state, f"workbench={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {"message": "Host não permitido."})
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8")}
        if self.path in assets:
            filename, mime = assets[self.path]
            return self.send(200, (ROOT / "web" / filename).read_bytes(), mime)
        if self.path == "/api/health":
            return self.send(200, {"status": "ok", "video_available": False})
        if self.path == "/api/status":
            state, cookie = self.session(create=True)
            if state is None:
                return self.send(503, {"message": "Limite de sessões locais atingido."})
            with state["lock"]:
                try:
                    config = Config.from_environment()
                    auth_mode = config.auth_mode
                    configured, reason = True, ""
                except IntegrationError as exc:
                    configured, reason = False, str(exc)
                    auth_mode = "unavailable"
                return self.send(200, {"csrf": state["csrf"], "configured": configured,
                                       "auth_mode": auth_mode,
                                       "configuration_message": reason,
                                       "authenticated": state["client"] is not None,
                                       "devices": state["devices"], "video_available": False}, cookie=cookie)
        return self.send(404, {"message": "Recurso não encontrado."})

    def do_POST(self):
        if not self.valid_host() or self.headers.get("Origin") != "http://" + self.headers.get("Host", ""):
            return self.send(403, {"message": "Origem não permitida."})
        state, _ = self.session()
        if state is None or not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), state["csrf"]):
            return self.send(403, {"message": "Sessão inválida ou expirada. Recarregue a página."})
        if self.headers.get("Content-Type") != "application/json":
            return self.send(415, {"message": "Envie JSON."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8192:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            return self.send(400, {"message": "Requisição inválida."})
        with state["lock"]:
            try:
                if self.path == "/api/connectivity":
                    if body:
                        return self.send(400, {"message": "O teste de rede não recebe login ou senha."})
                    if state["last_probe"] and time.monotonic() - state["last_probe"] < 30:
                        return self.send(429, {"message": "Aguarde 30 segundos entre testes de rede."})
                    state["last_probe"] = time.monotonic()
                    observations = probe()
                    answered = sum(bool(row.get("protocol_response")) for row in observations)
                    return self.send(200, {
                        "observations": observations,
                        "message": f"{answered} de {len(observations)} servidores responderam como API. Este teste não faz login nem acessa vídeos.",
                    })
                if self.path == "/api/logout":
                    state["client"], state["devices"] = None, []
                    state["csrf"] = secrets.token_urlsafe(32)
                    return self.send(200, {"message": "Sessão local apagada."})
                if self.path == "/api/login":
                    if time.monotonic() - state["last_login"] < 5:
                        return self.send(429, {"message": "Aguarde alguns segundos antes de tentar novamente."})
                    state["last_login"] = time.monotonic()
                    state["client"], state["devices"] = None, []
                    client = YooseeClient(Config.from_environment())
                    client.login(body.get("username"), body.get("password"))
                    # Separate authentication from device retrieval and video readiness.
                    state["client"] = client
                    return self.send(200, {"message": "Login aceito pelo serviço. Consulte agora as câmeras da conta. O vídeo ainda não está implementado."})
                if self.path == "/api/devices":
                    state["devices"] = []
                    if state["client"] is None:
                        raise IntegrationError("authentication", "Entre na conta primeiro.")
                    state["devices"] = state["client"].devices()
                    return self.send(200, {"devices": state["devices"]})
                return self.send(404, {"message": "Recurso não encontrado."})
            except IntegrationError as exc:
                return self.send(422, {"error": exc.kind, "message": str(exc)})
            except Exception:
                return self.send(500, {"message": "Falha interna; nenhum detalhe de credencial foi registrado."})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = Workbench(("127.0.0.1", args.port))
    print(f"Bancada local iniciada na porta {server.server_port}. Vídeo P2P ainda indisponível.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
