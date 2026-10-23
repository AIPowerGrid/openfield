(() => {
  const state=globalThis.studioSession;
  if(state?.mode!=='hosted') return;
  const button=document.getElementById('sign-out');
  button.hidden=false;
  window.addEventListener('storage',event=>{
    if(event.key==='studio-session-version') location.replace('/');
  });
  button.addEventListener('click',async()=>{
    button.disabled=true;
    try {
      if(typeof saveDraft==='function') saveDraft();
      const response=await fetch('/auth/logout',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Studio-CSRF':state.csrf},body:'{}'});
      if(!response.ok) throw new Error('Sign-out failed. Reload the page and try again.');
      try { localStorage.setItem('studio-session-version',crypto.randomUUID()); } catch {}
      location.replace('/signin');
    } catch(e) {
      if(typeof error==='function') error(e.message);
      button.disabled=false;
    }
  });
})();
