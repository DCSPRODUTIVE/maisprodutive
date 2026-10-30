"""Local browser workbench with an experimental native one-frame adapter."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlsplit,parse_qs
import argparse
import math
import webcam
import hashlib
import sqlite3
import json
from pathlib import Path
import secrets
import re
import threading
import time

from yoosee import Config, IntegrationError, YooseeClient, probe
from desktop import DesktopClient, load_profile, profile_path
from video import readiness as video_readiness
from live import LiveStream
from background import BackgroundMonitor
from camera_archive import CameraArchive
from reports import EventStore, ReportMonitor
from access import Gate, TTL as ACCESS_TTL, origin as validate_origin

ROOT = Path(__file__).parent
SESSION_TTL = 20 * 60


def current_config():
    # An invalid imported profile is an error, never a reason to silently retry
    # the same credentials through another protocol or server.
    return load_profile() if profile_path().exists() else Config.from_environment()


from telegram_alerts import TelegramAlerts


class Workbench(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, public_origin=None, access_gate=None):
        if address[0] not in ("127.0.0.1", "localhost"):
            raise ValueError("Use loopback; hospedagem pública exige autenticação e HTTPS adicionais.")
        self.public_origin = validate_origin(public_origin) if public_origin else None
        self.access_gate = access_gate
        if self.public_origin and self.access_gate is None:
            raise ValueError('Acesso externo exige configurar a senha do sistema.')
        self.sessions = {}
        self.guard = threading.Lock()
        self.request_guard = threading.BoundedSemaphore(48)
        self.video_guard = threading.BoundedSemaphore(12)
        self.viewer_guard = threading.BoundedSemaphore(16)
        self.active_streams = set()
        self.stream_guard = threading.Lock()
        self.reports = ReportMonitor(self, EventStore())
        self.archive = CameraArchive(self.reports.store,self.video_guard)
        self.reports.recordings.archive=self.archive
        self.telegram = TelegramAlerts(self.reports.store, self.public_origin)
        self.background = BackgroundMonitor(self.open_background, self.stream_snapshot)
        super().__init__(address, Handler)
        self.reports.start()
        self.background.start()

    def stream_snapshot(self):
        with self.stream_guard:
            return list(self.active_streams)

    def open_background(self, entry):
        if not self.video_guard.acquire(blocking=False):
            raise IntegrationError("video_busy", "Aguardando uma das 12 conexões disponíveis.")
        stream = None
        def release():
            with self.stream_guard:
                self.active_streams.discard(stream)
            self.video_guard.release()
        try:
            stream = LiveStream(entry.account, entry.device_id, float("inf"), release, preview_width=entry.width, definition=entry.definition,**({'local_device':True} if entry.device_id.startswith('webcam:') else {}))
            if not entry.device_id.startswith('webcam:'):stream.archive_account=entry.account
            stream.background = True
            stream.monitor_until = entry.active_until(self.background.clock())
            stream.report_owner, stream.report_name, stream.report_detect = entry.owner, entry.name, entry.detection
            with self.stream_guard:
                self.active_streams.add(stream)
            stream.start()
            return stream
        except Exception:
            if stream is not None and stream.worker.ident is not None:
                stream.stop()
            else:
                release()
            raise

    def process_request(self, request, client_address):
        if not self.request_guard.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.request_guard.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_guard.release()

    @staticmethod
    def stop_streams(state, device_id=None):
        streams = state.get("streams", {})
        if device_id is None:
            selected = list(streams.values())
            streams.clear()
        else:
            stream = streams.pop(device_id, None)
            selected = [stream] if stream is not None else []
        selected = [stream for stream in selected if not getattr(stream, "background", False)]
        for stream in selected:
            stream.stop(wait=False)
        for stream in selected:
            stream.stop()

    def server_close(self):
        self.background.close()
        self.reports.close()
        self.archive.close()
        self.telegram.close()
        with self.stream_guard:
            streams = list(self.active_streams)
        for stream in streams:
            stream.stop(wait=False)
        for stream in streams:
            stream.stop()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_):
        pass  # Don't log submitted data, sessions or provider URLs.

    def send(self, status, data, content_type="application/json; charset=utf-8", cookie=None, location=None):
        cookie=cookie or getattr(self,"session_cookie",None)
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if location:
            self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie + ("; Secure" if self.public_request() else ""))
        if getattr(self, "access_cookie", None):
            self.send_header("Set-Cookie", self.access_cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_video(self, path, cookie, download=False):
        try:
            with path.open('rb') as file:
                size=path.stat().st_size
                start,end=0,size-1
                value=self.headers.get('Range')
                if value:
                    match=re.fullmatch(r'bytes=(\d{0,20})-(\d{0,20})',value)
                    if not match or not any(match.groups()):
                        return self.send(416, {"message":"Intervalo de vídeo inválido."})
                    a,b=match.groups()
                    if a:
                        start=int(a);end=min(int(b),end) if b else end
                    else:
                        start=max(0,size-int(b))
                    if not 0<=start<=end<size:
                        return self.send(416, {"message":"Intervalo de vídeo inválido."})
                self.send_response(206 if value else 200)
                self.send_header('Content-Type','video/mp4')
                if download:self.send_header('Content-Disposition','attachment; filename="DCS-video.mp4"')
                self.send_header('Content-Length',str(end-start+1))
                self.send_header('Accept-Ranges','bytes')
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                if value:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
                if cookie:self.send_header('Set-Cookie',cookie+('; Secure' if self.public_request() else ''))
                if getattr(self,'access_cookie',None):self.send_header('Set-Cookie',self.access_cookie)
                self.end_headers();file.seek(start)
                remaining=end-start+1
                while remaining:
                    chunk=file.read(min(65536,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
        except FileNotFoundError:
            return self.send(404,{"message":"Vídeo não encontrado."})
        except (BrokenPipeError,ConnectionResetError):
            return

    def public_request(self):
        return bool(self.server.public_origin and self.headers.get("Host") == self.server.public_origin[8:])

    def valid_host(self):
        port = self.server.server_port
        local = self.headers.get("Host") in (f"localhost:{port}", f"127.0.0.1:{port}")
        public = self.public_request() and self.headers.get("X-Forwarded-Proto") == "https"
        return local or public

    def expected_origin(self):
        return self.server.public_origin if self.public_request() else "http://" + self.headers.get("Host", "")

    def gate_cookie(self, token):
        return f"dcs_access={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={ACCESS_TTL}" + ("; Secure" if self.public_request() else "")

    def gate_allowed(self):
        if self.server.access_gate is None:
            return True
        if self.path in ("/access", "/access.js", "/style.css", "/icon.svg"):
            return True
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies["dcs_access"].value if "dcs_access" in cookies else None
        except Exception:
            token = None
        if self.server.access_gate.valid(token):
            self.access_cookie = self.gate_cookie(token)
            return True
        if self.path.startswith("/api/"):
            self.send(401, {"message": "Entre com a senha de acesso ao sistema.", "error": "access_required"})
        else:
            self.send(303, {}, location="/access")
        return False

    def access_login(self):
        if self.server.access_gate is None:
            return self.send(404, {"message": "Acesso protegido não configurado."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Content-Type") != "application/json" or not 0 < length <= 2048:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, UnicodeError):
            return self.send(400, {"message": "Requisição inválida."})
        token, code = self.server.access_gate.login(body.get("password"))
        if not token:
            return self.send(code, {"message": "Aguarde um minuto antes de tentar novamente." if code == 429 else "Senha de acesso inválida."})
        self.access_cookie = self.gate_cookie(token)
        return self.send(200, {"message": "Acesso autorizado."})

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
                self.session_cookie=f"workbench={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"
                return state,self.session_cookie
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

    def mjpeg(self):
        state,cookie=self.session()
        if state is None:return self.send(403,{'message':'Entre na conta.'})
        query=parse_qs(urlsplit(self.path).query)
        with state['lock']:
            stream=state['streams'].get(query.get('device_id',[''])[0])
            if state['client'] is None or stream is None or stream.handle!=query.get('stream_id',[''])[0]:
                return self.send(403,{'message':'Visualização inválida.'})
        if not self.server.viewer_guard.acquire(blocking=False):return self.send(429,{'message':'Limite de visualizações contínuas atingido.'})
        try:
            self.send_response(200)
            self.send_header('Content-Type','multipart/x-mixed-replace; boundary=dcsframe')
            self.send_header('Cache-Control','no-store, no-transform')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Accel-Buffering','no')
            self.send_header('Set-Cookie',cookie+('; Secure' if self.public_request() else ''))
            self.end_headers()
            self.connection.settimeout(5)
            sequence=0;checked=0;last_sent=time.monotonic()
            while not stream.stopped.is_set():
                now=time.monotonic()
                if now-checked>2:
                    checked=now
                    with state['lock']:
                        if state['client'] is None or state['streams'].get(query['device_id'][0]) is not stream or state['expires']<=now:break
                    if self.server.access_gate:
                        cookies=SimpleCookie(self.headers.get('Cookie',''))
                        token=cookies['dcs_access'].value if 'dcs_access' in cookies else ''
                        if not self.server.access_gate.valid(token):break
                image,new_sequence=stream.jpeg_frame(sequence)
                if image:
                    self.wfile.write(b'--dcsframe\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(image)).encode()+b'\r\n\r\n'+image+b'\r\n')
                    self.wfile.flush();sequence=new_sequence;last_sent=now
                elif now-last_sent>20:break
                stream.stopped.wait(.08)
        except (OSError,IntegrationError):pass
        finally:self.server.viewer_guard.release()

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {"message": "Host não permitido."})
        if not self.gate_allowed():
            return
        if urlsplit(self.path).path=='/api/video/mjpeg':
            return self.mjpeg()
        assets = {"/access": ("access.html", "text/html; charset=utf-8"),
                  "/access.js": ("access.js", "text/javascript; charset=utf-8"),
                  "/": ("index.html", "text/html; charset=utf-8"),
                  "/reports": ("reports.html", "text/html; charset=utf-8"),
                  "/reports.js": ("reports.js", "text/javascript; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/icon.svg": ("icon.svg", "image/svg+xml")}
        if self.path in assets:
            filename, mime = assets[self.path]
            return self.send(200, (ROOT / "web" / filename).read_bytes(), mime)
        if self.path.startswith(("/api/reports/image/", "/api/reports/video/", "/api/reports/download/")):
            state, cookie = self.session()
            if state is None:
                return self.send(403, {"message": "Entre na conta para acessar os registros."})
            with state["lock"]:
                if not isinstance(state["client"], DesktopClient):
                    return self.send(403, {"message": "Entre na conta para acessar os registros."})
                try:
                    event_id = int(self.path.rsplit("/", 1)[1])
                    if not 0 < event_id <= 9223372036854775807:
                        raise ValueError
                    is_video = self.path.startswith(("/api/reports/video/","/api/reports/download/"))
                    media = self.server.reports.store.video if is_video else self.server.reports.store.image
                    image = media(self.report_owner(state), event_id)
                except (ValueError, OSError, sqlite3.Error):
                    image = None
            if image is None:
                return self.send(404, {"message": "Registro não encontrado."})
            if is_video:
                return self.send_video(image, cookie,download=self.path.startswith("/api/reports/download/"))
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
                                       "detection_ready": self.server.reports.ready, "detection_message": self.server.reports.message,
                                       "server_monitoring": True,"mjpeg_available":True,
                                       "webcam_available":bool(webcam.cameras()),"webcam_message":"Webcam local detectada." if webcam.cameras() else "Nenhuma webcam exposta ao Linux do servidor. No Chromebook, o ChromeOS pode não disponibilizar a câmera integrada ao Linux. Confira o compartilhamento USB de uma webcam compatível.",
                                       "background_status": self.server.background.status(self.report_owner(state)) if isinstance(state["client"], DesktopClient) else None,
                                       "preferences_key": self.report_owner(state) if isinstance(state["client"], DesktopClient) else None,
                                       "preferences": self.server.reports.store.preferences(self.report_owner(state)) if isinstance(state["client"], DesktopClient) else None}, cookie=cookie)
        return self.send(404, {"message": "Recurso não encontrado."})

    def do_POST(self):
        if not self.valid_host() or self.headers.get("Origin") != self.expected_origin():
            return self.send(403, {"message": "Origem não permitida."})
        if self.path == "/api/access/login":
            return self.access_login()
        if not self.gate_allowed():
            return
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
        if self.path == "/api/video/frame":
            # Never hold the account lock while encoding or sending camera bytes.
            # A slow viewer/source must not serialize every camera in the mosaic.
            try:
                device_id=body.get('device_id')
                with state['lock']:
                    if not isinstance(device_id,str):raise IntegrationError('input','Selecione uma câmera da transmissão.')
                    stream=state['streams'].get(device_id)
                    if stream is None or state['client'] is None:raise IntegrationError('authentication','Inicie a transmissão desta câmera nesta sessão primeiro.')
                    if body.get('stream_id')!=stream.handle:raise IntegrationError('video_stopped','Esta transmissão foi substituída. Inicie novamente.')
                data=stream.frame(body.get('after',0),wait=False)
                if body.get('metadata_only') is True:data['image']=None
                return self.send(200,data)
            except IntegrationError as error:return self.send(422,{'error':error.kind,'message':str(error)})
            except Exception:return self.send(500,{'message':'Falha na leitura da imagem; tente novamente.'})
        with state["lock"]:
            try:
                if self.path in ('/api/card/start','/api/card/status'):
                    client=state['client']
                    if not isinstance(client,DesktopClient):raise IntegrationError('authentication','Entre na conta e consulte as câmeras.')
                    owner=self.report_owner(state)
                    if self.path.endswith('/status'):
                        key=body.get('job_id')
                        if not isinstance(key,str) or len(key)>64:raise IntegrationError('input','Solicitação inválida.')
                        value=self.server.archive.job(owner,key)
                        if value is None:return self.send(404,{'message':'Solicitação não encontrada.'})
                        return self.send(200,value)
                    device=body.get('device_id');client.require_device(device)
                    start,end=body.get('start'),body.get('end');action=body.get('action')
                    if (action not in ('list','backup') or type(start) not in (float,int) or type(end) not in (float,int)
                        or not math.isfinite(start) or not math.isfinite(end) or start<1000000000 or end>time.time()+5
                        or not 0<end-start<=(3600 if action=='list' else 125)):
                        raise IntegrationError('input','Escolha um intervalo passado: até 1 hora para consulta e até 2 minutos para backup.')
                    if time.monotonic()-state.get('last_card',0)<5:return self.send(429,{'message':'Aguarde 5 segundos entre solicitações.'})
                    state['last_card']=time.monotonic()
                    camera=next((c for c in state['devices'] if c['id']==device),None)
                    if camera is None:raise IntegrationError('input','Consulte as câmeras primeiro.')
                    prefs=self.server.reports.store.preferences(owner)
                    deadline=self.server.background.deadline(owner,device) if device in prefs.get('economy_ids',[]) else float('inf')
                    if deadline<=time.monotonic():raise IntegrationError('input','Câmera em Economia. Aguarde a janela ativa do monitoramento ou desative Economia antes de consultar o cartão.')
                    try:key=self.server.archive.submit(owner,client.account,camera,float(start),float(end),action,deadline)
                    except RuntimeError:return self.send(429,{'message':'Fila de cartões cheia. Aguarde uma solicitação terminar.'})
                    return self.send(200,{'job_id':key,'message':'Solicitação enfileirada.'})
                if self.path in ("/api/telegram/status", "/api/telegram/save", "/api/telegram/test"):
                    if not isinstance(state["client"], DesktopClient):
                        raise IntegrationError("authentication", "Entre na conta para configurar Telegram.")
                    owner = self.report_owner(state)
                    if self.path.endswith('/save'):
                        try:
                            self.server.telegram.config(owner, body)
                        except ValueError as error:
                            return self.send(400, {"message": str(error)})
                    if self.path.endswith('/test'):
                        if time.monotonic()-state.get('last_telegram_test', 0)<30:
                            return self.send(429, {"message":"Aguarde 30 segundos entre testes."})
                        state['last_telegram_test'] = time.monotonic()
                        if not self.server.telegram.enqueue(owner):
                            return self.send(400, {"message":"Ative e salve o Telegram antes de testar; confira também a fila de envio."})
                        return self.send(200, {"message":"Teste colocado na fila. Aguarde alguns segundos e confira o celular ou Atualizar status."})
                    return self.send(200, self.server.telegram.status(owner))
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
                if self.path == "/api/preferences":
                    if not isinstance(state["client"], DesktopClient):
                        raise IntegrationError("authentication", "Entre na conta para salvar preferências.")
                    ids=body.get("economy_ids")
                    allowed_ids=state["client"].device_ids|{c["id"] for c in state["devices"] if c.get("local")}
                    webcam_ids=body.get("webcam_enabled_ids",self.server.reports.store.preferences(self.report_owner(state)).get("webcam_enabled_ids",[]))
                    detection_ids=body.get("detection_ids", self.server.reports.store.preferences(self.report_owner(state)).get("detection_ids",[]))
                    limit=body.get("mosaic_limit")
                    if (not isinstance(ids,list) or len(ids)>100 or any(not isinstance(i,str) or i not in allowed_ids for i in ids)
                            or not isinstance(detection_ids,list) or len(detection_ids)>100
                            or any(not isinstance(i,str) or i not in allowed_ids for i in detection_ids)
                            or type(limit) is not int or limit not in (8,12)
                            or not isinstance(webcam_ids,list) or len(webcam_ids)>2 or any(not isinstance(i,str) or i not in allowed_ids or not i.startswith('webcam:') for i in webcam_ids)):
                        raise IntegrationError("input", "Preferências de câmera inválidas.")
                    values={"economy_ids":sorted(set(ids)), "detection_ids":sorted(set(detection_ids)), "mosaic_limit":limit,"webcam_enabled_ids":sorted(set(webcam_ids))}
                    self.server.reports.store.preferences(self.report_owner(state),values)
                    with self.server.stream_guard:
                        for stream in self.server.active_streams:
                            if getattr(stream,"report_owner",None)==self.report_owner(state):
                                stream.report_detect=stream.device_id in values["detection_ids"]
                    self.server.background.configure(self.report_owner(state), state["client"].account, state["devices"], values)
                    self.server.archive.configure_economy(self.report_owner(state),values["economy_ids"],self.server.background)
                    return self.send(200, {"message":"Preferências salvas. Monitoramento habilitado continua com a página fechada.","preferences":values,"background_status":self.server.background.status(self.report_owner(state))})
                if self.path in ("/api/reports", "/api/reports/videos"):
                    if not isinstance(state["client"], DesktopClient):
                        raise IntegrationError("authentication", "Entre na conta para acessar Reports.")
                    before = body.get("before")
                    if before is not None and (type(before) is not int or before < 1 or before > 9223372036854775807):
                        raise IntegrationError("input", "Página de registros inválida.")
                    return self.send(200, {"events": (self.server.reports.store.videos if self.path.endswith("/videos") else self.server.reports.store.list)(self.report_owner(state), before),
                                           "detection_ready": self.server.reports.ready,
                                           "message": self.server.reports.message})
                if self.path == "/api/logout":
                    if isinstance(state["client"],DesktopClient):self.server.archive.cancel(self.report_owner(state))
                    if isinstance(state["client"], DesktopClient):
                        self.server.background.remove(self.report_owner(state))
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
                    return self.send(200, {"message": "Visualização encerrada. Câmeras habilitadas para detecção continuam em segundo plano."})
                if self.path == "/api/video/start":
                    client = state["client"]
                    if not isinstance(client, DesktopClient):
                        raise IntegrationError("authentication", "Entre pelo perfil Windows e consulte as câmeras primeiro.")
                    device_id = body.get("device_id")
                    if isinstance(device_id,str) and device_id.startswith('webcam:'):
                        try:webcam.device(device_id)
                        except ValueError as error:raise IntegrationError('input',str(error))
                    else:client.require_device(device_id)
                    owner = self.report_owner(state)
                    prefs = self.server.reports.store.preferences(owner)
                    if device_id.startswith('webcam:') and device_id not in prefs.get('webcam_enabled_ids',[]):raise IntegrationError('input','Ative a webcam no painel primeiro.')
                    self.server.background.configure(owner, client.account, state["devices"], prefs)
                    if self.server.background.enabled(owner, device_id):
                        mosaic = body.get("mosaic", False)
                        quality = body.get("quality", "balanced")
                        if not isinstance(mosaic, bool) or quality not in ("balanced", "original", "hd", "fhd"):
                            raise IntegrationError("input", "Qualidade de imagem inválida.")
                        previous = state["streams"].get(device_id)
                        if previous is not None and not previous.stopped.is_set() and hasattr(previous, "manager"):
                            return self.send(200, {"device_id":device_id,"stream_id":previous.handle,"background":True})
                        self.server.stop_streams(state, device_id)
                        view = self.server.background.view(owner, device_id, (640 if mosaic else 960) if quality == "balanced" else 0, {"hd":1,"fhd":2}.get(quality,0))
                        state["streams"][device_id] = view
                        return self.send(200, {"device_id":device_id,"stream_id":view.handle,"background":True})
                    previous = state["streams"].get(device_id)
                    if previous is not None and not previous.stopped.is_set():
                        return self.send(200, {"device_id": device_id, "stream_id": previous.handle, "message": "Esta câmera já está em transmissão."})
                    self.server.stop_streams(state, device_id)
                    if not self.server.video_guard.acquire(blocking=False):
                        raise IntegrationError("video_busy", "O limite de 12 transmissões simultâneas foi atingido. Pare uma câmera antes de iniciar outra.")
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
                        stream.archive_account=client.account
                        stream.report_owner = self.report_owner(state)
                        stream.report_detect = device_id in self.server.reports.store.preferences(stream.report_owner).get("detection_ids",[])
                        stream.report_name = next((item["name"] for item in state["devices"] if item["id"] == device_id), device_id)
                        stream.start()
                        self.server.reports.start()
                    except Exception:
                        state["streams"].pop(device_id, None)
                        if stream is not None and stream.worker.ident is not None:
                            stream.stop()
                        else:
                            release_slot()
                        raise
                    return self.send(200, {"device_id": device_id, "stream_id": stream.handle, "message": "Conectando à câmera. Até 10 imagens/s, sem áudio."})
                if self.path == "/api/video/snapshot":
                    client = state["client"]
                    if not isinstance(client, DesktopClient):
                        raise IntegrationError("authentication", "Entre pelo perfil Windows e consulte as câmeras primeiro.")
                    device_id = body.get("device_id")
                    if isinstance(device_id,str) and device_id.startswith('webcam:'):
                        try:webcam.device(device_id)
                        except ValueError as error:raise IntegrationError('input',str(error))
                    else:client.require_device(device_id)
                    owner=self.report_owner(state)
                    if self.server.background.enabled(owner,device_id):
                        data=self.server.background.frame(owner,device_id,0)
                        if data["state"]=="paused":
                            raise IntegrationError("video_waiting", "A câmera está na pausa de economia. Aguarde a próxima janela de monitoramento.")
                        if not data["image"] or data["age_seconds"] is None or data["age_seconds"]>3:
                            raise IntegrationError("video_waiting", "Aguarde um quadro recente do monitoramento.")
                        return self.send(200,{"image":data["image"],"message":"Captura obtida do monitoramento em segundo plano."})
                    stream = state["streams"].get(device_id)
                    if stream is not None and not stream.stopped.is_set():
                        data = stream.frame(0, wait=False)
                        if not data["image"]:
                            raise IntegrationError("video_waiting", "Aguarde o primeiro quadro da transmissão antes de capturar.")
                        return self.send(200, {"image": data["image"], "message": "Captura obtida da transmissão desta câmera."})
                    if isinstance(device_id,str) and device_id.startswith('webcam:'):raise IntegrationError('video_waiting','Ative a webcam e aguarde o primeiro quadro.')
                    if not self.server.video_guard.acquire(blocking=False):
                        raise IntegrationError("video_busy", "Todas as 12 conexões estão em uso. Pare uma câmera para capturar outra imagem.")
                    try:
                        return self.send(200, client.snapshot(body.get("device_id")))
                    finally:
                        self.server.video_guard.release()
                if self.path == "/api/devices":
                    self.server.stop_streams(state)
                    state["devices"] = []
                    if state["client"] is None:
                        raise IntegrationError("authentication", "Entre na conta primeiro.")
                    state["devices"] = state["client"].devices()+webcam.cameras()
                    if isinstance(state["client"],DesktopClient):
                        self.server.background.configure(self.report_owner(state),state["client"].account,state["devices"],self.server.reports.store.preferences(self.report_owner(state)))
                    return self.send(200, {"devices": state["devices"]})
                return self.send(404, {"message": "Recurso não encontrado."})
            except IntegrationError as exc:
                return self.send(422, {"error": exc.kind, "message": str(exc)})
            except Exception:
                return self.send(500, {"message": "Falha interna; nenhum detalhe de credencial foi registrado."})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--public-origin", help="Origem HTTPS exata de um proxy/túnel local")
    parser.add_argument("--protected", action="store_true", help="Exigir senha de acesso também localmente")
    args = parser.parse_args()
    server = Workbench(("127.0.0.1", args.port), public_origin=args.public_origin,
                       access_gate=Gate() if args.public_origin or args.protected else None)
    print(f"Bancada local iniciada na porta {server.server_port}. Transmissão experimental disponível após preparação do adaptador.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
