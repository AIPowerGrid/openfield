/* Openfield navigation: Home (two main paths and more ways to start), the
   Product video builder, Projects, and the editor. Views only open the editor
   in the right mode; nothing renders until an explicit Generate. */
let homeFiles=[], homeStyle=null, homeBusy=false, homeDrawn=false, showcaseDrawn=false;
// Every studio capability as a starting point. A card only opens the editor in
// the right mode (and its file picker); nothing renders until Generate.
const ICON=d=>`<svg viewBox="0 0 24 24" fill="none" stroke="#ff9900" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const HOME_FEATURES=[
  {id:'product',title:'Create a product ad',text:'One photo becomes a calm, finished ad with a closing card and music.',icon:'<path d="M4 8l8-4 8 4-8 4z"/><path d="M4 8v8l8 4 8-4V8"/><path d="M12 12v8"/>'},
  {id:'reshoot',title:'Transform a video',tag:'OpenReshoot',text:'Upload footage and restyle it. Motion, timing and sound stay yours.',mode:'video',picker:'upload',heading:'Transform a video',direction:'Restyle the source clip as a warm 35mm film scene with soft natural light. Keep the original motion, framing and timing.',icon:'<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/>'},
  {id:'animate',title:'Animate a photo',text:'Turn a still image into a moving shot with a camera move.',mode:'image',picker:'upload-look',heading:'Animate a photo',icon:'<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/>'},
  {id:'idea',title:'Idea to video',text:'Describe a scene in words and get a five-second shot.',mode:'text',focus:'prompt',heading:'Idea to video',icon:'<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>'},
  {id:'audio',title:'Shot from audio',text:'Bring a voice or music track; the shot is timed to it. Not lip-sync.',mode:'audio',picker:'upload-audio',speech:true,heading:'Shot from audio',icon:'<path d="M12 3v18M8 7v10M4 10v4M16 7v10M20 10v4"/>'},
  {id:'story',title:'Multi-shot story',text:'Plan a hook, reveal and payoff, then export one edited short.',story:true,icon:'<rect x="3" y="5" width="5" height="14" rx="1"/><rect x="10" y="5" width="5" height="14" rx="1"/><rect x="17" y="5" width="4" height="14" rx="1"/>'},
  {id:'looks',title:'Look lab',text:'Try opening looks side by side before you spend a render.',looks:true,heading:'Look lab',icon:'<rect x="3" y="5" width="8" height="14" rx="1"/><rect x="13" y="5" width="8" height="14" rx="1"/>'},
];
let homeFeature=null, homeDismissed=false;
globalThis.featureTitle=()=>homeFeature?.heading || null;
async function launchFeature(feature,file=null,{picker=true}={}) {
  if(feature.id==='product') { location.hash='product'; return; }
  try {
    homeFeature=feature;
    if(shortProject) await loadBoard(null);
    if(!feature.looks && $('auditions-tab').classList.contains('active')) $('shot-tab').click();
    if(feature.story) {
      homeDismissed=true;
      $('project-form').hidden=false; $('new-project-structure').value='hook-reveal-payoff'; productForm();
      syncHome(); window.scrollTo({top:0}); $('new-project-title').focus(); return;
    }
    homeDismissed=true; syncHome(); window.scrollTo({top:0});
    if(feature.looks) { $('auditions-tab').click(); return; }
    if($('input-mode').value!==feature.mode) { $('input-mode').value=feature.mode; $('input-mode').dispatchEvent(new Event('change')); }
    // Replace a stock example from another mode, never the user's own words.
    const stock=Object.values(startingDirections);
    if(feature.direction && (!$('prompt').value.trim() || stock.includes($('prompt').value))) { $('prompt').value=feature.direction; $('prompt').dispatchEvent(new Event('input')); }
    if(feature.speech) { $('render-profile').value='single-pass-audio'; $('render-profile').dispatchEvent(new Event('change')); }
    controls();
    if(file) { const transfer=new DataTransfer(); transfer.items.add(file); $('file').files=transfer.files; $('file').dispatchEvent(new Event('change')); }
    else if(feature.picker && picker) $(feature.picker).click(); else if(feature.focus) $(feature.focus).focus();
  } catch(e) { error(e.message); }
}
function openfieldView() {
  if(shortProject || !$('project-form').hidden || pendingCreation) return 'editor';
  if(location.hash==='#projects') return 'projects';
  if(location.hash==='#product') return 'product';
  return homeDismissed ? 'editor' : 'home';
}
function homeVisible() { return ['home','product'].includes(openfieldView()); }
let shownView=null;
function syncHome() {
  const view=openfieldView(), home=['home','product'].includes(view);
  $('home').hidden=!home;
  $('home-main').hidden=view!=='home'; $('home-product').hidden=view!=='product';
  $('projects-view').hidden=view!=='projects';
  const workspace=document.querySelector('.workspace');
  workspace.classList.toggle('at-home',home); workspace.classList.toggle('at-projects',view==='projects');
  if(home && !showcaseDrawn) { showcaseDrawn=true; drawShowcase(); }
  if(home && !homeDrawn && config.estimates) drawHome();
  if(view==='projects' && shownView!=='projects') drawProjects();
  if(view!==shownView) window.scrollTo({top:0});
  shownView=view;
  $('nav-home').classList.toggle('active',home);
  $('nav-projects').classList.toggle('active',view==='projects' || (view==='editor' && !!shortProject));
  $('back-nav').textContent=view!=='editor' ? '' : shortProject ? '\u2190 Projects' : '\u2190 Home';
  $('project-name').textContent=view==='editor' ? shortProject?.title || '' : '';
  $('home-create').disabled=homeBusy || !homeFiles.length;
}
async function leaveProject() {
  homeFeature=null; $('project-form').hidden=true;
  if(shortProject) await loadBoard(null);
}
async function goHome() {
  try { homeDismissed=false; await leaveProject(); if(location.hash) history.pushState(null,'',location.pathname); }
  catch(e) { error(e.message); }
  syncHome();
}
async function goProjects() {
  try { await leaveProject(); if(location.hash!=='#projects') location.hash='projects'; }
  catch(e) { error(e.message); }
  shownView=null; syncHome();
}
function projectThumb(project) {
  for(const shot of project.shots) {
    const take=takes.find(t=>t.id===shot.selected_take_id);
    if(take?.output_url) { const video=document.createElement('video'); Object.assign(video,{src:take.output_url+'#t=1',muted:true,preload:'metadata'}); return video; }
  }
  const look=project.shots.find(s=>s.draft.look_id)?.draft.look_id;
  const image=document.createElement(look || project.product ? 'img' : 'div');
  if(look) image.src=`/api/looks/${look}`; else if(project.product) image.src=`/api/products/${project.product.photo_ids[0]}`;
  image.alt='';
  return image;
}
async function drawProjects() {
  const grid=$('project-grid');
  let list=[]; try { list=await api('/api/projects'); } catch(e) { error(e.message); }
  grid.replaceChildren(); $('projects-empty').hidden=!!list.length;
  for(const project of list) {
    const card=document.createElement('button'); card.type='button'; card.className='project-card '+project.frame_format;
    const media=projectThumb(project); media.classList.add('thumb');
    const done=project.shots.filter(s=>s.selected_take_id).length, seconds=project.shots.reduce((sum,s)=>sum+(s.trim_end-s.trim_start)/24,0);
    const title=document.createElement('strong'); title.textContent=project.title;
    const meta=document.createElement('small'); meta.textContent=`${project.product ? 'Product video' : 'Short'} · ${done}/${project.shots.length} shots done · ${seconds.toFixed(1)} s`;
    card.append(media,title,meta);
    card.onclick=async()=>{ try { history.pushState(null,'',location.pathname); await loadBoard(project.id); } catch(e) { error(e.message); } syncHome(); };
    grid.append(card);
  }
}
function homeStatus(text,failed=false) {
  $('home-status').textContent=text || ''; $('home-status').classList.toggle('failed',failed);
}
function homeMedia(url,label) {
  const video=document.createElement('video');
  Object.assign(video,{src:url,muted:true,loop:true,autoplay:true,playsInline:true,preload:'metadata'});
  video.setAttribute('aria-label',label);
  return video;
}
// One card per feature, Transform first: each plays its best reviewed example
// (from showcase.json) and opens that feature. Video and photo cards also take
// a dropped file.
const SHOWCASE_ORDER=['reshoot','product','animate','idea','audio','story'];
async function drawShowcase() {
  let examples={}; try { examples=await (await fetch('/showcase/showcase.json')).json(); } catch(e) { examples={}; }
  const strip=$('showcase'); strip.replaceChildren();
  for(const id of SHOWCASE_ORDER) {
    const feature=HOME_FEATURES.find(f=>f.id===id), example=examples[id];
    const card=document.createElement('button'); card.type='button';
    card.className='show-card'+(['reshoot','product'].includes(id) ? ' big' : '');
    card.setAttribute('aria-label',`${feature.title}: ${feature.text}`);
    const text=document.createElement('span'); text.className='show-text';
    const kind=document.createElement('span'); kind.className='show-kind'; kind.textContent=feature.tag || example?.label || {animate:'Photo to video',idea:'Text to video',audio:'Audio to video',story:'Short'}[id] || '';
    const title=document.createElement('strong'); title.textContent=feature.title;
    const caption=document.createElement('small'); caption.textContent=example?.caption || feature.text;
    const go=document.createElement('span'); go.className='show-try';
    go.textContent=id==='reshoot' ? 'Drop a video or click \u2192' : id==='product' ? 'Drop a photo or click \u2192' : 'Start \u2192';
    text.append(kind,title,caption,go);
    if(example?.video) {
      const video=document.createElement('video');
      Object.assign(video,{src:`/showcase/${example.video}.mp4`,poster:`/showcase/${example.video}.jpg`,muted:true,loop:true,autoplay:true,playsInline:true,preload:'auto'});
      card.append(video);
      if(example.segments) {
        // Captions (and, when the reel opens on its original, a Before/After
        // chip) follow the reel's segments.
        const chip=document.createElement('span'); chip.className='show-chip'; chip.hidden=!example.before_seconds; card.append(chip);
        video.addEventListener('timeupdate',()=>{
          const t=video.currentTime, segment=[...example.segments].reverse().find(s=>t>=s.start) || example.segments[0];
          const after=t-segment.start>=(example.before_seconds || 0);
          if(caption.textContent!==segment.caption) { caption.textContent=segment.caption; caption.classList.remove('swap'); void caption.offsetWidth; caption.classList.add('swap'); }
          chip.textContent=after ? 'Openfield' : 'Original'; chip.classList.toggle('after',after);
          shownSegment=segment;
        });
        // Recreate the segment on screen: its clip and style, ready for Generate.
        let shownSegment=example.segments[0];
        card.append(styleHooks.recreateButton(()=>{
          const style=styleHooks.byId(shownSegment.style);
          if(style) styleHooks.recreateExample(style,`/style-previews/examples/${shownSegment.example}.mp4`);
        }));
      }
    } else { const empty=document.createElement('span'); empty.className='show-empty'; empty.innerHTML=ICON(feature.icon); card.append(empty); }
    card.append(text);
    if(id==='reshoot') { card.onclick=()=>$('reshoot-file').click(); cardDrop(card,/^video\//,files=>launchFeature(feature,files[0])); }
    else if(id==='product') { card.onclick=()=>{location.hash='product';}; cardDrop(card,/^image\//,files=>{setHomeFiles(files); location.hash='product';}); }
    else card.onclick=()=>launchFeature(feature);
    strip.append(card);
  }
  const credits=$('showcase-credits'); credits.replaceChildren();
  for(const [i,c] of (examples.credits || []).entries()) {
    if(i) credits.append(' \u00b7 ');
    const link=document.createElement('a'); link.href=c.url; link.target='_blank'; link.rel='noopener'; link.textContent=`${c.title}, ${c.author}, ${c.license}`;
    credits.append(link);
  }
  credits.hidden=!credits.children.length;
  strip.hidden=false;
}
function cardDrop(card,accept,onFiles) {
  for(const name of ['dragenter','dragover']) card.addEventListener(name,event=>{event.preventDefault(); card.classList.add('dragging');});
  for(const name of ['dragleave','drop']) card.addEventListener(name,()=>card.classList.remove('dragging'));
  card.addEventListener('drop',event=>{event.preventDefault(); const files=[...event.dataTransfer.files].filter(f=>accept.test(f.type)); if(files.length) onFiles(files);});
}
async function drawHome() {
  homeDrawn=true;
  if(!shortTemplates.length) { try { shortTemplates=await api('/api/templates'); } catch(e) { shortTemplates=[]; } }
  homeStyle ||= shortTemplates.find(t=>t.id==='aipg-bottle') || shortTemplates[0] || null;
  drawHomeStyles();
  const strip=$('home-presets'); strip.replaceChildren();
  for(const preset of config.presets || []) {
    const tile=document.createElement('button'); tile.type='button'; tile.className='home-preset';
    tile.title=`${preset.name}: preview of this ${preset.kind==='effect' ? 'effect' : 'camera move'}`;
    const name=document.createElement('span'); name.textContent=preset.name;
    const kind=document.createElement('small'); kind.textContent=preset.kind==='effect' ? 'Effect' : 'Camera';
    tile.append(homeMedia(preset.preview_url,preset.name),name,kind);
    tile.onclick=()=>presetBrowserHooks?.open(preset.kind || 'camera');
    strip.append(tile);
  }
  $('home-presets-section').hidden=!strip.children.length;
  styleHooks?.home();
  toolHooks?.home();
  const e=config.estimates;
  $('home-estimate').textContent=config.autobrief
    ? `Planning is free. Drafting the brief from your photo ${e.brief.label.replace(' (est.)','')}. Each shot then shows its price before it renders.`
    : 'Planning is free. Each shot shows its price before it renders.';
  $('home-name').placeholder=config.autobrief ? 'Product name (optional: drafted from the photo)' : 'Product name';
}
function drawHomeStyles() {
  const list=$('home-styles'); list.replaceChildren();
  for(const t of shortTemplates) {
    const card=document.createElement('button'); card.type='button';
    card.className='home-style'+(homeStyle?.id===t.id ? ' selected' : '');
    card.setAttribute('aria-pressed',String(homeStyle?.id===t.id));
    if(t.preview_url) card.append(homeMedia(t.preview_url,t.name)); else { const blank=document.createElement('div'); blank.className='blank'; card.append(blank); }
    const name=document.createElement('span'); name.textContent=t.name.replace(/\s*\(.*\)$/,'');
    const meta=document.createElement('small'); meta.textContent=`${t.pacing==='calm' ? 'Calm' : 'Punchy'} · ${t.shots.length} shots${t.worn ? ' · worn' : ''}`;
    card.append(name,meta);
    card.onclick=()=>{homeStyle=homeStyle?.id===t.id ? null : t; drawHomeStyles();};
    list.append(card);
  }
}
function setHomeFiles(files) {
  const images=[...files].filter(f=>/^image\/(png|jpeg|webp)$/.test(f.type)).slice(0,3);
  if(!images.length) { homeStatus('Choose a PNG, JPEG or WebP photo.',true); return; }
  homeFiles=images; homeStatus('');
  const thumbs=$('home-thumbs'); thumbs.replaceChildren();
  for(const file of images) { const image=document.createElement('img'); image.alt='Product photo'; image.src=URL.createObjectURL(file); thumbs.append(image); }
  $('home-drop').classList.add('filled'); syncHome();
}
$('reshoot-file').onchange=()=>{ if($('reshoot-file').files.length) launchFeature(HOME_FEATURES.find(f=>f.id==='reshoot'),$('reshoot-file').files[0]); };
$('product-path-photo').onchange=()=>{ if($('product-path-photo').files.length) { setHomeFiles($('product-path-photo').files); location.hash='product'; } };
$('home-create').onclick=async()=>{
  if(homeBusy || !homeFiles.length) return;
  homeBusy=true; syncHome(); error('');
  try {
    openProductForm();
    if(!$('product-name').value.trim()) {
      if(!config.autobrief) throw new Error('Add a product name.');
      homeStatus('Drafting your brief from the photo');
      await $('product-fill').onclick();
      if(!$('product-name').value.trim()) throw new Error($('error').textContent || 'The brief could not be drafted. Add a product name.');
      $('new-project-title').value=`${$('product-name').value.trim()} short`.slice(0,100);
    }
    homeStatus('Planning your shots');
    $('project-form').requestSubmit();
    window.scrollTo({top:0});
  } catch(e) { $('project-form').hidden=true; homeStatus(e.message,true); }
  finally { homeBusy=false; syncHome(); }
};
$('home-browse').onclick=()=>presetBrowserHooks.open('camera');
$('home-brief').onclick=()=>{openProductForm(); syncHome(); $('product-name').focus();};
for(const id of ['home-link','nav-home']) $(id).onclick=event=>{event.preventDefault(); goHome();};
$('nav-projects').onclick=event=>{event.preventDefault(); goProjects();};
$('product-back').onclick=event=>{event.preventDefault(); goHome();};
$('back-nav').onclick=()=>shortProject ? goProjects() : goHome();
$('projects-new').onclick=()=>launchFeature(HOME_FEATURES.find(f=>f.id==='story'));
$('projects-import').onclick=()=>$('import-project').click();
addEventListener('hashchange',async()=>{ if(location.hash==='#projects' && shortProject) await goProjects(); else syncHome(); });
addEventListener('popstate',()=>syncHome());
// The shot editor's error line is hidden on the home screen; mirror errors
// raised while the home screen is creating a short.
new MutationObserver(()=>{ if(homeBusy && $('error').textContent) homeStatus($('error').textContent,true); }).observe($('error'),{childList:true,characterData:true,subtree:true});
const baseProductControls=productHooks.controls;
productHooks.controls=frozen=>{baseProductControls(frozen); syncHome();};
syncHome();
