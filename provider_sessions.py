"""Reuse provider sessions; password proof stays in RAM and is never persisted."""
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from desktop import DesktopAccount,DesktopClient
from yoosee import IntegrationError,YooseeClient
from remembered import TTL

class ProviderSessions:
    def __init__(self,vault,scope,config):
        self.vault,self.scope,self.config=vault,scope,config
        self.lock=threading.RLock();self.key=secrets.token_bytes(32)
        self.cache={};self.cooldown={};self.invalid=set();self.stats={}

    def count(self,owner,kind):
        if owner not in self.stats and len(self.stats)>=128:self.stats.pop(next(iter(self.stats)))
        counters=self.stats.setdefault(owner,{})
        counters[kind]=counters.get(kind,0)+1

    @staticmethod
    def owner(username,country):
        value=str(username or '').strip().lower()
        if '@' not in value:value=str(country)+':'+value
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def token_id(client):
        account=getattr(client,'account',None)
        return hashlib.sha256(account.access_token.encode()).hexdigest() if isinstance(account,DesktopAccount) else ''

    def rejected(self,client):return bool(self.token_id(client)) and self.token_id(client) in self.invalid

    def login(self,config,username,password,country='55',factory=None):
        if not isinstance(username,str) or not isinstance(password,str) or not 1<=len(username)<=320 or not 1<=len(password)<=1024:
            raise IntegrationError('input','Informe login e senha válidos.')
        owner=self.owner(username,country)
        proof=hmac.new(self.key,json.dumps([config.auth_mode,username.strip().lower(),password,country]).encode(),hashlib.sha256).digest()
        with self.lock:
            if time.monotonic()<self.cooldown.get(owner,0):
                self.count(owner,'cooldown_blocks')
                raise IntegrationError('login_cooldown',f"Aguarde {max(1,int(self.cooldown[owner]-time.monotonic()))} segundos antes de outra tentativa. Falha de conexão não exige trocar a senha.")
            cached=self.cache.get(owner)
            if cached and hmac.compare_digest(proof,cached[0]) and not self.rejected(cached[1]):
                self.count(owner,'session_reuses')
                client=factory(config) if factory else DesktopClient(config);client.account=DesktopAccount(cached[1].account.access_id,cached[1].account.access_token)
                return client,owner
            client=factory(config) if factory else DesktopClient(config) if config.auth_mode=='windows-experimental' else YooseeClient(config)
            self.count(owner,'provider_login_requests')
            try:
                if isinstance(client,DesktopClient):client.login(username,password,country)
                else:client.login(username,password)
            except IntegrationError as error:
                self.count(owner,'login_failures')
                self.cooldown[owner]=time.monotonic()+(300 if error.kind in ('provider','authentication') else 30)
                raise
            if len(self.cache)>=64:self.cache.pop(next(iter(self.cache)))
            if isinstance(client,DesktopClient):
                self.invalid.discard(self.token_id(client));self.cache[owner]=(proof,client)
            self.cooldown.pop(owner,None)
            return client,owner

    def save(self,sid,state):
        if not state.get('remember') or not isinstance(state.get('client'),DesktopClient):return False
        client=state['client']
        if self.rejected(client):return False
        value={'owner':state['report_owner'],'access_id':client.account.access_id,'access_token':client.account.access_token,
            'device_ids':sorted(client.device_ids),'devices':state['devices']}
        return self.vault.save('provider',self.scope,sid,value,state['remember_until'])

    def decode(self,value):
        if not isinstance(value,dict) or set(value)!={'owner','access_id','access_token','device_ids','devices'}:return None
        if any(not isinstance(value.get(k),str) or not value[k] or len(value[k])>8192 for k in ('owner','access_id','access_token')):return None
        if len(value['owner'])!=64 or not isinstance(value['devices'],list) or len(value['devices'])>102:return None
        if not isinstance(value['device_ids'],list) or len(value['device_ids'])>100 or any(not isinstance(v,str) or len(v)>128 for v in value['device_ids']):return None
        try:
            config=self.config()
            if config.auth_mode!='windows-experimental':return None
            client=DesktopClient(config);client.account=DesktopAccount(value['access_id'],value['access_token']);client.device_ids=set(value['device_ids'])
            if self.rejected(client):return None
            return client,value['owner'],value['devices']
        except IntegrationError:return None

    def restore(self,sid):
        row=self.vault.load('provider',self.scope,sid)
        if not row:return None
        bound=row[0]
        decoded=self.decode(bound)
        # A previously authorized device may reuse a newer accepted session of the same owner.
        if not decoded:
            for candidate,expiry in self.vault.providers(self.scope):
                if candidate.get('owner')==bound.get('owner'):
                    decoded=self.decode(candidate)
                    if decoded:break
        if decoded:self.count(decoded[1],'device_restores')
        return (*decoded,row[1]) if decoded else None

    def forget(self,sid):self.vault.forget('provider',self.scope,sid)

    def reject(self,client):
        token=self.token_id(client)
        if token:self.reject_id(token)

    def reject_account(self,account):
        if account:self.reject_id(hashlib.sha256(account.access_token.encode()).hexdigest())

    def reject_id(self,token):
        if token in self.invalid:return
        self.invalid.add(token)
        try:self.vault.reject_provider(self.scope,token)
        except (OSError,sqlite3.Error):pass
