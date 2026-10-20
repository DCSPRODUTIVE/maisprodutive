"""One authenticated, bounded, persistent native connection and latest JPEG only."""
import base64
import os
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time

import video
from yoosee import IntegrationError

MAX_JPEG = 8 * 1024 * 1024
IDLE_TIMEOUT = 20
FIRST_FRAME_TIMEOUT = 45
STALE_TIMEOUT = 15


def jpeg_frames(pipe):
    """Read our FFmpeg's JPEG pipe; tolerate split markers, bound retained data."""
    pending = bytearray()
    while True:
        chunk = pipe.read1(65536)
        if not chunk:
            if pending:
                raise IntegrationError('video_decode', 'O último quadro da transmissão chegou incompleto.')
            return
        pending.extend(chunk)
        while pending:
            if len(pending) < 2:
                break
            if pending[:2] != b'\xff\xd8':
                raise IntegrationError('video_decode', 'O conversor não entregou uma sequência JPEG válida.')
            end = pending.find(b'\xff\xd9', 2)
            if end < 0:
                if len(pending) > MAX_JPEG:
                    raise IntegrationError('video_decode', 'Um quadro excedeu o tamanho permitido.')
                break
            if end + 2 > MAX_JPEG:
                raise IntegrationError('video_decode', 'Um quadro excedeu o tamanho permitido.')
            yield bytes(pending[:end+2])
            del pending[:end+2]


class LiveStream:
    def __init__(self, account, device_id, expires, on_close):
        ready, reason = video.readiness()
        if not ready:
            raise IntegrationError('video_configuration', reason)
        values = (account.access_id, account.access_token, device_id)
        if any(not isinstance(v, str) or not v or len(v) > 8190 or any(c in v for c in '\n\r\0') for v in values):
            raise IntegrationError('protocol', 'Dados de sessão incompatíveis com a transmissão.')
        self.device_id = device_id
        self.handle = secrets.token_urlsafe(18)
        self.expires = expires
        self._payload = ('\n'.join(values)+'\n').encode()
        self._on_close = on_close
        self.condition = threading.Condition()
        self.stopped = threading.Event()
        self.done = threading.Event()
        self.process_guard = threading.Lock()
        self.processes = []
        self.started = self.last_seen = time.monotonic()
        self.last_frame = None
        self.image = None
        self.sequence = 0
        self.error = None
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.watchdog = threading.Thread(target=self._watch, daemon=True)

    def start(self):
        self.worker.start()
        self.watchdog.start()

    def _fail(self, kind, message):
        with self.condition:
            if self.error is None and not self.stopped.is_set():
                self.error = IntegrationError(kind, message)
            self.condition.notify_all()
        self.stop(wait=False)

    def _watch(self):
        while not self.stopped.wait(.25):
            now = time.monotonic()
            with self.condition:
                last_seen, last_frame = self.last_seen, self.last_frame
            if now >= self.expires:
                self._fail('authentication', 'A sessão expirou. Entre novamente para continuar.')
            elif now - last_seen > IDLE_TIMEOUT:
                self._fail('video_idle', 'A transmissão foi encerrada por falta de visualização.')
            elif last_frame is None and now - self.started > FIRST_FRAME_TIMEOUT:
                self._fail('video_timeout', 'A câmera não entregou o primeiro quadro no tempo esperado.')
            elif last_frame is not None and now - last_frame > STALE_TIMEOUT:
                self._fail('video_stale', 'A câmera parou de entregar novos quadros. A transmissão foi encerrada.')

    def _launch(self, args, **kwargs):
        with self.process_guard:
            if self.stopped.is_set():
                raise IntegrationError('video_stopped', 'Transmissão encerrada.')
            process = subprocess.Popen(args, start_new_session=True, stderr=subprocess.DEVNULL, **kwargs)
            self.processes.append(process)
            return process

    def _run(self):
        try:
            with tempfile.TemporaryDirectory(prefix='yoosee-live-') as directory:
                try:
                    env = dict(os.environ, WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree,mshtml=',
                               WINEPREFIX=str(video.ROOT / '.local' / 'wine-video'))
                    wine = shutil.which('wine') or shutil.which('wine64')
                    native = self._launch([wine, str(video.NATIVE / 'yoosee_snapshot.exe'), '--stream'],
                                          cwd=directory, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                    encoder = self._launch([shutil.which('ffmpeg'), '-hide_banner', '-loglevel', 'error',
                                            '-probesize', '32', '-analyzeduration', '0',
                                            '-protocol_whitelist', 'pipe', '-f', 'yuv4mpegpipe', '-i', 'pipe:0',
                                            '-vf', "scale='min(960,iw)':-2", '-threads', '1', '-q:v', '5',
                                            '-f', 'image2pipe', '-vcodec', 'mjpeg', '-flush_packets', '1', 'pipe:1'],
                                           stdin=native.stdout, stdout=subprocess.PIPE)
                    native.stdout.close()
                    native.stdin.write(self._payload)
                    native.stdin.close()
                    self._payload = None
                    for image in jpeg_frames(encoder.stdout):
                        if self.stopped.is_set():
                            break
                        with self.condition:
                            self.image = image
                            self.sequence += 1
                            self.last_frame = time.monotonic()
                            self.condition.notify_all()
                    if not self.stopped.is_set():
                        code = native.poll()
                        error = video.native_failure(code) if code else IntegrationError('video_decode', 'A transmissão de imagens foi interrompida.')
                        self._fail(error.kind, str(error))
                finally:
                    self.stop(wait=False)
                    self._reap()
        except IntegrationError as exc:
            with self.condition:
                if self.error is None:
                    self.error = exc
                self.condition.notify_all()
        except Exception:
            with self.condition:
                if self.error is None:
                    self.error = IntegrationError('video_native', 'Não foi possível manter o processo de transmissão. Detalhes de sessão omitidos.')
                self.condition.notify_all()
        finally:
            self._payload = None
            self.stopped.set()
            try:
                self._on_close()
            finally:
                self.done.set()
                with self.condition:
                    self.condition.notify_all()

    def _reap(self):
        for process in self.processes:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    pipe.close()

    def stop(self, wait=True):
        self.stopped.set()
        with self.condition:
            self.image = None
            self.condition.notify_all()
        with self.process_guard:
            for process in reversed(self.processes):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if wait and self.worker.ident is not None and threading.current_thread() is not self.worker:
            self.done.wait(3)

    def frame(self, after, wait=True):
        if not isinstance(after, int) or isinstance(after, bool) or after < 0:
            raise IntegrationError('input', 'Sequência de vídeo inválida.')
        with self.condition:
            self.last_seen = time.monotonic()
            if wait and not self.stopped.is_set() and self.sequence <= after:
                self.condition.wait(timeout=1)
            if self.error is not None:
                raise self.error
            if self.stopped.is_set():
                raise IntegrationError('video_stopped', 'Transmissão encerrada.')
            image = self.image if self.sequence > after else None
            age = time.monotonic()-self.last_frame if self.last_frame is not None else None
            return {'device_id': self.device_id, 'sequence': self.sequence,
                    'image': 'data:image/jpeg;base64,'+base64.b64encode(image).decode() if image else None,
                    'age_seconds': round(age, 2) if age is not None else None,
                    'state': 'receiving' if image else 'waiting' if self.sequence else 'connecting'}
