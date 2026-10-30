const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
process.env.TZ='America/Sao_Paulo';
class Element {
  constructor(){this.children=[];this.handlers={};this.value='';}
  append(...items){this.children.push(...items);}
  replaceChildren(){this.children=[];}
  addEventListener(name,handler){this.handlers[name]=handler;}
}
async function setup(records,cardStatus=null,videos=[]){
  const elements=new Map(),calls=[];
  const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const fetch=async(path,options)=>{
    const body=options?.body?JSON.parse(options.body):{};calls.push({path,body});let data={};
    if(path==='/api/status')data={csrf:'test',authenticated:true,devices:[{id:'owned',name:'Portão'}]};
    if(path==='/api/reports')data={message:'Fotos',events:[]};
    if(path==='/api/reports/videos')data={message:'Vídeos',events:videos};
    if(path==='/api/telegram/status')data={enabled:false,configured:false,chat_id:'',message:'Sem envio.'};
    if(path==='/api/card/start')data={job_id:'job'};
    if(path==='/api/card/status')data=cardStatus||{status:'done',records};
    return {ok:true,json:async()=>data};
  };
  const context={fetch,Date,location:{hash:''},document:{getElementById:get,createElement:()=>new Element()},setTimeout:()=>{},window:{location:{replace:()=>{}}}};
  vm.createContext(context);vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../web/reports.js'),'utf8'),context);
  await new Promise(setImmediate);
  return {context,get,calls};
}
test('selecting a card recording preserves seconds, milliseconds and local timezone',async()=>{
  const start=new Date('2026-10-29T15:36:15.123-03:00').getTime()/1000,end=start+64;
  const {context,get,calls}=await setup([{start,end}]);
  get('card-camera').value='owned';get('card-from').value='2026-10-29T15:37:00';get('card-to').value='2026-10-29T15:38:00';
  await context.cardRequest('list');
  const button=get('card-results').children[0].children[1];button.handlers.click();
  assert.equal(get('card-from').value,'2026-10-29T15:36:15.123');
  assert.equal(get('card-to').value,'2026-10-29T15:37:19.123');
  await context.cardRequest('backup');
  const request=calls.filter(c=>c.path==='/api/card/start').at(-1);
  assert.equal(request.body.start,start);assert.equal(request.body.end,end);
});
test('choosing a long file limits backup to two minutes without rounding its start',async()=>{
  const start=new Date('2026-10-29T15:36:15-03:00').getTime()/1000;
  const {context,get}=await setup([{start,end:start+600}]);
  get('card-camera').value='owned';get('card-from').value='2026-10-29T15:36:00';get('card-to').value='2026-10-29T15:37:00';
  await context.cardRequest('list');get('card-results').children[0].children[1].handlers.click();
  assert.equal(new Date(get('card-to').value)-new Date(get('card-from').value),120000);
  assert.equal(new Date(get('card-from').value).getTime()/1000,start);
});

test('failed manual backup shows a useful diagnostic without claiming a local video exists',async()=>{
  const diagnostic={stage:3,frames:12,clock_callbacks:0,clock_unit:0,clock_delta_ms:0};
  const {context,get}=await setup([],{status:'timestamp_unverified',diagnostic},[{id:1,name:'Portão',source:'sd_requested',status:'failed',archive_status:'timestamp_unverified',archive_diagnostic:diagnostic,created:1,duration:0}]);
  get('card-from').value='2026-10-29T15:36:15';get('card-to').value='2026-10-29T15:37:19';
  await context.cardRequest('backup');
  assert.match(get('card-status').textContent,/posicionamento · 12 quadros · 0 retornos/);
  get('videos-tab').handlers.click();await new Promise(setImmediate);
  const texts=el=>[el.textContent||'',...el.children.flatMap(texts)];
  const rendered=texts(get('report-list')).join(' ');
  assert.match(rendered,/Nenhum backup foi salvo/);assert.doesNotMatch(rendered,/Vídeo local preservado/);
});

test('confirmed SD partial has a download and is never labeled complete',async()=>{
  const {context,get}=await setup([],{status:'partial',record_id:2},[{id:2,name:'Portão',source:'sd_partial',status:'partial',archive_status:'ready',duration:56.762,archive_start:1800000000,archive_end:1800000056.762,created:1}]);
  get('card-from').value='2026-10-29T18:02:20.421';get('card-to').value='2026-10-29T18:03:24.381';
  await context.cardRequest('backup');
  assert.match(get('card-status').textContent,/vídeo parcial/);
  assert.equal(get('card-results').children[0].href,'/api/reports/download/2');
  get('videos-tab').handlers.click();await new Promise(setImmediate);
  const texts=el=>[el.textContent||'',...el.children.flatMap(texts)];const rendered=texts(get('report-list')).join(' ');
  assert.match(rendered,/Trecho parcial do cartão/);assert.match(rendered,/vídeo local original mantido/);
  assert.match(rendered,/Horário confirmado/);assert.doesNotMatch(rendered,/concluído/);
});
