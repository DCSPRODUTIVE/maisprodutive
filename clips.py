"""Record bounded 2-minute, silent MP4 clips from existing camera frames only."""
import json
import os
from pathlib import Path
from frame_buffer import PRE_ROLL
import shutil
import signal
import subprocess
import threading
import time
import uuid

DURATION = 120
FPS = 10
MIN_FREE = 256 * 1024 * 1024
MAX_BYTES = 96 * 1024 * 1024


class RecordingService:
    def __init__(self, store, archive=None):
        self.store = store
        self.archive = archive
        self.lock = threading.Lock()
        self.active = {}
        self.last_started = {}
        self.closed = False

    def trigger(self, stream):
        key = (stream.report_owner, stream.device_id)
        with self.lock:
            if self.closed or key in self.active or len(self.active)>=12 or not getattr(stream, 'report_detect', False):
                return
            now=time.monotonic()
            if now-self.last_started.get(key,0)<60:return
            self.last_started={k:v for k,v in self.last_started.items() if now-v<600}
            self.last_started[key]=now
            recorder = Recorder(self.store, stream, lambda: self.finished(key), archive=self.archive)
            self.active[key] = recorder
            recorder.start()

    def finished(self, key):
        with self.lock:
            self.active.pop(key, None)

    def close(self):
        with self.lock:
            self.closed = True
            active = list(self.active.values())
        for recorder in active:
            recorder.stop()
        deadline = time.monotonic()+10
        for recorder in active:
            recorder.thread.join(timeout=max(0, deadline-time.monotonic()))


class Recorder:
    def __init__(self, store, stream, on_close, archive=None):
        self.store, self.stream, self.on_close = store, stream, on_close
        self.archive=archive
        self.triggered=time.monotonic()
        self.wall_trigger=time.time()
        with stream.condition:
            history=getattr(stream,'history',None)
            self.pre_frames=history.snapshot(self.triggered) if history else []
        self.pre_roll=min(PRE_ROLL,max(0,self.triggered-self.pre_frames[0][0])) if self.pre_frames else 0
        self.stopped = threading.Event()
        self.process = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopped.set()
        process = self.process
        if process and process.poll() is None:
            # Let the worker close stdin and finalize MP4 before forced cleanup.
            timer=threading.Timer(3, lambda: self.kill(process))
            timer.daemon=True;timer.start()

    def run(self):
        filename = uuid.uuid4().hex+'.mp4'
        directory = self.store.root/'videos'
        temporary = directory/(filename+'.part.mp4')
        final = directory/filename
        record_id = None
        watchdog = None
        process = None
        frames = 0
        interrupted = False
        reason = ''
        try:
            directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            record_id = self.store.video_add(self.stream.report_owner, self.stream.device_id, self.stream.report_name, filename)
            if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
                raise RuntimeError('video_tools')
            if shutil.disk_usage(directory).free < MIN_FREE:
                raise RuntimeError('disk_space')
            process = subprocess.Popen([shutil.which('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y',
                '-filter_threads','1','-threads','1','-f','image2pipe','-vcodec','mjpeg','-framerate',str(FPS),
                '-i','pipe:0','-an','-vf',"scale='min(1920,iw)':-2,format=yuv420p",
                '-c:v','libx264','-threads','1','-preset','ultrafast','-crf','22',
                '-movflags','+faststart',str(temporary)],stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            self.process=process
            # An encoder blocked on input/output cannot outlive the bounded recording.
            watchdog=threading.Timer(DURATION+PRE_ROLL+15,lambda: self.kill(process))
            watchdog.daemon=True;watchdog.start()
            # Replay the pre-event ring at its actual timeline, not one frame per source callback.
            if self.pre_frames:
                index=0;tick=self.pre_frames[0][0]
                while tick<self.triggered:
                    while index+1<len(self.pre_frames) and self.pre_frames[index+1][0]<=tick:index+=1
                    process.stdin.write(self.pre_frames[index][1]);frames+=1;tick+=1/FPS
                process.stdin.flush()
            self.pre_frames=[]
            started=time.monotonic();deadline=self.triggered+DURATION;next_frame=started
            while time.monotonic()<deadline:
                if (self.stopped.is_set() or self.stream.stopped.is_set() or not getattr(self.stream,'report_detect',False)
                        or time.monotonic() >= getattr(self.stream,'monitor_until',float('inf'))):
                    interrupted=True;reason='interrupted';break
                now=time.monotonic()
                if now<next_frame:
                    self.stopped.wait(min(.2,next_frame-now));continue
                with self.stream.condition:
                    image=self.stream.image
                    age=now-self.stream.last_frame if self.stream.last_frame is not None else 999
                if image and age<=3:
                    process.stdin.write(image);process.stdin.flush();frames+=1
                next_frame+=1/FPS
                if next_frame < time.monotonic()-1/FPS:next_frame=time.monotonic()+1/FPS
                if frames % 20 == 0 and (shutil.disk_usage(directory).free<MIN_FREE or (temporary.exists() and temporary.stat().st_size>MAX_BYTES)):
                    interrupted=True;reason='disk_space';break
            if process.stdin:
                try:process.stdin.close()
                except (OSError,ValueError):pass
            process.wait(timeout=8)
            if frames<1 or not temporary.exists():raise RuntimeError('no_frames')
            probe=subprocess.run([shutil.which('ffprobe'),'-v','error','-select_streams','v:0',
                '-show_entries','stream=codec_name:format=duration','-of','json',str(temporary)],
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=5)
            metadata=json.loads(probe.stdout) if probe.returncode==0 else {}
            duration=float(metadata.get('format',{}).get('duration',0))
            if not metadata.get('streams') or duration<=0:raise RuntimeError('invalid_video')
            os.chmod(temporary,0o600);temporary.replace(final)
            status='ready' if not interrupted and duration>=DURATION-1 else 'partial'
            self.store.video_finish(record_id,status,round(duration,2),reason)
            self.store.video_details(record_id,pre_roll=round(self.pre_roll,2),source='live')
            if self.archive and not interrupted:
                self.archive.enqueue(record_id,self.stream,self.wall_trigger-PRE_ROLL,self.wall_trigger+DURATION)
        except Exception as error:
            # Only fixed reason categories are persisted, never raw tool output.
            known=str(error) if isinstance(error,RuntimeError) else ''
            reason=known if known in ('video_tools','disk_space','no_frames','invalid_video') else 'recording_failed'
            if record_id is not None:
                try:self.store.video_finish(record_id,'failed',0,reason)
                except Exception:pass
        finally:
            if watchdog:watchdog.cancel()
            if process:
                if process.poll() is None:self.kill(process)
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:self.kill(process);process.wait(timeout=3)
                if process.stdin:
                    try:process.stdin.close()
                    except (OSError,ValueError):pass
            temporary.unlink(missing_ok=True)
            self.on_close()

    @staticmethod
    def kill(process):
        if process.poll() is not None:return
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
