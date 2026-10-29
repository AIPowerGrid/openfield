/* Transform styles: named restyles with split before/after examples. Picking
   one fills the art direction and the motion text (both stay editable) and,
   when a clip is loaded, makes the opening look, a single image that shows
   the style before any video render. The take still waits for Generate. */
let styleBrowserReturn=null, styleAwaitingSource=false, styleShown='';
// Style compare: up to four opening looks of the user's clip, one after another.
const compareSet=new Set(); let compareBusy=false, styleBusy=false;
// Long-run status polls (whole clip, replace, flight, background, scene,
// remove) stop when the run is done, as before, and now also after five
// consecutive failed reads instead of asking the server every 5 s forever.
// One error is shown and a "Check again" control resumes the same poll;
// nothing is re-sent.
const STYLE_POLL_FAILURE_LIMIT=5, stylePollFailures={};
function pollFailed(name,e,statusId) {
  stylePollFailures[name]=(stylePollFailures[name] || 0)+1;
  $(statusId).textContent=`${e.message} (try ${stylePollFailures[name]} of ${STYLE_POLL_FAILURE_LIMIT})`;
}
function pollNext(name,run,poll,statusId,label) {
  if(!run || run.done) return;
  if((stylePollFailures[name] || 0)<STYLE_POLL_FAILURE_LIMIT) { setTimeout(poll,5000); return; }
  stylePollFailures[name]=0;
  const status=$(statusId); status.textContent=`Status unavailable after ${STYLE_POLL_FAILURE_LIMIT} tries; nothing was retried. `;
  const again=document.createElement('button'); again.type='button'; again.className='text-button'; again.textContent='Check again';
  again.onclick=()=>{ status.textContent='Checking'; poll(); };
  status.append(again);
  error(`${label}: the status could not be read ${STYLE_POLL_FAILURE_LIMIT} times in a row. Nothing was retried; use Check again once the connection is back.`);
}
// An uploaded picture used as the style reference (Klein looks only).
globalThis.styleImageId=null;
// Add to video (beta): object photos and the looser source guide they need.
globalThis.insertRefs=[]; globalThis.motionStrength=1;
const STYLE_IMAGE_LOOK='Restyle this frame in the visual style of the reference picture: its medium, color palette, textures, brushwork and lighting. Keep the same subjects, poses, setting and composition.';
const STYLE_IMAGE_MOTION='Keep the visual style of the opening frame throughout. Follow the source motion, subjects and camera exactly in one continuous shot.';
function transformStyles() { return config.styles || []; }
// Saved styles: looks the user kept, shown first in the library.
let myStyles=[];
function allStyles() { return [...myStyles,...transformStyles()]; }
function loadMyStyles() { return api('/api/my-styles').then(list=>{myStyles=list.map(s=>({...s,mine:true})); styleShown=''; controls();}).catch(()=>{}); }
// The style in use is the one whose art direction is unchanged in the editor.
function currentTransformStyle() { return allStyles().find(s=>s.look===$('prompt').value && (!s.style_image_id || s.style_image_id===globalThis.styleImageId)) || null; }
function usingStyleImage() { return !!globalThis.styleImageId && $('prompt').value===STYLE_IMAGE_LOOK; }
function splitPreview(style,autoplay=true) {
  if(style.mine) { const image=document.createElement('img'); Object.assign(image,{src:style.poster_url,alt:`${style.name}: your saved look`}); image.style.cssText='width:100%;height:100%;object-fit:cover'; return image; }
  const video=document.createElement('video');
  Object.assign(video,{src:style.preview_url,poster:style.poster_url,muted:true,loop:true,autoplay,playsInline:true,preload:autoplay ? 'auto' : 'metadata'});
  video.setAttribute('aria-label',`${style.name}: original and restyled`);
  return video;
}
// The split preview with its Original/Openfield tags and an optional action.
function splitMedia(style,...extra) {
  const media=document.createElement('span'); media.className='split-media';
  media.append(splitPreview(style),...(style.mine ? [] : [splitTags()]),...extra); return media;
}
function splitTags() {
  const tags=document.createElement('span'); tags.className='split-tags';
  const before=document.createElement('b'); before.textContent='Original';
  const after=document.createElement('b'); after.textContent='Openfield';
  tags.append(before,after); return tags;
}
function drawStylePicker() {
  if(!transformStyles().length || inputMode!=='video') { $('style-current').hidden=true; $('look-preset-label').hidden=true; return; }
  const style=currentTransformStyle(), key=style?.id || (usingStyleImage() ? 'image:'+globalThis.styleImageId : $('prompt').value.trim() ? 'custom' : '');
  $('style-current').disabled=!!pendingLook || lookSubmitting || styleBusy;
  if(styleBusy) $('generate').disabled=true;
  if(key===styleShown) return;
  styleShown=key;
  const thumb=$('style-thumb'); thumb.replaceChildren();
  if(style) thumb.append(splitPreview(style));
  else if(usingStyleImage()) { const image=document.createElement('img'); image.src=`/api/looks/${globalThis.styleImageId}`; image.alt=''; image.style.cssText='width:100%;height:100%;object-fit:cover'; thumb.append(image); }
  else { const icon=document.createElement('img'); icon.className='icon'; icon.src='/icons/sparkles.svg'; icon.alt=''; thumb.append(icon); }
  $('style-name').textContent=style ? style.name : usingStyleImage() ? 'Your style image' : key ? 'Custom direction' : 'Choose a style';
  $('style-hint').textContent=style ? 'Change style' : `Browse ${allStyles().length} styles`;
}
// Offer to keep the current look as a named style when it isn't one already.
function drawSaveStyle() {
  const savable=inputMode==='video' && !!lookId && !!$('prompt').value.trim() && !currentTransformStyle() && !styleBusy;
  $('save-style-row').hidden=!savable;
  $('save-style').disabled=!savable || !$('save-style-name').value.trim();
}
$('save-style-name').oninput=drawSaveStyle;
$('save-style').onclick=async()=>{
  const name=$('save-style-name').value.trim(); if(!name || !lookId) return;
  error(''); $('save-style').disabled=true;
  try {
    const saved=await api('/api/my-styles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,look:$('prompt').value,motion:$('motion-prompt').value,poster_id:lookId,...(usingStyleImage() ? {style_image_id:globalThis.styleImageId} : {})})});
    myStyles=[{...saved,mine:true},...myStyles]; $('save-style-name').value=''; styleShown=''; controls();
  } catch(e) { error(e.message); drawSaveStyle(); }
};
async function removeMyStyle(style) {
  try { await api(`/api/my-styles/${style.id}`,{method:'DELETE'}); myStyles=myStyles.filter(s=>s.id!==style.id); compareSet.delete(style.id); styleShown=''; drawStyleBrowser(); controls(); }
  catch(e) { error(e.message); }
}
function drawStyleBrowser() {
  const grid=$('style-grid'), current=currentTransformStyle(); grid.replaceChildren();
  const credits=new Set();
  if(/^klein/.test(config.look_engine || '')) {
    const own=document.createElement('button'); own.type='button'; own.className='style-tile';
    const blank=document.createElement('span'); blank.className='blank'; blank.textContent='+ Upload any picture';
    if(globalThis.styleImageId) { blank.textContent=''; const image=document.createElement('img'); image.src=`/api/looks/${globalThis.styleImageId}`; image.alt=''; image.style.cssText='width:100%;height:100%;object-fit:cover;border-radius:6px'; blank.append(image); }
    const name=document.createElement('span'); name.textContent='Your own style image';
    const blurb=document.createElement('small'); blurb.textContent='A painting, a still, a palette: your clip takes on its look.';
    own.append(blank,name,blurb);
    own.onclick=()=>$('style-image-file').click();
    grid.append(own);
  }
  for(const style of allStyles()) {
    const inUse=style.id===current?.id;
    const name=document.createElement('span'); name.textContent=style.name+(inUse ? ' · in use' : '');
    const blurb=document.createElement('small'); blurb.textContent=style.mine ? 'Your saved style' : style.blurb;
    // One checkbox-like Compare control in the media's lower-left corner; the
    // Original/Openfield badges keep the top line to themselves.
    const on=compareSet.has(style.id);
    const pick=document.createElement('button'); pick.type='button'; pick.className='compare-pick'+(on ? ' on' : '');
    pick.setAttribute('aria-pressed',String(on)); pick.setAttribute('aria-label',`Compare ${style.name} on my clip`); pick.title=on ? 'Remove from the comparison' : 'Add to the comparison';
    pick.textContent='Compare';
    pick.onclick=event=>{event.preventDefault(); event.stopPropagation(); if(on) compareSet.delete(style.id); else if(compareSet.size<4) compareSet.add(style.id); drawStyleBrowser();};
    const action=style.mine ? recreateButton(()=>removeMyStyle(style),'Remove') : recreateButton(()=>{closeStyleBrowser(); recreateExample(style);},'Try on the example');
    const tile=styleCard('style-tile'+(inUse ? ' selected' : ''),`${style.name}: use this style`,()=>{closeStyleBrowser(); applyTransformStyle(style);},splitMedia(style,action,pick),name,blurb);
    tile.querySelector('.style-main').setAttribute('aria-pressed',String(inUse));
    grid.append(tile); if(style.source) credits.add(style.source);
  }
  $('style-credits').textContent=`Example footage: ${[...credits].join(' · ')}`;
  $('compare-run').disabled=compareBusy || !sourceId || inputMode!=='video' || compareSet.size<2;
  $('compare-run').lastChild.textContent=compareSet.size>=2 ? ` Compare ${compareSet.size} on my clip` : ' Compare on my clip';
  $('compare-hint').textContent=!sourceId ? 'Load a clip first, then check up to four styles to compare as stills.' : `Check up to four styles (${compareSet.size}/4). Each still is one look, ${config.estimates?.look?.label || 'cheap'}.`;
}
function openStyleBrowser() {
  styleBrowserReturn=document.activeElement;
  $('style-browser').hidden=false; document.body.classList.add('modal-open');
  drawStyleBrowser(); $('style-close').focus();
}
function closeStyleBrowser() {
  $('style-browser').hidden=true; document.body.classList.remove('modal-open');
  for(const video of $('style-grid').querySelectorAll('video')) video.pause();
  styleBrowserReturn?.focus?.();
}
// One click: the style's wording goes into the editor and, with a clip loaded,
// its opening look is made (a single image) so the style shows before any
// video render. Without a clip, the look waits for the upload.
async function applyTransformStyle(style) {
  error(''); globalThis.styleImageId=style.style_image_id || null; globalThis.insertRefs=[]; globalThis.motionStrength=1;
  if(inputMode!=='video') { $('input-mode').value='video'; $('input-mode').dispatchEvent(new Event('change')); }
  $('prompt').value=style.look; $('motion-prompt').value=style.motion;
  $('look').value='custom'; draftChanged(); styleShown=''; controls();
  await makeStyleLook();
}
// One look made directly (not through the editor's single pending look) and
// waited for; returns its id.
async function directLook(prompt,frameIndex,references=[]) {
  const klein=/^klein/.test(config.look_engine || '');
  let look=await api('/api/look-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),source_id:sourceId,prompt,seed:editorSeed(),denoise:klein ? null : 0.65,frame_index:frameIndex,...(globalThis.styleImageId ? {style_image_id:globalThis.styleImageId} : {}),...(references.length ? {reference_ids:references} : {}),...windowSpec()})});
  while(look.active || !['succeeded','failed','cancelled','needs_review','needs_recovery'].includes(look.status)) { await sleep(2500); look=await api(`/api/look-jobs/${look.id}`); }
  if(!look.output_url) throw new Error(look.error || 'The look did not finish. Nothing was retried.');
  return look.id;
}
// Long takes drift back toward the source after a few seconds; an ending look
// in the same style anchors the last frame too.
async function makeHeldStyleLooks(references=[],report=null) {
  const prompt=$('prompt').value, status=$('look-status'), before=status.textContent;
  const say=text=>{status.textContent=text; report?.(text);};
  styleBusy=true; controls();
  try {
    say(`Making the opening look (1 of 2)`);
    const opening=await directLook(prompt,0,references);
    say(`Making the ending look (2 of 2)`);
    const ending=await directLook(prompt,takeSeconds()*24,references);
    lookId=opening; closingId=ending; lookFrame=0;
    draftChanged(); showLook(); updateLooks();
  } catch(e) { error(e.message); }
  finally { styleBusy=false; status.textContent=before; styleShown=''; controls(); refresh().catch(()=>{}); }
}
async function makeStyleLook() {
  styleAwaitingSource=!sourceId;
  if(!sourceId || !(currentTransformStyle() || usingStyleImage())) return;
  if(takeSeconds()>5) { await makeHeldStyleLooks(); return; }
  if(lookFrame!==0) $('reference-opening').click();
  if($('generate-look').disabled) return;
  await $('generate-look').onclick();
}
const baseStyleFileChange=$('file').onchange;
$('file').onchange=async()=>{
  await baseStyleFileChange();
  if(styleAwaitingSource && sourceId) await makeStyleLook();
};
// Home strip loops play only while on screen: nine previews are 10 MB, so
// off-screen tiles keep their poster until they scroll into view.
const lazyLoops=typeof IntersectionObserver==='undefined' ? null : new IntersectionObserver(entries=>{
  for(const {target,isIntersecting} of entries) {
    if(isIntersecting) { target.preload='auto'; target.play?.().catch(()=>{}); }
    else target.pause?.();
  }
},{rootMargin:'120px'});
function drawHomeTransformStyles() {
  const strip=$('home-tstyles'); strip.replaceChildren();
  for(const style of transformStyles()) {
    const name=document.createElement('span'); name.textContent=style.name;
    const blurb=document.createElement('small'); blurb.textContent=style.blurb;
    const tile=styleCard('home-tstyle',`${style.name}: open Transform with this style`,()=>recreateWithStyle(style),splitMedia(style,recreateButton(()=>recreateExample(style))),name,blurb);
    const loop=tile.querySelector('video');
    if(loop && lazyLoops) { loop.autoplay=false; loop.preload='none'; lazyLoops.observe(loop); }
    strip.append(tile);
  }
  $('home-styles-section').hidden=!strip.children.length;
}
// Open Transform with this style chosen. With a file (or the style's bundled
// example clip) the clip uploads through the normal path and the look follows;
// otherwise the clip picker opens and the look waits for the upload.
async function recreateWithStyle(style,file=null) {
  const feature=HOME_FEATURES.find(f=>f.id==='reshoot');
  await launchFeature(feature,null,{picker:!file});
  // Upload the new clip first, so the look is made from it and not from a
  // clip the editor already had loaded.
  if(file) { styleAwaitingSource=false; const transfer=new DataTransfer(); transfer.items.add(file); $('file').files=transfer.files; await $('file').onchange(); }
  await applyTransformStyle(style);
}
async function exampleClip(url) {
  const response=await fetch(url);
  if(!response.ok) throw new Error('The example clip could not be loaded.');
  return new File([await response.blob()],url.split('/').pop(),{type:'video/mp4'});
}
// "Recreate this": the example's own clip and style, ready for Generate.
async function recreateExample(style,url=style.example_url) {
  try { await recreateWithStyle(style,await exampleClip(url)); }
  catch(e) { error(e.message); }
}
// A real button: it must sit beside, never inside, another button (styleCard
// below keeps that arrangement for this script's own cards).
function recreateButton(onClick,label='Recreate this') {
  const button=document.createElement('button'); button.type='button'; button.className='recreate';
  button.textContent=label;
  button.onclick=event=>{event.preventDefault(); event.stopPropagation(); onClick();};
  return button;
}
// A style card is a <div> whose pick action is one transparent, full-size
// <button class="style-main"> (first in tab order, aria-label names the style)
// layered under the Compare/Recreate controls, which are sibling <button>s
// inside the media span. No interactive element nests inside a button, so the
// markup is valid and every control is reachable by keyboard.
function styleCard(className,label,onPick,media,...rest) {
  const card=document.createElement('div'); card.className=className;
  const main=document.createElement('button'); main.type='button'; main.className='style-main';
  main.setAttribute('aria-label',label); main.title=label; main.onclick=onPick;
  card.append(main,media,...rest);
  return card;
}
// Presentation for the card structure above; app.html's stylesheet belongs to
// another owner, so these rules travel with this script. The Compare control
// moves from the badge line to the lower-left corner of the media.
const styleCardStyle=document.createElement('style');
styleCardStyle.dataset.from='styles.js';
styleCardStyle.textContent=[
  'div.style-tile,div.home-tstyle{border:1px solid var(--line);transition:border-color .12s}',
  'div.style-tile:hover,div.home-tstyle:hover{border-color:var(--line-strong)}',
  '.style-tile>.style-main,.home-tstyle>.style-main{position:absolute;inset:0;z-index:1;min-height:0;padding:0;background:none;border:0;border-radius:inherit;cursor:pointer}',
  '.style-tile>.style-main:hover:not(:disabled),.home-tstyle>.style-main:hover:not(:disabled){background:none;border:0}',
  'button.recreate,button.compare-pick{min-height:0;font-weight:700;line-height:1.2}',
  'button.recreate:hover:not(:disabled),button.recreate:focus-visible{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}',
  '.compare-pick{top:auto;bottom:8px;left:8px;transform:none;display:inline-flex;align-items:center;gap:6px}',
  '.compare-pick::before{content:"";width:11px;height:11px;border:1.5px solid currentColor;border-radius:3px;box-sizing:border-box;flex:none}',
  '.compare-pick.on::before{background:currentColor}',
  'button.compare-pick:hover:not(:disabled){background:#000d;border-color:#fff9;color:#fff}',
  'button.compare-pick.on:hover:not(:disabled){background:var(--accent);border-color:var(--accent);color:var(--accent-ink)}',
].join('');
document.head.append(styleCardStyle);
$('style-image-file').onchange=async()=>{
  const file=$('style-image-file').files[0]; if(!file) return;
  closeStyleBrowser(); error('');
  try {
    const form=new FormData(); form.append('file',file);
    const uploaded=await api(`/api/looks?frame_format=${frameFormat}`,{method:'POST',body:form});
    if(inputMode!=='video') { $('input-mode').value='video'; $('input-mode').dispatchEvent(new Event('change')); }
    globalThis.styleImageId=uploaded.look_id;
    $('prompt').value=STYLE_IMAGE_LOOK; $('motion-prompt').value=STYLE_IMAGE_MOTION;
    $('look').value='custom'; draftChanged(); styleShown=''; controls();
    styleAwaitingSource=!sourceId;
    if(sourceId) await makeStyleLook();
  } catch(e) { error(e.message); }
  finally { $('style-image-file').value=''; }
};
async function compareStyles() {
  const chosen=allStyles().filter(s=>compareSet.has(s.id));
  if(chosen.length<2 || !sourceId || compareBusy) return;
  compareBusy=true; closeStyleBrowser(); error('');
  const grid=$('compare-grid'); grid.replaceChildren();
  const cells=chosen.map(style=>{
    const cell=document.createElement('div'); cell.className='compare-cell';
    const frame=document.createElement('div'); frame.className='frame'; frame.textContent='Waiting';
    const row=document.createElement('div'); row.className='row';
    const name=document.createElement('strong'); name.textContent=style.name;
    const use=document.createElement('button'); use.type='button'; use.textContent='Use this'; use.disabled=true;
    row.append(name,use); cell.append(frame,row); grid.append(cell);
    return {style,frame,use};
  });
  $('style-compare').hidden=false; document.body.classList.add('modal-open');
  const klein=/^klein/.test(config.look_engine || '');
  try {
    for(const cell of cells) {
      cell.frame.textContent='Making the look';
      let look=await api('/api/look-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),source_id:sourceId,prompt:cell.style.look,seed:editorSeed(),denoise:klein ? null : 0.65,frame_index:0,...(cell.style.style_image_id ? {style_image_id:cell.style.style_image_id} : {}),...windowSpec()})});
      while(look.active || !['succeeded','failed','cancelled','needs_review','needs_recovery'].includes(look.status)) { await sleep(2500); look=await api(`/api/look-jobs/${look.id}`); }
      if(!look.output_url) { cell.frame.textContent=look.error || 'This look did not finish.'; continue; }
      const image=document.createElement('img'); image.src=look.output_url; image.alt=`${cell.style.name} look`;
      cell.frame.replaceChildren(image); cell.use.disabled=false;
      cell.use.onclick=()=>useComparedLook(cell.style,look.id);
    }
  } catch(e) { error(e.message); }
  finally { compareBusy=false; refresh().catch(()=>{}); }
}
function useComparedLook(style,look) {
  closeCompare();
  globalThis.styleImageId=style.style_image_id || null;
  $('prompt').value=style.look; $('motion-prompt').value=style.motion; $('look').value='custom';
  lookId=look; closingId=null; lookFrame=0;
  draftChanged(); showLook(); updateLooks(); styleShown=''; controls();
}
function closeCompare() { $('style-compare').hidden=true; document.body.classList.remove('modal-open'); }
$('compare-run').onclick=compareStyles;
$('compare-close').onclick=closeCompare;
$('style-compare').addEventListener('click',event=>{if(event.target===$('style-compare')) closeCompare();});
function openInsert() {
  $('insert-modal').hidden=false; document.body.classList.add('modal-open'); drawInsert(); $('insert-what').focus();
}
function closeInsert() { $('insert-modal').hidden=true; document.body.classList.remove('modal-open'); }
function drawInsert(status) {
  const thumbs=$('insert-thumbs'); thumbs.replaceChildren();
  for(const id of globalThis.insertRefs) { const image=document.createElement('img'); image.src=`/api/looks/${id}`; image.alt='Object photo'; thumbs.append(image); }
  $('insert-add').disabled=styleBusy || globalThis.insertRefs.length>=3;
  const klein=/^klein/.test(config.look_engine || '');
  $('insert-run').disabled=styleBusy || !sourceId || inputMode!=='video' || !klein || !globalThis.insertRefs.length || !$('insert-what').value.trim();
  $('insert-estimate').textContent=!klein ? 'Needs a Klein look engine.' : !sourceId ? 'Load a clip first.' : `Two looks (${config.estimates?.look?.label || 'cheap'} each), then Generate take.`;
  if(status!==undefined) $('insert-status').textContent=status;
}
$('insert-add').onclick=()=>$('insert-file').click();
$('insert-file').onchange=async()=>{
  const file=$('insert-file').files[0]; if(!file) return;
  try {
    const form=new FormData(); form.append('file',file);
    const uploaded=await api(`/api/looks?frame_format=${frameFormat}`,{method:'POST',body:form});
    globalThis.insertRefs=[...globalThis.insertRefs,uploaded.look_id].slice(0,3); drawInsert('');
  } catch(e) { drawInsert(e.message); }
  finally { $('insert-file').value=''; }
};
$('insert-what').oninput=()=>drawInsert();
$('insert-run').onclick=async()=>{
  const what=$('insert-what').value.trim().replace(/\.$/,'');
  if(!what || !globalThis.insertRefs.length) return;
  const others=globalThis.insertRefs.length>1 ? 'the other images' : 'the second image';
  globalThis.styleImageId=null; globalThis.motionStrength=0.6;
  $('prompt').value=`Edit the first image: ${what}. Use the object exactly as it appears in ${others}: same shape, colors and logo, at a realistic size and lit to match the scene. Keep everything else in the first image exactly the same: people, poses, faces, clothes, setting, lighting and composition.`;
  $('motion-prompt').value=`${what}. The added object stays the same shape, logo and size for the whole shot and moves naturally with whatever holds it. Keep the appearance of the opening frame throughout. Follow the source motion, faces and camera in one continuous shot.`;
  $('look').value='custom'; draftChanged(); styleShown=''; controls();
  drawInsert('');
  await makeHeldStyleLooks(globalThis.insertRefs,text=>drawInsert(text));
  if(lookId && closingId) { drawInsert('Looks ready. Press Generate take.'); setTimeout(closeInsert,1200); }
};
$('insert-close').onclick=closeInsert;
$('insert-open').onclick=openInsert;
$('insert-modal').addEventListener('click',event=>{if(event.target===$('insert-modal')) closeInsert();});
$('style-current').onclick=openStyleBrowser;
$('home-styles-browse').onclick=()=>{
  const feature=HOME_FEATURES.find(f=>f.id==='reshoot');
  launchFeature(feature,null,{picker:false}).then(openStyleBrowser);
};
$('style-close').onclick=closeStyleBrowser;
$('style-browser').addEventListener('click',event=>{if(event.target===$('style-browser')) closeStyleBrowser();});
document.addEventListener('keydown',event=>{if(event.key==='Escape' && !$('style-browser').hidden) closeStyleBrowser();});
// Whole-clip restyle: back-to-back 10 s takes that share their boundary
// looks, joined with the original sound (server: wholevideo.py).
let wholeRun=null;
try { wholeRun=JSON.parse(studioStorage.getItem('openfield-whole') || 'null'); } catch {}
// Clip bounds come from config.whole_clip when the server sends them; the
// defaults match the server's historical 20 s minimum, 120 s cap and 10 s takes.
function wholeLimits() { const w=config.whole_clip || {}; return {min:w.min_seconds ?? 20,max:w.max_seconds ?? 120,window:w.window_seconds ?? 10}; }
function wholeWindows() { const {min,max,window}=wholeLimits(); const usable=Math.min(Math.floor(sourceDuration+1e-6),max); const seconds=usable-usable%5; return seconds>=min ? {takes:Math.ceil(seconds/window),seconds} : null; }
// The plan needs one take per window and one look per boundary (takes+1);
// unknown session limits (missing from config) impose no shortfall.
function wholeShortfall(plan) {
  if(!plan || config.max_renders==null || config.max_looks==null) return null;
  const takesLeft=config.max_renders-(config.renders_used || 0), looksLeft=config.max_looks-(config.looks_used || 0), looks=plan.takes+1;
  return plan.takes>takesLeft || looks>looksLeft ? {takes:plan.takes,looks,takesLeft,looksLeft} : null;
}
let wholeHint='';
function drawWhole() {
  const plan=wholeWindows(), klein=/^klein/.test(config.look_engine || ''), {min}=wholeLimits();
  const running=!!wholeRun && !wholeRun.done;
  const eligible=inputMode==='video' && !!sourceId && klein;
  // A loaded clip shorter than the minimum keeps the row (and the reason)
  // visible instead of hiding the feature; 0 s means the duration is not read yet.
  const tooShort=eligible && !plan && sourceDuration>0;
  $('whole-row').hidden=!running && !wholeRun?.output_url && !(eligible && (plan || tooShort));
  if(plan && !running) {
    const each=config.estimates?.take10?.label;
    $('whole-run').textContent=`Restyle the whole clip · ${plan.takes} takes, ${plan.seconds} s${each ? ` (${each} each)` : ''}`;
  }
  const shortfall=eligible && !running ? wholeShortfall(plan) : null;
  const hint=tooShort ? `Whole-clip restyle needs a clip of at least ${min} s (this one is ${Math.floor(sourceDuration+1e-6)} s).`
    : shortfall ? `Needs ${shortfall.takes} takes and ${shortfall.looks} looks; this session has ${shortfall.takesLeft} and ${shortfall.looksLeft} left. Restart with --max-renders ${shortfall.takes} --max-looks ${shortfall.looks}.`
    : '';
  // The hint owns the status line only while it applies; a run's own status
  // (progress, Stopped, ready) is never overwritten by an empty hint.
  const status=$('whole-status');
  if(hint) status.textContent=hint; else if(wholeHint && status.textContent===wholeHint) status.textContent='';
  wholeHint=hint;
  $('whole-run').hidden=running;
  $('whole-run').disabled=running || !plan || !!shortfall || !$('prompt').value.trim() || !!pending || styleBusy || !config.connected;
}
async function pollWhole() {
  if(!wholeRun || wholeRun.done) return;
  try {
    const item=await api(`/api/restyles/${wholeRun.id}`);
    wholeRun={id:item.id,done:!item.active,output_url:item.output_url};
    $('whole-status').textContent=item.output_url ? 'Whole video ready.' : item.active ? `${item.step || 'Starting'} · seams share their looks` : `Stopped: ${item.error || item.status}. Nothing was retried.`;
    $('whole-result').hidden=!item.output_url; if(item.output_url) $('whole-result').href=item.output_url;
    studioStorage.setItem('openfield-whole',JSON.stringify(wholeRun)); stylePollFailures.whole=0;
  } catch(e) { pollFailed('whole',e,'whole-status'); }
  drawWhole();
  pollNext('whole',wholeRun,pollWhole,'whole-status','Whole clip');
}
$('whole-run').onclick=async()=>{
  const plan=wholeWindows(); if(!plan || !sourceId) return;
  error(''); $('whole-run').disabled=true;
  try {
    const item=await api('/api/restyles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),source_id:sourceId,look:$('prompt').value,motion:$('motion-prompt').value,seed:editorSeed(),frame_format:frameFormat,...(usingStyleImage() ? {style_image_id:globalThis.styleImageId} : {})})});
    wholeRun={id:item.id,done:false}; $('whole-result').hidden=true; pollWhole();
  } catch(e) { error(e.message); drawWhole(); }
};
// Prompt helper: a vibe becomes full directions (a local model if one is
// running, otherwise a template); the result stays editable.
$('vibe-write').onclick=async()=>{
  const idea=$('vibe').value.trim(); if(idea.length<2) return;
  const transform=inputMode==='video';
  $('vibe-write').disabled=true; $('vibe-status').textContent='Writing… (a backend writer looks at the picture; up to two minutes)'; error('');
  try {
    // The clip's first frame or the uploaded image goes with the idea so a
    // backend writer (Qwen3-VL) can fit the directions to the picture.
    const picture=transform && sourceId ? {source_id:sourceId,frame_format:frameFormat,source_start:sourceStart} : inputMode==='image' && lookId ? {look_id:lookId} : {};
    const result=await api('/api/prompt-helper',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea,mode:transform ? 'transform' : 'scene',...picture})});
    if(transform) { globalThis.styleImageId=null; $('prompt').value=result.look; $('motion-prompt').value=result.motion; $('look').value='custom'; }
    else $('prompt').value=result.prompt;
    draftChanged(); styleShown=''; controls();
    $('vibe-status').textContent=result.source==='template' ? 'Written from a template (no model reachable). Edit freely.' : /^Qwen3-VL/.test(result.source) ? `Written by ${result.source}. Edit freely.` : `Written by ${result.source} on your machine. Edit freely.`;
  } catch(e) { $('vibe-status').textContent=''; error(e.message); }
  finally { $('vibe-write').disabled=false; }
};
$('vibe').addEventListener?.('keydown',event=>{if(event.key==='Enter') $('vibe-write').onclick();});
// Replace the person (beta): someone from a photo takes over the talking
// clip. Swap (MiniMax H3, server: swap.py) keeps the clip's motion and voice;
// when its models are missing, Rebuild (Klein + LTX, replace.py) animates the
// new person from the voice instead.
let replaceRun=null, replaceReady=null;
try { replaceRun=JSON.parse(studioStorage.getItem('openfield-replace') || 'null'); } catch {}
function replaceEngines() {
  const klein=/^klein/.test(config.look_engine || '');
  const swap=replaceReady ? replaceReady.swap : (config.replace || {}).swap;
  return {swap:swap===true, unknown:swap==null, rebuild:klein, help:replaceReady ? replaceReady.swap_help : (config.replace || {}).swap_help};
}
function drawReplace() {
  const engines=replaceEngines(), running=!!replaceRun && !replaceRun.done;
  $('replace-open').hidden=inputMode!=='video' || !(engines.swap || engines.unknown || engines.rebuild);
  $('replace-open').disabled=running || !sourceId || !!pending || styleBusy;
  const note=engines.swap ? 'Keeps their moves and voice (MiniMax H3, about 3 minutes).' : engines.unknown ? '' : engines.rebuild ? `Swap unavailable, so the person is rebuilt (Klein + LTX; new body motion). ${engines.help || ''}` : (engines.help || '');
  $('replace-note').textContent=note; $('replace-note').hidden=inputMode!=='video' || !note;
  $('replace-row').hidden=!replaceRun || inputMode!=='video';
}
async function checkReplace() {
  try { replaceReady=await api('/api/replacements/ready'); } catch(e) { replaceReady={swap:false,swap_help:e.message,rebuild:/^klein/.test(config.look_engine || '')}; }
  drawReplace();
  return replaceEngines();
}
async function pollReplace(force=false) {
  if(!replaceRun || (replaceRun.done && !force)) return drawReplace();
  try {
    const item=await api(`/api/replacements/${replaceRun.id}`);
    replaceRun={id:item.id,done:!item.active};
    const who=item.engine==='swap' ? 'Swapped person ready: their moves and voice kept.' : 'New person ready.';
    $('replace-status').textContent=item.output_url ? who : item.active ? (item.step || 'Starting') : `Stopped: ${item.error || item.status}. Nothing was retried.`;
    for(const [id,url] of [['replace-result',item.output_url],['replace-compare',item.compare_url]]) { $(id).hidden=!url; if(url) $(id).href=url; }
    studioStorage.setItem('openfield-replace',JSON.stringify(replaceRun)); stylePollFailures.replace=0;
  } catch(e) { pollFailed('replace',e,'replace-status'); }
  drawReplace();
  pollNext('replace',replaceRun,pollReplace,'replace-status','Swap the person');
}
$('replace-open').onclick=async()=>{
  const engines=replaceEngines().unknown ? await checkReplace() : replaceEngines();
  if(!engines.swap && !engines.rebuild) { error(engines.help || 'Replacing a person is unavailable.'); return; }
  $('replace-file').click();
};
$('replace-file').onchange=async()=>{
  const file=$('replace-file').files[0]; if(!file || !sourceId) return;
  error(''); $('replace-open').disabled=true;
  try {
    const engines=replaceEngines();
    const form=new FormData(); form.append('file',file);
    const photo=await api(`/api/looks?frame_format=${frameFormat}`,{method:'POST',body:form});
    const item=await api('/api/replacements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),source_id:sourceId,photo_id:photo.look_id,frame_format:frameFormat,source_start:sourceStart,seed:editorSeed(),engine:engines.swap ? 'swap' : 'rebuild'})});
    replaceRun={id:item.id,done:false}; $('replace-result').hidden=$('replace-compare').hidden=true; pollReplace();
  } catch(e) { error(e.message); drawReplace(); }
  finally { $('replace-file').value=''; }
};
// Camera flight from a photo (server: flight.py): MiniMax H3 orbits the
// frozen scene or flies through it, from the uploaded opening image.
let flightRun=null, flightReady=null;
try { flightRun=JSON.parse(studioStorage.getItem('openfield-flight') || 'null'); } catch {}
function flightMoves() {
  if(flightReady) return flightReady.moves;
  return Object.entries(config.flights || {}).map(([id,ready])=>({id,ready,help:null}));
}
function drawFlight() {
  const running=!!flightRun && !flightRun.done, moves=flightMoves(), move=moves.find(m=>m.id===$('flight-move').value);
  const unknown=!move || move.ready==null, any=moves.some(m=>m.ready) || unknown;
  $('flight-row-open').hidden=inputMode!=='image' || !any;
  $('flight-open').disabled=running || !lookId || !!pending || styleBusy;
  const note=move && move.ready ? (move.id==='speak' ? 'The person in the photo says the art direction text, voice and lips by MiniMax H3 (a few minutes). Beta: mouth timing varies.' : 'The photo stays frozen; only the camera moves (MiniMax H3, a few minutes). Art direction names the subject or the flight path.') : move && move.ready===false ? (move.help || '') : '';
  $('flight-note').textContent=note; $('flight-note').hidden=inputMode!=='image' || !note;
  $('flight-row').hidden=!flightRun || inputMode!=='image';
}
async function checkFlight() {
  try { flightReady=await api('/api/flights/ready'); } catch(e) { flightReady={moves:[{id:'orbit',ready:false,help:e.message},{id:'fpv',ready:false,help:e.message}]}; }
  drawFlight();
  return flightMoves();
}
async function pollFlight(force=false) {
  if(!flightRun || (flightRun.done && !force)) return drawFlight();
  try {
    const item=await api(`/api/flights/${flightRun.id}`);
    flightRun={id:item.id,done:!item.active};
    $('flight-status').textContent=item.output_url ? 'Your photo is moving.' : item.active ? (item.step || 'Starting') : `Stopped: ${item.error || item.status}. Nothing was retried.`;
    $('flight-result').hidden=!item.output_url; if(item.output_url) $('flight-result').href=item.output_url;
    studioStorage.setItem('openfield-flight',JSON.stringify(flightRun)); stylePollFailures.flight=0;
  } catch(e) { pollFailed('flight',e,'flight-status'); }
  drawFlight();
  pollNext('flight',flightRun,pollFlight,'flight-status','Bring this photo to life');
}
$('flight-move').onchange=drawFlight;
$('flight-open').onclick=async()=>{
  if(!lookId) return;
  const moves=flightMoves().some(m=>m.ready==null) ? await checkFlight() : flightMoves();
  const move=moves.find(m=>m.id===$('flight-move').value);
  if(!move || !move.ready) { error(move?.help || 'This camera move is unavailable.'); return; }
  error(''); $('flight-open').disabled=true;
  try {
    const item=await api('/api/flights',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),photo_id:lookId,move:move.id,note:$('prompt').value.trim().slice(0,300),frame_format:frameFormat,seed:editorSeed()})});
    flightRun={id:item.id,done:false}; $('flight-result').hidden=true; pollFlight();
  } catch(e) { error(e.message); drawFlight(); }
};
// Change the background from a photo (server: swap.py, background mode): H3
// keeps the person and takes the place from the photo. Same route as the
// replacement, engine "background"; no LoRA, so Cloud runs it as is.
let backgroundRun=null;
try { backgroundRun=JSON.parse(studioStorage.getItem('openfield-background') || 'null'); } catch {}
function backgroundState() {
  if(replaceReady) return {ready:replaceReady.background, help:replaceReady.background_help};
  return {ready:(config.replace || {}).background, help:(config.replace || {}).background_help};
}
function drawBackground() {
  const state=backgroundState(), running=!!backgroundRun && !backgroundRun.done;
  $('background-open').hidden=inputMode!=='video' || state.ready===false;
  $('background-open').disabled=running || !sourceId || !!pending || styleBusy;
  const note=state.ready ? 'They stay exactly as they are; the photo becomes the place behind them (MiniMax H3, about four minutes).' : state.ready===false ? (state.help || '') : '';
  $('background-note').textContent=note; $('background-note').hidden=inputMode!=='video' || !note;
  $('background-row').hidden=!backgroundRun || inputMode!=='video';
}
async function pollBackground(force=false) {
  if(!backgroundRun || (backgroundRun.done && !force)) return drawBackground();
  try {
    const item=await api(`/api/replacements/${backgroundRun.id}`);
    backgroundRun={id:item.id,done:!item.active};
    $('background-status').textContent=item.output_url ? 'New background ready.' : item.active ? (item.step || 'Starting') : `Stopped: ${item.error || item.status}. Nothing was retried.`;
    for(const [id,url] of [['background-result',item.output_url],['background-compare',item.compare_url]]) { $(id).hidden=!url; if(url) $(id).href=url; }
    studioStorage.setItem('openfield-background',JSON.stringify(backgroundRun)); stylePollFailures.background=0;
  } catch(e) { pollFailed('background',e,'background-status'); }
  drawBackground();
  pollNext('background',backgroundRun,pollBackground,'background-status','Change the background');
}
$('background-open').onclick=async()=>{
  if(backgroundState().ready==null) await checkReplace();
  const state=backgroundState();
  if(!state.ready) { error(state.help || 'Changing the background is unavailable.'); return; }
  $('background-file').click();
};
$('background-file').onchange=async()=>{
  const file=$('background-file').files[0]; if(!file || !sourceId) return;
  error(''); $('background-open').disabled=true;
  try {
    const form=new FormData(); form.append('file',file);
    const photo=await api(`/api/looks?frame_format=${frameFormat}`,{method:'POST',body:form});
    const item=await api('/api/replacements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),source_id:sourceId,photo_id:photo.look_id,frame_format:frameFormat,source_start:sourceStart,seed:editorSeed(),engine:'background',note:$('prompt').value.trim().slice(0,300)})});
    backgroundRun={id:item.id,done:false}; $('background-result').hidden=$('background-compare').hidden=true; pollBackground();
  } catch(e) { error(e.message); drawBackground(); }
  finally { $('background-file').value=''; }
};
pollBackground(true);
// New place from words (server: replace.py, engine "scene"): BiRefNet cuts
// the person out of the first frame, Klein paints the place described in the
// art direction around them, and Transform follows the clip's motion.
let sceneRun=null;
try { sceneRun=JSON.parse(studioStorage.getItem('openfield-scene') || 'null'); } catch {}
function drawScene() {
  const klein=/^klein/.test(config.look_engine || ''), running=!!sceneRun && !sceneRun.done;
  $('scene-open').hidden=inputMode!=='video' || !klein;
  $('scene-open').disabled=running || !sourceId || !!pending || styleBusy || $('prompt').value.trim().length<3;
  const note=klein && inputMode==='video' ? 'Write where they are now in Art direction. The matte keeps them pixel-exact, Klein paints the place on the first frame, Transform follows the motion (about five minutes).' : '';
  $('scene-note').textContent=note; $('scene-note').hidden=!note;
  $('scene-row').hidden=!sceneRun || inputMode!=='video';
}
async function pollScene(force=false) {
  if(!sceneRun || (sceneRun.done && !force)) return drawScene();
  try {
    const item=await api(`/api/replacements/${sceneRun.id}`);
    sceneRun={id:item.id,done:!item.active};
    $('scene-status').textContent=item.output_url ? 'New place ready.' : item.active ? (item.step || 'Starting') : `Stopped: ${item.error || item.status}. Nothing was retried.`;
    for(const [id,url] of [['scene-result',item.output_url],['scene-compare',item.compare_url]]) { $(id).hidden=!url; if(url) $(id).href=url; }
    studioStorage.setItem('openfield-scene',JSON.stringify(sceneRun)); stylePollFailures.scene=0;
  } catch(e) { pollFailed('scene',e,'scene-status'); }
  drawScene();
  pollNext('scene',sceneRun,pollScene,'scene-status','New place');
}
$('scene-open').onclick=async()=>{
  if(!sourceId) return;
  error(''); $('scene-open').disabled=true;
  try {
    const item=await api('/api/replacements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),source_id:sourceId,frame_format:frameFormat,source_start:sourceStart,seed:editorSeed(),engine:'scene',note:$('prompt').value.trim().slice(0,300)})});
    sceneRun={id:item.id,done:false}; $('scene-result').hidden=$('scene-compare').hidden=true; pollScene();
  } catch(e) { error(e.message); drawScene(); }
};
pollScene(true);
// Remove something from the clip (server: remove.py): SAM 3.1 finds what is
// named and shows its mask; Remove it then paints the region out with Wan VACE.
let removeRun=null, removeReady=null, removeOpen=false;
try { removeRun=JSON.parse(studioStorage.getItem('openfield-remove') || 'null'); } catch {}
function removeState() {
  if(removeReady) return removeReady;
  return {ready:config.removal, help:null};
}
function drawRemove() {
  const state=removeState(), running=!!removeRun && !removeRun.done;
  $('remove-open').hidden=inputMode!=='video' || state.ready===false;
  $('remove-open').disabled=!sourceId || !!pending || styleBusy;
  $('remove-row-open').hidden=inputMode!=='video' || !removeOpen;
  $('remove-find').disabled=running || !sourceId || !!pending || styleBusy || $('remove-target').value.trim().length<2;
  const note=state.ready===false ? (state.help || '') : removeOpen ? 'Name one thing and say what should be there instead (naming the thing again paints it back). SAM 3.1 shows the mask first; Remove it then paints the region out with Wan VACE, a few minutes.' : '';
  $('remove-note').textContent=note; $('remove-note').hidden=inputMode!=='video' || !note;
  $('remove-row').hidden=!removeRun || inputMode!=='video';
}
async function checkRemove() {
  try { removeReady=await api('/api/removals/ready'); } catch(e) { removeReady={ready:false,help:e.message}; }
  drawRemove();
  return removeReady;
}
async function pollRemove(force=false) {
  if(!removeRun || (removeRun.done && !force)) return drawRemove();
  try {
    const item=await api(`/api/removals/${removeRun.id}`);
    const stage=item.remove.status ? item.remove : item.find;
    removeRun={id:item.id,done:!item.active,removed:!!item.remove.status};
    $('remove-status').textContent=item.output_url ? `"${item.target}" removed.` : item.active ? (stage.step || 'Starting') : item.mask_url && !item.remove.status ? `Mask for "${item.target}" ready. Check it, then Remove it.` : `Stopped: ${stage.error || stage.status}. Nothing was retried.`;
    for(const [id,url] of [['remove-mask',item.mask_url],['remove-result',item.output_url],['remove-compare',item.compare_url]]) { $(id).hidden=!url; if(url) $(id).href=url; }
    $('remove-go').hidden=!item.mask_url || !!item.remove.status;
    studioStorage.setItem('openfield-remove',JSON.stringify(removeRun)); stylePollFailures.remove=0;
  } catch(e) { pollFailed('remove',e,'remove-status'); }
  drawRemove();
  pollNext('remove',removeRun,pollRemove,'remove-status','Remove an object');
}
$('remove-open').onclick=async()=>{
  removeOpen=!removeOpen; drawRemove();
  if(removeOpen && removeState().ready==null) { const state=await checkRemove(); if(!state.ready) error(state.help || 'Removal is unavailable.'); }
  if(removeOpen) $('remove-target').focus();
};
$('remove-target').addEventListener?.('input',drawRemove);
$('remove-target').addEventListener?.('keydown',event=>{if(event.key==='Enter' && !$('remove-find').disabled) $('remove-find').onclick();});
$('remove-find').onclick=async()=>{
  const target=$('remove-target').value.trim(); if(target.length<2 || !sourceId) return;
  error(''); $('remove-find').disabled=true;
  try {
    const item=await api('/api/removals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),source_id:sourceId,target,fill:$('remove-fill').value.trim().slice(0,300),note:$('prompt').value.trim().slice(0,300),frame_format:frameFormat,source_start:sourceStart,seed:editorSeed()})});
    removeRun={id:item.id,done:false,removed:false}; for(const id of ['remove-mask','remove-result','remove-compare','remove-go']) $(id).hidden=true; pollRemove();
  } catch(e) { error(e.message); drawRemove(); }
};
$('remove-go').onclick=async()=>{
  if(!removeRun) return;
  error(''); $('remove-go').hidden=true;
  try { const item=await api(`/api/removals/${removeRun.id}/remove`,{method:'POST'}); removeRun={id:item.id,done:false,removed:true}; pollRemove(); }
  catch(e) { error(e.message); $('remove-go').hidden=false; }
};
// On load, look once even at a run the page had given up on: a recovery
// started elsewhere (or a studio restart) may have finished it.
pollRemove(true);
pollFlight(true);
pollReplace(true);
pollWhole();
loadMyStyles();
var styleHooks={insert:openInsert,home:drawHomeTransformStyles,recreateExample,recreateButton,open:openStyleBrowser,apply:applyTransformStyle,recreate:recreateWithStyle,byId:id=>transformStyles().find(s=>s.id===id) || null};
const baseStyleControls=productHooks.controls;
productHooks.controls=frozen=>{baseStyleControls(frozen); drawStylePicker(); drawSaveStyle(); drawWhole(); drawReplace(); drawFlight(); drawRemove(); drawBackground(); drawScene();};
