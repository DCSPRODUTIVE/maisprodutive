"""Opt-in image descriptions and owner-scoped read-only Telegram conversation."""
import hashlib
import json
from pathlib import Path
import queue
import re
import threading
import time
import urllib.request

from google_ai import AIError, generate
from telegram_alerts import NoRedirect

DEFAULTS = {'enabled': False, 'event_descriptions': False, 'conversation': False,
            'model': 'gemini-2.5-flash', 'daily_limit': 60}


class AIAssistant:
    def __init__(self, server, start=True):
        self.server = server
        self.store = server.reports.store
        self.vault = server.device_vault
        self.jobs = queue.Queue(maxsize=12)
        self.stopped = threading.Event()
        self.results, self.cooldown, self.last_question = {}, {}, {}
        self.history = {}
        self.poll_retry = {}
        self.lock = threading.RLock()
        with self.store.guard, self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS ai_settings(owner TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS ai_usage(owner TEXT,day TEXT,used INTEGER,PRIMARY KEY(owner,day))')
            db.execute('CREATE TABLE IF NOT EXISTS ai_events(owner TEXT,event INTEGER,description TEXT,PRIMARY KEY(owner,event))')
            db.execute('CREATE TABLE IF NOT EXISTS ai_poll(bot TEXT PRIMARY KEY,offset INTEGER)')
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.listener = threading.Thread(target=self.poll, daemon=True)
        if start:
            self.worker.start(); self.listener.start()

    def key(self, owner, value=None):
        sid = hashlib.sha256(owner.encode()).hexdigest()
        if value is not None:
            if not self.vault.save('ai', 'gemini', sid, {'key': value}, time.time()+10*365*86400):
                raise ValueError('Armazenamento criptografado indisponível. Instale python3-cryptography.')
        row = self.vault.load('ai', 'gemini', sid)
        if row:
            return row[0].get('key', '')
        # Optional private server configuration, never exposed by status APIs.
        path = Path(__file__).parent / '.local' / 'google-ai.key'
        try:
            if not path.is_symlink() and path.stat().st_mode & 0o077 == 0:
                return path.read_text().strip()
        except OSError:
            pass
        return ''

    def config(self, owner, values=None):
        with self.lock:
            with self.store.guard, self.store.connect() as db:
                row = db.execute('SELECT value FROM ai_settings WHERE owner=?', (owner,)).fetchone()
            config = {**DEFAULTS, **(json.loads(row[0]) if row else {})}
            if values is None:
                return config
            if not isinstance(values, dict) or set(values)-set(DEFAULTS)-{'api_key'}:
                raise ValueError('Configuração de IA inválida.')
            updated = {**config, **{k: v for k, v in values.items() if k in DEFAULTS}}
            if any(type(updated[k]) is not bool for k in ('enabled', 'event_descriptions', 'conversation')):
                raise ValueError('Opções de IA inválidas.')
            if (type(updated['daily_limit']) is not int or not 1 <= updated['daily_limit'] <= 300
                    or not isinstance(updated['model'], str)
                    or not re.fullmatch(r'gemini-[a-zA-Z0-9._-]{1,70}', updated['model'])):
                raise ValueError('Escolha um modelo Gemini e limite entre 1 e 300 consultas por dia.')
            key = values.get('api_key', '')
            if not isinstance(key, str) or (key and not re.fullmatch(r'[A-Za-z0-9._-]{20,256}', key)):
                raise ValueError('Chave inválida. Cole somente a chave da API Google.')
            telegram = self.server.telegram.config(owner)
            if updated['enabled']:
                if not (key or self.key(owner)):
                    raise ValueError('Informe a chave da API Google.')
                if not telegram['enabled'] or not telegram['token'] or not telegram['chat_id']:
                    raise ValueError('Configure e ative o Telegram primeiro.')
                if updated['conversation'] and not telegram['chat_id'].isdigit():
                    raise ValueError('A conversa com IA exige seu chat privado, não um grupo.')
                with self.store.guard, self.store.connect() as db:
                    others = db.execute('SELECT owner FROM ai_settings WHERE owner<>?', (owner,)).fetchall()
                for other in others:
                    cfg = self.config(other[0]); tg = self.server.telegram.config(other[0])
                    if cfg['enabled'] and tg['token'] == telegram['token'] and tg['chat_id'] == telegram['chat_id']:
                        raise ValueError('Este chat já está associado a outra conta do sistema.')
            if key:
                self.key(owner, key)
            with self.store.guard, self.store.connect() as db:
                db.execute('INSERT OR REPLACE INTO ai_settings VALUES (?,?)', (owner, json.dumps(updated)))
            self.cooldown.pop(owner, None)
            self.history.pop(owner, None)
            self.results[owner] = 'Configuração salva. Envie /ajuda ao seu bot no Telegram.'
            return updated

    def status(self, owner):
        config = self.config(owner)
        with self.store.guard, self.store.connect() as db:
            row = db.execute('SELECT used FROM ai_usage WHERE owner=? AND day=?', (owner, self.day())).fetchone()
        return {**config, 'configured': bool(self.key(owner)), 'used_today': row[0] if row else 0,
                'message': self.results.get(owner, 'IA desativada até ser configurada.')}

    @staticmethod
    def day():
        return time.strftime('%Y-%m-%d', time.gmtime())

    def reserve(self, owner):
        with self.store.guard, self.store.connect() as db:
            day = self.day()
            db.execute('DELETE FROM ai_usage WHERE day<?', (time.strftime('%Y-%m-%d', time.gmtime(time.time()-7*86400)),))
            db.execute('INSERT OR IGNORE INTO ai_usage VALUES (?,?,0)', (owner, day))
            used = db.execute('SELECT used FROM ai_usage WHERE owner=? AND day=?', (owner, day)).fetchone()[0]
            # Configuration read without recursively taking the store lock.
            row = db.execute('SELECT value FROM ai_settings WHERE owner=?', (owner,)).fetchone()
            limit = json.loads(row[0])['daily_limit'] if row else DEFAULTS['daily_limit']
            if used >= limit:
                raise AIError('Limite diário de consultas de IA atingido. Os alertas locais continuam ativos.')
            db.execute('UPDATE ai_usage SET used=used+1 WHERE owner=? AND day=?', (owner, day))

    def enqueue_event(self, owner, event):
        if not self.config(owner)['enabled'] or not self.config(owner)['event_descriptions']:
            return False
        return self.enqueue((owner, 'event', event))

    def enqueue(self, job):
        try:
            self.jobs.put_nowait(job)
            return True
        except queue.Full:
            self.results[job[0]] = 'Fila de IA cheia; alertas e gravações locais continuam ativos.'
            return False

    def context(self, owner, event=None, include_images=True):
        with self.store.guard, self.store.connect() as db:
            if event is None:
                rows = db.execute('SELECT id,name,camera,created,confidence,image FROM events WHERE owner=? ORDER BY id DESC LIMIT 6', (owner,)).fetchall()
            else:
                rows = db.execute('SELECT id,name,camera,created,confidence,image FROM events WHERE owner=? AND id=?', (owner, event)).fetchall()
            descriptions = {r[0]: r[1] for r in db.execute('SELECT event,description FROM ai_events WHERE owner=? ORDER BY event DESC LIMIT 12', (owner,))}
        events, images = [], []
        for row in rows:
            item = {k: row[k] for k in ('id', 'name', 'camera', 'confidence')}
            item['horario_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(row['created']))
            if row['id'] in descriptions:
                item['descricao_ia_anterior'] = descriptions[row['id']]
            if include_images and len(images) < 3 and row['image']:
                image = self.preview(bytes(row['image']))
                if image:
                    images.append((f"Foto do evento {row['id']} · {item['horario_utc']}", image))
                    item['foto_enviada'] = True
            events.append(item)
        health = getattr(self.server, 'health', None)
        context = {'agora_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   'eventos_recentes': events, 'fotos_sao_instantes_nao_video': True,
                   'saude_cameras': getattr(health, 'snapshot', {}).get(owner, {}), 'cameras': []}
        context['videos_recentes'] = [{k: row[k] for k in ('id','name','created','status','duration','source','archive_status')}
                                     for row in self.store.videos(owner)[:6]]
        for stream in self.server.stream_snapshot():
            if getattr(stream, 'report_owner', None) != owner or stream.stopped.is_set():
                continue
            last = getattr(stream, 'last_frame', None)
            context['cameras'].append({'nome': getattr(stream, 'report_name', '')[:100],
                'segundos_sem_quadro': round(max(0, time.monotonic()-last)) if last else None})
        background = getattr(self.server, 'background', None)
        if background:
            with background.lock:
                context['monitoramento_programado'] = [
                    {'nome':entry.name[:100], 'economia':entry.economy,
                     'janela_ativa':entry.window(time.monotonic()),
                     'sessao_rejeitada':entry.auth_blocked, 'detectar_pessoas':entry.detection}
                    for entry in background.entries.values() if entry.owner == owner][:100]
        diagnostics = getattr(self.server, 'diagnostics', None)
        if diagnostics:
            context['ultimos_logs_sanitizados'] = diagnostics.history(owner)[0][:12]
        return context, images

    @staticmethod
    def preview(jpeg):
        try:
            import cv2
            import numpy as np
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                return None
            h, w = frame.shape[:2]
            if max(h, w) > 960:
                scale = 960/max(h, w)
                frame = cv2.resize(frame, (max(1, round(w*scale)), max(1, round(h*scale))))
            ok, output = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            return output.tobytes() if ok and len(output) <= 512*1024 else None
        except ImportError:
            return jpeg if len(jpeg) <= 512*1024 else None

    def process(self, owner, kind, value):
        if self.stopped.is_set():
            return
        config = self.config(owner)
        if not config['enabled'] or not config['event_descriptions' if kind == 'event' else 'conversation']:
            return
        tg = self.server.telegram.config(owner)
        if not tg['enabled']:
            return
        if kind == 'chat' and value.strip().lower() in ('/start', '/ajuda', '/help'):
            return self.server.telegram.send_text(owner,
                'Assistente Torre de Controle (somente leitura). Pergunte sobre câmeras, quedas ou detecções. '
                '/status: estado das câmeras, sem fotos. /eventos ou /resumo: últimas detecções, '
                'com até 3 fotos. Mensagens comuns também consultam as últimas detecções. '
                'As fotos são enviadas ao Google; não analiso vídeo contínuo nem executo alterações. '
                'Para interromper, desative Conversa no Reports.')
        if time.monotonic() < self.cooldown.get(owner, 0):
            if kind == 'chat':
                self.server.telegram.send_text(owner, 'IA temporariamente em espera após uma falha. Tente novamente em alguns minutos.')
            return
        context, images = self.context(owner, value if kind == 'event' else None,
                                       include_images=kind == 'event' or value.strip().lower() != '/status')
        if kind == 'chat':
            previous = self.history.get(owner, (0, []))
            context['conversa_anterior'] = previous[1] if time.monotonic()-previous[0] < 900 else []
        if kind == 'event' and not context['eventos_recentes']:
            return
        self.reserve(owner)
        question = ('Descreva somente o que está visível na foto deste evento e indique limitações.'
                    if kind == 'event' else value)
        try:
            answer = generate(self.key(owner), config['model'], question, context, images)
        except AIError:
            self.cooldown[owner] = time.monotonic()+300
            raise
        if self.stopped.is_set() or not self.config(owner)['enabled']:
            return
        if kind == 'event':
            with self.store.guard, self.store.connect() as db:
                db.execute('INSERT OR REPLACE INTO ai_events VALUES (?,?,?)', (owner, value, answer))
                db.execute('DELETE FROM ai_events WHERE NOT EXISTS (SELECT 1 FROM events WHERE events.owner=ai_events.owner AND events.id=ai_events.event)')
            event = context['eventos_recentes'][0]
            prefix = f"Descrição por IA · evento {event['id']} · {event['name'][:100]}\n{event['horario_utc']}\n"
        else:
            prefix = 'Assistente IA · consulta aos registros recentes\n'
            self.history[owner] = (time.monotonic(), (context['conversa_anterior'] + [
                {'pergunta':value[:1000], 'resposta':answer[:1000]}])[-3:])
        self.server.telegram.send_text(owner, prefix+answer)
        self.results[owner] = 'Última consulta de IA concluída. Descrições podem conter erros.'

    def run(self):
        while not self.stopped.is_set():
            try:
                job = self.jobs.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                self.process(*job)
            except AIError as error:
                self.results[job[0]] = str(error)
                try:
                    if job[1] == 'chat':
                        self.server.telegram.send_text(job[0], str(error))
                except Exception:
                    pass
            except Exception:
                self.results[job[0]] = 'Consulta de IA falhou. Alertas e gravações locais continuam ativos.'
            finally:
                self.jobs.task_done()

    @staticmethod
    def telegram_request(token, method, body):
        request = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}',
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=10) as response:
            data = json.loads(response.read(1024*1024))
        if not data.get('ok'):
            raise ValueError('telegram')
        return data.get('result')

    def poll_once(self):
        with self.store.guard, self.store.connect() as db:
            owners = [r[0] for r in db.execute('SELECT owner FROM ai_settings')]
        bots = {}
        for owner in owners:
            config = self.config(owner); tg = self.server.telegram.config(owner)
            if config['enabled'] and config['conversation'] and tg['enabled'] and tg['chat_id'].isdigit():
                bots.setdefault(tg['token'], {}).setdefault(tg['chat_id'], []).append(owner)
        for token, chats in bots.items():
            if self.stopped.is_set():
                break
            bot = hashlib.sha256(token.encode()).hexdigest()
            if time.monotonic() < self.poll_retry.get(bot, 0):
                continue
            try:
                with self.store.guard, self.store.connect() as db:
                    row = db.execute('SELECT offset FROM ai_poll WHERE bot=?', (bot,)).fetchone()
                if row is None:
                    hook = self.telegram_request(token, 'getWebhookInfo', {})
                    if hook.get('url'):
                        self.poll_retry[bot] = time.monotonic()+60
                        for matches in chats.values():
                            for owner in matches:
                                self.results[owner] = 'O bot tem webhook ativo. Use um bot exclusivo para esta integração.'
                        continue
                updates = self.telegram_request(token, 'getUpdates', {
                    'offset': row[0] if row else -1, 'timeout': 0, 'limit': 20,
                    'allowed_updates': ['message']})
                offset = row[0] if row else 0
                for update in updates:
                    offset = max(offset, update['update_id']+1)
                    if row is None:  # discard old queued messages on first activation
                        continue
                    message = update.get('message', {})
                    chat = message.get('chat', {}); sender = message.get('from', {})
                    matches = chats.get(str(chat.get('id')), [])
                    text = message.get('text')
                    if (len(matches) != 1 or chat.get('type') != 'private' or sender.get('is_bot')
                            or sender.get('id') != chat.get('id') or not isinstance(text, str)
                            or not 0 < len(text) <= 2000 or time.time()-message.get('date', 0) > 120):
                        continue
                    owner = matches[0]
                    if time.monotonic()-self.last_question.get(owner, -1000) < 10:
                        continue
                    self.last_question[owner] = time.monotonic()
                    self.enqueue((owner, 'chat', text))
                with self.store.guard, self.store.connect() as db:
                    db.execute('INSERT OR REPLACE INTO ai_poll VALUES (?,?)', (bot, offset))
            except Exception:
                self.poll_retry[bot] = time.monotonic()+30
                for matches in chats.values():
                    for owner in matches:
                        self.results[owner] = 'Não foi possível ler o Telegram. Confira o bot e se outro serviço usa getUpdates.'

    def poll(self):
        while not self.stopped.wait(3):
            try:
                self.poll_once()
            except Exception:
                pass

    def close(self):
        self.stopped.set()
        for thread in (self.listener, self.worker):
            if thread.ident is not None:
                thread.join(timeout=2)
