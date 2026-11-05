"""Password gate for a loopback service published through an HTTPS tunnel."""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
import time
from remembered import DeviceVault,TTL as REMEMBER_TTL
from urllib.parse import urlsplit

CONFIG = Path(__file__).parent / '.local' / 'access.json'
TTL = 12 * 60 * 60


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or any(c in parsed.netloc for c in '\r\n ,') or parsed.netloc != parsed.netloc.lower()):
        raise ValueError('Informe somente a origem HTTPS pública, sem caminho.')
    return 'https://' + parsed.netloc


def configure(password, path=CONFIG):
    if not isinstance(password, str) or len(password) < 8 or len(password) > 256:
        raise ValueError('A senha de acesso deve ter entre 8 e 256 caracteres.')
    salt = secrets.token_bytes(32)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as file:
        json.dump({'schema': 1, 'salt': salt.hex(), 'digest': digest}, file)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


class Gate:
    def __init__(self, path=CONFIG):
        data = json.loads(Path(path).read_text())
        if data.get('schema') != 1:
            raise ValueError('Configuração de acesso inválida.')
        self.salt = bytes.fromhex(data['salt'])
        self.digest = bytes.fromhex(data['digest'])
        if len(self.salt) != 32 or len(self.digest) != 64:
            raise ValueError('Configuração de acesso inválida.')
        self.vault=DeviceVault(Path(path).parent)
        self.scope=hashlib.sha256(self.salt+self.digest).hexdigest()
        self.trusted={}
        self.sessions = {}
        self.attempts = deque()
        self.lock = threading.Lock()

    def remembered_until(self,token):
        digest=DeviceVault.digest(token)
        if not digest:return 0
        if digest in self.trusted:return self.trusted[digest]
        record=self.vault.load('gate',self.scope,token)
        if record:self.trusted[digest]=record[1];return record[1]
        return 0

    def cookie_ttl(self,token):
        if token in self.sessions:return TTL
        expiry=self.remembered_until(token)
        return max(0,int(expiry-time.time())) if expiry else TTL

    def revoke(self,token):
        with self.lock:
            self.sessions.pop(token,None);self.trusted.pop(DeviceVault.digest(token),None)
            self.vault.forget('gate',self.scope,token)

    def valid(self, token):
        with self.lock:
            now = time.monotonic()
            self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}
            if token in self.sessions:
                self.sessions[token]=now+TTL;return True
            return self.remembered_until(token)>time.time()

    def login(self, password, remember=False):
        with self.lock:
            now = time.monotonic()
            while self.attempts and now-self.attempts[0] >= 60:
                self.attempts.popleft()
            if len(self.attempts) >= 5:
                return None, 429
            self.attempts.append(now)
            if not isinstance(password, str) or len(password) > 256:
                return None, 401
            candidate = hashlib.scrypt(password.encode(), salt=self.salt, n=16384, r=8, p=1)
            if not secrets.compare_digest(candidate, self.digest):
                return None, 401
            self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}
            if len(self.sessions) >= 32:
                return None, 429
            token = secrets.token_urlsafe(32)
            if remember and self.vault.available:
                expires=time.time()+REMEMBER_TTL
                if not self.vault.save('gate',self.scope,token,{},expires):return None,429
                self.trusted[DeviceVault.digest(token)]=expires
            else:self.sessions[token] = now + TTL
            return token, 200
