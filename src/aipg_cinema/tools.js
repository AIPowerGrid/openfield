/* Single-purpose tools: FPS boost, background removal, upscale and reframe on
   an uploaded clip or a finished take, plus Relight (a Transform style). Each
   run is one request; nothing is retried. */
const TOOLS=[
  {id:'fps-boost',name:'FPS boost',text:'Smoother motion: 24 fps becomes 48 with RIFE frame interpolation.',icon:'<path d="M5 12h14"/><path d="M5 6h9"/><path d="M5 18h11"/>'},
  {id:'remove-background',name:'Remove background',text:'Cut people and objects out onto a green screen, a solid colour or a matte.',icon:'<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.2-3.6 3.8-5.5 7-5.5s5.8 1.9 7 5.5"/>'},
  {id:'upscale',name:'Upscale 2×',text:'Sharper, bigger frames with RealESRGAN.',icon:'<path d="M4 14v6h6"/><path d="M20 10V4h-6"/><path d="M4 20 10 14"/><path d="M20 4l-6 6"/>'},
  {id:'depth-map',name:'Depth map',text:'A grey depth pass of every frame (Depth Anything V2 Small) for compositing and 3D.',icon:'<path d="M3 20l6-10 4 6 3-4 5 8z"/><circle cx="17" cy="6" r="2"/>'},
  {id:'extend',name:'Extend +5 s',text:'Continue a finished take for five more seconds from its last frame, joined seamlessly.',icon:'<path d="M3 12h13"/><path d="M12 7l5 5-5 5"/><path d="M20 5v14"/>'},
  {id:'reframe',name:'Reframe',text:'Turn landscape into vertical (or back) with a blurred fill or a centre crop. Runs locally.',icon:'<rect x="3" y="6" width="12" height="12" rx="2"/><rect x="9" y="3" width="12" height="18" rx="2"/>'},
  {id:'relight',name:'Relight',text:'Golden-hour light on your own footage: a Transform style.',icon:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'},
];
let toolRun=null, toolTimer=null, toolSourceId=null, toolBusy=false, toolReturn=null, toolCurrent=null;
function toolEstimate(tool) {
  if(tool==='reframe') return 'Runs on this computer; no GPU.';
  if(tool==='extend') return config.estimates?.take?.label || 'One five-second take';
  return config.tool_backend==='cloud' ? 'A few Cloud credits (est.)' : 'Under a minute on your GPU (est.)';
}
function drawHomeTools() {
  const strip=$('home-tools'); strip.replaceChildren();
  for(const tool of TOOLS) {
    const card=document.createElement('button'); card.type='button'; card.className='tool-card';
    const icon=document.createElement('span'); icon.className='tool-icon'; icon.innerHTML=ICON(tool.icon);
    const name=document.createElement('strong'); name.textContent=tool.name;
    const text=document.createElement('small'); text.textContent=tool.text;
    card.append(icon,name,text);
    card.onclick=()=>tool.id==='relight' ? relightStyle() : openTool(tool.id);
    strip.append(card);
  }
  $('home-tools-section').hidden=false;
}
function relightStyle() {
  const style=styleHooks.byId('golden-hour');
  if(style) styleHooks.recreate(style); else launchFeature(HOME_FEATURES.find(f=>f.id==='reshoot'));
}
function finishedTakes() { return takes.filter(t=>t.status==='succeeded' && t.output_url && (t.mode || 'video')!=='packshot'); }
function drawToolTabs() {
  const tabs=$('tool-tabs'); tabs.replaceChildren();
  for(const tool of TOOLS.filter(t=>t.id!=='relight')) {
    const tab=document.createElement('button'); tab.type='button'; tab.textContent=tool.name;
    tab.classList.toggle('active',tool.id===toolCurrent?.id); tab.setAttribute('aria-pressed',String(tool.id===toolCurrent?.id));
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
}
function closeTool() {
  $('tool-runner').hidden=true; document.body.classList.remove('modal-open');
  $('tool-video').pause(); toolReturn?.focus?.();
}
function toolStatus(text,failed=false) { $('tool-status').textContent=text || ''; $('tool-status').classList.toggle('failed',failed); }
function drawToolControls() {
  if(!toolCurrent) return;
  const ready=(config.tools || {})[toolCurrent.id]; // null: checked when run
  const input=$('tool-take').value || (toolCurrent.id==='extend' ? null : toolSourceId);
  $('tool-upload').hidden=toolCurrent.id==='extend';
  const active=toolRun && (toolRun.active || !['succeeded','failed','cancelled','needs_review','needs_recovery'].includes(toolRun.status));
  $('tool-run').disabled=toolBusy || active || !input || ready===false;
  $('tool-upload').disabled=toolBusy || active;
  $('tool-estimate').textContent=ready===false
    ? (config.tool_backend==='cloud' ? 'Comfy Cloud is unavailable.' : 'This tool needs its model on your ComfyUI worker, or start Openfield with --tool-backend cloud.')
    : toolEstimate(toolCurrent.id);
}
function showToolResult(run) {
  const done=run?.status==='succeeded' && run.output_url;
  $('tool-result').hidden=!done;
  if(done) {
    if($('tool-video').getAttribute('src')!==run.output_url) $('tool-video').src=run.output_url;
    $('tool-download').href=run.output_url;
    $('tool-comfy').hidden=!run.comfyui_url; if(run.comfyui_url) $('tool-comfy').href=run.comfyui_url;
  } else $('tool-video').removeAttribute('src');
}
async function pollTool() {
  clearTimeout(toolTimer);
  if(!toolRun) return;
  try {
    toolRun=await api(`/api/tools/${toolRun.id}`);
    const label={preparing:'Preparing the clip',queued:'Queued',running:'Running',exporting:'Saving the result',succeeded:'Done'}[toolRun.status] || states[toolRun.status] || toolRun.status;
    toolStatus(toolRun.error || label,['failed','cancelled','needs_review','needs_recovery'].includes(toolRun.status));
    showToolResult(toolRun);
    if(toolRun.active || ['preparing','queued','running','exporting','submitting','in_progress','pending'].includes(toolRun.status)) toolTimer=setTimeout(pollTool,3000);
  } catch(e) { toolStatus(e.message,true); }
  drawToolControls();
}
$('tool-upload').onclick=()=>$('tool-file').click();
$('tool-file').onchange=async()=>{
  const file=$('tool-file').files[0]; if(!file) return;
  toolBusy=true; drawToolControls(); toolStatus('Uploading');
  try {
    const form=new FormData(); form.append('file',file);
    toolSourceId=(await api('/api/sources',{method:'POST',body:form})).source_id;
    $('tool-take').options[0].textContent=`Uploaded: ${file.name}`; $('tool-take').value=''; toolStatus('');
  } catch(e) { toolStatus(e.message,true); }
  finally { toolBusy=false; $('tool-file').value=''; drawToolControls(); }
};
$('tool-take').onchange=drawToolControls;
$('tool-run').onclick=async()=>{
  if($('tool-run').disabled) return;
  toolBusy=true; drawToolControls(); toolStatus('Starting');
  const take=$('tool-take').value;
  const body={request_id:crypto.randomUUID().replaceAll('-',''),tool:toolCurrent.id,...(take ? {take_id:take} : {source_id:toolSourceId}),background:$('tool-background').value,target:$('tool-target').value,fit:$('tool-fit').value};
  try { toolRun=await api('/api/tools',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); showToolResult(null); pollTool(); }
  catch(e) { toolStatus(e.message,true); }
  finally { toolBusy=false; drawToolControls(); }
};
$('tool-close').onclick=closeTool;
$('tool-runner').addEventListener('click',event=>{if(event.target===$('tool-runner')) closeTool();});
document.addEventListener('keydown',event=>{if(event.key==='Escape' && !$('tool-runner').hidden) closeTool();});
$('take-tools').onclick=()=>openTool('fps-boost',selected);
var toolHooks={home:drawHomeTools,open:openTool};
const baseToolControls=productHooks.controls;
productHooks.controls=frozen=>{
  baseToolControls(frozen);
  const take=takes.find(t=>t.id===selected);
  $('take-tools').hidden=!(take?.status==='succeeded' && take.output_url && !projectHooks?.active());
};
