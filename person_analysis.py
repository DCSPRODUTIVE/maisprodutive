"""Lightweight per-camera motion tracks. IDs are temporary, never identities."""
import math

DEFAULTS={'confidence':.55,'min_height':.01,'night_auto':True,'night_confidence':.5,
          'dwell_seconds':60,'dwell_enabled':True,'line_enabled':False,'line_axis':'x','line_position':.5,'line_direction':'both'}

def settings(values=None):
    values=values or {}
    if not isinstance(values,dict) or set(values)-set(DEFAULTS):raise ValueError('Configuração de análise inválida.')
    result=dict(DEFAULTS,**values)
    for key,lo,hi in [('confidence',.35,.95),('min_height',.01,.7),('night_confidence',.35,.95),('dwell_seconds',10,1800),('line_position',.05,.95)]:
        value=result[key]
        if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('Valor de análise fora do intervalo.')
    for key in ('night_auto','dwell_enabled','line_enabled'):
        if type(result[key]) is not bool:raise ValueError('Escolha ativado ou desativado.')
    if result['line_axis'] not in ('x','y') or result['line_direction'] not in ('both','positive','negative'):raise ValueError('Linha inválida.')
    return result

def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union>0 else 0

def center(box):return ((box[0]+box[2])/2,(box[1]+box[3])/2)

class Tracker:
    def __init__(self):self.tracks={};self.counter=0;self.last=None
    def update(self,rows,now,config):
        if self.last is not None and now-self.last>12:self.tracks.clear()
        self.last=now
        self.tracks={k:t for k,t in self.tracks.items() if now-t['last']<=8}
        available=set(self.tracks);active=[];events=[]
        for row in sorted(rows,key=lambda r:r['confidence'],reverse=True)[:32]:
            box=row['box'];point=center(box)
            candidates=[]
            for key in available:
                t=self.tracks[key];overlap=iou(box,t['box']);old=center(t['box']);distance=math.hypot(point[0]-old[0],point[1]-old[1])
                if overlap>.15 or distance<.12:candidates.append((overlap-distance,key))
            if candidates:
                key=max(candidates)[1];available.remove(key);t=self.tracks[key]
                t['hits']+=1;t['box']=box;t['last']=now
            else:
                self.counter+=1;key=self.counter
                t=self.tracks[key]={'box':box,'first':now,'last':now,'hits':1,'announced':False,'dwell':False,'side':0,'crossed_at':-1e9}
            confirmed=t['hits']>=2 or row['confidence']>=.85
            if confirmed:
                active.append(key);row['track_id']=key
                if not t['announced']:events.append(('presence',key));t['announced']=True
                if config['dwell_enabled'] and not t['dwell'] and now-t['first']>=config['dwell_seconds']:
                    events.append(('dwell',key));t['dwell']=True
            axis=0 if config['line_axis']=='x' else 1;delta=point[axis]-config['line_position']
            side=1 if delta>.025 else -1 if delta<-.025 else 0
            if side:
                if confirmed and config['line_enabled'] and t['side'] and side!=t['side'] and now-t['crossed_at']>=10:
                    direction='positive' if side>0 else 'negative'
                    if config['line_direction'] in ('both',direction):events.append(('line_'+direction,key));t['crossed_at']=now
                t['side']=side
        return {'track_ids':active,'reasons':sorted({reason for reason,key in events}),
                'duration_seconds':round(max((now-self.tracks[k]['first'] for k in active),default=0),1)}

def photo_score(frame,rows):
    confidence=max((r['confidence'] for r in rows),default=0)
    area=max(((r['box'][2]-r['box'][0])*(r['box'][3]-r['box'][1]) for r in rows),default=0)
    sharpness=0
    if frame is not None:
        import cv2
        h,w=frame.shape[:2]
        for row in rows:
            a,b,c,d=row['box'];crop=frame[max(0,int(b*h)):min(h,int(d*h)),max(0,int(a*w)):min(w,int(c*w))]
            if crop.size:
                gray=cv2.cvtColor(cv2.resize(crop,(64,64)),cv2.COLOR_BGR2GRAY)
                sharpness=max(sharpness,min(1,float(cv2.Laplacian(gray,cv2.CV_64F).var())/500))
    return confidence*.6+math.sqrt(max(0,area))*.2+sharpness*.2
