"""Local, opt-in YuNet/SFace enrollment. Only human labels become recognition examples."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time

MODEL_ROOT = Path(__file__).parent / '.local' / 'faces'
MODELS = {
    'face_detection_yunet_2023mar.onnx': ('face_detection_yunet', '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'),
    'face_recognition_sface_2021dec.onnx': ('face_recognition_sface', '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79'),
}
THRESHOLD = .55
MARGIN = .08


def readiness():
    if importlib.util.find_spec('cv2') is None:
        return False, 'Instale python3-opencv e execute python3 configure_faces.py.'
    try:
        import cv2
        version=tuple(int(part) for part in cv2.__version__.split('.')[:2])
        if version<(4,8) or not hasattr(cv2, 'FaceDetectorYN') or not hasattr(cv2, 'FaceRecognizerSF'):
            return False, 'OpenCV 4.8 ou mais recente com YuNet e SFace necessário.'
        for name, (_, digest) in MODELS.items():
            if hashlib.sha256((MODEL_ROOT/name).read_bytes()).hexdigest() != digest:
                return False, 'Prepare os modelos: python3 configure_faces.py.'
    except (OSError, ImportError):
        return False, 'Prepare os modelos: python3 configure_faces.py.'
    return True, 'Reconhecimento local disponível. Resultados são sugestões; revise os nomes.'


def vector(values):
    if not isinstance(values, list) or len(values) != 128:
        raise ValueError('Descritor facial inválido.')
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError('Descritor facial inválido.')
    norm = math.sqrt(sum(v*v for v in values))
    if norm < 1e-9:
        raise ValueError('Descritor facial inválido.')
    return [float(v/norm) for v in values]


def identify(feature, templates):
    # Rank by distinct human-assigned identity, never by previous automatic predictions.
    scores = {}
    for name, example in templates:
        score = sum(a*b for a,b in zip(feature, example))
        scores[name] = max(score, scores.get(name, -1))
    ranked = sorted(scores.items(), key=lambda item:item[1], reverse=True)
    if ranked and ranked[0][1] >= THRESHOLD and (len(ranked)<2 or ranked[0][1]-ranked[1][1]>=MARGIN):
        return {'state':'known', 'name':ranked[0][0], 'similarity':round(ranked[0][1],3)}
    return {'state':'unrecognized', 'name':None, 'similarity':None}


class FaceStore:
    def __init__(self, store):
        self.store = store

    def schema(self, db):
        db.execute('CREATE TABLE IF NOT EXISTS face_settings(owner TEXT PRIMARY KEY, enabled INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS faces(id INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT NOT NULL,camera TEXT NOT NULL,name TEXT NOT NULL,created REAL NOT NULL,image BLOB NOT NULL,embedding TEXT NOT NULL,label TEXT NOT NULL DEFAULT "")')
        db.execute('CREATE INDEX IF NOT EXISTS faces_owner ON faces(owner,id)')
        db.execute('DELETE FROM faces WHERE label="" AND created<?',(time.time()-30*86400,))

    def enabled(self, owner, value=None):
        with self.store.guard, self.store.connect() as db:
            self.schema(db)
            if value is not None:
                if type(value) is not bool:raise ValueError('Opção facial inválida.')
                db.execute('INSERT OR REPLACE INTO face_settings VALUES (?,?)',(owner,int(value)))
            row=db.execute('SELECT enabled FROM face_settings WHERE owner=?',(owner,)).fetchone()
            return bool(row and row[0])

    def templates(self, db, owner):
        return [(r['label'],json.loads(r['embedding'])) for r in db.execute('SELECT label,embedding FROM faces WHERE owner=? AND label!=""',(owner,))]

    def add(self, owner, camera, name, image, feature):
        if not isinstance(image,bytes) or len(image)>1024*1024:raise ValueError('Recorte facial inválido.')
        feature=vector(feature)
        with self.store.guard, self.store.connect() as db:
            self.schema(db)
            setting=db.execute('SELECT enabled FROM face_settings WHERE owner=?',(owner,)).fetchone()
            if not setting or not setting[0]:return
            # A repeated view of the same face in this camera does not fill the gallery.
            recent=db.execute('SELECT embedding FROM faces WHERE owner=? AND camera=? AND created>? ORDER BY id DESC LIMIT 24',(owner,camera,time.time()-30)).fetchall()
            if any(sum(a*b for a,b in zip(feature,json.loads(r[0])))>.85 for r in recent):return
            db.execute('INSERT INTO faces(owner,camera,name,created,image,embedding) VALUES (?,?,?,?,?,?)',(owner,camera,name,time.time(),image,json.dumps(feature)))
            db.execute('DELETE FROM faces WHERE owner=? AND label="" AND id NOT IN (SELECT id FROM faces WHERE owner=? AND label="" ORDER BY id DESC LIMIT 500)',(owner,owner))

    def list(self, owner, before=None):
        with self.store.guard, self.store.connect() as db:
            self.schema(db)
            templates=self.templates(db,owner)
            rows=db.execute('SELECT id,camera,name,created,label,embedding FROM faces WHERE owner=? AND id<? ORDER BY id DESC LIMIT 24',(owner,before or 9223372036854775807)).fetchall()
            result=[]
            for row in rows:
                item={k:row[k] for k in ('id','camera','created','label')}
                item['camera_name']=row['name']
                item.update({'state':'enrolled','name_label':row['label']} if row['label'] else identify(json.loads(row['embedding']),templates))
                result.append(item)
            return result

    def image(self, owner, face_id):
        with self.store.guard, self.store.connect() as db:
            self.schema(db)
            row=db.execute('SELECT image FROM faces WHERE owner=? AND id=?',(owner,face_id)).fetchone()
            return bytes(row[0]) if row else None

    def label(self, owner, face_id, name):
        if not isinstance(name,str) or len(name)>80 or any(ord(c)<32 for c in name):raise ValueError('Nome inválido (até 80 caracteres).')
        name=name.strip()
        with self.store.guard, self.store.connect() as db:
            self.schema(db)
            if db.execute('SELECT 1 FROM faces WHERE owner=? AND id=?',(owner,face_id)).fetchone() is None:raise ValueError('Rosto não encontrado.')
            if name and db.execute('SELECT COUNT(*) FROM faces WHERE owner=? AND label!="" AND id!=?',(owner,face_id)).fetchone()[0]>=1000:raise ValueError('Limite de 1.000 exemplos nomeados; remova exemplos antigos.')
            db.execute('UPDATE faces SET label=? WHERE owner=? AND id=?',(name,owner,face_id))

    def delete(self, owner, face_id):
        with self.store.guard, self.store.connect() as db:
            self.schema(db)
            db.execute('DELETE FROM faces WHERE owner=? AND id=?',(owner,face_id))

    def clear(self, owner):
        with self.store.guard, self.store.connect() as db:
            self.schema(db)
            db.execute('DELETE FROM faces WHERE owner=?',(owner,))
            db.execute('INSERT OR REPLACE INTO face_settings VALUES (?,0)',(owner,))


class FaceEngine:
    def __init__(self):
        import cv2
        self.cv=cv2
        self.detector=cv2.FaceDetectorYN.create(str(MODEL_ROOT/'face_detection_yunet_2023mar.onnx'),'',(320,320),.9,.3,100)
        self.recognizer=cv2.FaceRecognizerSF.create(str(MODEL_ROOT/'face_recognition_sface_2021dec.onnx'),'')

    def extract(self, frame, boxes):
        cv=self.cv
        height,width=frame.shape[:2]
        # Detect within person regions to retain small face detail without upscaling.
        results=[]
        for box in boxes[:8]:
            x1,y1,x2,y2=[max(0,min(1,v)) for v in box]
            left,top,right,bottom=int(x1*width),int(y1*height),int(x2*width),int(y2*height)
            region=frame[top:bottom,left:right]
            if region.size==0 or min(region.shape[:2])<64:continue
            if max(region.shape[:2])>960:
                scale=960/max(region.shape[:2]);region=cv.resize(region,(round(region.shape[1]*scale),round(region.shape[0]*scale)))
            self.detector.setInputSize((region.shape[1],region.shape[0]))
            _,faces=self.detector.detect(region)
            for face in ([] if faces is None else faces[:4]):
                x,y,w,h=face[:4]
                if min(w,h)<64:continue
                crop=region[max(0,int(y)):min(region.shape[0],int(y+h)),max(0,int(x)):min(region.shape[1],int(x+w))]
                if crop.size==0:continue
                gray=cv.cvtColor(crop,cv.COLOR_BGR2GRAY)
                if cv.Laplacian(gray,cv.CV_64F).var()<65 or not 35<gray.mean()<230:continue
                aligned=self.recognizer.alignCrop(region,face)
                feature=vector(self.recognizer.feature(aligned).flatten().tolist())
                if max(crop.shape[:2])>512:
                    scale=512/max(crop.shape[:2]);crop=cv.resize(crop,(round(crop.shape[1]*scale),round(crop.shape[0]*scale)))
                ok,jpeg=cv.imencode('.jpg',crop,[cv.IMWRITE_JPEG_QUALITY,95])
                if ok:results.append((jpeg.tobytes(),feature))
        return results
