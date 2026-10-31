"""Bounded fallback: encode SD playback using the camera's per-frame clock.

No inferred correction of a vendor MP4's missing seconds. Only validated, decoded
frames inside the requested interval may form a complete/partial copy.
"""
import re
import shutil
import subprocess
import os
import select
import time
from pathlib import Path

from clips import ENCODERS

MAX_STAGING=96*1024*1024
MIN_FREE=256*1024*1024
HEADER=re.compile(rb'DCSYUV1 ([0-9]{2,4}) ([0-9]{2,4}) ([0-9]{13}) ([0-9]{3,8})\n')


def read_frames(pipe,directory,start,end,convert):
    timeline=[];size=0;dimensions=None
    while len(timeline)<6000:
        line=pipe.readline(160)
        if not line:break
        match=HEADER.fullmatch(line)
        if not match:raise RuntimeError('timestamp_unverified')
        width,height,stamp,length=(int(x) for x in match.groups());stamp/=1000
        if not (16<=width<=4096 and 16<=height<=4096 and width%2==height%2==0 and length==width*height*3//2 and length<=16*1024*1024):
            raise RuntimeError('invalid_video')
        if not start<=stamp<end or (timeline and stamp<=timeline[-1][0]):raise RuntimeError('timestamp_unverified')
        if dimensions is not None and dimensions!=(width,height):break
        if timeline and stamp-timeline[-1][0]>2:break # keep only a contiguous prefix
        raw=bytearray()
        while len(raw)<length:
            chunk=pipe.read(length-len(raw))
            if not chunk:break
            raw.extend(chunk)
        if len(raw)!=length:break # interrupted final frame never enters the file
        jpeg=convert(bytes(raw),width,height)
        if not jpeg:raise RuntimeError('invalid_video')
        if size+len(jpeg)>MAX_STAGING or shutil.disk_usage(directory).free<MIN_FREE:break
        filename=f'{len(timeline):06d}.jpg'
        (Path(directory)/filename).write_bytes(jpeg)
        timeline.append((stamp,filename));size+=len(jpeg);dimensions=(width,height)
    if len(timeline)<2 or timeline[-1][0]-timeline[0][0]<1:raise RuntimeError('no_frames')
    return timeline


def convert_frame(raw,width,height):
    import cv2
    import numpy
    image=numpy.frombuffer(raw,dtype=numpy.uint8).reshape(height*3//2,width)
    image=cv2.cvtColor(image,cv2.COLOR_YUV2BGR_I420)
    ok,jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,94])
    return jpeg.tobytes() if ok else None


class BoundedPipe:
    """Nonblocking reads keep a dead SDK from trapping the archive worker."""
    def __init__(self,pipe,archive,stream,deadline):
        self.fd=pipe.fileno();os.set_blocking(self.fd,False)
        self.archive,self.stream,self.deadline=archive,stream,deadline
        self.pending=bytearray();self.eof=False

    def fill(self):
        while not self.eof:
            if self.archive.stopped.is_set() or not self.archive.allowed(self.stream) or time.monotonic()>self.deadline:
                self.eof=True;return
            ready,_,_=select.select([self.fd],[],[],.2)
            if not ready:continue
            try:chunk=os.read(self.fd,65536)
            except BlockingIOError:continue
            if not chunk:self.eof=True;return
            self.pending.extend(chunk);return

    def readline(self,limit):
        while b'\n' not in self.pending and len(self.pending)<limit and not self.eof:self.fill()
        at=self.pending.find(b'\n')
        if at<0:
            if self.eof:return b''
            at=limit-1
        count=min(at+1,limit);result=bytes(self.pending[:count]);del self.pending[:count]
        return result

    def read(self,size):
        while len(self.pending)<size and not self.eof:self.fill()
        count=min(size,len(self.pending));result=bytes(self.pending[:count]);del self.pending[:count]
        return result


def capture(archive,stream,start,end,directory,payload,env,deadline):
    import video
    # Use the installed local detector's image libraries; no download or cloud API.
    try:import cv2,numpy
    except ImportError:raise RuntimeError('video_tools')
    cv2.setNumThreads(1)
    process=archive.launch([shutil.which('wine') or shutil.which('wine64'),str(video.NATIVE/'yoosee_snapshot.exe'),'--archive-frames' if getattr(stream,'archive_without_list',False) else '--archive-frames-known'],
        cwd=directory,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        process.stdin.write(payload.encode());process.stdin.close()
        pipe=BoundedPipe(process.stdout,archive,stream,deadline)
        timeline=read_frames(pipe,directory,start,end,convert_frame)
    finally:
        archive.kill(process);process.wait(timeout=5)
        for pipe in (process.stdin,process.stdout,process.stderr):
            if pipe:pipe.close()
    first,last=timeline[0][0],timeline[-1][0]
    lines=['ffconcat version 1.0']
    for i,(stamp,name) in enumerate(timeline):
        duration=timeline[i+1][0]-stamp if i+1<len(timeline) else .001
        lines.extend([f"file '{name}'",'option framerate 1000',f'duration {duration:.6f}'])
    lines.extend([f"file '{timeline[-1][1]}'",'option framerate 1000'])
    manifest=Path(directory)/'frames.txt';manifest.write_text('\n'.join(lines)+'\n')
    output=Path(directory)/'archive.mp4';held=False;encoder=None
    try:
        until=min(time.monotonic()+120,deadline+120)
        while not held:
            if archive.stopped.is_set() or time.monotonic()>until:raise RuntimeError('encoder_busy')
            held=ENCODERS.acquire(timeout=.25)
        encoder=archive.launch([shutil.which('ffmpeg'),'-v','error','-y','-threads','1','-filter_threads','1',
            '-protocol_whitelist','file,pipe','-f','concat','-safe','0','-i',str(manifest),'-an','-vf','format=yuv420p',
            '-fps_mode','vfr','-c:v','libx264','-threads','1','-preset','veryfast','-crf','20','-movflags','+faststart',str(output)],
            stdout=subprocess.DEVNULL)
        while encoder.poll() is None:
            if archive.stopped.wait(.1) or time.monotonic()>until or shutil.disk_usage(directory).free<MIN_FREE:
                raise RuntimeError('bounded_export')
            if output.exists() and output.stat().st_size>MAX_STAGING:raise RuntimeError('disk_space')
        if encoder.returncode or not output.is_file():raise RuntimeError('invalid_video')
    finally:
        if encoder:archive.kill(encoder);encoder.wait(timeout=5)
        if held:ENCODERS.release()
    stream.archive_piece={'first':first,'last':last,'partial':first>start+1 or last<end-1,'record_setup_ms':0,'frame_count':len(timeline),'method':'sd_frames'}
    return output,round(max(0,min(5,start+5-first)),2)
