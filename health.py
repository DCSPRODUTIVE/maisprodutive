"""Cheap JPEG geometry parsing and camera diagnostics, without decoding another frame."""
import time
from contextlib import nullcontext


def jpeg_size(data):
    if not data or data[:2]!=b'\xff\xd8':return None
    position=2
    while position+4<=len(data):
        if data[position]!=255:return None
        marker=data[position+1];position+=2
        if marker==255:position-=1;continue
        if marker in (0xd8,0xd9):continue
        if marker==0xda:return None
        length=int.from_bytes(data[position:position+2],'big')
        if length<2 or position+length>len(data):return None
        if marker in (0xc0,0xc1,0xc2) and length>=7:
            return [int.from_bytes(data[position+5:position+7],'big'),int.from_bytes(data[position+3:position+5],'big')]
        position+=length
    return None


def snapshot(stream):
    with getattr(stream,'condition',nullcontext()):
        times=list(getattr(stream,'frame_times',()))
    now=time.monotonic()
    recent=[value for value in times if now-value<=5]
    fps=(len(recent)-1)/(recent[-1]-recent[0]) if len(recent)>1 and recent[-1]>recent[0] else 0
    detection=dict(getattr(stream,'detection_health',{}))
    if 'analyzed_at' in detection:detection['age_seconds']=round(max(0,now-detection.pop('analyzed_at')),1)
    return {'resolution':getattr(stream,'resolution',None),'fps':round(fps,1),
            'target_fps':10,'definition':getattr(stream,'definition',0),'detection':detection}
