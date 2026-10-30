"""Best-effort SD playback export; validated replacement only, never delete fallback."""
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import secrets
from types import SimpleNamespace
import threading
import time

import video

MAX_ARCHIVE_BYTES = 160 * 1024 * 1024


class CameraArchive:
    def __init__(self, store, slots):
        self.store,self.slots=store,slots
        self.queue=queue.Queue(maxsize=12)
        self.stopped=threading.Event()
        self.lock=threading.Lock();self.process=None
        self.failed={}
        self.jobs={}
        # Remove only stale private export directories from interrupted prior runs.
        for path in self.store.root.glob('sd-export-*'):
            try:
                if not path.is_symlink() and path.is_dir() and time.time()-path.stat().st_mtime>900:shutil.rmtree(path)
            except OSError:pass
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def enqueue(self, record_id, stream, start, end):
        if self.stopped.is_set() or not getattr(stream,'archive_account',None):return
        try:
            self.queue.put_nowait((record_id,stream,start,end,None,'automatic'))
        except queue.Full:self.status(record_id,'busy')

    def submit(self,owner,account,camera,start,end,action,monitor_until=float('inf')):
        stream=SimpleNamespace(report_owner=owner,device_id=camera['id'],report_name=camera['name'],
            report_detect=True,archive_account=account,monitor_until=monitor_until)
        key=secrets.token_urlsafe(18)
        record_id=None
        with self.lock:
            self.jobs={k:v for k,v in self.jobs.items() if time.monotonic()-v['created']<3600}
            if len(self.jobs)>=32:raise RuntimeError('busy')
            self.jobs[key]={'owner':owner,'created':time.monotonic(),'status':'queued','records':[],
                'record_id':None,'stream':stream}
        try:
            if action=='backup':
                import uuid
                record_id=self.store.video_add(owner,camera['id'],camera['name'],uuid.uuid4().hex+'.mp4')
                self.store.video_details(record_id,source='sd_requested',archive_status='queued')
                self.job_update(key,record_id=record_id)
            self.queue.put_nowait((record_id,stream,start,end,key,action))
        except queue.Full:
            if record_id:self.store.video_finish(record_id,'failed',0,'archive_busy')
            self.job_update(key,status='busy')
        except Exception:
            self.job_update(key,status='unavailable')
            if record_id:self.store.video_finish(record_id,'failed',0,'archive_unavailable')
            raise
        return key

    def job_update(self,key,**values):
        if key:
            with self.lock:
                if key in self.jobs:self.jobs[key].update(values)

    def job(self,owner,key):
        with self.lock:
            value=self.jobs.get(key)
            if not value or value['owner']!=owner:return None
            return {name:value[name] for name in ('status','records','record_id')}

    def cancel(self,owner):
        with self.lock:
            for value in self.jobs.values():
                if value['owner']==owner:value['stream'].report_detect=False

    def configure_economy(self,owner,economy_ids,background):
        with self.lock:
            for value in self.jobs.values():
                stream=value['stream']
                if value['owner']==owner and value['status'] in ('queued','running') and stream.device_id in economy_ids:
                    stream.monitor_until=min(stream.monitor_until,background.deadline(owner,stream.device_id))

    def list_records(self,stream,start,end,directory):
        if not video.readiness()[0]:raise RuntimeError('adapter_update_required')
        account=stream.archive_account
        payload='\n'.join((account.access_id,account.access_token,stream.device_id,str(round(start*1000)),str(round(end*1000))))+'\n'
        if any(c in v for v in (account.access_id,account.access_token,stream.device_id) for c in '\r\n\0'):raise RuntimeError('unavailable')
        env=dict(os.environ,WINEDEBUG='-all',WINEDLLOVERRIDES='mscoree,mshtml=',WINEPREFIX=str(video.ROOT/'.local'/'wine-video'))
        # A bounded native listing can exceed a pipe's capacity; spool it to disk
        # so the child cannot deadlock while the parent waits for completion.
        output=open(Path(directory)/'listing.txt','w+b')
        try:
            child=self.launch([shutil.which('wine') or shutil.which('wine64'),str(video.NATIVE/'yoosee_snapshot.exe'),'--list'],
                cwd=directory,env=env,stdin=subprocess.PIPE,stdout=output)
        except Exception:
            output.close();raise
        try:
            child.stdin.write(payload.encode());child.stdin.close();deadline=time.monotonic()+35
            while child.poll() is None:
                if not self.allowed(stream) or time.monotonic()>deadline:raise RuntimeError('list_unavailable')
                self.stopped.wait(.2)
            output.seek(0);data=output.read(65536)
            if child.returncode==37:raise RuntimeError('list_request_rejected')
            if child.returncode==38:raise RuntimeError('list_response_unsupported')
            if child.returncode or not data.startswith(b'SDLIST\n'):raise RuntimeError('list_unavailable')
            records=[]
            for line in data.splitlines()[1:513]:
                match=re.fullmatch(rb'([0-9]{13}) ([0-9]{13})',line)
                if not match:raise RuntimeError('list_unavailable')
                begin,finish=(int(v)/1000 for v in match.groups())
                if begin<finish and finish>start and begin<end:records.append({'start':begin,'end':finish})
            return sorted(records,key=lambda row:row['start'])
        finally:
            self.kill(child);child.wait(timeout=5)
            if child.stdin and not child.stdin.closed:child.stdin.close()
            output.close()
            with self.lock:self.process=None

    def status(self, record_id, status):
        with self.store.guard,self.store.connect() as db:
            db.execute('UPDATE videos SET archive_status=? WHERE id=?',(status,record_id))

    def allowed(self, stream, budget=0):
        return (not self.stopped.is_set() and getattr(stream,'report_detect',False)
                and time.monotonic()+budget<getattr(stream,'monitor_until',float('inf')))

    def launch(self,args,**kwargs):
        with self.lock:
            if self.stopped.is_set():raise RuntimeError('stopped')
            self.process=subprocess.Popen(args,start_new_session=True,stderr=subprocess.DEVNULL,**kwargs)
            return self.process

    def export(self, stream, start, end, directory):
        if not video.readiness()[0]:raise RuntimeError('adapter_update_required')
        if not self.allowed(stream,end-start+40):return None
        account=stream.archive_account
        payload='\n'.join((account.access_id,account.access_token,stream.device_id,str(round(start*1000)),str(round(end*1000))))+'\n'
        if any(c in v for v in (account.access_id,account.access_token,stream.device_id) for c in '\r\n\0'):return None
        env=dict(os.environ,WINEDEBUG='-all',WINEDLLOVERRIDES='mscoree,mshtml=',WINEPREFIX=str(video.ROOT/'.local'/'wine-video'))
        process=self.launch([shutil.which('wine') or shutil.which('wine64'),str(video.NATIVE/'yoosee_snapshot.exe'),'--archive'],
            cwd=directory,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        try:
            process.stdin.write(payload.encode());process.stdin.close()
            deadline=time.monotonic()+end-start+40
            output=Path(directory)/'archive.mp4'
            while process.poll() is None:
                if (not self.allowed(stream) or time.monotonic()>deadline or shutil.disk_usage(directory).free<256*1024*1024
                    or (output.exists() and output.stat().st_size>MAX_ARCHIVE_BYTES)):
                    raise RuntimeError('bounded_export')
                self.stopped.wait(.25)
            metadata=process.stdout.read(512)
            match=re.fullmatch(rb'SDTIME ([0-9]{13}) ([0-9]{13})\n',metadata)
            if process.returncode==31:raise RuntimeError('no_recording')
            if process.returncode==33:raise RuntimeError('timestamp_unverified')
            if process.returncode==34:raise RuntimeError('list_unavailable')
            if process.returncode==35:raise RuntimeError('seek_unavailable')
            if process.returncode==36:raise RuntimeError('playback_unavailable')
            if process.returncode==37:raise RuntimeError('list_request_rejected')
            if process.returncode==38:raise RuntimeError('list_response_unsupported')
            if process.returncode or not output.is_file() or output.stat().st_size>MAX_ARCHIVE_BYTES:return None
            if not match:raise RuntimeError('timestamp_unverified')
            first,last=(int(value)/1000 for value in match.groups())
            if not start<=first<=start+5 or not end-3<=last<=end+5:raise RuntimeError('timestamp_unverified')
            return output,round(max(0,min(5,start+5-first)),2)
        finally:
            self.kill(process);process.wait(timeout=5)
            if process.stdin and not process.stdin.closed:process.stdin.close()
            if process.stdout:process.stdout.close()
            with self.lock:self.process=None

    def replace(self, record_id, owner, path, desired_duration, pre_roll=0,allow_empty=False):
        # Decode only if the original codec needs browser compatibility. Never invent FPS.
        probe=subprocess.run([shutil.which('ffprobe'),'-v','error','-read_intervals','0%+1','-count_frames','-show_entries','stream=codec_type,codec_name,nb_read_frames:format=duration','-of','json',str(path)],capture_output=True,timeout=10)
        info=json.loads(probe.stdout) if probe.returncode==0 else {}
        duration=float(info.get('format',{}).get('duration',0))
        streams=[s for s in info.get('streams',[]) if s.get('codec_type')=='video']
        if (not streams or int(streams[0].get('nb_read_frames','0'))<1
            or duration<desired_duration-10 or duration>desired_duration+10):return False
        target=self.store.video(owner,record_id)
        if target is None and not allow_empty:return False
        if shutil.disk_usage(path.parent).free<256*1024*1024:raise RuntimeError('disk_space')
        prepared=path.parent/'ready.mp4'
        codec=['-c:v','copy'] if streams[0]['codec_name']=='h264' else ['-c:v','libx264','-threads','1','-preset','veryfast','-crf','22']
        process=self.launch([shutil.which('ffmpeg'),'-v','error','-y','-threads','1','-i',str(path),'-map','0:v:0','-an',*codec,'-movflags','+faststart',str(prepared)],stdout=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+90
            while process.poll() is None:
                if self.stopped.wait(.25) or time.monotonic()>deadline or (prepared.exists() and prepared.stat().st_size>MAX_ARCHIVE_BYTES):raise RuntimeError('conversion')
                if shutil.disk_usage(path.parent).free<256*1024*1024:raise RuntimeError('disk_space')
            if process.returncode or not prepared.exists() or prepared.stat().st_size>MAX_ARCHIVE_BYTES:return False
            if shutil.disk_usage(path.parent).free<256*1024*1024:raise RuntimeError('disk_space')
            # Atomically switch the filename in SQLite. Existing viewers can finish the old file.
            import uuid
            filename=uuid.uuid4().hex+'.mp4'
            with self.store.guard,self.store.connect() as db:
                row=db.execute('SELECT filename FROM videos WHERE id=? AND owner=?',(record_id,owner)).fetchone()
                if not row:return False
                destination=self.store._video_path(filename)
                destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                os.chmod(prepared,0o600);prepared.replace(destination)
                status='ready' if duration>=desired_duration-1 else 'partial'
                try:db.execute("UPDATE videos SET filename=?,duration=?,status=?,reason='',source=?,archive_status='ready',pre_roll=? WHERE id=? AND owner=?",(filename,round(duration,2),status,'sd_backup' if allow_empty else 'sd',0 if allow_empty else pre_roll,record_id,owner))
                except Exception:destination.unlink(missing_ok=True);raise
            if target:target.unlink(missing_ok=True)
            return True
        finally:
            self.kill(process);process.wait(timeout=5)
            with self.lock:self.process=None

    def run(self):
        while not self.stopped.is_set():
            try:record_id,stream,start,end,key,action=self.queue.get(timeout=.5)
            except queue.Empty:continue
            acquired=False
            try:
                camera=(stream.report_owner,stream.device_id)
                budget=35 if action=='list' else end-start+40
                if not self.allowed(stream,budget):raise RuntimeError('economy_or_disabled')
                if action=='automatic' and time.monotonic()-self.failed.get(camera,-1e9)<600:raise RuntimeError('cooldown')
                acquired=self.slots.acquire(blocking=False)
                if not acquired:raise RuntimeError('busy')
                if record_id:self.status(record_id,'fetching')
                self.job_update(key,status='running')
                with tempfile.TemporaryDirectory(dir=self.store.root,prefix='sd-export-') as directory:
                    if action=='list':
                        records=self.list_records(stream,start,end,directory)
                        self.job_update(key,status='done',records=records)
                    else:
                        result=self.export(stream,start,end,directory)
                        if not result or not self.allowed(stream) or not self.replace(record_id,stream.report_owner,result[0],end-start,result[1],allow_empty=action=='backup'):
                            raise RuntimeError('unavailable')
                        self.job_update(key,status='done')
                self.failed={k:v for k,v in self.failed.items() if time.monotonic()-v<600}
            except Exception as error:
                known=str(error) if isinstance(error,RuntimeError) else ''
                status=known if known in ('adapter_update_required','no_recording','timestamp_unverified','disk_space','list_unavailable',
                    'seek_unavailable','playback_unavailable','list_request_rejected','list_response_unsupported','economy_or_disabled','cooldown','busy') else 'unavailable'
                try:
                    if record_id:self.status(record_id,status)
                    if action=='backup' and record_id:self.store.video_finish(record_id,'failed',0,'archive_'+status)
                    self.job_update(key,status=status)
                    if action=='automatic' and status not in ('economy_or_disabled','cooldown','busy'):
                        self.failed[(stream.report_owner,stream.device_id)]=time.monotonic()
                except Exception:pass
            finally:
                if acquired:self.slots.release()
                self.queue.task_done()

    @staticmethod
    def kill(process):
        if process.poll() is None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass

    def close(self):
        self.stopped.set()
        with self.lock:
            if self.process:self.kill(self.process)
        self.thread.join(timeout=3)
        while True:
            try:self.queue.get_nowait();self.queue.task_done()
            except queue.Empty:break
