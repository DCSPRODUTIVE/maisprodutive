"""Enumerate server-side Linux cameras only; never activate a viewer's webcam."""
import os
from pathlib import Path
import re
import stat


def cameras():
    result=[]
    for path in sorted(Path('/dev').glob('video[0-9]*')):
        if not re.fullmatch(r'video[0-9]{1,3}',path.name):continue
        try:
            if not stat.S_ISCHR(path.stat().st_mode) or not os.access(path,os.R_OK|os.W_OK):continue
            # Filter metadata-only V4L2 nodes when the kernel exposes capabilities.
            index=Path('/sys/class/video4linux')/path.name/'index'
            if index.exists() and index.read_text().strip()!='0':continue
            label=Path('/sys/class/video4linux')/path.name/'name'
            name=label.read_text().strip()[:80] if label.exists() else path.name
            result.append({'id':'webcam:'+path.name,'name':'Webcam do servidor · '+''.join(c for c in name if c.isprintable()),'local':True})
        except OSError:continue
    return result[:2]


def device(camera_id):
    if not isinstance(camera_id,str) or camera_id not in {c['id'] for c in cameras()}:
        raise ValueError('Webcam indisponível no Linux do servidor. Confira conexão USB e permissão do dispositivo.')
    return '/dev/'+camera_id.split(':',1)[1]
