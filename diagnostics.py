"""Bounded, account-scoped operational diagnostics. Never collect raw vendor logs."""
from collections import deque
import json
import math
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time

import health
import runtime_health

EVENTS={'source_started','source_closed','connection_lost','connection_failed','connection_retry','camera_state','card_requested','card_attempt','card_attempt_result','card_result','person_detected','detection_failed','account_connected','account_disconnected'}
WORDS=set('sd_frames sd_requested recording fetching interrupted no_frames invalid_video encoder_busy encoding_timeout video_tools conversion balanced original hd fhd sent idle queue_full receiving paused retrying queued connecting waiting stopped done partial ready failed live sd sd_backup sd_partial automatic backup list unavailable invalid_video video_stale video_timeout video_native video_decode video_resources video_stopped video_busy video_idle authentication protocol input video_configuration no_recording timestamp_unverified list_unavailable list_incomplete recording_unavailable recording_gap archive_fragmented seek_unavailable playback_unavailable list_request_rejected list_response_unsupported economy_or_disabled cooldown busy adapter_update_required disk_space partial_saved bounded_export'.split())
NUMBERS={'attempt','max_attempts','frames','duration','age_seconds','definition','width','stage','list_kind','records','clock_callbacks','clock_unit','clock_delta_ms','frame_rejection','received_seconds','requested_seconds','fps','record_id','partial','analysis_ms','people','expected_seconds','probe_frames','height','load1','record_setup_ms'}
IDENTIFIER=re.compile(r'[A-Za-z0-9_:\-]{1,80}\Z')


def fields(values):
    result={}
    for key,value in values.items():
        if key in NUMBERS and type(value) in (bool,int,float) and math.isfinite(value):result[key]=value
        elif key in ('code','state','status','action','source') and isinstance(value,str) and value in WORDS:result[key]=value
    return result


def identifier(value):
    return value if isinstance(value,str) and IDENTIFIER.fullmatch(value) else 'unknown-camera'


def label(value):
    return ''.join(c for c in str(value)[:100] if c.isprintable())


