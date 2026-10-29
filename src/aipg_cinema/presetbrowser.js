/* Full-screen preset browser: every qualified camera move and effect as a
   looping preview. Picking one only sets the active shot's camera preset;
   nothing renders until Generate. */
let presetBrowserKind='camera', presetBrowserReturn=null;
function presetBrowserTarget() {
  const shot=activeShot();
  return shot && !$('camera-presets').hidden ? shot : null;
}
// Each preset plays its own bundled preview (config.presets[].preview_url is
// /preset-previews/<id>.mp4; the server lists only presets whose file exists).
// Without a preview, or when the file fails to load, the tile shows the
// preset's own name on a plain panel rather than a borrowed poster. The
// Custom entry has no preview by design.
function presetPreview(preset) {
  const plain=text=>{ const blank=document.createElement('div'); blank.className='blank'; blank.textContent=text; return blank; };
  if(!preset.id) return plain('Your own direction');
  if(!preset.preview_url) return plain(preset.name);
  const video=document.createElement('video');
  Object.assign(video,{src:preset.preview_url,muted:true,loop:true,autoplay:true,playsInline:true,preload:'metadata'});
  video.setAttribute('aria-label',`${preset.name}: preview of this ${preset.kind==='effect' ? 'effect' : 'camera move'}`);
  video.onerror=()=>video.replaceWith(plain(preset.name));
  return video;
}
function drawPresetBrowser() {
  const shot=presetBrowserTarget(), current=(shot?.camera || '').split('@')[0];
  for(const kind of ['camera','effect']) {
    const tab=$(`preset-tab-${kind}`), active=kind===presetBrowserKind;
    tab.classList.toggle('active',active); tab.setAttribute('aria-selected',String(active));
  }
  $('preset-browser-note').textContent=presetBrowserKind==='effect'
    ? 'Effects are louder and opt-in. Each was tested on a product and a scene; the product stays recognizable.'
    : 'Gentle moves keep the product steady. Each preset sets a recommended trim.';
  const grid=$('preset-grid'); grid.replaceChildren();
  const list=(config.presets || []).filter(p=>(p.kind || 'camera')===presetBrowserKind);
  if(presetBrowserKind==='camera' && shot) list.unshift({id:'',name:'Custom',kind:'camera',trim_end:120});
  for(const preset of list) {
    const tile=document.createElement('button'); tile.type='button';
    tile.className='preset-tile'+(preset.id===current ? ' selected' : '');
    tile.setAttribute('aria-pressed',String(preset.id===current));
    tile.append(presetPreview(preset));
    const label=document.createElement('span'); label.textContent=preset.name;
    const meta=document.createElement('small');
    meta.textContent=preset.id ? `${(preset.trim_end/24).toFixed(1)} s${preset.id===current ? ' · in use' : ''}` : 'Write the motion yourself';
    tile.append(label,meta);
    tile.disabled=!shot;
    tile.onclick=()=>{
      $('camera-preset').value=preset.id; $('camera-preset').dispatchEvent(new Event('change'));
      closePresetBrowser();
    };
    grid.append(tile);
  }
  $('preset-browser-pick').hidden=!!shot;
}
function openPresetBrowser(kind='camera') {
  presetBrowserKind=kind; presetBrowserReturn=document.activeElement;
  $('preset-browser').hidden=false; document.body.classList.add('modal-open');
  drawPresetBrowser(); $(`preset-tab-${kind}`).focus();
}
function closePresetBrowser() {
  $('preset-browser').hidden=true; document.body.classList.remove('modal-open');
  for(const video of $('preset-grid').querySelectorAll('video')) video.pause();
  presetBrowserReturn?.focus?.();
}
for(const kind of ['camera','effect']) $(`preset-tab-${kind}`).onclick=()=>{presetBrowserKind=kind; drawPresetBrowser();};
$('preset-close').onclick=closePresetBrowser;
$('preset-browser').addEventListener('click',event=>{if(event.target===$('preset-browser')) closePresetBrowser();});
document.addEventListener('keydown',event=>{if(event.key==='Escape' && !$('preset-browser').hidden) closePresetBrowser();});
$('browse-presets').onclick=()=>{
  const id=(activeShot()?.camera || '').split('@')[0];
  openPresetBrowser((config.presets || []).find(p=>p.id===id)?.kind || 'camera');
};
var presetBrowserHooks={open:openPresetBrowser};
