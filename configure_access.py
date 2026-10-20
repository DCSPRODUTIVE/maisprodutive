"""Configure the dashboard password locally; store only a salted password hash."""
from getpass import getpass
from access import configure

if __name__ == '__main__':
    configure(getpass('Senha para acessar a Torre de Controle DCS: '))
    print('Proteção configurada. A senha não foi salva em texto; reinicie o acesso externo.')
