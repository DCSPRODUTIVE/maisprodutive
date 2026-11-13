/* Secrets are write-only; only the owner's authenticated settings are queried. */
async function aiStatus() {
  try {
    const data=await settingsRequest('ai/status');
    $('ai-enabled').checked=data.enabled;
    $('ai-events').checked=data.event_descriptions;
    $('ai-conversation').checked=data.conversation;
    $('ai-model').value=data.model;
    $('ai-limit').value=data.daily_limit;
    $('ai-key').placeholder=data.configured?'Chave salva. Deixe vazio para manter.':'Cole a chave da API Google';
    $('ai-status').textContent=`${data.enabled?'IA ativada':'IA desativada'} · ${data.used_today}/${data.daily_limit} consultas hoje (UTC). ${data.message}`+(data.retry_after_seconds?` Espera restante: ${data.retry_after_seconds}s. Última falha: ${data.last_failure}`:'');
  } catch(error) { $('ai-status').textContent=error.message; }
}
$('ai-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter;if(button)button.disabled=true;
  const key=$('ai-key').value.trim();$('ai-key').value='';
  try {
    await settingsRequest('ai/save',{
      api_key:key,enabled:$('ai-enabled').checked,event_descriptions:$('ai-events').checked,
      conversation:$('ai-conversation').checked,model:$('ai-model').value.trim(),
      daily_limit:Number($('ai-limit').value)
    });
    await aiStatus();
  } catch(error) { $('ai-status').textContent=error.message; }
  finally { if(button)button.disabled=false; }
});
$('ai-refresh').addEventListener('click',aiStatus);
$('ai-test').addEventListener('click',async()=>{
  $('ai-test').disabled=true;
  try { $('ai-status').textContent=(await settingsRequest('ai/test')).message; }
  catch(error) { $('ai-status').textContent=error.message; }
  finally { $('ai-test').disabled=false; }
});
aiStatus();
