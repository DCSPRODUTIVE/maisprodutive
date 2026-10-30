let csrf = "", before = null, loading = false, view = location.hash==="#videos" ? "videos" : "photos";
const $ = id => document.getElementById(id);
function node(tag, text, cls) { const el=document.createElement(tag); if(text)el.textContent=text;if(cls)el.className=cls;return el; }
async function load(reset=false) {
  if(loading)return;loading=true;$("reload-reports").disabled=true;
  try {
    if(reset){before=null;$("report-list").replaceChildren();}
    const sessionResponse=await fetch('/api/status',{cache:'no-store'});
    if(sessionResponse.status===401){window.location.replace('/access');return;}
    const session=await sessionResponse.json();csrf=session.csrf;
    const select=$('card-camera');const previous=select.value;select.replaceChildren();
    for(const camera of session.devices||[]){if(camera.local)continue;const option=node('option',camera.name);option.value=camera.id;select.append(option);}
    if(previous)select.value=previous;
    if(!session.authenticated)throw new Error('Abra o painel e entre na sua conta para ver os registros.');
    const response=await fetch(view==='videos'?'/api/reports/videos':'/api/reports',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({before})});
    const data=await response.json();if(!response.ok)throw new Error(data.message);
    $("report-status").textContent=data.message;
    for(const event of data.events){
      const card=node('article',null,'report-card');
      if(view==='videos'){
        if(event.status==='ready'||event.status==='partial'){
          const video=node('video');video.src=`/api/reports/video/${event.id}`;video.controls=true;video.preload='metadata';card.append(video);
        }
      }
      if(view==='photos' && event.has_image){
        const media=node('div',null,'report-image'),img=node('img');
        img.src=`/api/reports/image/${event.id}`;img.alt=`Registro de ${event.name}`;img.loading='lazy';media.append(img);
        for(const box of event.boxes){const overlay=node('span',null,'report-box');
          // Geometry comes only from our detector; clamp before assigning CSS.
          const [x1,y1,x2,y2]=box.map(n=>Math.max(0,Math.min(1,Number(n)||0)));
          Object.assign(overlay.style,{left:`${x1*100}%`,top:`${y1*100}%`,width:`${(x2-x1)*100}%`,height:`${(y2-y1)*100}%`});media.append(overlay);}
        card.append(media);
      }
      const info=node('div',null,'report-info');
      info.append(node('h2',view==='videos'?(['sd_requested','sd_backup'].includes(event.source)?'Backup do cartão':'Vídeo registrado'):'Pessoa detectada'));
      if(view==='videos'){
        const label=event.status==='recording'?'Gravando · até 2 minutos':event.status==='failed'?'Não foi possível gravar':`${Math.round(event.duration)} segundos · ${event.status==='partial'?'trecho parcial':'concluído'} · sem áudio`;
        info.append(node('p',label));
        if(event.status==='ready'||event.status==='partial'){
          const download=node('a','Baixar MP4','reports-link');download.href='/api/reports/download/'+event.id;download.download='DCS-'+event.id+'.mp4';info.append(download);
        }
        if(event.source==='live'&&event.frame_count)info.append(node('p',`${event.frame_count} quadros distintos · ${event.capture_fps||0} fps recebidos · maior intervalo: ${event.max_gap||0}s`));
        info.append(node('p',event.source==='sd_backup'?'Origem: backup do cartão da câmera':event.source==='sd_requested'?'Origem: solicitação de backup no cartão':event.source==='sd'?`Origem: cartão da câmera · ${event.pre_roll||0}s anteriores confirmados`:`Origem: gravação local · ${event.pre_roll||0}s anteriores disponíveis`));
        const archiveLabels={queued:'Solicitação na fila.',list_unavailable:'O SDK não respondeu à consulta do cartão.',seek_unavailable:'A câmera não aceitou posicionar a reprodução no horário pedido.',playback_unavailable:'O cartão informou um arquivo, mas não entregou imagens na reprodução.',disk_space:'Sem espaço suficiente para preparar o vídeo do cartão. Vídeo local preservado.',adapter_update_required:'Atualize o adaptador com configure_video.py --update para tentar consultar o cartão.',no_recording:'A câmera não entregou gravação nesse horário; confira cartão e gravação no app Yoosee. Vídeo local preservado.',timestamp_unverified:'Não foi possível confirmar o horário da gravação do cartão. Vídeo local preservado.',fetching:'Buscando a gravação do cartão; o vídeo local continua disponível.',unavailable:'Cartão indisponível ou exportação incompatível. Vídeo local preservado.',busy:'Sem conexão livre para consultar o cartão. Vídeo local preservado.',cooldown:'Consulta ao cartão em espera após falha anterior.',economy_or_disabled:'Consulta ao cartão não iniciada para respeitar economia ou detecção desativada.'};
        if(archiveLabels[event.archive_status])info.append(node('p',archiveLabels[event.archive_status]));
        if(event.reason==='disk_space')info.append(node('p','Espaço em disco insuficiente. Libere espaço para novas gravações.'));
      }
      info.append(node('p',`${event.name} · ${new Date(event.created*1000).toLocaleString('pt-BR')}`));
      if(event.confidence)info.append(node('p',`Confiança do detector: ${Math.round(event.confidence*100)}%`));
      card.append(info);$("report-list").append(card);before=event.id;
    }
    $("older-reports").hidden=data.events.length<24;
    if(reset&&!data.events.length)$("report-list").append(node('p','Ainda não há registros nesta aba. Ative Detectar pessoas nas câmeras desejadas.'));
  }catch(error){$("report-status").textContent=error.message;}
  finally{loading=false;$("reload-reports").disabled=false;}
}
$("reload-reports").addEventListener('click',()=>load(true));
$("older-reports").addEventListener('click',()=>load());
load(true);

