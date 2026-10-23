/* Product shorts: brief + photos plan the board; looks use the real photo as a
   reference and the packshot is composed locally. Nothing renders without an
   explicit button press, and a pending look is retried only by its saved ID. */
let productLook=saved('studio-product-look'), productBusy=false, productTimer=null;
globalThis.pendingProductProject=()=>productLook?.project_id || null;
function productProject() { return shortProject?.product ? shortProject : null; }
function isPackshot(shot) { return !!shot && productProject()?.product.packshot_shot_id===shot.id; }
// Continuity anchors on the Reveal shot's look so every shot matches one
// approved model; chaining shot to shot carried a print glitch forward.
// Without a reveal look, use the nearest other scene shot. Packshots never count.
function previousLook(shot) {
  const shots=shortProject.shots.filter(s=>s.id!==shot.id && !isPackshot(s) && s.draft.look_id);
  const reveal=shots.find(s=>s.beat==='reveal');
  if(reveal) return reveal.draft.look_id;
  const index=shortProject.shots.findIndex(s=>s.id===shot.id);
  const distance=s=>Math.abs(shortProject.shots.findIndex(x=>x.id===s.id)-index);
  return shots.sort((a,b)=>distance(a)-distance(b))[0]?.draft.look_id || null;
}
function productStatus(text) { $('product-status').textContent=text || ''; }
// Template starters: approved shorts as plans (never media or keys).
let shortTemplates=[], selectedTemplate=null;
async function drawTemplates() {
  try { shortTemplates=await api('/api/templates'); } catch(e) { shortTemplates=[]; }
  const gallery=$('template-gallery'); gallery.replaceChildren();
  for(const t of shortTemplates) {
    const card=document.createElement('div'); card.className='template-card'+(selectedTemplate?.id===t.id ? ' selected' : '');
    const media=document.createElement(t.preview_url ? 'video' : 'div');
    if(t.preview_url) Object.assign(media,{src:t.preview_url,muted:true,loop:true,autoplay:true,playsInline:true}); else media.className='blank';
    const name=document.createElement('span'); name.textContent=t.name;
    const use=document.createElement('button'); use.type='button'; use.className='text-button';
    use.textContent=selectedTemplate?.id===t.id ? 'Selected (click to clear)' : 'Use as template';
    use.onclick=()=>{ selectedTemplate=selectedTemplate?.id===t.id ? null : t; applyTemplateFields(); drawTemplates(); };
    card.append(media,name,use); gallery.append(card);
  }
  $('template-status').textContent=selectedTemplate ? `Using "${selectedTemplate.name}": pacing, camera moves, captions and music come from it. Add your photo and product.` : '';
}
function applyTemplateFields() {
  const t=selectedTemplate; if(!t) return;
  $('product-tone').value=t.tone; $('product-pacing').value=t.pacing;
  $('product-captions').value=t.captions; $('product-worn').checked=t.worn;
}
function productForm() {
  const product=$('new-project-structure').value==='product';
  $('product-fields').hidden=!product;
  if(product) drawTemplates();
  for(const id of ['product-photos','product-name']) $(id).required=product;
}
// Uploaded photos are remembered per file so drafting and creating share them.
const productUploads=new Map();
async function uploadProductPhoto(file) {
  const key=[file.name,file.size,file.lastModified].join(':');
  if(!productUploads.has(key)) {
    const body=new FormData(); body.append('file',file);
    productUploads.set(key,(await api('/api/products',{method:'POST',body})).product_id);
  }
  return productUploads.get(key);
}
async function prepareProduct() {
  if($('new-project-structure').value!=='product') return {};
  const files=[...$('product-photos').files];
  if(!files.length || files.length>3) throw new Error('Choose one to three product photos.');
  const photo_ids=[];
  for(const file of files) photo_ids.push(await uploadProductPhoto(file));
  const value=id=>$(id).value.trim();
  return {template_id:selectedTemplate?.id || null, product:{photo_ids,brief:{
    name:value('product-name'),audience:value('product-audience'),tone:$('product-tone').value,
    setting:value('product-setting'),tagline:value('product-tagline'),cta:value('product-cta'),worn:$('product-worn').checked,hook:value('product-hook'),captions:$('product-captions').value,pacing:$('product-pacing').value,
    benefits:['product-benefit-1','product-benefit-2','product-benefit-3'].map(value).filter(Boolean),
  }}};
}
function drawProduct() {
  const project=productProject(), shot=activeShot();
  $('product-panel').hidden=!project || !shot;
  if(!project || !shot) return;
  const photos=$('product-thumbs');
  if(photos.dataset.key!==project.product.photo_ids.join()) {
    photos.dataset.key=project.product.photo_ids.join(); photos.replaceChildren();
    for(const id of project.product.photo_ids) { const image=document.createElement('img'); image.src=`/api/products/${id}`; image.alt='Product photo'; photos.append(image); }
  }
  const packshot=isPackshot(shot);
  $('product-look').hidden=packshot; $('product-refine-label').hidden=packshot || !config.product_refine;
  // Matching a previous shot's look only matters for a worn model.
  const continues=!packshot && !!project.product.brief.worn && !!previousLook(shot);
  $('product-continuity-label').hidden=!continues;
  if(continues && $('product-continuity').dataset.shot!==shot.id) { $('product-continuity').dataset.shot=shot.id; $('product-continuity').checked=!!project.product.brief.worn; }
  $('product-packshot').hidden=!packshot; $('product-accent-label').hidden=!packshot;
  const take=takes.find(t=>t.id===shot.selected_take_id);
  $('product-hint').textContent=packshot
    ? 'The closing card is built from your real photo, name and call to action.'
    : take ? 'This shot is done. Make another version, or open the next shot.'
    : shot.draft.look_id ? 'The look is set. Animate it with Generate take.'
    : 'Start with a look: your real product placed in this shot\'s scene.';
  const mine=productLook && productLook.project_id===project.id && productLook.shot_id===shot.id;
  $('product-look').querySelector('span').textContent=mine ? 'Check product look' : 'Generate product look';
  $('product-recover').hidden=!(mine && productLook.status==='needs_recovery');
}
// Product shorts open in a simple shot panel; Pro reveals prompts, frames
// and seeds. Shot status drives the storyboard chips.
let proMode=localStorage.getItem('openfield-pro')==='1';
function drawSimple() {
  const product=!!productProject();
  document.body.classList.toggle('simple',product && !proMode);
  // Leaving a product short must not leave its panel behind.
  if(!product) $('product-panel').hidden=true;
  $('pro-toggle').hidden=!product;
  $('pro-toggle').setAttribute('aria-pressed',String(proMode));
  $('pro-toggle').textContent=proMode ? 'Hide Pro controls' : 'Pro controls: prompts, frames, seed';
}
$('pro-toggle').onclick=()=>{proMode=!proMode; try {localStorage.setItem('openfield-pro',proMode ? '1' : '0');} catch(e) {} drawSimple();};
const TERMINAL=['succeeded','failed','cancelled','needs_review'];
globalThis.shotStatus=(shot,take)=>{
  if(take?.output_url) return ['Done','done'];
  if(takes.some(t=>t.shot_id===shot.id && t.project_id===shortProject?.id && (t.active || !TERMINAL.includes(t.status)))) return ['Rendering','working'];
  if(productLook && productLook.shot_id===shot.id) return ['Making look','working'];
  if(isPackshot(shot)) return ['Closing card',''];
  if(shot.draft.look_id) return ['Look ready',''];
  return ['Planned',''];
};
globalThis.shotStatusKey=()=>[productLook?.shot_id || '',takes.filter(t=>t.project_id===shortProject?.id).map(t=>t.status).join()].join('|');
function productControls(frozen) {
  drawSimple();
  // Only the next step is orange: look, then take; a finished shot has none.
  const next=productProject() && activeShot() && !isPackshot(activeShot()) ? (activeShot().selected_take_id ? null : activeShot().draft.look_id ? 'generate' : 'product-look') : 'generate';
  $('product-look').classList.toggle('quiet',next!=='product-look');
  $('generate').classList.toggle('quiet',next!=='generate');
  const project=productProject(), shot=activeShot();
  const busy=frozen || productBusy || variantBusy || !!pending || submitting;
  $('product-look-3').disabled=busy || !project || isPackshot(shot) || !config.look_connected || !!productLook;
  $('generate-3').hidden=!shot || isPackshot(shot);
  $('generate-3').disabled=busy || !shot || (shot.draft.mode==='image' && !shot.draft.look_id);
  drawEstimates();
  const lookFree=!productLook || (productLook.project_id===project?.id && productLook.shot_id===shot?.id);
  $('product-look').disabled=busy || !project || isPackshot(shot) || !config.look_connected || !lookFree;
  $('product-packshot').disabled=busy || !project || !isPackshot(shot);
  // The packshot is never an LTX render.
  if(isPackshot(shot)) $('generate').disabled=true;
}
function rememberLook(item) {
  productLook=item; if(item) localStorage.setItem('studio-product-look',JSON.stringify(item)); else localStorage.removeItem('studio-product-look');
}
async function useProductLook(item) {
  const shot=shortProject?.shots.find(s=>s.id===item.shot_id);
  if(shortProject?.id!==item.project_id || !shot) return;
  shot.draft.mode='image'; shot.draft.look_id=item.look_id;
  if(shot.id===activeShotId) { inputMode='image'; lookId=item.look_id; }
  markBoard(); await saveBoard(); await showShot();
}
async function pollProductLook() {
  clearTimeout(productTimer);
  if(!productLook?.id) return;
  try {
    const item=await api(`/api/product-looks/${productLook.id}`);
    rememberLook({...productLook,...item});
    productStatus(item.status==='succeeded' ? `${item.model} / ${item.elapsed_seconds ? item.elapsed_seconds.toFixed(1)+'s' : 'ready'}` : states[item.status] || item.status);
    if(item.status==='succeeded') { const done=productLook; rememberLook(null); if(done.variant) addVariant('look',done); else await useProductLook(done); }
    else if(['failed','cancelled','needs_review'].includes(item.status)) { if(item.error) error(item.error); rememberLook(null); }
    else if(item.active) productTimer=setTimeout(pollProductLook,3000);
  } catch(e) { productStatus('Status unavailable'); productTimer=setTimeout(pollProductLook,6000); }
  finally { drawProduct(); if(shortProject) drawBoard(); controls(); }
}
$('product-look').onclick=async()=>{
  const project=productProject(), shot=activeShot();
  if(productBusy || !project || !shot) return;
  productBusy=true; controls(); error('');
  try {
    captureShot(); await saveBoard();
    const previous=$('product-continuity').checked ? previousLook(shot) : null;
    if(!productLook) rememberLook({project_id:project.id,shot_id:shot.id,request_id:crypto.randomUUID().replaceAll('-',''),revision:shortProject.revision,seed:Number($('seed').value),refine:$('product-refine').checked && !!config.product_refine,continuity_look_id:previous});
    const p=productLook;
    const item=await api(`/api/projects/${p.project_id}/shots/${p.shot_id}/product-look`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:p.request_id,revision:p.revision,seed:p.seed,refine:p.refine,continuity_look_id:p.continuity_look_id || null})});
    rememberLook({...p,...item}); await pollProductLook();
  } catch(e) {
    if(e.status && e.status<500) rememberLook(null);
    error(e.message);
  } finally { productBusy=false; drawProduct(); controls(); }
};
$('product-recover').onclick=async()=>{
  if(!productLook?.id) return;
  try { rememberLook({...productLook,...await api(`/api/product-looks/${productLook.id}/resume`,{method:'POST'})}); await pollProductLook(); }
  catch(e) { error(e.message); }
};
$('product-packshot').onclick=async()=>{
  const project=productProject(), shot=activeShot();
  if(productBusy || !isPackshot(shot)) return;
  productBusy=true; controls(); error(''); productStatus('Composing packshot');
  try {
    captureShot(); await saveBoard();
    const result=await api(`/api/projects/${project.id}/shots/${shot.id}/packshot`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),revision:shortProject.revision,accent:$('product-accent').value})});
    await refresh(); await loadBoard(result.project.id,shot.id,true);
    productStatus('Packshot ready');
  } catch(e) { productStatus(''); error(e.message); }
  finally { productBusy=false; drawProduct(); controls(); }
};
$('product-fill').onclick=async()=>{
  const file=$('product-photos').files[0];
  if(!file) {error('Choose a product photo first.'); return;}
  $('product-fill').disabled=true; error(''); $('product-fill-status').textContent='Drafting from photo';
  try {
    const id=await uploadProductPhoto(file);
    const result=await api(`/api/products/${id}/brief`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('product-name').value.trim()})});
    const b=result.brief, set=(field,value)=>{if(value!==undefined) $(field).value=value;};
    set('product-name',b.name); set('product-tone',b.tone); set('product-setting',b.setting);
    set('product-tagline',b.tagline); set('product-cta',b.cta); set('product-hook',b.hook);
    ['product-benefit-1','product-benefit-2','product-benefit-3'].forEach((field,i)=>set(field,b.benefits[i] || ''));
    // A chosen template decides tone and pacing; the draft fills the rest.
    applyTemplateFields();
    const pattern=result.hook_pattern ? ` / ${result.hook_pattern} hook` : '';
    $('product-fill-status').textContent=`Drafted by ${result.model}${pattern} / USD ${result.cost_usd.toFixed(4)} / review and edit`;
  } catch(e) {$('product-fill-status').textContent=''; error(e.message);}
  finally {$('product-fill').disabled=false;}
};
// Camera presets: a picked move replaces the camera sentence, keeps any sound
// line, sets the recommended trim and records id@version on the shot.
function cameraPresets() { return config.presets || []; }
function drawCamera() {
  const shot=activeShot(), menu=$('camera-preset'), list=cameraPresets();
  $('camera-presets').hidden=!shot || shot.draft.mode!=='image' || isPackshot(shot) || !list.length;
  if($('camera-presets').hidden) return;
  if(menu.options.length!==list.length+1) {
    menu.replaceChildren(new Option('Custom',''));
    for(const [kind,label] of [['camera','Camera moves'],['effect','Effects (opt-in)']]) {
      const group=document.createElement('optgroup'); group.label=label;
      for(const p of list.filter(p=>(p.kind || 'camera')===kind)) group.append(new Option(p.name,p.id));
      if(group.children.length) menu.append(group);
    }
  }
  const id=(shot.camera || '').split('@')[0], preset=list.find(p=>p.id===id);
  menu.value=preset ? preset.id : '';
  const video=$('camera-preview');
  video.hidden=!preset; $('camera-placeholder').hidden=!!preset;
  $('camera-name').textContent=preset ? `${preset.name}${preset.kind==='effect' ? ' (effect)' : ''}` : 'Custom';
  if(preset && video.getAttribute('src')!==preset.preview_url) video.src=preset.preview_url;
}
$('camera-preset').onchange=()=>{
  const shot=activeShot(), preset=cameraPresets().find(p=>p.id===$('camera-preset').value);
  if(!shot) return;
  if(!preset) {shot.camera=null; markBoard(); drawCamera(); return;}
  const sound=($('motion-prompt').value.match(/Sound:[^]*$/) || [''])[0];
  $('motion-prompt').value=[preset.motion,sound].filter(Boolean).join(' ');
  shot.camera=`${preset.id}@${preset.version}`;
  shot.trim_start=0; shot.trim_end=preset.trim_end;
  $('trim-start').value='0.000'; $('trim-end').value=(preset.trim_end/24).toFixed(3);
  captureShot(); markBoard(); drawBoard(true); drawCamera();
};
// One generated track under the whole short; the server mutes shot sound.
$('generate-music').onclick=async()=>{
  if(!shortProject) return;
  $('generate-music').disabled=true; error(''); $('music-status').textContent='Composing with ACE-Step';
  try {
    captureShot(); await saveBoard();
    const result=await api(`/api/projects/${shortProject.id}/music`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),revision:shortProject.revision})});
    await loadBoard(result.project.id,activeShotId,true);
    $('music-status').textContent=`${result.music.model} / ${result.music.seconds}s track / shot sound muted`;
  } catch(e) {$('music-status').textContent=''; error(e.message);}
  finally {$('generate-music').disabled=false;}
};
// Variants: three versions of one look or take (consecutive seeds), run one at
// a time, shown side by side; nothing is selected until the user picks one.
let variantSet=saved('studio-variants'), variantBusy=false;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function rememberVariants(value) { variantSet=value; if(value) localStorage.setItem('studio-variants',JSON.stringify(value)); else localStorage.removeItem('studio-variants'); drawVariants(); }
function addVariant(kind,item) {
  const shot=activeShot(); if(!shot) return;
  const set=variantSet?.shot_id===shot.id && variantSet.kind===kind ? variantSet : {kind,project_id:shortProject.id,shot_id:shot.id,ids:[]};
  const id=kind==='look' ? item.look_id : item.id;
  if(id && !set.ids.includes(id)) set.ids.push(id);
  rememberVariants({...set});
}
function drawVariants() {
  const grid=$('variant-grid'), shot=activeShot();
  const set=variantSet && shot && variantSet.shot_id===shot.id ? variantSet : null;
  grid.hidden=!set; grid.replaceChildren(); if(!set) return;
  for(const id of set.ids) {
    const cell=document.createElement('div'); cell.className='variant';
    let media;
    if(set.kind==='look') { media=document.createElement('img'); media.src=`/api/looks/${id}`; media.alt='Version'; }
    else {
      const take=takes.find(t=>t.id===id);
      media=document.createElement(take?.output_url ? 'video' : 'div');
      if(take?.output_url) Object.assign(media,{src:take.output_url,muted:true,loop:true,autoplay:true,playsInline:true});
      else media.textContent=states[take?.status] || 'Rendering';
    }
    const pick=document.createElement('button'); pick.type='button'; pick.className='text-button';
    const chosen=set.kind==='look' ? shot.draft.look_id===id : shot.selected_take_id===id;
    pick.textContent=chosen ? 'Picked' : 'Use this'; pick.disabled=chosen || (set.kind==='take' && !takes.find(t=>t.id===id)?.output_url);
    pick.onclick=async()=>{
      try {
        if(set.kind==='look') await useProductLook({project_id:set.project_id,shot_id:set.shot_id,look_id:id});
        else { shot.selected_take_id=id; markBoard(); await saveBoard(); drawBoard(true); }
        drawVariants();
      } catch(e) { error(e.message); }
    };
    cell.append(media,pick); grid.append(cell);
  }
}
async function lookVariants() {
  const project=productProject(), shot=activeShot();
  if(variantBusy || !project || !shot || isPackshot(shot)) return;
  variantBusy=true; controls(); error('');
  rememberVariants({kind:'look',project_id:project.id,shot_id:shot.id,ids:[]});
  try {
    captureShot(); await saveBoard();
    const used=new Set(lookJobs.filter(l=>l.shot_id===shot.id).map(l=>Number(l.seed)));
    let base=Number($('seed').value); while([0,1,2].some(i=>used.has(base+i))) base++;
    const previous=$('product-continuity').checked ? previousLook(shot) : null;
    for(let i=0;i<3;i++) {
      rememberLook({project_id:project.id,shot_id:shot.id,request_id:crypto.randomUUID().replaceAll('-',''),revision:shortProject.revision,seed:base+i,refine:$('product-refine').checked && !!config.product_refine,continuity_look_id:previous,variant:true});
      const p=productLook;
      const item=await api(`/api/projects/${p.project_id}/shots/${p.shot_id}/product-look`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:p.request_id,revision:p.revision,seed:p.seed,refine:p.refine,continuity_look_id:p.continuity_look_id || null})});
      rememberLook({...p,...item}); await pollProductLook();
      while(productLook) await sleep(2000);
    }
  } catch(e) { rememberLook(null); error(e.message); }
  finally { variantBusy=false; drawProduct(); controls(); }
}
async function takeVariants() {
  const shot=activeShot();
  if(variantBusy || !shortProject || !shot || isPackshot(shot) || shot.draft.mode==='image' && !shot.draft.look_id) return;
  variantBusy=true; controls(); error('');
  rememberVariants({kind:'take',project_id:shortProject.id,shot_id:shot.id,ids:[]});
  try {
    // Skip seeds this shot already rendered; a repeat is a cached duplicate.
    const used=new Set(takes.filter(t=>t.shot_id===shot.id).map(t=>Number(t.seed)));
    let base=Number($('seed').value); while([0,1,2].some(i=>used.has(base+i))) base++;
    for(let i=0;i<3;i++) {
      $('seed').value=base+i; captureShot(); await saveBoard();
      const before=new Set(takes.map(t=>t.id));
      await generateBoardShot(); await refresh();
      const take=takes.find(t=>!before.has(t.id) && t.shot_id===shot.id);
      if(!take) throw new Error('The version could not start. Nothing was retried.');
      addVariant('take',take);
      for(;;) {
        await sleep(4000); await refresh(); drawVariants();
        const now=takes.find(t=>t.id===take.id);
        if(!now || (!now.active && ['succeeded','failed','cancelled','needs_review'].includes(now.status))) break;
      }
    }
  } catch(e) { error(e.message); }
  finally { variantBusy=false; drawVariants(); controls(); }
}
$('product-look-3').onclick=()=>lookVariants();
$('generate-3').onclick=()=>takeVariants();
$('save-template').onclick=async()=>{
  if(!shortProject) return;
  try {
    captureShot(); await saveBoard();
    const t=await api(`/api/projects/${shortProject.id}/template`,{method:'POST'});
    $('save-template-status').textContent=`Saved "${t.name}" as a template`;
  } catch(e) { error(e.message); }
};
// Every Generate button carries an approximate cost or time before it runs.
function drawEstimates() {
  const e=config.estimates; if(!e) return;
  const tag=(id,text)=>{ const b=$(id); if(!b) return; let s=b.querySelector('small.est'); if(!s) {s=document.createElement('small'); s.className='est'; b.append(s);} s.textContent=text; };
  const length=globalThis.takeSeconds?.() || 5;
  tag('generate',(e[`take${length}`] || e.take).label); tag('generate-3',e.take3.label); tag('generate-look',e.look.label);
  tag('product-look',e.look.label); tag('product-look-3',e.look3.label);
  tag('product-fill',e.brief.label); tag('generate-music',e.music.label);
  const shot=activeShot(), take=shot && takes.find(t=>t.id===shot.selected_take_id);
  $('take-actual').textContent=take?.actual ? `Selected take: ${take.actual} / estimate ${e.take.label}` : '';
}
$('new-project-structure').addEventListener('change',productForm);
productHooks={prepare:prepareProduct,loaded:()=>{if(productProject() && $('shots-panel').dataset.project!==shortProject.id) {$('shots-panel').dataset.project=shortProject.id; $('shots-panel').open=true;} drawProduct(); drawCamera(); drawVariants(); drawEstimates(); $('generate-music').hidden=!config.autobrief; if(productLook?.id && !productTimer) pollProductLook();},controls:productControls};
productForm();
