/* Transform styles: named restyles with split before/after examples. Picking
   one fills the art direction and the motion text (both stay editable) and,
   when a clip is loaded, makes the opening look, a single image that shows
   the style before any video render. The take still waits for Generate. */
let styleBrowserReturn=null, styleAwaitingSource=false, styleShown='';
// Style compare: up to four opening looks of the user's clip, one after another.
const compareSet=new Set(); let compareBusy=false, styleBusy=false;
// An uploaded picture used as the style reference (Klein looks only).
globalThis.styleImageId=null;
// Add to video (beta): object photos and the looser source guide they need.
globalThis.insertRefs=[]; globalThis.motionStrength=1;
const STYLE_IMAGE_LOOK='Restyle this frame in the visual style of the reference picture: its medium, colour palette, textures, brushwork and lighting. Keep the same subjects, poses, setting and composition.';
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
    const tile=document.createElement('button'); tile.type='button';
    tile.className='style-tile'+(style.id===current?.id ? ' selected' : '');
    tile.setAttribute('aria-pressed',String(style.id===current?.id));
    const name=document.createElement('span'); name.textContent=style.name+(style.id===current?.id ? ' · in use' : '');
    const blurb=document.createElement('small'); blurb.textContent=style.blurb;
    const pick=document.createElement('span'); pick.className='compare-pick'+(compareSet.has(style.id) ? ' on' : ''); pick.role='checkbox'; pick.tabIndex=0;
    pick.setAttribute('aria-checked',String(compareSet.has(style.id))); pick.textContent=compareSet.has(style.id) ? '✓ Compare' : '+ Compare';
    const toggle=event=>{event.preventDefault(); event.stopPropagation(); if(compareSet.has(style.id)) compareSet.delete(style.id); else if(compareSet.size<4) compareSet.add(style.id); drawStyleBrowser();};
    pick.addEventListener('click',toggle); pick.addEventListener('keydown',event=>{if(event.key===' ' || event.key==='Enter') toggle(event);});
    if(style.mine) {
      blurb.textContent='Your saved style';
      tile.append(splitMedia(style,recreateButton(()=>removeMyStyle(style),'Remove'),pick),name,blurb);
    } else tile.append(splitMedia(style,recreateButton(()=>{closeStyleBrowser(); recreateExample(style);},'Try on the example'),pick),name,blurb);
    tile.onclick=()=>{closeStyleBrowser(); applyTransformStyle(style);};
    grid.append(tile); if(style.source) credits.add(style.source);
  }
  $('style-credits').textContent=`Example footage: ${[...credits].join(' · ')}`;
  $('compare-run').disabled=compareBusy || !sourceId || inputMode!=='video' || compareSet.size<2;
  $('compare-run').lastChild.textContent=compareSet.size>=2 ? ` Compare ${compareSet.size} on my clip` : ' Compare on my clip';
  $('compare-hint').textContent=!sourceId ? 'Load a clip first, then tick up to four styles to compare as stills.' : `Tick up to four styles (${compareSet.size}/4). Each still is one look, ${config.estimates?.look?.label || 'cheap'}.`;
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
function drawHomeTransformStyles() {
  const strip=$('home-tstyles'); strip.replaceChildren();
  for(const style of transformStyles()) {
    const tile=document.createElement('button'); tile.type='button'; tile.className='home-tstyle';
    tile.title=`${style.name}: open Transform with this style`;
    const name=document.createElement('span'); name.textContent=style.name;
    const blurb=document.createElement('small'); blurb.textContent=style.blurb;
    tile.append(splitMedia(style,recreateButton(()=>recreateExample(style))),name,blurb);
    tile.onclick=()=>recreateWithStyle(style);
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
function recreateButton(onClick,label='Recreate this') {
  const button=document.createElement('span'); button.className='recreate'; button.role='button'; button.tabIndex=0;
  button.textContent=label;
  const run=event=>{event.preventDefault(); event.stopPropagation(); onClick();};
  button.addEventListener('click',run);
  button.addEventListener('keydown',event=>{if(event.key==='Enter' || event.key===' ') run(event);});
  return button;
}
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
  $('prompt').value=`Edit the first image: ${what}. Use the object exactly as it appears in ${others}: same shape, colours and logo, at a realistic size and lit to match the scene. Keep everything else in the first image exactly the same: people, poses, faces, clothes, setting, lighting and composition.`;
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
function wholeWindows() { const usable=Math.min(Math.floor(sourceDuration+1e-6),120); const seconds=usable-usable%5; return seconds>=20 ? {takes:Math.ceil(seconds/10),seconds} : null; }
function drawWhole() {
  const plan=wholeWindows(), klein=/^klein/.test(config.look_engine || '');
  const running=!!wholeRun && !wholeRun.done;
  $('whole-row').hidden=!running && !wholeRun?.output_url && !(inputMode==='video' && sourceId && plan && klein);
  if(plan && !running) {
    const each=config.estimates?.take10?.label;
    $('whole-run').textContent=`Restyle the whole clip · ${plan.takes} takes, ${plan.seconds} s${each ? ` (${each} each)` : ''}`;
  }
  $('whole-run').hidden=running;
  $('whole-run').disabled=running || !plan || !$('prompt').value.trim() || !!pending || styleBusy || !config.connected;
}
async function pollWhole() {
  if(!wholeRun || wholeRun.done) return;
  try {
    const item=await api(`/api/restyles/${wholeRun.id}`);
    wholeRun={id:item.id,done:!item.active,output_url:item.output_url};
    $('whole-status').textContent=item.output_url ? 'Whole video ready.' : item.active ? `${item.step || 'Starting'} · seams share their looks` : `Stopped: ${item.error || item.status}. Nothing was retried.`;
    $('whole-result').hidden=!item.output_url; if(item.output_url) $('whole-result').href=item.output_url;
    studioStorage.setItem('openfield-whole',JSON.stringify(wholeRun));
  } catch(e) { $('whole-status').textContent=e.message; }
  drawWhole();
  if(wholeRun && !wholeRun.done) setTimeout(pollWhole,5000);
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
  $('vibe-write').disabled=true; $('vibe-status').textContent='Writing…'; error('');
  try {
    const result=await api('/api/prompt-helper',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idea,mode:transform ? 'transform' : 'scene'})});
    if(transform) { globalThis.styleImageId=null; $('prompt').value=result.look; $('motion-prompt').value=result.motion; $('look').value='custom'; }
    else $('prompt').value=result.prompt;
    draftChanged(); styleShown=''; controls();
    $('vibe-status').textContent=result.source==='template' ? 'Written from a template (no local model running). Edit freely.' : `Written by ${result.source} on your machine. Edit freely.`;
  } catch(e) { $('vibe-status').textContent=''; error(e.message); }
  finally { $('vibe-write').disabled=false; }
};
$('vibe').addEventListener?.('keydown',event=>{if(event.key==='Enter') $('vibe-write').onclick();});
// Replace the person (beta): someone from a photo takes over the talking
// clip, animated from its voice (server: replace.py).
let replaceRun=null;
try { replaceRun=JSON.parse(studioStorage.getItem('openfield-replace') || 'null'); } catch {}
function drawReplace() {
  const klein=/^klein/.test(config.look_engine || ''), running=!!replaceRun && !replaceRun.done;
  $('replace-open').hidden=inputMode!=='video' || !klein;
  $('replace-open').disabled=running || !sourceId || !!pending || styleBusy;
  $('replace-row').hidden=!replaceRun;
}
async function pollReplace() {
  if(!replaceRun || replaceRun.done) return drawReplace();
  try {
    const item=await api(`/api/replacements/${replaceRun.id}`);
    replaceRun={id:item.id,done:!item.active};
    $('replace-status').textContent=item.output_url ? 'New person ready.' : item.active ? (item.step || 'Starting') : `Stopped: ${item.error || item.status}. Nothing was retried.`;
    for(const [id,url] of [['replace-result',item.output_url],['replace-compare',item.compare_url]]) { $(id).hidden=!url; if(url) $(id).href=url; }
    studioStorage.setItem('openfield-replace',JSON.stringify(replaceRun));
  } catch(e) { $('replace-status').textContent=e.message; }
  drawReplace();
  if(replaceRun && !replaceRun.done) setTimeout(pollReplace,5000);
}
$('replace-open').onclick=()=>$('replace-file').click();
$('replace-file').onchange=async()=>{
  const file=$('replace-file').files[0]; if(!file || !sourceId) return;
  error(''); $('replace-open').disabled=true;
  try {
    const form=new FormData(); form.append('file',file);
    const photo=await api(`/api/looks?frame_format=${frameFormat}`,{method:'POST',body:form});
    const item=await api('/api/replacements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:crypto.randomUUID().replaceAll('-',''),source_id:sourceId,photo_id:photo.look_id,frame_format:frameFormat,source_start:sourceStart,seed:editorSeed()})});
    replaceRun={id:item.id,done:false}; $('replace-result').hidden=$('replace-compare').hidden=true; pollReplace();
  } catch(e) { error(e.message); drawReplace(); }
  finally { $('replace-file').value=''; }
};
pollReplace();
pollWhole();
loadMyStyles();
var styleHooks={insert:openInsert,home:drawHomeTransformStyles,recreateExample,recreateButton,open:openStyleBrowser,apply:applyTransformStyle,recreate:recreateWithStyle,byId:id=>transformStyles().find(s=>s.id===id) || null};
const baseStyleControls=productHooks.controls;
productHooks.controls=frozen=>{baseStyleControls(frozen); drawStylePicker(); drawSaveStyle(); drawWhole(); drawReplace();};
