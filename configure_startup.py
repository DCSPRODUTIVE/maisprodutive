"""Install systemd services on the computer running DCS; never stores account passwords."""
import argparse
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import subprocess
import sys

from access import CONFIG, Gate, origin

ROOT = Path(__file__).resolve().parent
SERVICES = ('dcs-control.service', 'dcs-tunnel.service')


def quote(value):
    value=str(value)
    if any(c in value for c in '\n\r\0'):
        raise ValueError('Caminho ou argumento inválido.')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'


def units(root, home, username, python, cloudflared, public_origin, port):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*\$?',username):
        raise ValueError('Nome de usuário incompatível com o serviço.')
    public_origin=origin(public_origin)
    if type(port) is not int or not 1<=port<=65535:
        raise ValueError('Porta inválida.')
    quote(root)  # Reject control characters before writing a path directive.
    if not Path(root).is_absolute():raise ValueError('Diretório do projeto deve ser absoluto.')
    directory=str(root).replace('%','%%')
    common=f'''User={username}
WorkingDirectory={directory}
Environment={quote('HOME='+str(home))}
Environment="PYTHONUNBUFFERED=1"
Restart=always
RestartSec=5
TimeoutStopSec=20
KillMode=control-group
KillSignal=SIGINT
UMask=0077

[Install]
WantedBy=multi-user.target
'''
    app=f'''[Unit]
Description=Torre de Controle DCS
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart={quote(python)} {quote(Path(root)/'server.py')} --port {port} --public-origin {quote(public_origin)}
'''+common
    tunnel=f'''[Unit]
Description=Tunel permanente da Torre de Controle DCS
Wants=network-online.target
After=network-online.target dcs-control.service
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart={quote(cloudflared)} tunnel --config {quote(Path(home)/'.cloudflared'/'config.yml')} run torre-dcs
StandardOutput=null
StandardError=null
'''+common
    return dict(zip(SERVICES,(app,tunnel)))


def run(command):
    subprocess.run(command,check=True)


def validate_tunnel(path):
    # Validate only fixed routing values; never read/print credential contents.
    text=Path(path).read_text()
    if not re.search(r'^\s*tunnel:\s*[^\s#]+',text,re.M) or 'http://127.0.0.1:' not in text:
        raise ValueError('Configuração do túnel permanente ausente ou incompatível.')
    return text


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--origin',default='https://cameras.maisprodutive.com.br')
    parser.add_argument('--port',type=int,default=8097)
    parser.add_argument('--install',action='store_true')
    parser.add_argument('--uninstall',action='store_true')
    args=parser.parse_args()
    if args.install and args.uninstall:
        parser.error('Escolha instalar ou remover.')
    if os.geteuid()==0:
        raise SystemExit('Execute com python3, sem sudo. O programa pedirá sudo somente para instalar os serviços.')
    if args.uninstall:
        run(['sudo','systemctl','disable','--now',*SERVICES])
        for service in SERVICES:run(['sudo','rm','-f','/etc/systemd/system/'+service])
        run(['sudo','systemctl','daemon-reload'])
        print('Inicialização automática removida. Configurações e Reports foram preservados.')
        return
    user=pwd.getpwuid(os.getuid())
    home=Path(user.pw_dir)
    executable=shutil.which('cloudflared')
    if not executable:raise SystemExit('Instale cloudflared antes de configurar a inicialização.')
    if not CONFIG.exists():raise SystemExit('Configure a senha com python3 configure_access.py primeiro.')
    Gate()
    public_origin=origin(args.origin)
    text=validate_tunnel(home/'.cloudflared'/'config.yml')
    if public_origin[8:] not in text or f'http://127.0.0.1:{args.port}' not in text:
        raise SystemExit('O domínio/porta não correspondem a ~/.cloudflared/config.yml. Nenhum serviço foi instalado.')
    files=units(ROOT,home,user.pw_name,Path(sys.executable).resolve(),executable,public_origin,args.port)
    destination=ROOT/'.local'/'startup'
    destination.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,content in files.items():
        path=destination/name;path.write_text(content);path.chmod(0o600)
    print('Arquivos de serviço preparados em .local/startup, sem senha ou token.')
    if not args.install:
        print('Para instalar, execute novamente com --install após parar os servidores manuais.')
        return
    if not Path('/run/systemd/system').is_dir():
        raise SystemExit('O ambiente Linux não está executando systemd. Nenhum serviço foi instalado.')
    # Avoid replacing a manually running server and repeatedly failing on its port.
    with socket.socket() as sock:
        sock.settimeout(1)
        occupied=sock.connect_ex(('127.0.0.1',args.port))==0
    active=subprocess.run(['systemctl','is-active','--quiet',SERVICES[0]],capture_output=True).returncode==0
    if occupied and not active:
        raise SystemExit('Pare o servidor manual com Ctrl+C nos terminais antes de instalar. A porta está ocupada.')
    for service in SERVICES:
        run(['sudo','install','-m','644',str(destination/service),'/etc/systemd/system/'+service])
    run(['sudo','systemctl','daemon-reload'])
    run(['sudo','systemctl','enable',*SERVICES])
    run(['sudo','systemctl','restart',*SERVICES])
    for service in SERVICES:
        result=subprocess.run(['systemctl','is-active','--quiet',service])
        if result.returncode:
            raise SystemExit('Um serviço não iniciou. Consulte systemctl status '+service+' --no-pager')
    print('Servidor e túnel ativos. Voltarão quando o Linux iniciar; não dependem de terminais abertos.')
    print('O ChromeOS pode exigir abrir o Terminal para iniciar o Linux. O login Yoosee continua necessário após reiniciar.')
    print('Endereço: '+public_origin)


if __name__=='__main__':
    main()
