"""Local event storage and a single bounded detector worker; no camera credentials saved."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import time

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
    return True, 'Detecção local ativa: pessoas e veículos; amostragem a cada 5 segundos por câmera.'


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
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add(self, owner, camera, name, kind, image=None, confidence=None, plate=None, boxes=()):
        with self.guard, self.connect() as db:
            db.execute('INSERT INTO events(owner,camera,name,created,kind,confidence,plate,boxes,image) VALUES (?,?,?,?,?,?,?,?,?)',
                       (owner, camera, name, time.time(), kind, confidence, plate, json.dumps(boxes), image))
            # Keep at most 1,000 images/events per account and 30 days of history.
            db.execute('DELETE FROM events WHERE created < ?', (time.time()-30*86400,))
            db.execute('DELETE FROM events WHERE owner=? AND id NOT IN (SELECT id FROM events WHERE owner=? ORDER BY id DESC LIMIT 1000)', (owner, owner))

    def list(self, owner, before=None):
        with self.guard, self.connect() as db:
            rows = db.execute('SELECT id,camera,name,created,kind,confidence,plate,boxes,image IS NOT NULL AS has_image FROM events WHERE owner=? AND id<? ORDER BY id DESC LIMIT 24',
                              (owner, before or 9223372036854775807)).fetchall()
            return [dict(row, boxes=json.loads(row['boxes'])) for row in rows]

    def image(self, owner, event_id):
        with self.guard, self.connect() as db:
            row = db.execute('SELECT image FROM events WHERE owner=? AND id=?', (owner, event_id)).fetchone()
            return bytes(row[0]) if row and row[0] is not None else None


def plate_candidate(text):
    # Brazilian old/Mercosul patterns only; OCR is a suggestion, never verified identity.
    return next(iter(re.findall(r'(?<![A-Z0-9])[A-Z]{3}[ -]?[0-9][A-Z0-9][0-9]{2}(?![A-Z0-9])', text.upper())), None)


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
        classes = {15:'person', 7:'vehicle', 6:'vehicle', 14:'vehicle', 19:'vehicle'}
        for row in detections:
            label = classes.get(int(row[1])); confidence = float(row[2])
            if not label or confidence < .65:
                continue
            x1,y1,x2,y2 = row[3:7].clip(0,1).tolist()
            if x2<=x1 or y2<=y1:
                continue
            rows.append({'kind':label,'confidence':round(confidence,3),'box':[x1,y1,x2,y2]})
        return rows, frame

    def read_plate(self, frame, box):
        if not shutil.which('tesseract'):
            return None
        h,w=frame.shape[:2]; x1,y1,x2,y2=box
        crop=frame[int(y1*h):int(y2*h),int(x1*w):int(x2*w)]
        if crop.shape[1]<120 or crop.shape[0]<50:
            return None
        ok, png=self.cv.imencode('.png',crop)
        if not ok:
            return None
        try:
            result=subprocess.run(['tesseract','stdin','stdout','--psm','11','-l','eng'], input=png.tobytes(),
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
            candidate=plate_candidate(result.stdout.decode(errors='ignore'))
            return candidate.replace(' ','').replace('-','') if candidate else None
        except (OSError,subprocess.TimeoutExpired):
            return None


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

    def start(self):
        with self.guard:
            if self.thread is None and self.ready:
                self.thread=threading.Thread(target=self.run,daemon=True)
                self.thread.start()

    def run(self):
        try:
            detector=Detector()
            while not self.stopped.wait(.2):
                with self.server.stream_guard:
                    streams=list(self.server.active_streams)
                for stream in streams:
                    if self.stopped.is_set():break
                    owner=getattr(stream,'report_owner',None)
                    if not owner or stream.stopped.is_set():continue
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
                    for kind in ('person','vehicle'):
                        matches=[row for row in rows if row['kind']==kind]
                        event_key=key+(kind,)
                        if not matches or now-self.saved.get(event_key,0)<60:continue
                        plate=detector.read_plate(frame,matches[0]['box']) if kind=='vehicle' else None
                        self.store.add(owner,stream.device_id,stream.report_name,kind,jpeg,
                                       max(row['confidence'] for row in matches),plate,[row['box'] for row in matches])
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
