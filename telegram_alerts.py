"""Opt-in Telegram delivery; credentials stay in the private local database."""
import json
import queue
import re
import secrets
import threading
import time
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class TelegramAlerts:
    def __init__(self, store, public_origin=None):
        self.store, self.origin = store, public_origin
        self.jobs = queue.Queue(maxsize=24)
        self.lock = threading.Lock()
        self.results = {}
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def config(self, owner, values=None):
        with self.store.guard, self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS telegram(owner TEXT PRIMARY KEY, value TEXT NOT NULL)')
            row = db.execute('SELECT value FROM telegram WHERE owner=?', (owner,)).fetchone()
            config = json.loads(row[0]) if row else {'enabled': False, 'token': '', 'chat_id': ''}
            if values is not None:
                token = values.get('token') or config['token']
                chat = values.get('chat_id', '')
                enabled = values.get('enabled')
                if (type(enabled) is not bool or not isinstance(token, str) or not isinstance(chat, str)
                    or (token and not re.fullmatch(r'[0-9]{5,20}:[A-Za-z0-9_-]{20,100}', token))
                    or (chat and not re.fullmatch(r'-?[0-9]{1,20}', chat))
                    or (enabled and (not token or not chat))):
                    raise ValueError('Informe o token do BotFather e o ID numérico da conversa.')
                config = {'enabled': enabled, 'token': token, 'chat_id': chat}
                db.execute('INSERT OR REPLACE INTO telegram VALUES (?,?)', (owner, json.dumps(config)))
            return config

    def status(self, owner):
        config = self.config(owner)
        with self.lock:
            result = self.results.get(owner, 'Nenhum envio realizado nesta execução.')
        return {'enabled': config['enabled'], 'configured': bool(config['token']),
                'chat_id': config['chat_id'], 'message': result}

    def enqueue(self, owner, name='Teste de conexão', jpeg=None, confidence=None):
        if not self.config(owner)['enabled']:
            return False
        try:
            self.jobs.put_nowait((owner, name, jpeg, confidence, time.time()))
            return True
        except queue.Full:
            with self.lock:
                self.results[owner] = 'Fila de alertas cheia; este alerta não foi enviado.'
            return False

    def deliver(self, owner, name, jpeg, confidence, created):
        config = self.config(owner)
        if not config['enabled'] or time.time()-created > 300:
            return
        text = ('Torre de Controle DCS\nPessoa detectada: ' if jpeg else 'Torre de Controle DCS\n') + name[:150]
        text += '\n' + time.strftime('%d/%m/%Y %H:%M:%S %Z', time.localtime(created))
        if confidence is not None:
            text += f'\nConfiança: {confidence:.0%}'
        if self.origin:
            text += '\nVídeos no Reports (a gravação pode levar até 2 minutos):\n' + self.origin + '/reports#videos'
        else:
            text += '\nConsulte o Reports no painel. Configure o endereço público do servidor para receber um link acessível no celular.'
        fields = {'chat_id': config['chat_id'], 'caption' if jpeg else 'text': text}
        boundary = 'DCS'+secrets.token_hex(16)
        parts = []
        for key, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        if jpeg:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="pessoa.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()+jpeg+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        request = urllib.request.Request('https://api.telegram.org/bot'+config['token']+('/sendPhoto' if jpeg else '/sendMessage'),
            data=b''.join(parts), headers={'Content-Type': 'multipart/form-data; boundary='+boundary})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
            result = json.loads(response.read(65536))
            if not result.get('ok'):
                raise ValueError('delivery')
        with self.lock:
            self.results[owner] = 'Último alerta enviado ao Telegram.'

    def run(self):
        while not self.stopped.is_set():
            try:
                job = self.jobs.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                self.deliver(*job)
            except Exception:
                # HTTP exceptions contain the bot token in their URL: never log them.
                with self.lock:
                    self.results[job[0]] = 'Envio falhou. Confira token, ID e se você iniciou a conversa com o bot. O registro continua no Reports.'
            finally:
                self.jobs.task_done()

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)
