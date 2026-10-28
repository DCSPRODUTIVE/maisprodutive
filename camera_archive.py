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
        # Remove only stale private export directories from interrupted prior runs.
        for path in self.store.root.glob('sd-export-*'):
            try:
                if not path.is_symlink() and path.is_dir() and time.time()-path.stat().st_mtime>900:shutil.rmtree(path)
            except OSError:pass
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def enqueue(self, record_id, stream, start, end):
        if self.stopped.is_set() or not getattr(stream,'archive_account',None):return
        try:
            self.queue.put_nowait((record_id,stream,start,end))
        except queue.Full:self.status(record_id,'busy')

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

    def replace(self, record_id, owner, path, desired_duration, pre_roll=0):
        # Decode only if the original codec needs browser compatibility. Never invent FPS.
        probe=subprocess.run([shutil.which('ffprobe'),'-v','error','-read_intervals','0%+1','-count_frames','-show_entries','stream=codec_type,codec_name,nb_read_frames:format=duration','-of','json',str(path)],capture_output=True,timeout=10)
        info=json.loads(probe.stdout) if probe.returncode==0 else {}
        duration=float(info.get('format',{}).get('duration',0))
        streams=[s for s in info.get('streams',[]) if s.get('codec_type')=='video']
        if (not streams or int(streams[0].get('nb_read_frames','0'))<1
            or duration<desired_duration-10 or duration>desired_duration+10):return False
        target=self.store.video(owner,record_id)
        if target is None:return False
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
                os.chmod(prepared,0o600);prepared.replace(destination)
                status='ready' if duration>=desired_duration-1 else 'partial'
                try:db.execute("UPDATE videos SET filename=?,duration=?,status=?,reason='',source='sd',archive_status='ready',pre_roll=? WHERE id=? AND owner=?",(filename,round(duration,2),status,pre_roll,record_id,owner))
                except Exception:destination.unlink(missing_ok=True);raise
            target.unlink(missing_ok=True)
            return True
        finally:
            self.kill(process);process.wait(timeout=5)
            with self.lock:self.process=None

    def run(self):
        while not self.stopped.is_set():
            try:record_id,stream,start,end=self.queue.get(timeout=.5)
            except queue.Empty:continue
            acquired=False
            try:
                key=(stream.report_owner,stream.device_id)
                if not self.allowed(stream,end-start+40):self.status(record_id,'economy_or_disabled');continue
                if time.monotonic()-self.failed.get(key,-1e9)<600:self.status(record_id,'cooldown');continue
                acquired=self.slots.acquire(blocking=False)
                if not acquired:self.status(record_id,'busy');continue
                self.status(record_id,'fetching')
                with tempfile.TemporaryDirectory(dir=self.store.root,prefix='sd-export-') as directory:
                    result=self.export(stream,start,end,directory)
                    if not result or not self.allowed(stream) or not self.replace(record_id,stream.report_owner,result[0],end-start,result[1]):
                        self.status(record_id,'unavailable');self.failed[key]=time.monotonic()
                self.failed={k:v for k,v in self.failed.items() if time.monotonic()-v<600}
            except Exception as error:
                # Provider exceptions can contain account credentials. Persist fixed categories only.
                known=str(error) if isinstance(error,RuntimeError) else ''
                status=known if known in ('adapter_update_required','no_recording','timestamp_unverified','disk_space') else 'unavailable'
                try:self.status(record_id,status);self.failed[(stream.report_owner,stream.device_id)]=time.monotonic()
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
