"""Own enabled camera connections and economy schedules independently of browser sessions."""
import base64
import secrets
import threading
import time

from yoosee import IntegrationError

PERIOD = 30 * 60
ACTIVE = 5 * 60


class Entry:
    def __init__(self, owner, device_id, account, name, economy, now):
        self.owner, self.device_id = owner, device_id
        self.account, self.name = account, name
        self.economy = economy
        self.anchor = now
        self.native = None
        self.image = None
        self.last_frame = None
        self.native_sequence = -1
        self.sequence = 0
        self.width, self.definition = 640, 0
        self.retry_at = 0
        self.attempts = 0
        self.message = ''

    def window(self, now):
        phase = (now-self.anchor) % PERIOD
        return not self.economy or phase < ACTIVE

    def active_until(self, now):
        return now + max(0, ACTIVE-(now-self.anchor)%PERIOD) if self.economy else float('inf')

    def next_open(self, now):
        return max(0, PERIOD-(now-self.anchor) % PERIOD) if self.economy and not self.window(now) else 0


class ManagedView:
    """A browser may detach this view without stopping the owner's monitoring."""
    def __init__(self, manager, owner, device_id):
        self.manager, self.owner, self.device_id = manager, owner, device_id
        self.handle = secrets.token_urlsafe(18)
        self.stopped = threading.Event()
        self.expires = float('inf')

    def stop(self, wait=True):
        self.stopped.set()

    def frame(self, after, wait=True):
        if self.stopped.is_set():
            raise IntegrationError('video_stopped', 'Visualização encerrada.')
        return self.manager.frame(self.owner, self.device_id, after)


class BackgroundMonitor:
    def __init__(self, factory, streams, clock=time.monotonic):
        self.factory, self.streams, self.clock = factory, streams, clock
        self.lock = threading.RLock()
        self.entries = {}
        self.stopped = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def configure(self, owner, account, devices, preferences):
        names = {item['id']: item['name'] for item in devices}
        wanted = set(preferences.get('detection_ids', [])) & names.keys()
        economy = set(preferences.get('economy_ids', []))
        now = self.clock()
        with self.lock:
            for key in list(self.entries):
                if key[0] == owner and key[1] not in wanted:
                    self._drop(self.entries.pop(key))
            candidates = self.streams()
            for device_id in names:
                if device_id not in wanted:
                    continue
                key = owner, device_id
                entry = self.entries.get(key)
                if entry is None:
                    entry = self.entries[key] = Entry(owner, device_id, account, names[device_id], device_id in economy, now)
                    existing = next((stream for stream in candidates if getattr(stream, 'report_owner', None) == owner
                                     and stream.device_id == device_id and not stream.stopped.is_set()), None)
                    if existing:
                        existing.background = True
                        existing.report_detect = True
                        entry.native = existing
                        entry.width = getattr(existing, 'preview_width', 640)
                        entry.definition = getattr(existing, 'definition', 0)
                if entry.account != account:
                    self._drop(entry)
                    entry.account = account
                    entry.retry_at = now
                entry.name = names[device_id]
                if entry.economy != (device_id in economy):
                    entry.economy = device_id in economy
                    entry.anchor = now
                if entry.native is not None:
                    entry.native.monitor_until = entry.active_until(now)

    def enabled(self, owner, device_id):
        with self.lock:
            return (owner, device_id) in self.entries

    def view(self, owner, device_id, width, definition):
        with self.lock:
            entry = self.entries.get((owner, device_id))
            if entry is None:
                raise IntegrationError('video_stopped', 'Monitoramento desativado nesta câmera.')
            if (entry.width, entry.definition) != (width, definition):
                self._drop(entry)
                entry.width, entry.definition = width, definition
                entry.retry_at = self.clock()
            return ManagedView(self, owner, device_id)

    def _capture(self, entry):
        stream = entry.native
        if stream is None:
            return
        with stream.condition:
            sequence = getattr(stream, 'sequence', 0)
            if stream.image and sequence != entry.native_sequence:
                entry.image, entry.last_frame = stream.image, stream.last_frame
                entry.native_sequence = sequence
                entry.sequence += 1
                entry.attempts = 0

    def _drop(self, entry):
        if entry.native is not None:
            self._capture(entry)
            entry.native.report_detect = False
            entry.native.background = False
            entry.native.stop(wait=False)
            entry.native = None
            entry.native_sequence = -1

    def tick(self):
        now = self.clock()
        with self.lock:
            for entry in self.entries.values():
                self._capture(entry)
                if not entry.window(now):
                    self._drop(entry)
                    entry.retry_at = 0
                    continue
                stream = entry.native
                if stream is not None and stream.stopped.is_set():
                    error = getattr(stream, 'error', None)
                    entry.message = str(error) if isinstance(error, IntegrationError) else 'A câmera interrompeu a conexão.'
                    entry.native = None
                    entry.native_sequence = -1
                    entry.retry_at = now + min(60, 5 * 2 ** min(entry.attempts, 4))
                    entry.attempts += 1
                if entry.native is not None:
                    entry.native.monitor_until = entry.active_until(now)
                if entry.native is not None or now < entry.retry_at:
                    continue
                try:
                    entry.native = self.factory(entry)
                    entry.native.monitor_until = entry.active_until(now)
                    entry.message = ''
                except Exception as error:
                    entry.message = str(error) if isinstance(error, IntegrationError) else 'Não foi possível preparar a conexão da câmera.'
                    entry.retry_at = now + min(60, 5 * 2 ** min(entry.attempts, 4))
                    entry.attempts += 1

    def frame(self, owner, device_id, after):
        if type(after) is not int or after < 0:
            raise IntegrationError('input', 'Sequência de vídeo inválida.')
        with self.lock:
            entry = self.entries.get((owner, device_id))
            if entry is None:
                raise IntegrationError('video_stopped', 'Monitoramento desativado nesta câmera.')
            self._capture(entry)
            now = self.clock()
            paused = not entry.window(now)
            stream = entry.native
            has_native = stream is not None and not stream.stopped.is_set()
            age = now-entry.last_frame if entry.last_frame is not None else None
            image = entry.image if entry.sequence > after else None
            state = ('paused' if paused else 'retrying' if not has_native and entry.message else
                     'receiving' if has_native and age is not None and age <= 3 else
                     'queued' if has_native and getattr(stream, 'connect_started', None) is None else 'connecting')
            return {'device_id': device_id, 'sequence': entry.sequence,
                    'image': 'data:image/jpeg;base64,'+base64.b64encode(image).decode() if image else None,
                    'age_seconds': round(age, 2) if age is not None else None, 'state': state,
                    'next_open_seconds': round(entry.next_open(now)),
                    'retry_seconds': max(0, round(entry.retry_at-now)), 'message': entry.message,
                    'background': True}

    def status(self, owner):
        with self.lock:
            now = self.clock()
            entries = [entry for entry in self.entries.values() if entry.owner == owner]
            return {'configured': len(entries), 'paused': sum(not entry.window(now) for entry in entries),
                    'connected': sum(entry.native is not None and not entry.native.stopped.is_set() for entry in entries)}

    def remove(self, owner):
        with self.lock:
            for key in list(self.entries):
                if key[0] == owner:
                    self._drop(self.entries.pop(key))

    def run(self):
        while not self.stopped.wait(.25):
            try:
                self.tick()
            except Exception:
                # Do not leak provider credentials through background exception logs.
                continue

    def close(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=3)
        with self.lock:
            for entry in self.entries.values():
                self._drop(entry)
            self.entries.clear()
