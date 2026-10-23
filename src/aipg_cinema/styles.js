/* Transform styles: named restyles with split before/after examples. Picking
   one fills the art direction and the motion text (both stay editable) and,
   when a clip is loaded, makes the opening look, a single image that shows
   the style before any video render. The take still waits for Generate. */
let styleBrowserReturn=null, styleAwaitingSource=false, styleShown='';
// An uploaded picture used as the style reference (Klein looks only).
globalThis.styleImageId=null;
const STYLE_IMAGE_LOOK='Restyle this frame in the visual style of the reference picture: its medium, colour palette, textures, brushwork and lighting. Keep the same subjects, poses, setting and composition.';
const STYLE_IMAGE_MOTION='Keep the visual style of the opening frame throughout. Follow the source motion, subjects and camera exactly in one continuous shot.';
function transformStyles() { return config.styles || []; }
// The style in use is the one whose art direction is unchanged in the editor.
function currentTransformStyle() { return transformStyles().find(s=>s.look===$('prompt').value) || null; }
function usingStyleImage() { return !!globalThis.styleImageId && $('prompt').value===STYLE_IMAGE_LOOK; }
function splitPreview(style,autoplay=true) {
  const video=document.createElement('video');
  Object.assign(video,{src:style.preview_url,poster:style.poster_url,muted:true,loop:true,autoplay,playsInline:true,preload:autoplay ? 'auto' : 'metadata'});
  video.setAttribute('aria-label',`${style.name}: original and restyled`);
  return video;
}
// The split preview with its Original/Openfield tags and an optional action.
function splitMedia(style,...extra) {
  const media=document.createElement('span'); media.className='split-media';
  media.append(splitPreview(style),splitTags(),...extra); return media;
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
  $('style-current').disabled=!!pendingLook || lookSubmitting;
  if(key===styleShown) return;
  styleShown=key;
  const thumb=$('style-thumb'); thumb.replaceChildren();
  if(style) thumb.append(splitPreview(style));
  else if(usingStyleImage()) { const image=document.createElement('img'); image.src=`/api/looks/${globalThis.styleImageId}`; image.alt=''; image.style.cssText='width:100%;height:100%;object-fit:cover'; thumb.append(image); }
  else { const icon=document.createElement('img'); icon.className='icon'; icon.src='/icons/sparkles.svg'; icon.alt=''; thumb.append(icon); }
  $('style-name').textContent=style ? style.name : usingStyleImage() ? 'Your style image' : key ? 'Custom direction' : 'Choose a style';
  $('style-hint').textContent=style ? 'Change style' : `Browse ${transformStyles().length} styles`;
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
  for(const style of transformStyles()) {
    const tile=document.createElement('button'); tile.type='button';
    tile.className='style-tile'+(style.id===current?.id ? ' selected' : '');
    tile.setAttribute('aria-pressed',String(style.id===current?.id));
    const name=document.createElement('span'); name.textContent=style.name+(style.id===current?.id ? ' · in use' : '');
    const blurb=document.createElement('small'); blurb.textContent=style.blurb;
    tile.append(splitMedia(style,recreateButton(()=>{closeStyleBrowser(); recreateExample(style);},'Try on the example')),name,blurb);
    tile.onclick=()=>{closeStyleBrowser(); applyTransformStyle(style);};
    grid.append(tile); credits.add(style.source);
  }
  $('style-credits').textContent=`Example footage: ${[...credits].join(' · ')}`;
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
  error(''); globalThis.styleImageId=null;
  if(inputMode!=='video') { $('input-mode').value='video'; $('input-mode').dispatchEvent(new Event('change')); }
  $('prompt').value=style.look; $('motion-prompt').value=style.motion;
  $('look').value='custom'; draftChanged(); styleShown=''; controls();
  await makeStyleLook();
}
async function makeStyleLook() {
  styleAwaitingSource=!sourceId;
  if(!sourceId || !(currentTransformStyle() || usingStyleImage())) return;
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
  await applyTransformStyle(style);
  if(file) { const transfer=new DataTransfer(); transfer.items.add(file); $('file').files=transfer.files; await $('file').onchange(); }
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
    if(sourceId) { if(lookFrame!==0) $('reference-opening').click(); if(!$('generate-look').disabled) await $('generate-look').onclick(); }
  } catch(e) { error(e.message); }
  finally { $('style-image-file').value=''; }
};
$('style-current').onclick=openStyleBrowser;
$('home-styles-browse').onclick=()=>{
  const feature=HOME_FEATURES.find(f=>f.id==='reshoot');
  launchFeature(feature,null,{picker:false}).then(openStyleBrowser);
};
$('style-close').onclick=closeStyleBrowser;
$('style-browser').addEventListener('click',event=>{if(event.target===$('style-browser')) closeStyleBrowser();});
document.addEventListener('keydown',event=>{if(event.key==='Escape' && !$('style-browser').hidden) closeStyleBrowser();});
var styleHooks={home:drawHomeTransformStyles,recreateExample,recreateButton,open:openStyleBrowser,apply:applyTransformStyle,recreate:recreateWithStyle,byId:id=>transformStyles().find(s=>s.id===id) || null};
const baseStyleControls=productHooks.controls;
productHooks.controls=frozen=>{baseStyleControls(frozen); drawStylePicker();};
