const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
async function setup(extra={}){
  const elements=new Map(),calls=[];
  const get=id=>{if(!elements.has(id))elements.set(id,{value:'',checked:false,handlers:{},addEventListener(name,fn){this.handlers[name]=fn;}});return elements.get(id);};
  const config={enabled:true,event_descriptions:true,conversation:true,configured:true,model:'gemini-flash-latest',daily_limit:60,used_today:2,message:'Pronto',...extra};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/ai.js'),'utf8'),{
    $:get,settingsRequest:async(action,body)=>{calls.push({action,body});return action==='ai/test'?{message:'Teste enfileirado, sem fotos.'}:config;}
  });
  await new Promise(setImmediate);return {get,calls};
}
test('diagnostic button uses server configuration without sending the key again',async()=>{
  const {get,calls}=await setup();get('ai-key').value='must-not-be-sent';
  await get('ai-test').handlers.click();
  const call=calls.find(c=>c.action==='ai/test');assert.ok(call);assert.equal(call.body,undefined);
  assert.match(get('ai-status').textContent,/sem fotos/);assert.equal(get('ai-test').disabled,false);
});
test('status shows original failure and time remaining without exposing a key',async()=>{
  const {get}=await setup({retry_after_seconds:45,last_failure:'HTTP 404'});
  assert.match(get('ai-status').textContent,/45s/);assert.match(get('ai-status').textContent,/HTTP 404/);
  assert.equal(get('ai-model').value,'gemini-flash-latest');
});
