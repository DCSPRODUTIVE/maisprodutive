document.getElementById('access-form').addEventListener('submit', async event => {
  event.preventDefault();
  const input=document.getElementById('access-password'),button=document.getElementById('access-submit'),message=document.getElementById('access-message');
  const password=input.value;input.value='';button.disabled=true;
  try {
    const response=await fetch('/api/access/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password}),signal:AbortSignal.timeout(12000)});
    const data=await response.json();
    if(!response.ok)throw new Error(data.message||'Não foi possível entrar.');
    window.location.replace('/');
  }catch(error){message.textContent=error.name==='TimeoutError'?'O servidor não respondeu. Tente novamente.':error.message;}
  finally{button.disabled=false;}
});
