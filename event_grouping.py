"""Group nearly unchanged scene notifications only, never recognize individuals."""
import hashlib
import time


class EventGrouping:
    def __init__(self):self.rows={}

    @staticmethod
    def signature(jpeg):
        digest=hashlib.blake2s(jpeg,digest_size=16).digest()
        try:
            import cv2
            import numpy as np
            image=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_GRAYSCALE)
            if image is not None:
                # Whole scene, no face/body crops, feature vectors, or identity database.
                tiny=cv2.resize(image,(32,20))[3:,:]
                return digest,tiny.astype('int16')
        except ImportError:pass
        return digest,None

    def group(self,key,event,jpeg,reasons,now=None):
        now=time.monotonic() if now is None else now
        signature=self.signature(jpeg);old=self.rows.get(key)
        if old and now-old['at']<30 and set(reasons)=={'presence'}:
            a,b=signature,old['signature']
            same=a[0]==b[0] or (a[1] is not None and b[1] is not None and float(abs(a[1]-b[1]).mean())<.15 and int(abs(a[1]-b[1]).max())<4)
            if same:return old['event']
        self.rows[key]={'at':now,'event':event,'signature':signature}
        self.rows={k:v for k,v in self.rows.items() if now-v['at']<60}
        return None
