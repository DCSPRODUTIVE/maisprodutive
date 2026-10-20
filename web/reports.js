let csrf = "", before = null, loading = false;
const $ = id => document.getElementById(id);
function node(tag, text, cls) { const el=document.createElement(tag); if(text)el.textContent=text;if(cls)el.className=cls;return el; }
async function load(reset=false) {
  if(loading)return;loading=true;$("reload-reports").disabled=true;
  try {
    if(reset){before=null;$("report-list").replaceChildren();}
    const session=await fetch('/api/status',{cache:'no-store'}).then(r=>r.json());csrf=session.csrf;
    if(!session.authenticated)throw new Error('Abra o painel e entre na sua conta para ver os registros.');
    const response=await fetch('/api/reports',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({before})});
    const data=await response.json();if(!response.ok)throw new Error(data.message);
    $("report-status").textContent=data.message;
    for(const event of data.events){
      const card=node('article',null,'report-card');
      if(event.has_image){
        const media=node('div',null,'report-image'),img=node('img');
        img.src=`/api/reports/image/${event.id}`;img.alt=`Registro de ${event.name}`;img.loading='lazy';media.append(img);
        for(const box of event.boxes){const overlay=node('span',null,'report-box');
          // Geometry comes only from our detector; clamp before assigning CSS.
          const [x1,y1,x2,y2]=box.map(n=>Math.max(0,Math.min(1,Number(n)||0)));
          Object.assign(overlay.style,{left:`${x1*100}%`,top:`${y1*100}%`,width:`${(x2-x1)*100}%`,height:`${(y2-y1)*100}%`});media.append(overlay);}
        card.append(media);
      }
      const info=node('div',null,'report-info');
      info.append(node('h2',event.kind==='person'?'Pessoa detectada':'Câmera aberta'));
      info.append(node('p',`${event.name} · ${new Date(event.created*1000).toLocaleString('pt-BR')}`));
      if(event.confidence)info.append(node('p',`Confiança do detector: ${Math.round(event.confidence*100)}%`));
      card.append(info);$("report-list").append(card);before=event.id;
    }
    $("older-reports").hidden=data.events.length<24;
    if(reset&&!data.events.length)$("report-list").append(node('p','Ainda não há registros. Abra as câmeras para iniciar o monitoramento.'));
  }catch(error){$("report-status").textContent=error.message;}
  finally{loading=false;$("reload-reports").disabled=false;}
}
$("reload-reports").addEventListener('click',()=>load(true));
$("older-reports").addEventListener('click',()=>load());
load(true);
