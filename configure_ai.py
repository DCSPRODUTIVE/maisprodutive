"""Optional private local key setup, independent of account opt-in in Reports."""
import argparse
import getpass
import os
from pathlib import Path
import re
from google_ai import AIError, generate


def main():
    parser=argparse.ArgumentParser(description='Configurar chave Google somente neste servidor; sem alterar câmeras.')
    parser.add_argument('--check',action='store_true',help='Testar chave salva com uma pergunta curta, sem imagens; pode consumir cota.')
    parser.add_argument('--model',default='gemini-flash-latest')
    args=parser.parse_args()
    path=Path(__file__).parent/'.local'/'google-ai.key'
    if args.check:
        try:
            key=path.read_text().strip()
            print(generate(key,args.model,'Responda somente: conexão disponível.',{},[]))
        except (OSError,AIError):
            print('Não foi possível validar a API. Confira chave, modelo, permissões, rede e cota no Google.');return 1
    else:
        key=getpass.getpass('Chave Google (entrada oculta): ').strip()
        if not re.fullmatch(r'[A-Za-z0-9._-]{20,256}',key):
            print('Formato inválido. Cole somente a chave.');return 1
        path.parent.mkdir(exist_ok=True,mode=0o700)
        if path.is_symlink():
            print('Caminho de configuração inválido.');return 1
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as file:file.write(key)
        path.chmod(0o600)
        print('Chave salva somente neste servidor. Ative as opções da IA nos Reports da sua conta.')
    return 0

if __name__=='__main__':raise SystemExit(main())
