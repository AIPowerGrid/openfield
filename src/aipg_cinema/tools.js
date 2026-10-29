/* Single-purpose tools: FPS boost, background removal, upscale and reframe on
   an uploaded clip or a finished take, plus Relight (a Transform style). Each
   run is one request; nothing is retried. */
// home.js loads before this script and draws the Home tool strip as soon as
// config arrives, which can happen before the definitions below exist. The
// hooks are therefore installed first: an early home() is remembered and
// honored once this script has run, and the strip is redrawn when the tool
// parts of config (backend, cloud-only list, readiness) change.
let toolHomeWanted=false, toolsDefined=false, toolHomeKey=null;
globalThis.toolHooks={
  home() { toolHomeWanted=true; if(toolsDefined) drawHomeTools(); },
  open(id,takeId=null) { if(toolsDefined) openTool(id,takeId); },
};
const TOOLS=[
  {id:'fps-boost',name:'FPS boost',text:'Smoother motion: 24 fps becomes 48 with RIFE frame interpolation.',icon:'<path d="M5 12h14"/><path d="M5 6h9"/><path d="M5 18h11"/>'},
  {id:'remove-background',name:'Remove background',text:'Cut people and objects out onto a green screen, a solid color or a matte.',icon:'<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5"/>'},
  {id:'upscale',name:'Upscale 2×',text:'Sharper, bigger frames with RealESRGAN.',icon:'<path d="M4 14v6h6"/><path d="M20 10V4h-6"/><path d="M4 20 10 14"/><path d="M20 4l-6 6"/>'},
  {id:'depth-map',name:'Depth map',text:'A gray depth pass of every frame (Depth Anything V2 Small) for compositing and 3D.',icon:'<path d="M3 20l6-10 4 6 3-4 5 8z"/><circle cx="17" cy="6" r="2"/>'},
  {id:'extend',name:'Extend +5 s',text:'Continue a finished take for five more seconds from its last frame, joined seamlessly.',icon:'<path d="M3 12h13"/><path d="M12 7l5 5-5 5"/><path d="M20 5v14"/>'},
  {id:'reframe',name:'Reframe',text:'Turn landscape into vertical (or back) with a blurred fill or a center crop. Runs locally.',icon:'<rect x="3" y="6" width="12" height="12" rx="2"/><rect x="9" y="3" width="12" height="18" rx="2"/>'},
  {id:'lipdub',name:'Change what they say',text:'Type new words, or change some of them, and the person says them in their own voice with matching lips. Any of ten languages. Up to 10 seconds, one speaker.',icon:'<path d="M4 6h16v9H9l-5 4z"/><path d="M8 10h8"/>'},
  {id:'captions',name:'Auto captions',text:'Big word-by-word captions from the speech, burned in social-style, plus an .srt file. Runs locally with Whisper.',icon:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 15h4M13 15h4M7 11h10"/>'},
  {id:'insert',name:'Add to video',beta:true,text:'Put a product or object from your photos into a clip, like a bottle in someone\'s hand. Beta: best on steady shots.',icon:'<path d="M12 5v14M5 12h14"/><rect x="3" y="3" width="18" height="18" rx="3"/>'},
  {id:'relight',name:'Relight',text:'Golden-hour light on your own footage: a Transform style.',icon:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'},
];
let toolRun=null, toolTimer=null, toolSourceId=null, toolBusy=false, toolReturn=null, toolCurrent=null;
// Elapsed-time hint while a run is active, and the consecutive status-read
// failures that stop the poll after five tries.
let toolStartedAt=null, toolTick=null, toolLabelNow='', toolPollFailures=0;
const TOOL_POLL_FAILURE_LIMIT=5;
// Tools the server lists in config.cloud_only_tools cannot run on a
// self-hosted worker. An undefined list means unknown, so nothing is marked.
const CLOUD_ONLY_NOTE='Comfy Cloud only';
const CLOUD_ONLY_MESSAGE='Comfy Cloud only: this tool is not available on this worker. Start Openfield with --tool-backend cloud to use it. Nothing was sent.';
function toolCloudOnly(id) { return config.tool_backend==='self-hosted' && Array.isArray(config.cloud_only_tools) && config.cloud_only_tools.includes(id); }
function toolConfigKey() { return JSON.stringify([config.tool_backend,config.cloud_only_tools,config.tools?.lipdub]); }
// Small presentation rules for cloud-only cards/tabs; app.html's stylesheet
// belongs to another owner, so they travel with this script.
const toolStyle=document.createElement('style');
toolStyle.dataset.from='tools.js';
toolStyle.textContent='.tool-card.cloud-only,.tool-tabs button.cloud-only{opacity:.55}.tool-card.cloud-only:hover:not(:disabled){border-color:var(--line);background:var(--panel-2)}.cloud-only-note{display:inline-block;margin-left:6px;font-size:10px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;color:var(--muted);vertical-align:middle;white-space:nowrap}';
document.head.append(toolStyle);
function cloudOnlyNote() { const note=document.createElement('span'); note.className='cloud-only-note'; note.textContent=CLOUD_ONLY_NOTE; return note; }
function toolEstimate(tool) {
  if(toolCloudOnly(tool)) return `${CLOUD_ONLY_NOTE} (not available on this worker)`;
  if(tool==='reframe' || tool==='captions') return 'Runs on this computer; no GPU.';
  if(tool==='extend') return config.estimates?.take?.label || 'One five-second take';
  if(tool==='lipdub') {
    if(config.tool_backend==='cloud') return 'About 4 minutes on Comfy Cloud (est.)';
    const ready=config.tools?.lipdub; // true/false from the server; null or undefined: not checked yet
    if(ready===true) return 'About 4 minutes on your GPU (est.)';
    if(ready===false) return 'Needs Comfy Cloud (not available on this worker)';
    return 'About 4 minutes (est.); availability is checked when it runs';
  }
  return config.tool_backend==='cloud' ? 'A few Cloud credits (est.)' : 'Under a minute on your GPU (est.)';
}
function drawHomeTools() {
  toolHomeKey=toolConfigKey();
  const strip=$('home-tools'); strip.replaceChildren();
  for(const tool of TOOLS) {
    const cloudOnly=toolCloudOnly(tool.id);
    const card=document.createElement('button'); card.type='button'; card.className='tool-card'+(cloudOnly ? ' cloud-only' : '');
    const icon=document.createElement('span'); icon.className='tool-icon'; icon.innerHTML=ICON(tool.icon);
    const name=document.createElement('strong'); name.textContent=tool.name;
    const text=document.createElement('small'); text.textContent=tool.text;
    card.append(icon,name,text);
    if(tool.beta) { const tag=document.createElement('span'); tag.className='beta-tag'; tag.textContent='Beta'; name.append(tag); }
    // The card still opens the tool, where Run explains why it cannot start.
    if(cloudOnly) { name.append(cloudOnlyNote()); card.setAttribute('aria-disabled','true'); card.title=CLOUD_ONLY_MESSAGE; }
    card.onclick=()=>tool.id==='relight' ? relightStyle() : tool.id==='insert' ? insertFromHome() : openTool(tool.id);
    strip.append(card);
  }
  $('home-tools-section').hidden=false;
}
async function insertFromHome() {
  await launchFeature(HOME_FEATURES.find(f=>f.id==='reshoot'),null,{picker:!sourceId});
  styleHooks.insert();
}
function relightStyle() {
  const style=styleHooks.byId('golden-hour');
  if(style) styleHooks.recreate(style); else launchFeature(HOME_FEATURES.find(f=>f.id==='reshoot'));
}
function finishedTakes() { return takes.filter(t=>t.status==='succeeded' && t.output_url && (t.mode || 'video')!=='packshot'); }
function drawToolTabs() {
  const tabs=$('tool-tabs'); tabs.replaceChildren();
  for(const tool of TOOLS.filter(t=>!['relight','insert'].includes(t.id))) {
    const cloudOnly=toolCloudOnly(tool.id);
    const tab=document.createElement('button'); tab.type='button'; tab.textContent=tool.name;
    tab.classList.toggle('active',tool.id===toolCurrent?.id); tab.setAttribute('aria-pressed',String(tool.id===toolCurrent?.id));
    if(cloudOnly) { tab.classList.add('cloud-only'); tab.setAttribute('aria-disabled','true'); tab.title=CLOUD_ONLY_MESSAGE; tab.append(cloudOnlyNote()); }
    tab.onclick=()=>openTool(tool.id,$('tool-take').value || null);
    tabs.append(tab);
  }
}
function openTool(id,takeId=null) {
  if($('tool-runner').hidden) toolReturn=document.activeElement;
  toolCurrent=TOOLS.find(t=>t.id===id); drawToolTabs();
  $('tool-title').textContent=toolCurrent.name; $('tool-text').textContent=toolCurrent.text;
  $('tool-background-field').hidden=id!=='remove-background';
  $('tool-reframe-fields').hidden=id!=='reframe';
  $('tool-lipdub-fields').hidden=id!=='lipdub';
  const select=$('tool-take'); select.replaceChildren();
  const none=document.createElement('option'); none.value=''; none.textContent=toolSourceId ? 'Uploaded clip' : 'Choose a clip or a take'; select.append(none);
  for(const [index,take] of finishedTakes().entries()) {
    const option=document.createElement('option'); option.value=take.id;
    option.textContent=`Take ${String(index+1).padStart(2,'0')} · ${(take.art_direction || take.prompt || '').slice(0,48)}`;
    select.append(option);
  }
  select.value=takeId || '';
  if(!toolRun || toolRun.tool!==id) showToolResult(null);
  const wasHidden=$('tool-runner').hidden;
  $('tool-runner').hidden=false; document.body.classList.add('modal-open');
  drawToolControls(); if(wasHidden) $('tool-close').focus();
  if(id==='lipdub') fillTranscript();
}
// Change what they say: show the clip's own words so any part can be edited.
let transcriptFor=null;
async function fillTranscript() {
  if(toolCurrent?.id!=='lipdub') return;
  const take=$('tool-take').value, key=take || toolSourceId;
  if(!key || key===transcriptFor) return;
  transcriptFor=key; $('tool-line').value=''; $('tool-line').placeholder='Reading what they say…';
  try {
    const spoken=await api(`/api/transcript?${take ? `take_id=${take}` : `source_id=${toolSourceId}`}`);
    if(transcriptFor===key) { $('tool-line').value=spoken.text; $('tool-line').placeholder='No speech found. Type what they should say.'; }
  } catch(e) { $('tool-line').placeholder=e.message; }
  drawToolControls();
}
function closeTool() {
  $('tool-runner').hidden=true; document.body.classList.remove('modal-open');
  $('tool-video').pause(); toolReturn?.focus?.();
}
function toolStatus(text,failed=false) { $('tool-status').textContent=text || ''; $('tool-status').classList.toggle('failed',failed); }
// "Running… 12 s": the status line counts the seconds while a run is active.
// The live region is quiet while it ticks so screen readers hear the final
// status once rather than every second.
function toolElapsed() { return toolStartedAt ? `${Math.max(0,Math.round((Date.now()-toolStartedAt)/1000))} s` : ''; }
function toolTicking(on) {
  clearInterval(toolTick); toolTick=null;
  $('tool-status').setAttribute('aria-live',on ? 'off' : 'polite');
  if(on) toolTick=setInterval(()=>{ if(toolStartedAt) toolStatus(`${toolLabelNow}… ${toolElapsed()}`); },1000);
}
function drawToolControls() {
  if(!toolCurrent) return;
  const ready=(config.tools || {})[toolCurrent.id]; // null: checked when run
  const cloudOnly=toolCloudOnly(toolCurrent.id);
  const input=$('tool-take').value || (toolCurrent.id==='extend' ? null : toolSourceId);
  $('tool-upload').hidden=toolCurrent.id==='extend';
  const active=toolRun && (toolRun.active || !['succeeded','failed','cancelled','needs_review','needs_recovery'].includes(toolRun.status));
  // A cloud-only tool keeps Run clickable so it can explain itself instead of sending.
  $('tool-run').disabled=toolBusy || active || (!cloudOnly && (!input || ready===false || (toolCurrent.id==='lipdub' && !$('tool-line').value.trim())));
  $('tool-upload').disabled=toolBusy || active;
  const lipdubWorker=toolCurrent.id==='lipdub' && config.tool_backend!=='cloud';
  $('tool-estimate').textContent=!cloudOnly && !lipdubWorker && ready===false
    ? (config.tool_backend==='cloud' ? 'Comfy Cloud is unavailable.' : 'This tool needs its model on your ComfyUI worker, or start Openfield with --tool-backend cloud.')
    : toolEstimate(toolCurrent.id);
}
function showToolResult(run) {
  const done=run?.status==='succeeded' && run.output_url;
  $('tool-result').hidden=!done;
  const video=$('tool-video');
  if(done) {
    if(video.getAttribute('src')!==run.output_url) video.src=run.output_url;
    // The element starts muted in the markup; a result's sound (dubbed speech,
    // or the source's own audio) must be audible, with the controls kept.
    video.muted=false; video.volume=1; video.controls=true;
    $('tool-download').href=run.output_url;
    $('tool-comfy').hidden=!run.comfyui_url; if(run.comfyui_url) $('tool-comfy').href=run.comfyui_url;
    $('tool-srt').hidden=!run.srt_url; if(run.srt_url) $('tool-srt').href=run.srt_url;
  } else video.removeAttribute('src');
}
// After five consecutive failed status reads the poll stops and offers one
// "Check again" that resumes the same poll; the run itself is never re-sent.
function offerToolRecheck() {
  const status=$('tool-status');
  const again=document.createElement('button'); again.type='button'; again.className='text-button'; again.textContent='Check again';
  again.onclick=()=>{ toolStatus('Checking'); pollTool(); };
  status.append(' ',again);
}
async function pollTool() {
  clearTimeout(toolTimer); toolTimer=null;
  if(!toolRun) return;
  try {
    toolRun=await api(`/api/tools/${toolRun.id}`);
    toolPollFailures=0;
    const label={preparing:'Preparing the clip',queued:'Queued',running:'Running',exporting:'Saving the result',succeeded:'Done'}[toolRun.status] || states[toolRun.status] || toolRun.status;
    const active=toolRun.active || ['preparing','queued','running','exporting','submitting','in_progress','pending'].includes(toolRun.status);
    if(active) {
      toolStartedAt ||= Date.now(); toolLabelNow=label;
      toolStatus(`${label}… ${toolElapsed()}`); toolTicking(true);
    } else {
      toolTicking(false); toolStartedAt=null;
      toolStatus(toolRun.error || label,['failed','cancelled','needs_review','needs_recovery'].includes(toolRun.status));
    }
    showToolResult(toolRun);
    if(active) toolTimer=setTimeout(pollTool,3000);
  } catch(e) {
    toolPollFailures+=1;
    if(toolPollFailures<TOOL_POLL_FAILURE_LIMIT) { toolStatus(`${e.message} (try ${toolPollFailures} of ${TOOL_POLL_FAILURE_LIMIT})`,true); toolTimer=setTimeout(pollTool,5000); }
    else {
      toolPollFailures=0; toolTicking(false);
      toolStatus(`${e.message} The status could not be read ${TOOL_POLL_FAILURE_LIMIT} times in a row; nothing was retried.`,true);
      offerToolRecheck();
    }
  }
  drawToolControls();
}
$('tool-upload').onclick=()=>$('tool-file').click();
$('tool-file').onchange=async()=>{
  const file=$('tool-file').files[0]; if(!file) return;
  toolBusy=true; drawToolControls(); toolStatus('Uploading');
  try {
    const form=new FormData(); form.append('file',file);
    toolSourceId=(await api('/api/sources',{method:'POST',body:form})).source_id;
    $('tool-take').options[0].textContent=`Uploaded: ${file.name}`; $('tool-take').value=''; toolStatus(''); fillTranscript();
  } catch(e) { toolStatus(e.message,true); }
  finally { toolBusy=false; $('tool-file').value=''; drawToolControls(); }
};
$('tool-take').onchange=()=>{ drawToolControls(); fillTranscript(); };
$('tool-line').oninput=drawToolControls;
$('tool-run').onclick=async()=>{
  if($('tool-run').disabled) return;
  if(toolCloudOnly(toolCurrent.id)) { toolStatus(CLOUD_ONLY_MESSAGE,true); return; }
  toolBusy=true; drawToolControls(); toolStatus('Starting');
  const take=$('tool-take').value;
  const body={request_id:crypto.randomUUID().replaceAll('-',''),tool:toolCurrent.id,...(take ? {take_id:take} : {source_id:toolSourceId}),background:$('tool-background').value,target:$('tool-target').value,fit:$('tool-fit').value,...(toolCurrent.id==='lipdub' ? {line:$('tool-line').value,language:$('tool-language').value} : {})};
  try {
    toolRun=await api('/api/tools',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    toolStartedAt=Date.now(); toolPollFailures=0; showToolResult(null); pollTool();
  }
  catch(e) { toolStatus(e.message,true); }
  finally { toolBusy=false; drawToolControls(); }
};
$('tool-close').onclick=closeTool;
$('tool-runner').addEventListener('click',event=>{if(event.target===$('tool-runner')) closeTool();});
document.addEventListener('keydown',event=>{if(event.key==='Escape' && !$('tool-runner').hidden) closeTool();});
$('take-tools').onclick=()=>openTool('fps-boost',selected);
const baseToolControls=productHooks.controls;
productHooks.controls=frozen=>{
  baseToolControls(frozen);
  const take=takes.find(t=>t.id===selected);
  $('take-tools').hidden=!(take?.status==='succeeded' && take.output_url && !projectHooks?.active());
  // controls() runs after every config refresh: redraw the strip and tabs when
  // the tool parts of config changed since they were last drawn.
  if(toolHomeWanted && toolConfigKey()!==toolHomeKey) { drawHomeTools(); if(toolCurrent && !$('tool-runner').hidden) { drawToolTabs(); drawToolControls(); } }
};
// Definitions are in place: honor a home() that arrived early, or a Home that
// was already drawn before this script ran.
toolsDefined=true;
if(toolHomeWanted || (typeof homeDrawn!=='undefined' && homeDrawn)) drawHomeTools();
