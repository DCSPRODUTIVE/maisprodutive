/* Explicit local export only. No analytics endpoint or automatic transmission. */
(() => {
  const button=document.getElementById('copy-diagnostics');
  if(!button)return;
  const output=document.getElementById('diagnostics-output'),message=document.getElementById('diagnostics-message');
  button.addEventListener('click',async()=>{
    button.disabled=true;message.textContent='Reunindo diagnóstico das câmeras…';
    try{
      const status=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(12000)});
      const session=await status.json();if(!status.ok||!session.authenticated){output.value='';output.hidden=true;throw new Error('Entre na conta para copiar os logs.');}
      const match=(navigator.userAgent||'').match(/(Chrome|Firefox|Edg|Safari)\/([0-9.]+)/);
      const client={...(window.dcsClientDiagnostics?.()||{}),width:innerWidth,height:innerHeight,browser:match?match[0]:'unknown',timezone:Intl.DateTimeFormat().resolvedOptions().timeZone};
      const response=await fetch('/api/diagnostics',{method:'POST',cache:'no-store',signal:AbortSignal.timeout(15000),
        headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify({client})});
      const data=await response.json();if(!response.ok)throw new Error(data.message||'Não foi possível gerar os logs.');
      output.value='TORRE DE CONTROLE DCS — DIAGNÓSTICO\n'+JSON.stringify(data,null,2);
      output.hidden=false;
      let copied=false;
      try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(output.value);copied=true;}}catch{}
      if(!copied){output.focus();output.select();try{copied=document.execCommand('copy');}catch{}}
      message.textContent=copied?'Logs copiados. Cole aqui na conversa.':'Diagnóstico pronto e selecionado. Pressione Ctrl+C para copiar e cole na conversa.';
    }catch(error){message.textContent=error.name==='TimeoutError'?'O servidor não respondeu ao diagnóstico. Verifique o túnel ou tente pelo endereço local.':error.message;}
    finally{button.disabled=false;}
  });
})();