class Diagnostics:
    def __init__(self,store):
        self.store=store;self.started=time.monotonic();self.pending=queue.Queue(maxsize=512)
        self.lock=threading.Lock();self.recent=deque(maxlen=1000);self.stopped=threading.Event()
        self.dropped=0;self.write_errors=0
        try:
            value=subprocess.run(['git','rev-parse','--short','HEAD'],cwd=__import__('pathlib').Path(__file__).parent,
                capture_output=True,text=True,timeout=2).stdout.strip()
            self.version=value if re.fullmatch('[0-9a-f]{7,40}',value) else 'unknown'
        except (OSError,subprocess.TimeoutExpired):self.version='unknown'
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def record(self,owner,camera,event,**values):
        if not owner or event not in EVENTS or self.stopped.is_set():return
        if event in ('connection_lost','connection_failed','detection_failed') or (event=='card_result' and values.get('status') not in ('done','partial','cooldown','busy','economy_or_disabled')):
            try:values['load1']=round(os.getloadavg()[0],2)
            except (OSError,AttributeError):pass
        row={'owner':owner,'camera':identifier(camera),'event':event,'created':time.time(),'details':fields(values)}
        with self.lock:self.recent.append(row)
        try:self.pending.put_nowait(row)
        except queue.Full:self.dropped+=1

    @staticmethod
    def table(db):
        db.execute('CREATE TABLE IF NOT EXISTS diagnostic_events(id INTEGER PRIMARY KEY,owner TEXT NOT NULL,camera TEXT NOT NULL,created REAL NOT NULL,event TEXT NOT NULL,details TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS diagnostic_owner_time ON diagnostic_events(owner,created)')

    def run(self):
        while not self.stopped.is_set() or not self.pending.empty():
            try:first=self.pending.get(timeout=.2)
            except queue.Empty:continue
            batch=[first]
            for _ in range(31):
                try:batch.append(self.pending.get_nowait())
                except queue.Empty:break
            try:
                with self.store.guard,self.store.connect() as db:
                    self.table(db)
                    db.executemany('INSERT INTO diagnostic_events(owner,camera,created,event,details) VALUES (?,?,?,?,?)',
                        [(r['owner'],r['camera'],r['created'],r['event'],json.dumps(r['details'])) for r in batch])
                    db.execute('DELETE FROM diagnostic_events WHERE created<?',(time.time()-7*86400,))
                    db.execute('DELETE FROM diagnostic_events WHERE id NOT IN (SELECT id FROM diagnostic_events ORDER BY id DESC LIMIT 10000)')
            except Exception:self.write_errors+=1
            finally:
                for _ in batch:self.pending.task_done()

    def history(self,owner):
        try:
            with self.store.guard,self.store.connect() as db:
                self.table(db)
                rows=db.execute('SELECT camera,created,event,details FROM diagnostic_events WHERE owner=? AND created>? ORDER BY id DESC LIMIT 120',
                    (owner,time.time()-7*86400)).fetchall()
                counts=db.execute("SELECT camera,event,COALESCE(json_extract(details,'$.status'),'') AS status,COALESCE(json_extract(details,'$.action'),'') AS action,COUNT(*) AS total FROM diagnostic_events WHERE owner=? AND created>? GROUP BY camera,event,status,action",(owner,time.time()-7*86400)).fetchall()
            events=[dict(camera=r['camera'],created=r['created'],event=r['event'],details=fields(json.loads(r['details']))) for r in rows if r['event'] in EVENTS]
            return events,[dict(r) for r in counts]
        except Exception:
            with self.lock:rows=[r for r in self.recent if r['owner']==owner][-120:]
            return [{k:v for k,v in r.items() if k!='owner'} for r in reversed(rows)],[]

    def card_history(self,owner):
        # Keep SD evidence available even after 120 newer connection events.
        allowed=('card_requested','card_attempt','card_attempt_result','card_result')
        try:
            with self.store.guard,self.store.connect() as db:
                self.table(db)
                rows=db.execute('SELECT camera,created,event,details FROM diagnostic_events WHERE owner=? AND created>? AND event IN (?,?,?,?) ORDER BY id DESC LIMIT 40',
                    (owner,time.time()-7*86400,*allowed)).fetchall()
            return [dict(camera=r['camera'],created=r['created'],event=r['event'],details=fields(json.loads(r['details']))) for r in rows]
        except Exception:
            with self.lock:rows=[r for r in self.recent if r['owner']==owner and r['event'] in allowed][-40:]
            return [{k:v for k,v in r.items() if k!='owner'} for r in reversed(rows)]

    def build(self,server,owner,devices,client):
        now=time.monotonic();prefs=self.store.preferences(owner);names={d['id']:label(d['name']) for d in devices}
        sources=[s for s in server.stream_snapshot() if getattr(s,'report_owner',None)==owner and not s.stopped.is_set()]
        active={s.device_id:s for s in sources}
        cameras=[]
        with server.background.lock:
            for device in devices:
                camera=device['id'];entry=server.background.entries.get((owner,camera));native=entry.native if entry else active.get(camera)
                stamp=entry.last_frame if entry else getattr(native,'last_frame',None)
                state=('paused' if entry and not entry.window(server.background.clock()) else
                    'retrying' if entry and native is None and entry.message else
                    'stopped' if native is None else 'receiving' if stamp is not None and now-stamp<=3 and not native.stopped.is_set() else
                    'queued' if getattr(native,'connect_started',None) is None else 'connecting')
                camera_health=health.snapshot(native) if native else {}
                detection=camera_health.get('detection',{})
                cameras.append(dict(id=identifier(camera),name=names[camera],source_count=sum(s.device_id==camera for s in sources),state=state,economy=camera in prefs.get('economy_ids',[]),
                    detection=camera in prefs.get('detection_ids',[]),last_frame_age_seconds=round(max(0,now-stamp),1) if stamp is not None else None,
                    fps=camera_health.get('fps',0),resolution=camera_health.get('resolution') or (health.jpeg_size(entry.image) if entry and entry.image else None),definition=camera_health.get('definition',entry.definition if entry else None),
                    detection_health={k:v for k,v in detection.items() if k in ('people','analysis_ms','age_seconds','error') and type(v) in (int,float,bool)},
                    retry_in_seconds=round(max(0,entry.retry_at-server.background.clock()),1) if entry else 0,
                    next_window_seconds=round(entry.next_open(server.background.clock())) if entry else 0,
                    error_code=getattr(getattr(native,'error',None),'kind',None) if getattr(getattr(native,'error',None),'kind',None) in WORDS else None))
        events,counts=self.history(owner)
        card_events=self.card_history(owner)
        for event in card_events:event['name']=names.get(event['camera'],event['camera'])
        for event in events:event['name']=names.get(event['camera'],event['camera'])
        videos=[]
        for row in self.store.videos(owner):
            item={k:row[k] for k in ('id','created','duration','pre_roll','frame_count','capture_fps','max_gap','sd_gap_seconds','archive_start','archive_end')}
            item.update(camera=identifier(row['camera']),name=label(row['name']))
            for key in ('status','source','archive_status','reason'):
                value=row[key]
                item[key]=value if value=='' or value in WORDS or (key=='reason' and value.startswith('archive_') and value[8:] in WORDS) else 'other'
            item['archive_diagnostic']=fields(row['archive_diagnostic']);videos.append(item)
        with self.store.guard,self.store.connect() as db:
            people=db.execute("SELECT COUNT(*),MAX(created) FROM events WHERE owner=? AND kind='person'",(owner,)).fetchone()
        disk=shutil.disk_usage(self.store.root)
        memory={}
        try:
            from pathlib import Path
            for line in Path('/proc/meminfo').read_text().splitlines():
                key,value=line.split(':',1)
                if key in ('MemTotal','MemAvailable'):memory[key+'_mib']=round(int(value.split()[0])/1024)
        except (OSError,ValueError):pass
        from runtime_policy import FIRST_FRAME_TIMEOUT,STALE_TIMEOUT,QUEUE_TIMEOUT,startup_parallelism,encoder_parallelism
        from video import readiness as video_readiness
        adapter_ready=video_readiness()[0]
        telegram=server.telegram.status(owner)
        telegram_result='sent' if telegram['message'].startswith('Último alerta enviado') else 'failed' if telegram['message'].startswith('Envio falhou') else 'queue_full' if telegram['message'].startswith('Fila') else 'idle'
        browser={}
        if isinstance(client,dict):
            for key in ('width','height'):
                if type(client.get(key)) is int and 0<client[key]<20000:browser[key]=client[key]
            for key in ('browser','timezone'):
                value=client.get(key)
                if key=='browser' and isinstance(value,str) and re.fullmatch(r'(?:Chrome|Firefox|Edg|Safari)/[0-9.]{1,24}|unknown',value):browser[key]=value
                if key=='timezone' and isinstance(value,str) and len(value)<80:
                    try:
                        from zoneinfo import ZoneInfo
                        ZoneInfo(value);browser[key]=value
                    except (ValueError,KeyError):pass
            browser['cameras']=[]
            for row in client.get('cameras',[])[:14] if isinstance(client.get('cameras'),list) else []:
                if isinstance(row,dict) and row.get('id') in names:
                    camera={k:row[k] for k in ('mjpeg','error','reconnecting') if type(row.get(k)) is bool}
                    camera['id']=identifier(row['id']);camera['state']=row.get('state') if isinstance(row.get('state'),str) and row.get('state') in WORDS else 'other'
                    browser['cameras'].append(camera)
        findings=[];statistics=[]
        for camera in cameras:
            rows=[r for r in counts if r['camera']==camera['id']]
            total=lambda event,status=None:sum(r['total'] for r in rows if r['event']==event and (status is None or r.get('status')==status))
            starts=total('source_started');lost=total('connection_lost');opening_failed=total('connection_failed')
            card_rows=[r for r in rows if r['event']=='card_result' and r.get('action')!='list' and r.get('status') not in ('busy','cooldown','economy_or_disabled')]
            complete=sum(r['total'] for r in card_rows if r.get('status')=='done')
            partial=sum(r['total'] for r in card_rows if r.get('status')=='partial')
            jobs=sum(r['total'] for r in card_rows)
            statistics.append(dict(camera=camera['id'],name=camera['name'],connections_started=starts,unexpected_drops=lost,initial_open_failures=opening_failed,
                card_attempts=total('card_attempt'),card_jobs=jobs,card_complete=complete,card_partial=partial,
                card_complete_percent=round(complete/jobs*100,1) if jobs else None))
            if camera['source_count']>1:findings.append(dict(camera=camera['id'],code='multiple_sources',detail=f"{camera['source_count']} fontes simultâneas para esta câmera; verificar múltiplas visualizações e consumo do servidor."))
            if opening_failed>=3:findings.append(dict(camera=camera['id'],code='repeated_open_failures',detail=f'{opening_failed} aberturas sem receber o primeiro quadro. Comparar negociação P2P e carga do servidor.'))
            if lost>=3:findings.append(dict(camera=camera['id'],code='repeated_drops',detail=f'{lost} quedas registradas; comparar conexão, qualidade escolhida e carga do servidor.'))
            if camera['state']=='receiving' and camera['fps']<4:findings.append(dict(camera=camera['id'],code='low_received_fps',detail=f"FPS recebido neste instante: {camera['fps']}. Comparar com qualidade e carga do servidor."))
            if jobs>=3 and complete/jobs<.5:findings.append(dict(camera=camera['id'],code='low_card_completion',detail=f'{complete} cópias completas e {partial} parciais em {jobs} trabalhos. Os eventos detalham tentativas e falhas.'))
        if hasattr(os,'getloadavg') and os.getloadavg()[0]>(os.cpu_count() or 1):findings.append(dict(code='server_pressure',detail='Carga de trabalho elevada em relação ao número de CPUs; correlacionar com aberturas e cópias do cartão.'))
        if disk.free<1024**3:findings.append(dict(code='low_disk',detail='Menos de 1 GiB livre para gravações e arquivos temporários.'))
        return dict(format='DCS-diagnostics-v1',generated_at=time.time(),version=self.version,uptime_seconds=round(now-self.started),
            scope='Esta conta; sem senhas, tokens, cookies, imagens ou logs brutos do fornecedor. Histórico: até 7 dias/10000 eventos globais; últimos 120 desta conta e até 40 eventos do cartão.',
            system=dict(runtime=runtime_health.snapshot(),os=platform.system(),python=sys.version.split()[0],cpu_count=os.cpu_count(),architecture=platform.machine(),webcam_device_count=sum(bool(d.get('local')) for d in devices),load_average=list(os.getloadavg()) if hasattr(os,'getloadavg') else [],
                memory=memory,disk_free_mib=round(disk.free/1024**2),disk_total_mib=round(disk.total/1024**2),ffmpeg=bool(shutil.which('ffmpeg')),ffprobe=bool(shutil.which('ffprobe')),wine=bool(shutil.which('wine') or shutil.which('wine64'))),
            monitoring=dict(native_source_count=len(sources),startup_parallelism=startup_parallelism(),encoder_parallelism=encoder_parallelism(),first_frame_timeout=FIRST_FRAME_TIMEOUT,stale_timeout=STALE_TIMEOUT,queue_timeout=QUEUE_TIMEOUT,native_adapter_ready=adapter_ready,background_worker=bool(server.background.thread and server.background.thread.is_alive()),detection_ready=bool(server.reports.ready),
                detection_worker=bool(server.reports.thread and server.reports.thread.is_alive()),log_queue=self.pending.qsize(),log_dropped=self.dropped,log_write_errors=self.write_errors),
            telegram=dict(enabled=telegram['enabled'],configured=telegram['configured'],last_result=telegram_result),
            card_queue_size=server.archive.queue.qsize(),learning=dict(method='Estatísticas do histórico disponível; sem alteração automática do código ou da qualidade das câmeras.',statistics=statistics,findings=findings),cameras=cameras,people_reports=dict(count=people[0],last_created=people[1]),recent_videos=videos,events=events,card_events=card_events,event_counts=counts,browser=browser)

    def close(self):
        self.stopped.set();self.thread.join(timeout=3)
