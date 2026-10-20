"""Local browser workbench with an experimental native one-frame adapter."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
import argparse
import hashlib
import sqlite3
import json
from pathlib import Path
import secrets
import threading
import time

from yoosee import Config, IntegrationError, YooseeClient, probe
from desktop import DesktopClient, load_profile, profile_path
from video import readiness as video_readiness
from live import LiveStream
from reports import EventStore, ReportMonitor

ROOT = Path(__file__).parent
SESSION_TTL = 20 * 60


def current_config():
    # An invalid imported profile is an error, never a reason to silently retry
    # the same credentials through another protocol or server.
    return load_profile() if profile_path().exists() else Config.from_environment()


class Workbench(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        if address[0] not in ("127.0.0.1", "localhost"):
            raise ValueError("Use loopback; hospedagem pública exige autenticação e HTTPS adicionais.")
        self.sessions = {}
        self.guard = threading.Lock()
        self.video_guard = threading.BoundedSemaphore(8)
        self.active_streams = set()
        self.stream_guard = threading.Lock()
        self.reports = ReportMonitor(self, EventStore())
        super().__init__(address, Handler)

    @staticmethod
    def stop_streams(state, device_id=None):
        streams = state.get("streams", {})
        if device_id is None:
            selected = list(streams.values())
            streams.clear()
        else:
            stream = streams.pop(device_id, None)
            selected = [stream] if stream is not None else []
        for stream in selected:
            stream.stop(wait=False)
        for stream in selected:
            stream.stop()

    def server_close(self):
        self.reports.close()
        with self.stream_guard:
            streams = list(self.active_streams)
        for stream in streams:
            stream.stop(wait=False)
        for stream in streams:
            stream.stop()
        super().server_close()


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
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
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
                    self.server.stop_streams(state)
                    del self.server.sessions[key]
            state = self.server.sessions.get(sid)
            if state:
                # Sliding local session while the dashboard is actively used.
                state["expires"] = now + SESSION_TTL
                for stream in list(state["streams"].values()):
                    stream.expires = state["expires"]
                return state, f"workbench={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"
            if not create or len(self.server.sessions) >= 16:
                return None, None
            sid = secrets.token_urlsafe(32)
            state = {"csrf": secrets.token_urlsafe(32), "client": None, "devices": [],
                     "expires": now + SESSION_TTL, "last_login": 0,
                     "last_probe": 0, "streams": {}, "lock": threading.Lock()}
            self.server.sessions[sid] = state
            return state, f"workbench={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"

    @staticmethod
    def report_owner(state):
        return state.get("report_owner") or hashlib.sha256(state["client"].account.access_id.encode()).hexdigest()

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {"message": "Host não permitido."})
        assets = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/reports": ("reports.html", "text/html; charset=utf-8"),
                  "/reports.js": ("reports.js", "text/javascript; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/icon.svg": ("icon.svg", "image/svg+xml")}
        if self.path in assets:
            filename, mime = assets[self.path]
            return self.send(200, (ROOT / "web" / filename).read_bytes(), mime)
        if self.path.startswith("/api/reports/image/"):
            state, cookie = self.session()
            if state is None:
                return self.send(403, {"message": "Entre na conta para acessar os registros."})
            with state["lock"]:
                if not isinstance(state["client"], DesktopClient):
                    return self.send(403, {"message": "Entre na conta para acessar os registros."})
                try:
                    event_id = int(self.path.rsplit("/", 1)[1])
                    image = self.server.reports.store.image(self.report_owner(state), event_id)
                except (ValueError, OSError, sqlite3.Error):
                    image = None
            if image is None:
                return self.send(404, {"message": "Registro não encontrado."})
            return self.send(200, image, "image/jpeg", cookie=cookie)
        if self.path == "/api/health":
            return self.send(200, {"status": "ok", "video_available": False})
        if self.path == "/api/status":
            state, cookie = self.session(create=True)
            if state is None:
                return self.send(503, {"message": "Limite de sessões locais atingido."})
            with state["lock"]:
                try:
                    config = current_config()
                    auth_mode = config.auth_mode
                    configured, reason = True, ""
                except IntegrationError as exc:
                    configured, reason = False, str(exc)
                    auth_mode = "unavailable"
                snapshot_ready, snapshot_message = video_readiness() if auth_mode == "windows-experimental" else (False, "A captura exige o perfil Windows.")
                return self.send(200, {"csrf": state["csrf"], "configured": configured,
                                       "snapshot_ready": snapshot_ready, "snapshot_message": snapshot_message,
                                       "stream_device_ids": [key for key, stream in state.get("streams", {}).items() if not stream.stopped.is_set()],
                                       "auth_mode": auth_mode,
                                       "configuration_message": reason,
                                       "authenticated": state["client"] is not None,
                                       "devices": state["devices"], "video_available": False,
                                       "detection_ready": self.server.reports.ready, "detection_message": self.server.reports.message}, cookie=cookie)
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
                    observations = probe(desktop=True) if profile_path().exists() else probe()
                    answered = sum(bool(row.get("protocol_response")) for row in observations)
                    return self.send(200, {
                        "observations": observations,
                        "message": f"{answered} de {len(observations)} servidores responderam como API. Este teste não faz login nem acessa vídeos.",
                    })
                if self.path == "/api/reports":
                    if not isinstance(state["client"], DesktopClient):
                        raise IntegrationError("authentication", "Entre na conta para acessar Reports.")
                    before = body.get("before")
                    if before is not None and (type(before) is not int or before < 1 or before > 9223372036854775807):
                        raise IntegrationError("input", "Página de registros inválida.")
                    return self.send(200, {"events": self.server.reports.store.list(self.report_owner(state), before),
                                           "detection_ready": self.server.reports.ready,
                                           "message": self.server.reports.message})
                if self.path == "/api/logout":
                    self.server.stop_streams(state)
                    state["client"], state["devices"] = None, []
                    state["csrf"] = secrets.token_urlsafe(32)
                    return self.send(200, {"message": "Sessão local apagada."})
                if self.path == "/api/login":
                    if time.monotonic() - state["last_login"] < 5:
                        return self.send(429, {"message": "Aguarde alguns segundos antes de tentar novamente."})
                    state["last_login"] = time.monotonic()
                    self.server.stop_streams(state)
                    state["client"], state["devices"] = None, []
                    config = current_config()
                    if config.auth_mode == "windows-experimental":
                        client = DesktopClient(config)
                        client.login(body.get("username"), body.get("password"), body.get("country_code", "55"))
                    else:
                        client = YooseeClient(config)
                        client.login(body.get("username"), body.get("password"))
                    # Separate authentication from device retrieval and video readiness.
                    state["client"] = client
                    identity = str(body.get("username", "")).strip().lower()
                    if "@" not in identity:
                        identity = str(body.get("country_code", "55")) + ":" + identity
                    state["report_owner"] = hashlib.sha256(identity.encode()).hexdigest()
                    return self.send(200, {"message": "Login aceito pelo serviço. Consulte as câmeras para capturar uma imagem ou iniciar a transmissão experimental."})
                if self.path == "/api/video/stop":
                    device_id = body.get("device_id")
                    if device_id is not None and not isinstance(device_id, str):
                        raise IntegrationError("input", "Câmera inválida.")
                    target = state["streams"].get(device_id) if device_id is not None else None
                    if target is None or body.get("stream_id") is None or target.handle == body["stream_id"]:
                        self.server.stop_streams(state, device_id)
                    return self.send(200, {"message": "Transmissão encerrada."})
                if self.path == "/api/video/frame":
                    device_id = body.get("device_id")
                    if not isinstance(device_id, str):
                        raise IntegrationError("input", "Selecione uma câmera da transmissão.")
                    stream = state["streams"].get(device_id)
                    if stream is None or state["client"] is None:
                        raise IntegrationError("authentication", "Inicie a transmissão desta câmera nesta sessão primeiro.")
                    if body.get("stream_id") != stream.handle:
                        raise IntegrationError("video_stopped", "Esta transmissão foi substituída. Inicie novamente.")
                    return self.send(200, stream.frame(body.get("after", 0), wait=False))
                if self.path == "/api/video/start":
                    client = state["client"]
                    if not isinstance(client, DesktopClient):
                        raise IntegrationError("authentication", "Entre pelo perfil Windows e consulte as câmeras primeiro.")
                    device_id = body.get("device_id")
                    client.require_device(device_id)
                    previous = state["streams"].get(device_id)
                    if previous is not None and not previous.stopped.is_set():
                        return self.send(200, {"device_id": device_id, "stream_id": previous.handle, "message": "Esta câmera já está em transmissão."})
                    self.server.stop_streams(state, device_id)
                    if not self.server.video_guard.acquire(blocking=False):
                        raise IntegrationError("video_busy", "O limite de 8 transmissões simultâneas foi atingido. Pare uma câmera antes de iniciar outra.")
                    stream = None
                    def release_slot():
                        with self.server.stream_guard:
                            self.server.active_streams.discard(stream)
                        self.server.video_guard.release()
                    try:
                        mosaic = body.get("mosaic", False)
                        if not isinstance(mosaic, bool):
                            raise IntegrationError("input", "Modo de mosaico inválido.")
                        quality = body.get("quality", "balanced")
                        if quality not in ("balanced", "original", "hd", "fhd"):
                            raise IntegrationError("input", "Qualidade de imagem inválida.")
                        stream = LiveStream(client.account, device_id, state["expires"], release_slot, preview_width=(640 if mosaic else 960) if quality == "balanced" else 0, definition={"hd": 1, "fhd": 2}.get(quality, 0))
                        state["streams"][device_id] = stream
                        with self.server.stream_guard:
                            self.server.active_streams.add(stream)
                        stream.report_owner = self.report_owner(state)
                        stream.report_name = next((item["name"] for item in state["devices"] if item["id"] == device_id), device_id)
                        stream.start()
                        try:
                            self.server.reports.store.add(stream.report_owner, device_id, stream.report_name, "opened")
                        except (OSError, sqlite3.Error):
                            pass
                        self.server.reports.start()
                    except Exception:
                        state["streams"].pop(device_id, None)
                        if stream is not None and stream.worker.ident is not None:
                            stream.stop()
                        else:
                            release_slot()
                        raise
                    return self.send(200, {"device_id": device_id, "stream_id": stream.handle, "message": "Conectando à câmera. Até 5 imagens/s, sem áudio."})
                if self.path == "/api/video/snapshot":
                    client = state["client"]
                    if not isinstance(client, DesktopClient):
                        raise IntegrationError("authentication", "Entre pelo perfil Windows e consulte as câmeras primeiro.")
                    device_id = body.get("device_id")
                    client.require_device(device_id)
                    stream = state["streams"].get(device_id)
                    if stream is not None and not stream.stopped.is_set():
                        data = stream.frame(0, wait=False)
                        if not data["image"]:
                            raise IntegrationError("video_waiting", "Aguarde o primeiro quadro da transmissão antes de capturar.")
                        return self.send(200, {"image": data["image"], "message": "Captura obtida da transmissão desta câmera."})
                    if not self.server.video_guard.acquire(blocking=False):
                        raise IntegrationError("video_busy", "Todas as 8 conexões estão em uso. Pare uma câmera para capturar outra imagem.")
                    try:
                        return self.send(200, client.snapshot(body.get("device_id")))
                    finally:
                        self.server.video_guard.release()
                if self.path == "/api/devices":
                    self.server.stop_streams(state)
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
    print(f"Bancada local iniciada na porta {server.server_port}. Transmissão experimental disponível após preparação do adaptador.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
