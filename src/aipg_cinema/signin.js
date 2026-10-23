(() => {
  const $=id=>document.getElementById(id), providers=new Map();
  let state=null, busy=false, googleReady=false, discovering=false, googleWidth=0;
  function status(text,failed=false) { $('status').textContent=text; $('status').dataset.error=String(failed); }
  function lock(value) { busy=value; $('wallet').disabled=value || !state; $('google-button').inert=value || !state; $('google-button').setAttribute('aria-disabled',String(value || !state)); for(const button of $('wallet-list').querySelectorAll('button')) button.disabled=value; }
  async function request(path,body) {
    const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...(body ? {method:'POST',headers:{'Content-Type':'application/json','X-Studio-CSRF':state.csrf},body:JSON.stringify(body)} : {})});
    const data=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(typeof data.detail==='string' ? data.detail.slice(0,500) : 'Sign-in is unavailable. Try again.');
    return data;
  }
  function finish() { try { localStorage.setItem('studio-session-version',crypto.randomUUID()); } catch {} location.replace('/'); }
  async function credential(value) {
    if(busy || !state || typeof value.credential!=='string') return;
    lock(true); status('Signing in...');
    try { await request('/auth/google',{id_token:value.credential}); finish(); }
    catch(e) { await recover(e); }
  }
  function initGoogle() {
    if(googleReady || !state || !globalThis.google?.accounts?.id) return;
    googleReady=true;
    google.accounts.id.initialize({client_id:state.google_client_id,callback:credential,auto_select:false,button_auto_select:false,ux_mode:'popup'});
    renderGoogle();
  }
  function renderGoogle() {
    const width=Math.min(360,Math.floor($('google-button').clientWidth));
    if(!googleReady || !width || width===googleWidth) return;
    googleWidth=width;
    google.accounts.id.renderButton($('google-button'),{type:'standard',theme:'outline',size:'large',text:'continue_with',shape:'rectangular',width});
  }
  if(globalThis.ResizeObserver) new ResizeObserver(renderGoogle).observe($('google-button'));
  async function restore() {
    $('retry').hidden=true; lock(true);
    try {
      const data=await request('/auth/session');
      if(data.authenticated) { location.replace('/'); return; }
      state=data; lock(false); status(''); initGoogle(); return true;
    } catch(e) { state=null; lock(false); status(e.message,true); $('retry').hidden=false; return false; }
  }
  async function recover(failure) {
    // Recover sign-in state only; never replay a proof or wallet request.
    if(await restore()) status(failure.message,true);
  }
  async function connect(provider) {
    if(busy || !state) return;
    lock(true); status('Connecting wallet...');
    try {
      const addresses=await provider.request({method:'eth_requestAccounts'});
      const address=addresses?.[0];
      if(typeof address!=='string' || !/^0x[0-9a-fA-F]{40}$/.test(address)) throw new Error('Wallet did not return an EVM address.');
      const challenge=await request('/auth/wallet/challenge',{address});
      status('Confirm the sign-in message in your wallet.');
      const encoded='0x'+Array.from(new TextEncoder().encode(challenge.message),byte=>byte.toString(16).padStart(2,'0')).join('');
      const signature=await provider.request({method:'personal_sign',params:[encoded,address]});
      await request('/auth/wallet',{signature}); finish();
    } catch(e) { await recover(new Error(e.code===4001 ? 'Wallet sign-in cancelled.' : (e.message || 'Wallet sign-in failed.'))); }
  }
  function listWallets() {
    $('wallet-list').replaceChildren();
    for(const {provider,name} of providers.values()) {
      const button=document.createElement('button'); button.textContent=name; button.disabled=busy;
      button.addEventListener('click',()=>connect(provider)); $('wallet-list').append(button);
    }
    if(!providers.size) status('No compatible wallet found. You can continue with Google.',true);
  }
  $('wallet').addEventListener('click',()=>{
    if(busy || !state) return;
    if(!discovering) {
      discovering=true;
      window.addEventListener('eip6963:announceProvider',event=>{
        const detail=event.detail;
        if(!detail?.provider || typeof detail.provider.request!=='function' || typeof detail.info?.uuid!=='string' || typeof detail.info?.name!=='string' || providers.size>=16) return;
        providers.set(detail.info.uuid,{provider:detail.provider,name:detail.info.name.slice(0,80)}); listWallets();
      });
    }
    window.dispatchEvent(new Event('eip6963:requestProvider'));
    setTimeout(()=>{
      if(!providers.size && typeof globalThis.ethereum?.request==='function') providers.set('injected',{provider:ethereum,name:'Browser wallet'});
      listWallets();
    },150);
  });
  $('retry').addEventListener('click',restore);
  const script=document.createElement('script'); script.src='https://accounts.google.com/gsi/client'; script.async=true; script.onload=initGoogle;
  script.onerror=()=>status('Google sign-in could not load. Try again or use a wallet.',true);
  document.head.append(script);
  restore();
})();
