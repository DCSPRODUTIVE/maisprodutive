"""Names supplied by the user for historical events. No visual identity matching."""
import hashlib
import re
import time
from camera_names import display_name


class EventNotes:
    def __init__(self, store):
        self.store = store
        with store.guard, store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS telegram_event_links(bot TEXT,chat TEXT,message INTEGER,owner TEXT,event INTEGER,PRIMARY KEY(bot,chat,message))')

    @staticmethod
    def bot(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def bind(self, token, chat, message, owner, event):
        if type(message) is not int or type(event) is not int:
            return
        with self.store.guard, self.store.connect() as db:
            if db.execute('SELECT 1 FROM events WHERE owner=? AND id=?', (owner,event)).fetchone():
                db.execute('INSERT OR REPLACE INTO telegram_event_links VALUES (?,?,?,?,?)',
                           (self.bot(token),str(chat),message,owner,event))
            db.execute('DELETE FROM telegram_event_links WHERE NOT EXISTS (SELECT 1 FROM events WHERE events.owner=telegram_event_links.owner AND events.id=telegram_event_links.event)')

    def resolve(self, token, chat, message, owner):
        with self.store.guard, self.store.connect() as db:
            row = db.execute('SELECT l.event FROM telegram_event_links l JOIN events e ON e.owner=l.owner AND e.id=l.event WHERE l.bot=? AND l.chat=? AND l.message=? AND l.owner=?',
                             (self.bot(token),str(chat),message,owner)).fetchone()
            return row[0] if row else None

    def annotate(self, owner, event, name):
        name = ' '.join(name.split())
        if not 1 <= len(name) <= 80 or not re.fullmatch(r"[\w À-ÿ.'’-]+",name) or not any(c.isalpha() for c in name):
            raise ValueError('Informe um nome de até 80 caracteres, sem comandos ou perguntas.')
        with self.store.guard, self.store.connect() as db:
            row = db.execute('SELECT name FROM events WHERE owner=? AND id=?', (owner,event)).fetchone()
            if not row:
                raise ValueError('Evento não encontrado nesta conta ou já expirado.')
            db.execute('INSERT OR REPLACE INTO event_annotations VALUES (?,?,?,?,?)',
                       (owner,event,name,name.casefold(),time.time()))
        return f'Anotação salva no evento {event}: {name}. Nome informado por você, não verificado automaticamente. Não será usado para reconhecer pessoas em novas imagens.'

    def lookup(self, owner, name=''):
        with self.store.guard, self.store.connect() as db:
            if name:
                rows=db.execute('SELECT a.event,a.name,e.name AS camera,e.created FROM event_annotations a JOIN events e ON e.owner=a.owner AND e.id=a.event WHERE a.owner=? AND a.normalized=? ORDER BY a.event DESC LIMIT 12',
                                (owner,' '.join(name.split()).casefold())).fetchall()
                lines=[f"Evento {r['event']} · {display_name(r['camera'])} · {time.strftime('%d/%m/%Y %H:%M UTC',time.gmtime(r['created']))} · anotação: {r['name']}" for r in rows]
            else:
                rows=db.execute('SELECT MAX(a.name) AS name,COUNT(*) AS total FROM event_annotations a JOIN events e ON e.owner=a.owner AND e.id=a.event WHERE a.owner=? GROUP BY a.normalized ORDER BY MAX(a.event) DESC LIMIT 30',(owner,)).fetchall()
                lines=[f"{r['name']}: {r['total']} evento(s) anotado(s)" for r in rows]
        return 'Cadastro de anotações manuais (não é reconhecimento):\n'+('\n'.join(lines) if lines else 'Nenhuma anotação encontrada.')

    def forget(self, owner, name):
        with self.store.guard,self.store.connect() as db:
            count=db.execute('DELETE FROM event_annotations WHERE owner=? AND normalized=?',
                             (owner,' '.join(name.split()).casefold())).rowcount
        return f'{count} anotação(ões) removida(s). Fotos e vídeos originais preservados.'
