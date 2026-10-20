"""Run the protected local app through a Cloudflare HTTPS quick tunnel."""
import argparse
from getpass import getpass
import re
import selectors
import shutil
import subprocess
import threading
import time

from access import CONFIG, Gate, configure, origin
from server import Workbench


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8097)
    args=parser.parse_args()
    executable=shutil.which('cloudflared')
    if not executable:
        raise SystemExit('Instale cloudflared conforme docs/remote-access.md e execute novamente.')
    if not CONFIG.exists():
        configure(getpass('Crie a senha de acesso ao sistema: '))
    server=Workbench(('127.0.0.1',args.port),access_gate=Gate())
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    tunnel=None
    reader=None
    try:
        tunnel=subprocess.Popen([executable,'tunnel','--no-autoupdate','--url',f'http://127.0.0.1:{server.server_port}'],
                                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,bufsize=0)
        selector=selectors.DefaultSelector();selector.register(tunnel.stderr,selectors.EVENT_READ)
        pending=b'';url=None;deadline=time.monotonic()+60
        while time.monotonic()<deadline and tunnel.poll() is None and not url:
            for key,_ in selector.select(timeout=1):
                chunk=key.fileobj.read(4096)
                if not chunk:break
                pending=(pending+chunk)[-16384:]
                match=re.search(rb'https://[a-z0-9-]+\.trycloudflare\.com',pending)
                if match:url=origin(match[0].decode())
        selector.close()
        if not url:
            raise RuntimeError('O túnel não forneceu um endereço HTTPS. Verifique internet e disponibilidade do Cloudflare.')
        server.public_origin=url
        # Drain tunnel diagnostics without retaining or displaying them.
        def drain():
            while tunnel.stderr.read(4096):pass
        reader=threading.Thread(target=drain,daemon=True)
        reader.start()
        print(f'Acesso externo protegido: {url}',flush=True)
        print('Mantenha este terminal aberto. Ctrl+C encerra servidor e túnel.',flush=True)
        tunnel.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
            try:tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:tunnel.kill();tunnel.wait()
        if reader:reader.join(timeout=2)
        if tunnel and tunnel.stderr:tunnel.stderr.close()
        server.shutdown();server.server_close();worker.join(timeout=3)

if __name__=='__main__':
    main()
