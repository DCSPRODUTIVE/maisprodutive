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
    return True, 'Detecção local ativa: pessoas; análise de quadros novos a cada 1 segundo por câmera, conforme a capacidade do servidor.'


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
        columns={row[1] for row in conn.execute('PRAGMA table_info(videos)')}
        for column,definition in [('source',"TEXT NOT NULL DEFAULT 'live'"),('pre_roll','REAL NOT NULL DEFAULT 0'),('archive_status',"TEXT NOT NULL DEFAULT ''"),('frame_count','INTEGER NOT NULL DEFAULT 0'),('capture_fps','REAL NOT NULL DEFAULT 0'),('max_gap','REAL NOT NULL DEFAULT 0'),('archive_diagnostic',"TEXT NOT NULL DEFAULT '{}'"),('sd_gap_seconds','REAL NOT NULL DEFAULT 0')]:
            if column not in columns:
                try:conn.execute('ALTER TABLE videos ADD COLUMN '+column+' '+definition)
                except sqlite3.OperationalError:
                    if column not in {row[1] for row in conn.execute('PRAGMA table_info(videos)')}:raise
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
        expired=db.execute('SELECT filename FROM videos WHERE created<?',(now-15*86400,)).fetchall()
        for row in expired:
            self._video_path(row[0]).unlink(missing_ok=True)
            (self.root/'videos'/(row[0]+'.part.mp4')).unlink(missing_ok=True)
        db.execute('DELETE FROM videos WHERE created<?',(now-15*86400,))

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

    def video_details(self, record_id, pre_roll=0, source='live', archive_status='',frame_count=0,capture_fps=0,max_gap=0):
        with self.guard,self.connect() as db:
            db.execute('UPDATE videos SET pre_roll=?,source=?,archive_status=?,frame_count=?,capture_fps=?,max_gap=? WHERE id=?',(pre_roll,source,archive_status,frame_count,capture_fps,max_gap,record_id))

    def videos(self, owner, before=None):
        with self.guard,self.connect() as db:
            rows=db.execute('SELECT id,camera,name,created,status,duration,reason,source,pre_roll,archive_status,frame_count,capture_fps,max_gap,archive_diagnostic,sd_gap_seconds FROM videos WHERE owner=? AND id<? ORDER BY id DESC LIMIT 24',
                            (owner,before or 9223372036854775807)).fetchall()
            result=[]
            for row in rows:
                item=dict(row)
                try:item['archive_diagnostic']=json.loads(item['archive_diagnostic'])
                except (TypeError,ValueError):item['archive_diagnostic']={}
                result.append(item)
            return result

    def video(self, owner, record_id):
        with self.guard,self.connect() as db:
            row=db.execute("SELECT filename FROM videos WHERE owner=? AND id=? AND status IN ('ready','partial')",(owner,record_id)).fetchone()
            path=self._video_path(row[0]) if row else None
            return path if path and path.is_file() else None

    def recover_recordings(self):
        # Remove only abandoned private capture directories, never user media.
        import shutil
        for path in (self.root/'videos').glob('capture-*'):
            try:
                if not path.is_symlink() and path.is_dir() and time.time()-path.stat().st_mtime>900:
                    shutil.rmtree(path)
            except OSError:pass
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
        rows=[]
        def infer(image, region):
            self.net.setInput(self.cv.dnn.blobFromImage(image,0.007843,(300,300),127.5))
            detections=self.net.forward().reshape(-1,7)
            ox,oy,rw,rh=region
            for row in detections:
                confidence=float(row[2])
                if int(row[1])!=15 or confidence<.55:continue
                x1,y1,x2,y2=row[3:7].clip(0,1).tolist()
                if x2<=x1 or y2<=y1:continue
                box=[(ox+x1*rw)/width,(oy+y1*rh)/height,(ox+x2*rw)/width,(oy+y2*rh)/height]
                rows.append({'kind':'person','confidence':round(confidence,3),'box':box})
        infer(frame,(0,0,width,height))
        # A second scale preserves small-person detail that a whole-frame 300px input loses.
        if width>=960 and not rows:
            span=width*2//3
            for left in (0,width-span):infer(frame[:,left:left+span],(left,0,span,height))
        if rows:
            boxes=[[int(r['box'][0]*width),int(r['box'][1]*height),int((r['box'][2]-r['box'][0])*width),int((r['box'][3]-r['box'][1])*height)] for r in rows]
            indices=self.cv.dnn.NMSBoxes(boxes,[r['confidence'] for r in rows],.55,.4)
            rows=[rows[int(i)] for i in indices.flatten()] if len(indices) else []
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
        self.presence={}
        self.ready,self.message=readiness()
        self.recordings=RecordingService(self.store)

    def start(self):
        with self.guard:
            if self.thread is None:
                self.thread=threading.Thread(target=self.run,daemon=True)
                self.thread.start()

    def process(self, stream, detector):
        owner=getattr(stream,'report_owner',None)
        now=time.monotonic()
        if (not owner or stream.stopped.is_set() or not getattr(stream,'report_detect',False)
            or now>=getattr(stream,'monitor_until',float('inf'))):return
        key=(owner,stream.device_id)
        if now-self.last.get(key,0)<1:return
        with stream.condition:
            jpeg=stream.image
            stamp=stream.last_frame
            age=now-stamp if stamp is not None else 999
        if not jpeg or age>2 or stamp==getattr(stream,'report_sample_stamp',None):return
        self.last[key]=now
        stream.report_sample_stamp=stamp
        started=time.monotonic()
        rows,frame=detector.detect(jpeg)
        if not getattr(stream,'report_detect',False) or time.monotonic()>=getattr(stream,'monitor_until',float('inf')):return
        matches=[row for row in rows if row['kind']=='person']
        stream.detection_health={'people':len(matches),'analysis_ms':round((time.monotonic()-started)*1000),
                                 'analyzed_at':time.monotonic(),'error':False}
        if not matches:return
        previous=self.presence.get(key,0)
        self.presence[key]=now
        self.recordings.trigger(stream)
        event_key=key+('person',)
        elapsed=now-self.saved.get(event_key,0)
        if elapsed>=30 or (now-previous>=3 and elapsed>=5):
            self.store.add(owner,stream.device_id,stream.report_name,'person',jpeg,
                           max(row['confidence'] for row in matches),boxes=[row['box'] for row in matches])
            self.saved[event_key]=now
            alerts=getattr(self.server,'telegram',None)
            if alerts:alerts.enqueue(owner,stream.report_name,jpeg,max(row['confidence'] for row in matches))

    def run(self):
        try:
            self.store.recover_recordings()
            detector=Detector() if self.ready else None
            last_cleanup=0
            while not self.stopped.wait(.1):
                if time.monotonic()-last_cleanup>=60:
                    self.store.cleanup();last_cleanup=time.monotonic()
                if detector is None:continue
                with self.server.stream_guard:streams=list(self.server.active_streams)
                # Each camera gets one turn; a bad frame must not stop other cameras.
                for stream in streams:
                    if self.stopped.is_set():break
                    try:self.process(stream,detector)
                    except Exception:
                        stream.detection_health={'error':True,'analyzed_at':time.monotonic()}
                cutoff=time.monotonic()-600
                self.last={k:v for k,v in self.last.items() if v>cutoff}
                self.saved={k:v for k,v in self.saved.items() if v>cutoff}
                self.presence={k:v for k,v in self.presence.items() if v>cutoff}
        except Exception:
            self.ready=False
            self.message='Detecção interrompida. Verifique a instalação e o espaço em disco; as câmeras continuam independentes.'

    def close(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=7)
        self.recordings.close()
