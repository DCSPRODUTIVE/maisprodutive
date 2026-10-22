"""Install pinned public OpenCV face models, without uploading images or credentials."""
import hashlib
import os
import urllib.request
from faces import MODELS, MODEL_ROOT


def main():
    MODEL_ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,(folder,digest) in MODELS.items():
        path=MODEL_ROOT/name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==digest:continue
        urls=[f'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{folder}/{name}',
              f'https://huggingface.co/opencv/{folder}/resolve/main/{name}']
        for url in urls:
            try:
                with urllib.request.urlopen(url,timeout=90) as response:data=response.read(40*1024*1024+1)
                if hashlib.sha256(data).hexdigest()!=digest:continue
                temporary=path.with_suffix('.tmp');temporary.write_bytes(data);os.chmod(temporary,0o600);temporary.replace(path)
                break
            except (OSError,ValueError):continue
        else:raise RuntimeError('Não foi possível obter o modelo verificado '+name+'. Confira sua internet e tente novamente.')
    print('Modelos faciais preparados. Reinicie o servidor e ative Rostos no Reports.')

if __name__=='__main__':
    try:main()
    except RuntimeError as error:
        print(error);raise SystemExit(1)