for(const [id,tab] of [['photos-tab','photos'],['videos-tab','videos']]) $(id).addEventListener('click',()=>{
  if(loading)return;view=tab;
  $('photos-tab').className=view==='photos'?'selected':'secondary';
  $('videos-tab').className=view==='videos'?'selected':'secondary';
  location.hash=view;
  load(true);
});

async function settingsRequest(action,body={}){
  if(!csrf){
    const response=await fetch('/api/status',{cache:'no-store'});
    if(response.status===401){window.location.replace('/access');throw new Error('Entre no sistema.');}
    const session=await response.json();if(!session.authenticated)throw new Error('Abra Câmeras e entre na conta.');csrf=session.csrf;
  }
  const path=action.startsWith('card/')?'/api/'+action:'/api/telegram/'+action;
  const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.message||'Não foi possível completar a solicitação.');return data;
}
async function telegramStatus() {
  try{
    const data=await settingsRequest('status');
    $('telegram-enabled').checked=data.enabled;$('telegram-chat').value=data.chat_id;
    $('telegram-token').placeholder=data.configured?'Token salvo. Deixe vazio para manter.':'Cole o token do BotFather';
    $('telegram-status').textContent=(data.enabled?'Alertas ativados. ':'Alertas desativados. ')+data.message;
  }catch(error){$('telegram-status').textContent=error.message;}
}
$('telegram-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter;if(button)button.disabled=true;
  try{
    await settingsRequest('save',{enabled:$('telegram-enabled').checked,chat_id:$('telegram-chat').value.trim(),token:$('telegram-token').value.trim()});
    $('telegram-token').value='';await telegramStatus();
  }catch(error){$('telegram-status').textContent=error.message;}
  finally{if(button)button.disabled=false;}
});
$('telegram-test').addEventListener('click',async()=>{
  $('telegram-test').disabled=true;
  try{$('telegram-status').textContent=(await settingsRequest('test')).message;}
  catch(error){$('telegram-status').textContent=error.message;}
  finally{$('telegram-test').disabled=false;}
});
$('telegram-refresh').addEventListener('click',telegramStatus);
$('photos-tab').className=view==='photos'?'selected':'secondary';
$('videos-tab').className=view==='videos'?'selected':'secondary';
telegramStatus();


