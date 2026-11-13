"""Small sequence of distinct event frames; the selected alert photo stays separate."""
import hashlib
import time

WINDOW=5
MAX_PHOTOS=5
MAX_PHOTO_BYTES=256*1024


def collect(pending,jpeg):
    samples=pending.setdefault('samples',[])
    seen=pending.setdefault('sample_hashes',set())
    digest=hashlib.blake2s(jpeg,digest_size=16).digest()
    if len(samples)<MAX_PHOTOS and digest not in seen:
        samples.append((time.time(),jpeg));seen.add(digest)


def thumbnail(jpeg):
    if len(jpeg)<=MAX_PHOTO_BYTES:return jpeg
    try:
        import cv2
        import numpy as np
        image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
        if image is None:return None
        height,width=image.shape[:2];scale=min(1,640/max(height,width))
        image=cv2.resize(image,(max(1,round(width*scale)),max(1,round(height*scale))))
        ok,data=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,75])
        return data.tobytes() if ok and len(data)<=MAX_PHOTO_BYTES else None
    except ImportError:return None
