let csrf = "", before = null, loading = false, view = location.hash==="#faces" ? "faces" : location.hash==="#videos" ? "videos" : "photos";
const $ = id => document.getElementById(id);
function node(tag, text, cls) { const el=document.createElement(tag); if(text)el.textContent=text;if(cls)el.className=cls;return el; }
async function load(reset=false) {
  if(loading)return;$('faces-settings').hidden=view!=='faces';loading=true;$("reload-reports").disabled=true;
  try {
    if(reset){before=null;$("report-list").replaceChildren();}
    const sessionResponse=await fetch('/api/status',{cache:'no-store'});
    if(sessionResponse.status===401){window.location.replace('/access');return;}
    const session=await sessionResponse.json();csrf=session.csrf;
    if(!session.authenticated)throw new Error('Abra o painel e entre na sua conta para ver os registros.');
    const response=await fetch(view==='faces'?'/api/faces/list':view==='videos'?'/api/reports/videos':'/api/reports',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({before})});
    const data=await response.json();if(!response.ok)throw new Error(data.message);
    $("report-status").textContent=data.message;
    $("faces-settings").hidden=view!=='faces';
    if(view==='faces'){
      $("faces-enabled").checked=data.enabled;$("faces-status").textContent=(data.enabled?'Captura ativada. ':'Captura desativada. ')+data.message;
      $('faces-diagnostics').replaceChildren();
      for(const item of data.diagnostics||[])$('faces-diagnostics').append(node('p',`${item.camera_name}: ${item.reason} (há ${item.age_seconds}s)`));
      if(!(data.diagnostics||[]).length)$('faces-diagnostics').append(node('p','Ainda sem análise facial. Ative a captura, habilite Detectar pessoas na câmera e aguarde uma janela ativa de monitoramento.'));
    }
    for(const event of data.events){
      if(view==='faces'){renderFace(event);before=event.id;continue;}
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
      info.append(node('h2',view==='videos'?'Vídeo · Pessoa detectada':'Pessoa detectada'));
      if(view==='videos'){
        const label=event.status==='recording'?'Gravando · até 2 minutos':event.status==='failed'?'Não foi possível gravar':`${Math.round(event.duration)} segundos · ${event.status==='partial'?'trecho parcial':'concluído'} · sem áudio`;
        info.append(node('p',label));
        info.append(node('p',event.source==='sd'?`Origem: cartão da câmera · ${event.pre_roll||0}s anteriores confirmados`:`Origem: gravação local · ${event.pre_roll||0}s anteriores disponíveis`));
        const archiveLabels={disk_space:'Sem espaço suficiente para preparar o vídeo do cartão. Vídeo local preservado.',adapter_update_required:'Atualize o adaptador com configure_video.py --update para tentar consultar o cartão.',no_recording:'A câmera não entregou gravação nesse horário; confira cartão e gravação no app Yoosee. Vídeo local preservado.',timestamp_unverified:'Não foi possível confirmar o horário da gravação do cartão. Vídeo local preservado.',fetching:'Buscando a gravação do cartão; o vídeo local continua disponível.',unavailable:'Cartão indisponível ou exportação incompatível. Vídeo local preservado.',busy:'Sem conexão livre para consultar o cartão. Vídeo local preservado.',cooldown:'Consulta ao cartão em espera após falha anterior.',economy_or_disabled:'Consulta ao cartão não iniciada para respeitar economia ou detecção desativada.'};
        if(archiveLabels[event.archive_status])info.append(node('p',archiveLabels[event.archive_status]));
        if(event.reason==='disk_space')info.append(node('p','Espaço em disco insuficiente. Libere espaço para novas gravações.'));
      }
      info.append(node('p',`${event.name} · ${new Date(event.created*1000).toLocaleString('pt-BR')}`));
      if(event.confidence)info.append(node('p',`Confiança do detector: ${Math.round(event.confidence*100)}%`));
      card.append(info);$("report-list").append(card);before=event.id;
    }
    $("older-reports").hidden=data.events.length<24;
    if(reset&&!data.events.length)$("report-list").append(node('p','Ainda não há registros nesta aba. Ative Detectar pessoas nas câmeras desejadas.'));
  }catch(error){$("report-status").textContent=error.message;if(view==='faces')$("faces-status").textContent=error.message+' Se atualizou o projeto, reinicie o serviço DCS e recarregue a página.';}
  finally{loading=false;$("reload-reports").disabled=false;}
}
$("reload-reports").addEventListener('click',()=>load(true));
$("older-reports").addEventListener('click',()=>load());
load(true);

