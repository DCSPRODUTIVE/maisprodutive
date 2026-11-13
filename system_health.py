"""Cheap camera outage detection; inactivity during Economy never counts as failure."""
import threading
import time
from camera_names import display_name

class Outage:
    def __init__(self):self.rows={}
    def update(self,key,active,fresh,now):
        row=self.rows.setdefault(key,{'at':now,'active':False,'bad':0,'alerted':False})
        delta=max(0,min(30,now-row['at']));event=None
        if fresh:
            if row['alerted']:event='recovered'
            row['bad']=0;row['alerted']=False
        elif active and row['active']:row['bad']+=delta
        if active and row['bad']>=300 and not row['alerted']:
            row['alerted']=True;event='outage'
        row['at']=now;row['active']=active
        return event

class SystemHealth:
    def __init__(self,server):
        self.server=server;self.started=time.monotonic();self.heartbeat=self.started
        self.outages=Outage();self.snapshot={};self.stopped=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)
    def start(self):self.thread.start()
    def sample(self):
        now=time.monotonic();rows={}
        for stream in self.server.stream_snapshot():
            if stream.stopped.is_set():continue
            owner=getattr(stream,'report_owner',None)
            if owner:rows[(owner,stream.device_id)]=(True,stream.last_frame,getattr(stream,'report_name',stream.device_id))
        with self.server.background.lock:
            for key,entry in self.server.background.entries.items():
                rows[key]=(entry.window(now),entry.last_frame,entry.name)
        summary={}
        for key,(active,stamp,name) in rows.items():
            name=display_name(name,key[1])
            fresh=active and stamp is not None and now-stamp<15
            record=summary.setdefault(key[0],{'expected':0,'fresh':0,'stalled':[]})
            record['expected']+=int(active);record['fresh']+=int(fresh)
            event=self.outages.update(key,active,fresh,now)
            if self.outages.rows[key]['alerted'] and active:record['stalled'].append(key[1])
            if event:
                message=(f'{name}: mais de 5 minutos de atividade sem imagens. Abra o painel; pode ser necessário renovar a sessão Yoosee.' if event=='outage' else f'{name}: transmissão de imagens recuperada.')
                self.server.telegram.enqueue(key[0],message)
                self.server.diagnostics.record(key[0],key[1],'camera_outage' if event=='outage' else 'camera_recovered',duration=round(self.outages.rows[key]['bad']))
        # Remove cameras no longer watched; keep configured Economy pauses.
        self.outages.rows={k:v for k,v in self.outages.rows.items() if k in rows}
        self.snapshot=summary;self.heartbeat=now
    def status(self):
        now=time.monotonic()
        background=now-getattr(self.server.background,'heartbeat',now)
        detector=now-getattr(self.server.reports,'heartbeat',now)
        ok=now-self.heartbeat<60 and background<120 and detector<120
        return {'ok':ok,'uptime_seconds':round(now-self.started),'reason':'healthy' if ok else 'worker_stalled'}
    def run(self):
        while not self.stopped.wait(5):
            try:self.sample()
            except Exception:continue # watchdog sees heartbeat stop, no raw credentials in logs
    def close(self):self.stopped.set();self.thread.join(timeout=2)
