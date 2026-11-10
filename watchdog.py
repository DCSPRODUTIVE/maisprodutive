"""Independent systemd timer: detects an unresponsive DCS service, alerts and restarts once."""
import argparse
import json
from pathlib import Path
import time
import urllib.request
from reports import EventStore,ROOT
from telegram_alerts import TelegramAlerts


def check(port,root=ROOT,restart=False,origin=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    statefile=root/'watchdog.json'
    try:state=json.loads(statefile.read_text())
    except (OSError,ValueError):state={'failures':0,'alerted':False,'restart_at':0}
    if not isinstance(state,dict):state={'failures':0,'alerted':False,'restart_at':0}
    healthy=False
    try:
        request=urllib.request.Request(f'http://127.0.0.1:{port}/internal/health')
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=5) as response:
            healthy=json.loads(response.read(4096)).get('ok') is True
    except Exception:pass
    state['failures']=0 if healthy else state.get('failures',0)+1
    message=None
    if healthy and state.get('alerted'):
        message='Servidor voltou a responder. Confira no painel se as câmeras também recuperaram as imagens.';state['alerted']=False
    elif not healthy and state['failures']>=3 and not state.get('alerted'):
        state['alerted']=True;message='Servidor sem responder às verificações de saúde. O vigia independente tentará reiniciar o serviço.' if restart else 'Servidor sem responder às verificações de saúde. Verifique o serviço DCS no computador.'
    request_restart=bool(message and not healthy and restart and time.time()-state.get('restart_at',0)>1800)
    if message:
        state['pending_message']=message;state['notified']=[]
    if state.get('pending_message'):
        store=EventStore(root);alerts=TelegramAlerts(store,origin)
        sent=set(state.get('notified',[]));failed=False
        try:
            with store.guard,store.connect() as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='telegram'").fetchone()
                owners=[row[0] for row in db.execute('SELECT owner FROM telegram')] if exists else []
            for owner in owners:
                if owner in sent or not alerts.config(owner)['enabled']:continue
                try:alerts.deliver(owner,state['pending_message'],None,None,time.time());sent.add(owner)
                except Exception:failed=True
        finally:alerts.close()
        state['notified']=list(sent)
        if not failed:state.pop('pending_message',None)
    if request_restart:state['restart_at']=time.time();state['request_restart']=True
    requested=state.pop('request_restart',False)
    temporary=statefile.with_suffix('.tmp');temporary.write_text(json.dumps(state));temporary.chmod(0o600);temporary.replace(statefile)
    # systemd OnFailure starts a fixed privileged recovery unit for exit 2.
    return 0 if healthy else 2 if requested else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8097);parser.add_argument('--restart',action='store_true');parser.add_argument('--origin');args=parser.parse_args()
    raise SystemExit(check(args.port,restart=args.restart,origin=args.origin))
