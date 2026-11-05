"""Encrypted, bounded trusted-device sessions. Never stores provider passwords."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time

DAYS=90
TTL=DAYS*86400

class DeviceVault:
    def __init__(self,directory):
        self.directory=Path(directory);self.path=self.directory/'device-sessions.sqlite'
        self.lock=threading.RLock();self.available=False
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:return
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(self.directory,0o700)
        keyfile=self.directory/'device-sessions.key'
        try:
            fd=os.open(keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as file:file.write(secrets.token_bytes(32))
        except FileExistsError:pass
        if keyfile.is_symlink() or self.path.is_symlink():raise ValueError('Armazenamento de aparelhos inválido.')
        key=keyfile.read_bytes()
        if len(key)!=32:raise ValueError('Chave de aparelhos inválida.')
        os.chmod(keyfile,0o600);self.cipher=AESGCM(key)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS devices(kind TEXT,scope TEXT,token TEXT,expires REAL,payload BLOB,PRIMARY KEY(kind,scope,token))')
        os.chmod(self.path,0o600);self.available=True

    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path,timeout=5)
        try:
            with connection:yield connection
        finally:connection.close()

    @staticmethod
    def digest(token):
        if not isinstance(token,str) or not 30<=len(token)<=100:return None
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def aad(kind,scope,digest,expires):
        return ('device-v1:'+kind+':'+scope+':'+digest+':'+float(expires).hex()).encode()

    def save(self,kind,scope,token,value,expires):
        digest=self.digest(token)
        if not self.available or digest is None:return False
        expires=float(expires)
        if not math.isfinite(expires):return False
        raw=json.dumps(value,separators=(',',':')).encode()
        if len(raw)>256*1024:raise ValueError('Sessão excedeu o limite.')
        nonce=secrets.token_bytes(12);aad=self.aad(kind,scope,digest,expires)
        payload=nonce+self.cipher.encrypt(nonce,raw,aad)
        with self.lock,self.connect() as db:
            db.execute('DELETE FROM devices WHERE expires<=?',(time.time(),))
            existing=db.execute('SELECT 1 FROM devices WHERE kind=? AND scope=? AND token=?',(kind,scope,digest)).fetchone()
            if not existing and db.execute('SELECT COUNT(*) FROM devices').fetchone()[0]>=128:return False
            db.execute('INSERT OR REPLACE INTO devices VALUES(?,?,?,?,?)',(kind,scope,digest,expires,payload))
        return True

    def load(self,kind,scope,token):
        digest=self.digest(token)
        if not self.available or digest is None:return None
        with self.lock,self.connect() as db:
            row=db.execute('SELECT expires,payload FROM devices WHERE kind=? AND scope=? AND token=? AND expires>?',(kind,scope,digest,time.time())).fetchone()
        if row is None:return None
        try:
            expiry,payload=row;aad=self.aad(kind,scope,digest,expiry)
            return json.loads(self.cipher.decrypt(payload[:12],payload[12:],aad)),expiry
        except Exception:return None

    def forget(self,kind,scope,token):
        digest=self.digest(token)
        if self.available and digest:
            with self.lock,self.connect() as db:db.execute('DELETE FROM devices WHERE kind=? AND scope=? AND token=?',(kind,scope,digest))

    def providers(self,scope):
        if not self.available:return []
        with self.lock,self.connect() as db:
            rows=db.execute("SELECT token,expires,payload FROM devices WHERE kind='provider' AND scope=? AND expires>? ORDER BY expires DESC",(scope,time.time())).fetchall()
        result=[]
        for token,expiry,payload in rows:
            try:result.append((json.loads(self.cipher.decrypt(payload[:12],payload[12:],self.aad('provider',scope,token,expiry))),expiry))
            except Exception:continue
        return result

    def reject_provider(self,scope,fingerprint):
        if not self.available:return
        with self.lock,self.connect() as db:
            rows=db.execute("SELECT token,expires,payload FROM devices WHERE kind='provider' AND scope=?",(scope,)).fetchall()
            for token,expiry,payload in rows:
                try:
                    value=json.loads(self.cipher.decrypt(payload[:12],payload[12:],self.aad('provider',scope,token,expiry)))
                    candidate=hashlib.sha256(value['access_token'].encode()).hexdigest()
                except Exception:continue
                if secrets.compare_digest(candidate,fingerprint):db.execute("DELETE FROM devices WHERE kind='provider' AND scope=? AND token=?",(scope,token))
