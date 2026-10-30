"""Capture received JPEGs first; encode their actual timeline after capture."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid

from frame_buffer import PRE_ROLL
from runtime_policy import encoder_parallelism

DURATION = 120
FPS = 10  # compatibility: source target only; encoded frames use their actual timestamps
MIN_FREE = 256 * 1024 * 1024
MAX_BYTES = 96 * 1024 * 1024
ENCODERS = threading.BoundedSemaphore(encoder_parallelism())


class RecordingService:
    def __init__(self, store, archive=None):
        self.store,self.archive=store,archive
        self.lock=threading.Lock();self.active={};self.last_started={};self.closed=False

    def trigger(self, stream):
        key=(stream.report_owner,stream.device_id)
        with self.lock:
            if self.closed or key in self.active or len(self.active)>=12 or not getattr(stream,'report_detect',False):return
            now=time.monotonic()
            if now-self.last_started.get(key,0)<5:return
            self.last_started={k:v for k,v in self.last_started.items() if now-v<600}
            self.last_started[key]=now
            recorder=Recorder(self.store,stream,lambda:self.finished(key),archive=self.archive)
            self.active[key]=recorder;recorder.start()

    def finished(self,key):
        with self.lock:self.active.pop(key,None)

    def close(self):
        with self.lock:self.closed=True;active=list(self.active.values())
        for recorder in active:recorder.stop()
        deadline=time.monotonic()+10
        for recorder in active:recorder.thread.join(timeout=max(0,deadline-time.monotonic()))


class Recorder:
    def __init__(self,store,stream,on_close,archive=None):
        self.store,self.stream,self.on_close,self.archive=store,stream,on_close,archive
        self.triggered=time.monotonic();self.wall_trigger=time.time()
        with stream.condition:
            history=getattr(stream,'history',None)
            self.pre_frames=history.snapshot(self.triggered) if history else []
        self.stopped=threading.Event();self.process=None
        self.thread=threading.Thread(target=self.run,daemon=True)

    def start(self):self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.process:self.kill(self.process)

    def run(self):
        record_id=None;process=None;gate=False;temporary=None
        try:
            directory=self.store.root/'videos';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            filename=uuid.uuid4().hex+'.mp4';temporary=directory/(filename+'.part.mp4');final=directory/filename
            record_id=self.store.video_add(self.stream.report_owner,self.stream.device_id,self.stream.report_name,filename)
            if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):raise RuntimeError('video_tools')
            if shutil.disk_usage(directory).free<MIN_FREE:raise RuntimeError('disk_space')
            with tempfile.TemporaryDirectory(dir=directory,prefix='capture-') as staging:
                staging=Path(staging);timeline=[];size=0;last_stamp=-1.;last_image=None
                interrupted=False;reason=''
                def capture(stamp,image):
                    nonlocal size,last_stamp,last_image
                    if not image or stamp<=last_stamp:return
                    # Equal JPEGs add duration to the preceding frame; never invent motion.
                    if image==last_image:last_stamp=stamp;return
                    if size+len(image)>MAX_BYTES or shutil.disk_usage(directory).free<MIN_FREE:raise RuntimeError('disk_space')
                    path=staging/f'{len(timeline):06d}.jpg';path.write_bytes(image)
                    timeline.append((stamp,path.name));size+=len(image);last_stamp=stamp;last_image=image
                for stamp,image in self.pre_frames:capture(stamp,image)
                self.pre_frames=[]
                deadline=self.triggered+DURATION
                while time.monotonic()<deadline:
                    if (self.stopped.is_set() or self.stream.stopped.is_set() or not getattr(self.stream,'report_detect',False)
                        or time.monotonic()>=getattr(self.stream,'monitor_until',float('inf'))):
                        interrupted=True;reason='interrupted';break
                    with self.stream.condition:
                        stamp=self.stream.last_frame;image=self.stream.image
                        history=getattr(self.stream,'history',None)
                        batch=history.snapshot(time.monotonic()) if history else []
                    if batch:
                        for at,jpeg in batch:
                            if at>last_stamp:capture(at,jpeg)
                    elif stamp is not None and time.monotonic()-stamp<=3:capture(stamp,image)
                    self.stopped.wait(.04)
                ended=min(time.monotonic(),deadline)
                if not timeline:raise RuntimeError('no_frames')
                origin=timeline[0][0]
                pre_roll=round(max(0,min(PRE_ROLL,self.triggered-origin)),2)
                lines=['ffconcat version 1.0']
                max_gap=0.
                for index,(stamp,name) in enumerate(timeline):
                    until=timeline[index+1][0] if index+1<len(timeline) else max(stamp+.04,ended)
                    gap=max(.001,until-stamp);max_gap=max(max_gap,gap)
                    lines.extend([f"file '{name}'",'option framerate 1000',f'duration {gap:.6f}'])
                lines.extend([f"file '{timeline[-1][1]}'",'option framerate 1000'])
                manifest=staging/'frames.txt';manifest.write_text('\n'.join(lines)+'\n')
                # JPEG capture does not compete with multiple live H.264 encoders.
                wait_until=time.monotonic()+120
                while not gate:
                    if self.stopped.is_set() or time.monotonic()>wait_until:raise RuntimeError('encoder_busy')
                    gate=ENCODERS.acquire(timeout=.25)
                process=subprocess.Popen([shutil.which('ffmpeg'),'-v','error','-y','-threads','1','-filter_threads','1',
                    '-protocol_whitelist','file,pipe','-f','concat','-safe','0','-i',str(manifest),'-an',
                    '-vf',"scale='min(1280,iw)':-2,format=yuv420p",'-fps_mode','vfr','-c:v','libx264','-threads','1',
                    '-preset','veryfast','-crf','23','-movflags','+faststart',str(temporary)],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
                self.process=process;encode_deadline=time.monotonic()+120
                while process.poll() is None:
                    if self.stopped.wait(.1) or time.monotonic()>encode_deadline:self.kill(process);raise RuntimeError('encoding_timeout')
                    if shutil.disk_usage(directory).free<MIN_FREE or (temporary.exists() and temporary.stat().st_size>MAX_BYTES):
                        self.kill(process);raise RuntimeError('disk_space')
                if process.returncode or not temporary.exists():raise RuntimeError('invalid_video')
                probe=subprocess.run([shutil.which('ffprobe'),'-v','error','-select_streams','v:0',
                    '-show_entries','stream=codec_name:format=duration','-of','json',str(temporary)],capture_output=True,timeout=10)
                data=json.loads(probe.stdout) if probe.returncode==0 else {};duration=float(data.get('format',{}).get('duration',0))
                if not data.get('streams') or duration<=0:raise RuntimeError('invalid_video')
                os.chmod(temporary,0o600);temporary.replace(final)
                self.store.video_finish(record_id,'partial' if interrupted else 'ready',round(duration,2),reason)
                self.store.video_details(record_id,pre_roll=pre_roll,source='live',
                    frame_count=len(timeline),capture_fps=round(len(timeline)/max(.001,ended-origin),2),max_gap=round(max_gap,2))
                if self.archive and not interrupted:self.archive.enqueue(record_id,self.stream,self.wall_trigger-PRE_ROLL,self.wall_trigger+DURATION)
        except Exception as error:
            known=str(error) if isinstance(error,RuntimeError) else ''
            reason=known if known in ('video_tools','disk_space','no_frames','invalid_video','encoder_busy','encoding_timeout') else 'recording_failed'
            if record_id is not None:
                try:self.store.video_finish(record_id,'failed',0,reason)
                except Exception:pass
        finally:
            if process:
                self.kill(process)
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:pass
            if gate:ENCODERS.release()
            if temporary:temporary.unlink(missing_ok=True)
            self.pre_frames=[];self.on_close()

    @staticmethod
    def kill(process):
        if process.poll() is None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
