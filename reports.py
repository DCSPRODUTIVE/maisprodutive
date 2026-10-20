"""Local event storage and a single bounded detector worker; no camera credentials saved."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

from clips import RecordingService

ROOT = Path(__file__).parent / '.local' / 'reports'
MODEL_ROOT = Path(__file__).parent / '.local' / 'detection'
MODEL_FILES = {
    'deploy.prototxt': '2d180f723b3109e21f8287f6b3c691390d07b60eed998327cd3259ffa0e50608',
    'mobilenet_iter_73000.caffemodel': '52eed8be80522c152a17fb56740de705b79881bde1a167e0e747310523685fc7',
}
REVISION = 'bb17b6c3eef36d80be441ae8e5339be66e8e3b7a'


def readiness():
    if importlib.util.find_spec('cv2') is None or importlib.util.find_spec('numpy') is None:
        return False, 'Instale python3-opencv e execute configure_reports.py para ativar a detecção.'
    try:
        for name, digest in MODEL_FILES.items():
            if hashlib.sha256((MODEL_ROOT / name).read_bytes()).hexdigest() != digest:
                return False, 'Modelo de detecção ausente ou inválido. Execute configure_reports.py.'
    except OSError:
        return False, 'Modelo de detecção ausente. Execute configure_reports.py.'
    return True, 'Detecção local ativa: pessoas; amostragem a cada 5 segundos por câmera.'


class EventStore:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.guard = threading.Lock()

    @contextmanager
    def connect(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        conn = sqlite3.connect(self.root / 'events.sqlite3', timeout=10)
        os.chmod(self.root / 'events.sqlite3', 0o600)
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, owner TEXT NOT NULL, camera TEXT NOT NULL, name TEXT NOT NULL, created REAL NOT NULL, kind TEXT NOT NULL, confidence REAL, plate TEXT, boxes TEXT NOT NULL, image BLOB)')
        conn.execute('CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY, owner TEXT NOT NULL, camera TEXT NOT NULL, name TEXT NOT NULL, created REAL NOT NULL, filename TEXT NOT NULL, status TEXT NOT NULL, duration REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT "")')
        try:
            with conn:
                self._cleanup(conn)
                yield conn
        finally:
            conn.close()

    def add(self, owner, camera, name, kind, image=None, confidence=None, boxes=()):
        if kind != 'person':
            raise ValueError('Apenas pessoas detectadas são registradas.')
        with self.guard, self.connect() as db:
            db.execute('INSERT INTO events(owner,camera,name,created,kind,confidence,plate,boxes,image) VALUES (?,?,?,?,?,?,?,?,?)',
                       (owner, camera, name, time.time(), kind, confidence, None, json.dumps(boxes), image))
            # Keep at most 1,000 images/events per account and 30 days of history.
            db.execute('DELETE FROM events WHERE created < ?', (time.time()-30*86400,))
            db.execute('DELETE FROM events WHERE owner=? AND id NOT IN (SELECT id FROM events WHERE owner=? ORDER BY id DESC LIMIT 1000)', (owner, owner))

    def list(self, owner, before=None):
        with self.guard, self.connect() as db:
            rows = db.execute("SELECT id,camera,name,created,kind,confidence,boxes,image IS NOT NULL AS has_image FROM events WHERE owner=? AND kind='person' AND id<? ORDER BY id DESC LIMIT 24",
                              (owner, before or 9223372036854775807)).fetchall()
            return [dict(row, boxes=json.loads(row['boxes'])) for row in rows]

    def image(self, owner, event_id):
        with self.guard, self.connect() as db:
            row = db.execute("SELECT image FROM events WHERE owner=? AND id=? AND kind='person'", (owner, event_id)).fetchone()
            return bytes(row[0]) if row and row[0] is not None else None

    def preferences(self, owner, values=None):
        with self.guard, self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS preferences(owner TEXT PRIMARY KEY, value TEXT NOT NULL)')
            if values is not None:
                db.execute('INSERT OR REPLACE INTO preferences(owner,value) VALUES (?,?)', (owner,json.dumps(values)))
            row=db.execute('SELECT value FROM preferences WHERE owner=?',(owner,)).fetchone()
            return json.loads(row[0]) if row else {'economy_ids':[], 'detection_ids':[], 'mosaic_limit':8}

    def _video_path(self, filename):
        if len(filename)!=36 or not filename.endswith('.mp4') or any(c not in '0123456789abcdef' for c in filename[:32]):
            raise ValueError('Nome de vídeo inválido.')
        return self.root/'videos'/filename

    def _cleanup(self, db):
        now=time.time()
        db.execute('DELETE FROM events WHERE created<?',(now-30*86400,))
        expired=db.execute('SELECT filename FROM videos WHERE created<?',(now-5*86400,)).fetchall()
        for row in expired:
            self._video_path(row[0]).unlink(missing_ok=True)
            (self.root/'videos'/(row[0]+'.part.mp4')).unlink(missing_ok=True)
        db.execute('DELETE FROM videos WHERE created<?',(now-5*86400,))

    def cleanup(self):
        with self.guard, self.connect():
            pass

    def video_add(self, owner, camera, name, filename):
        self._video_path(filename)
        with self.guard,self.connect() as db:
            cursor=db.execute('INSERT INTO videos(owner,camera,name,created,filename,status) VALUES (?,?,?,?,?,?)',
                              (owner,camera,name,time.time(),filename,'recording'))
            return cursor.lastrowid

    def video_finish(self, record_id, status, duration, reason=''):
        with self.guard,self.connect() as db:
            db.execute('UPDATE videos SET status=?,duration=?,reason=? WHERE id=?',(status,duration,reason,record_id))

    def videos(self, owner, before=None):
        with self.guard,self.connect() as db:
            rows=db.execute('SELECT id,camera,name,created,status,duration,reason FROM videos WHERE owner=? AND id<? ORDER BY id DESC LIMIT 24',
                            (owner,before or 9223372036854775807)).fetchall()
            return [dict(row) for row in rows]

    def video(self, owner, record_id):
        with self.guard,self.connect() as db:
            row=db.execute("SELECT filename FROM videos WHERE owner=? AND id=? AND status IN ('ready','partial')",(owner,record_id)).fetchone()
            path=self._video_path(row[0]) if row else None
            return path if path and path.is_file() else None

    def recover_recordings(self):
        with self.guard,self.connect() as db:
            rows=db.execute("SELECT filename FROM videos WHERE status='recording'").fetchall()
            for row in rows:
                (self.root/'videos'/(row[0]+'.part.mp4')).unlink(missing_ok=True)
            db.execute("UPDATE videos SET status='failed',reason='interrupted' WHERE status='recording'")


class Detector:
    def __init__(self):
        import cv2
        self.cv = cv2
        cv2.setNumThreads(1)
        self.net = cv2.dnn.readNetFromCaffe(str(MODEL_ROOT/'deploy.prototxt'), str(MODEL_ROOT/'mobilenet_iter_73000.caffemodel'))

    def detect(self, jpeg):
        import numpy as np
        frame = self.cv.imdecode(np.frombuffer(jpeg, np.uint8), self.cv.IMREAD_COLOR)
        if frame is None:
            return [], None
        height, width = frame.shape[:2]
        self.net.setInput(self.cv.dnn.blobFromImage(frame, 0.007843, (300,300), 127.5))
        detections = self.net.forward().reshape(-1,7)
        rows = []
        classes = {15:'person'}
        for row in detections:
            label = classes.get(int(row[1])); confidence = float(row[2])
            if not label or confidence < .65:
                continue
            x1,y1,x2,y2 = row[3:7].clip(0,1).tolist()
            if x2<=x1 or y2<=y1:
                continue
            rows.append({'kind':label,'confidence':round(confidence,3),'box':[x1,y1,x2,y2]})
        return rows, frame



class ReportMonitor:
    def __init__(self, server, store=None):
        self.server=server
        self.store=store or EventStore()
        self.stopped=threading.Event()
        self.thread=None
        self.guard=threading.Lock()
        self.last={}
        self.saved={}
        self.ready,self.message=readiness()
        self.recordings=RecordingService(self.store)

    def start(self):
        with self.guard:
            if self.thread is None:
                self.thread=threading.Thread(target=self.run,daemon=True)
                self.thread.start()

    def run(self):
        try:
            self.store.recover_recordings()
            detector=Detector() if self.ready else None
            last_cleanup=0
            while not self.stopped.wait(.2):
                if time.monotonic()-last_cleanup>=60:
                    self.store.cleanup();last_cleanup=time.monotonic()
                if detector is None:continue
                with self.server.stream_guard:
                    streams=list(self.server.active_streams)
                for stream in streams:
                    if self.stopped.is_set():break
                    owner=getattr(stream,'report_owner',None)
                    if not owner or stream.stopped.is_set() or not getattr(stream,'report_detect',False):continue
                    key=(owner,stream.device_id)
                    now=time.monotonic()
                    if now-self.last.get(key,0)<5:continue
                    self.last[key]=now
                    # Do not heartbeat: reports never keep an abandoned camera alive.
                    with stream.condition:
                        jpeg=stream.image
                        age=now-stream.last_frame if stream.last_frame is not None else 999
                    if not jpeg or age>3:continue
                    rows,frame=detector.detect(jpeg)
                    if not getattr(stream,'report_detect',False):continue
                    for kind in ('person',):
                        matches=[row for row in rows if row['kind']==kind]
                        event_key=key+(kind,)
                        if not matches:continue
                        self.recordings.trigger(stream)
                        if now-self.saved.get(event_key,0)<60:continue
                        self.store.add(owner,stream.device_id,stream.report_name,kind,jpeg,
                                       max(row['confidence'] for row in matches),boxes=[row['box'] for row in matches])
                        self.saved[event_key]=now
                active={(getattr(s,'report_owner',None),s.device_id) for s in streams}
                self.last={k:v for k,v in self.last.items() if k in active}
                self.saved={k:v for k,v in self.saved.items() if k[:2] in active}
        except Exception:
            self.ready=False
            self.message='Detecção interrompida. Verifique a instalação e o espaço em disco; as câmeras continuam independentes.'

    def close(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=7)
        self.recordings.close()