let cardJob=null;
const cardMessages={queued:'Na fila de consulta ao cartão…',running:'Acessando o cartão da câmera. Isso pode levar alguns minutos.',done:'Solicitação concluída.',busy:'Sem uma conexão livre. Tente novamente após parar outra câmera.',economy_or_disabled:'Sem tempo na janela ativa de Economia. Aguarde outra janela ou desative Economia para esta consulta.',list_unavailable:'A câmera/SDK não respondeu à lista do cartão. Confira se há gravações no aplicativo Yoosee.',no_recording:'Não foi encontrado um arquivo que cubra o início selecionado.',seek_unavailable:'A câmera não aceitou buscar o horário selecionado.',playback_unavailable:'Arquivo listado, mas a câmera não entregou a reprodução.',timestamp_unverified:'O horário da reprodução não pôde ser confirmado. Nenhum vídeo incorreto foi salvo.',adapter_update_required:'Atualize o adaptador com configure_video.py --update e reinicie o servidor.',disk_space:'Espaço insuficiente no servidor.',unavailable:'Não foi possível obter um vídeo válido. Confira o cartão no aplicativo Yoosee.'};
function localDate(value){return new Date(value-new Date(value).getTimezoneOffset()*60000).toISOString().slice(0,16);}
$('card-from').value=localDate(Date.now()-15*60000);$('card-to').value=localDate(Date.now()-60000);
async function cardRequest(action){
  if(cardJob)return;
  const start=new Date($('card-from').value).getTime()/1000,end=new Date($('card-to').value).getTime()/1000;
  try{
    if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start||end-start>(action==='list'?3600:125))throw new Error(action==='list'?'Selecione até 1 hora.':'Selecione um trecho de até 2 minutos para backup.');
    $('card-list').disabled=true;$('card-backup').disabled=true;$('card-results').replaceChildren();
    const data=await settingsRequest('card/start',{device_id:$('card-camera').value,start,end,action});
    cardJob=data.job_id;await cardPoll(cardJob,action);
  }catch(error){$('card-status').textContent=error.message;cardJob=null;$('card-list').disabled=false;$('card-backup').disabled=false;}
}
async function cardPoll(key,action){
  if(cardJob!==key)return;
  try{
    const data=await settingsRequest('card/status',{job_id:key});$('card-status').textContent=cardMessages[data.status]||'Falha na solicitação.';
    if(data.status==='queued'||data.status==='running'){setTimeout(()=>cardPoll(key,action),2000);return;}
    if(data.status==='done'&&action==='list'){
      if(!data.records.length)$('card-results').append(node('p','O cartão não retornou gravações nesse intervalo.'));
      for(const record of data.records){
        const row=node('div',null,'card-result');row.append(node('p',new Date(record.start*1000).toLocaleString('pt-BR')+' → '+new Date(record.end*1000).toLocaleString('pt-BR')));
        const choose=node('button','Selecionar trecho de até 2 minutos','secondary');choose.type='button';
        choose.addEventListener('click',()=>{$('card-from').value=localDate(record.start*1000);$('card-to').value=localDate(Math.min(record.end,record.start+120)*1000);$('card-status').textContent='Trecho selecionado. Clique em Fazer backup do trecho.';});row.append(choose);$('card-results').append(row);
      }
    }
    if(data.status==='done'&&data.record_id){const link=node('a','Baixar backup MP4','reports-link');link.href='/api/reports/download/'+data.record_id;link.download='DCS-backup.mp4';$('card-results').append(link);if(view==='videos')await load(true);}
  }catch(error){$('card-status').textContent=error.message;}
  cardJob=null;$('card-list').disabled=false;$('card-backup').disabled=false;
}
$('card-form').addEventListener('submit',event=>{event.preventDefault();cardRequest('list');});
$('card-backup').addEventListener('click',()=>cardRequest('backup'));
