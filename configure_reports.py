"""Download a pinned public object detector; never connects to cameras."""
import hashlib
import os
import urllib.request
from reports import MODEL_ROOT, MODEL_FILES, REVISION


def main():
    MODEL_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,digest in MODEL_FILES.items():
        path=MODEL_ROOT/name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==digest:
            continue
        url=f'https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/{REVISION}/{name}'
        with urllib.request.urlopen(url,timeout=120) as response:
            data=response.read(30*1024*1024+1)
        if len(data)>30*1024*1024 or hashlib.sha256(data).hexdigest()!=digest:
            raise RuntimeError('Modelo recebido não corresponde à versão esperada.')
        temporary=path.with_suffix(path.suffix+'.tmp')
        temporary.write_bytes(data);os.chmod(temporary,0o600);temporary.replace(path)
    print('Modelo preparado. Reinicie o servidor para ativar Reports.')

if __name__=='__main__':
    main()
