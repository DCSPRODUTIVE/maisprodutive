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
      info.append(node('h2',view==='videos'?'Vídeo · Pessoa detectada':'Pessoa detectada'));
      if(view==='videos'){
        const label=event.status==='recording'?'Gravando · até 2 minutos':event.status==='failed'?'Não foi possível gravar':`${Math.round(event.duration)} segundos · ${event.status==='partial'?'trecho parcial':'concluído'} · sem áudio`;
        info.append(node('p',label));
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
  load(true);
});

async function telegramRequest(action, body={}) {
  const sessionResponse=await fetch('/api/status',{cache:'no-store'});
  if(sessionResponse.status===401){window.location.replace('/access');throw new Error('Entre no sistema.');}
  const session=await sessionResponse.json();
  if(!session.authenticated)throw new Error('Abra Câmeras e entre na conta Yoosee.');
  const response=await fetch('/api/telegram/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw new Error(data.message||'Não foi possível configurar Telegram.');
  return data;
}
async function telegramStatus() {
  try{
    const data=await telegramRequest('status');
    $('telegram-enabled').checked=data.enabled;$('telegram-chat').value=data.chat_id;
    $('telegram-token').placeholder=data.configured?'Token salvo. Deixe vazio para manter.':'Cole o token do BotFather';
    $('telegram-status').textContent=(data.enabled?'Alertas ativados. ':'Alertas desativados. ')+data.message;
  }catch(error){$('telegram-status').textContent=error.message;}
}
$('telegram-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter;if(button)button.disabled=true;
  try{
    await telegramRequest('save',{enabled:$('telegram-enabled').checked,chat_id:$('telegram-chat').value.trim(),token:$('telegram-token').value.trim()});
    $('telegram-token').value='';await telegramStatus();
  }catch(error){$('telegram-status').textContent=error.message;}
  finally{if(button)button.disabled=false;}
});
$('telegram-test').addEventListener('click',async()=>{
  $('telegram-test').disabled=true;
  try{$('telegram-status').textContent=(await telegramRequest('test')).message;}
  catch(error){$('telegram-status').textContent=error.message;}
  finally{$('telegram-test').disabled=false;}
});
$('telegram-refresh').addEventListener('click',telegramStatus);
$('photos-tab').className=view==='photos'?'selected':'secondary';
$('videos-tab').className=view==='videos'?'selected':'secondary';
telegramStatus();