for(const [id,tab] of [['photos-tab','photos'],['videos-tab','videos'],['faces-tab','faces']]) $(id).addEventListener('click',()=>{
  if(loading)return;view=tab;
  $('photos-tab').className=view==='photos'?'selected':'secondary';
  $('videos-tab').className=view==='videos'?'selected':'secondary';
  $('faces-tab').className=view==='faces'?'selected':'secondary';
  location.hash=view;
  load(true);
});

async function settingsRequest(action, body={}) {
  const sessionResponse=await fetch('/api/status',{cache:'no-store'});
  if(sessionResponse.status===401){window.location.replace('/access');throw new Error('Entre no sistema.');}
  const session=await sessionResponse.json();
  if(!session.authenticated)throw new Error('Abra Câmeras e entre na conta Yoosee.');
  const response=await fetch((action.startsWith('faces/')?'/api/'+action:'/api/telegram/'+action),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.message||'Não foi possível configurar Telegram.');
  return data;
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
$('faces-tab').className=view==='faces'?'selected':'secondary';
telegramStatus();

function renderFace(event){
  const card=node('article',null,'report-card face-card');
  const img=node('img');img.src='/api/faces/image/'+event.id;img.alt='Rosto capturado';img.loading='lazy';card.append(img);
  const info=node('div',null,'report-info');
  const label=event.label?'Cadastrado: '+event.label:event.state==='known'?'Possível conhecido: '+event.name:'Pessoa não reconhecida';
  info.append(node('h2',label),node('p',event.camera_name+' · '+new Date(event.created*1000).toLocaleString('pt-BR')));
  if(event.state==='known')info.append(node('p','Sugestão por semelhança facial; confirme antes de cadastrar.'));
  const form=node('form'),input=node('input');input.type='text';input.maxLength=80;input.value=event.label||'';
  input.placeholder='Nome da pessoa';input.setAttribute('aria-label','Nome deste rosto');
  const save=node('button','Salvar nome','secondary'),remove=node('button','Excluir foto','secondary');
  save.type='submit';remove.type='button';form.append(input,save);info.append(form,remove);card.append(info);$('report-list').append(card);
  form.addEventListener('submit',async e=>{e.preventDefault();save.disabled=true;try{await settingsRequest('faces/label',{id:event.id,name:input.value});await load(true);}catch(error){$('report-status').textContent=error.message;}finally{save.disabled=false;}});
  remove.addEventListener('click',async()=>{remove.disabled=true;try{await settingsRequest('faces/delete',{id:event.id});await load(true);}catch(error){$('report-status').textContent=error.message;}finally{remove.disabled=false;}});
}
$('faces-save').addEventListener('click',async()=>{
  try{const data=await settingsRequest('faces/settings',{enabled:$('faces-enabled').checked});$('faces-status').textContent=(data.enabled?'Captura facial ativada. ':'Captura facial desativada. ')+data.message;}
  catch(error){$('faces-status').textContent=error.message;}
});
$('faces-clear').addEventListener('click',async()=>{
  if(!window.confirm('Apagar todos os recortes e nomes desta conta e desativar a captura facial?'))return;
  try{await settingsRequest('faces/clear');await load(true);}catch(error){$('faces-status').textContent=error.message;}
});
