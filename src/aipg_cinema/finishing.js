/* Offline finishing. Editing never dispatches inference or replaces a take. */
let studioView=studioStorage.getItem('studio-view') || 'shot', soundUploading=false;
let captionSerial=0, previewFrame=0;
const captionImages=new Map(), soundMetadata=new Map();
function finishNode(tag,attributes={},text=null) {
  const item=document.createElement(tag);
  for(const [key,value] of Object.entries(attributes)) item.setAttribute(key,String(value));
  if(text!==null) item.textContent=text;
  return item;
}
function finishButton(icon,label,action) {
  const button=finishNode('button',{type:'button',title:label,'aria-label':label});
  button.append(finishNode('img',{src:`/icons/${icon}.svg`,alt:'',class:'icon'}));
  button.onclick=action; return button;
}
function projectFrames() {return shortProject?.shots.reduce((n,s)=>n+s.trim_end-s.trim_start,0) || 0;}
function changedFinish() {markBoard(); drawBoard(); controls(); paintCaption().catch(e=>error(e.message));}
function numberField(parent,label,value,change,{min=0,max=30,step=1/24}={}) {
  const wrap=finishNode('label',{},label), input=finishNode('input',{type:'number',min,max,step,'aria-label':label});
  input.value=Number(value).toFixed(3); wrap.append(input); parent.append(wrap);
  function commit(report) {
    const next=Number(input.value);
    if(!input.value.trim() || !Number.isFinite(next) || next<min || next>max) {
      if(report) {error(`Choose ${label.toLowerCase()} between ${min} and ${max}.`);input.value=Number(value).toFixed(3);}
      return;
    }
    if(next===value) return;
    change(next); value=next; changedFinish();
  }
  input.oninput=()=>commit(false);input.onchange=()=>commit(true);
  return input;
}
function layoutFinish(frozen=false) {
  const finishing=!!shortProject && studioView==='finish';
  const auditioning=studioView==='looks';
  document.querySelector('.workspace').classList.toggle('finishing',finishing);
  document.querySelector('.workspace').classList.toggle('auditioning',auditioning);
  $('edit-tabs').hidden=false; $('finish-tab').hidden=!shortProject;
  $('shot-controls').hidden=finishing || auditioning; $('finish-controls').hidden=!finishing;
  $('shot-workspace').hidden=finishing || auditioning; $('sequence-tools').hidden=!finishing;
  $('audition-controls').hidden=$('audition-workspace').hidden=!auditioning;
  const shotIndex=shortProject ? shortProject.shots.findIndex(s=>s.id===activeShotId) : -1;
  $('editor-title').textContent=finishing ? 'Finish your short' : auditioning ? 'Audition a look' : shotIndex>=0 ? `Shot ${shotIndex+1} · ${shortProject.shots[shotIndex].title}` : globalThis.featureTitle?.() || 'Compose a shot';
  for(const [id,active] of [['shot-tab',!finishing && !auditioning],['auditions-tab',auditioning],['finish-tab',finishing]]) {$(id).classList.toggle('active',active);$(id).setAttribute('aria-pressed',String(active));}
  $('short-stage').className='short-stage '+(shortProject?.frame_format || 'square');
  $('short-empty').hidden=!!$('short-output').getAttribute('src');
  const blocked=frozen || soundUploading;
  for(const field of document.querySelectorAll('#finish-controls input,#finish-controls textarea,#finish-controls select,#finish-controls button')) field.disabled=blocked;
  $('add-caption').disabled=blocked || !shortProject || (shortProject.captions?.length || 0)>=30 || !projectFrames();
  $('shot-tab').disabled=$('finish-tab').disabled=$('auditions-tab').disabled=blocked;
  auditionHooks?.controls(blocked);
  if(soundUploading) $('generate').disabled=$('export-short').disabled=true;
}
function selectStudioView(view) {
  studioView=view; studioStorage.setItem('studio-view',view);
  if(view!=='shot') pause(); else $('short-output').pause();
  if(view==='looks') { $('short-output').pause(); auditionHooks?.loaded(); }
  layoutFinish(); paintCaption().catch(e=>error(e.message));
}
async function uploadSound(role,file) {
  if(!file || soundUploading || !shortProject) return;
  const projectId=shortProject.id;
  soundUploading=true; controls(); error('');
  try {
    const form=new FormData(); form.append('file',file);
    const data=await api('/api/audio?purpose=soundtrack',{method:'POST',body:form});
    soundMetadata.set(data.audio_id,data);
    if(shortProject?.id!==projectId) return;
    const frames=projectFrames(), available=Math.floor(data.duration*24);
    if(!frames) throw new Error('Add a shot before placing sound.');
    shortProject[role]={audio_id:data.audio_id,source_start:0,start_frame:0,duration_frames:role==='music' ? frames : Math.min(frames,available),volume:role==='music' ? 0.3 : 1,loop:role==='music',fade_in:0,fade_out:0};
    changedFinish(); renderSound(role); await saveBoard();
  } catch(e){error(e.message);} finally {soundUploading=false; controls();}
}
function renderSound(role) {
  const parent=$(role+'-controls'), layer=shortProject?.[role], title=role==='music' ? 'Music' : 'Voiceover';
  parent.replaceChildren();
  const file=finishNode('input',{type:'file',accept:'audio/*,.m4a,.mp4,.webm',hidden:''});
  file.onchange=()=>uploadSound(role,file.files[0]);
  const upload=finishNode('button',{type:'button'});
  upload.append(finishNode('img',{src:'/icons/upload.svg',alt:'',class:'icon'}),finishNode('span',{},layer ? 'Replace audio' : 'Choose audio'));
  upload.onclick=()=>file.click();
  const buttons=finishNode('div',{class:'sound-buttons'}); buttons.append(upload); parent.append(file,buttons);
  if(!layer) return;
  buttons.append(finishButton('trash-2','Remove '+title.toLowerCase(),()=>{shortProject[role]=null;changedFinish();renderSound(role);}));
  const name=finishNode('div',{class:'sound-name'},'Audio file'); parent.append(name);
  const setName=data=>{if(shortProject?.[role]?.audio_id===layer.audio_id) name.textContent=data.name;};
  if(soundMetadata.has(layer.audio_id)) setName(soundMetadata.get(layer.audio_id));
  else api(`/api/audio/${layer.audio_id}/info`).then(data=>{soundMetadata.set(layer.audio_id,data);setName(data);refreshAudio();}).catch(e=>error(e.message));
  const mute=finishNode('input',{type:'checkbox','aria-label':'Mute '+title.toLowerCase()});
  const muteLabel=finishNode('label',{class:'finish-check'}); muteLabel.append(mute,finishNode('span',{},'Mute'));parent.append(muteLabel);
  const volume=finishNode('input',{type:'range',min:0,max:2,step:0.05,'aria-label':title+' volume'}), level=finishNode('output');
  let lastVolume=layer.volume || (role==='music' ? 0.3 : 1);
  const updateVolume=()=>{volume.value=layer.volume;level.textContent=Math.round(layer.volume*100)+'%';mute.checked=layer.volume===0;};
  volume.oninput=()=>{layer.volume=Number(volume.value);if(layer.volume) lastVolume=layer.volume;updateVolume();changedFinish();};
  mute.onchange=()=>{layer.volume=mute.checked ? 0 : lastVolume;updateVolume();changedFinish();};
  updateVolume();const row=finishNode('div',{class:'sound-volume'});row.append(volume,level);parent.append(row);
  const times=finishNode('div',{class:'trim-fields'}); parent.append(times);
  numberField(times,title+' start (s)',layer.start_frame/24,n=>layer.start_frame=Math.round(n*24),{max:719/24});
  numberField(times,title+' length (s)',layer.duration_frames/24,n=>layer.duration_frames=Math.round(n*24),{min:1/24});
  numberField(parent,title+' source start (s)',layer.source_start,n=>layer.source_start=n,{max:1800,step:0.01});
  if(role==='music') {
    const loop=finishNode('input',{type:'checkbox','aria-label':'Loop music'});loop.checked=layer.loop;
    const label=finishNode('label',{class:'finish-check'});label.append(loop,finishNode('span',{},'Loop'));parent.append(label);
    loop.onchange=()=>{layer.loop=loop.checked;changedFinish();};
  }
  const fades=finishNode('div',{class:'trim-fields'});parent.append(fades);
  numberField(fades,title+' fade in (s)',layer.fade_in/24,n=>layer.fade_in=Math.round(n*24),{max:10});
  numberField(fades,title+' fade out (s)',layer.fade_out/24,n=>layer.fade_out=Math.round(n*24),{max:10});
  const listen=finishNode('audio',{controls:'',preload:'metadata','aria-label':title+' source preview'});
  function refreshAudio() {
    const data=soundMetadata.get(layer.audio_id), available=Math.floor(((data?.duration || 0)-layer.source_start)*24);
    const url=`/api/audio/${layer.audio_id}/soundtrack?source_start=${layer.source_start}&frames=${Math.min(720,available,layer.duration_frames)}`;
    if(available>0 && listen.getAttribute('src')!==url) listen.src=url;
  }
  listen.onplay=()=>{listen.volume=Math.min(1,layer.volume);};refreshAudio();parent.append(listen);
  parent.onchange=refreshAudio;
}
function renderCaptions() {
  const parent=$('caption-list');parent.replaceChildren();
  for(const [index,cue] of (shortProject?.captions || []).entries()) {
    const item=finishNode('div',{class:'caption-cue'}), actions=finishNode('div',{class:'caption-actions'});
    actions.append(finishNode('span',{},String(index+1).padStart(2,'0')));
    actions.append(finishButton('play','Preview caption '+(index+1),()=>{
      previewFrame=cue.start_frame;const player=$('short-output');
      if(player.readyState && player.getAttribute('src')) player.currentTime=cue.start_frame/24;
      paintCaption(cue.start_frame).catch(e=>error(e.message));
    }));
    actions.append(finishButton('trash-2','Remove caption '+(index+1),()=>{shortProject.captions=shortProject.captions.filter(c=>c.id!==cue.id);changedFinish();renderCaptions();}));
    const text=finishNode('textarea',{maxlength:160,rows:2,'aria-label':'Caption '+(index+1)});text.value=cue.text;
    text.oninput=()=>{cue.text=text.value;changedFinish();};
    const timing=finishNode('div',{class:'trim-fields'});
    numberField(timing,'Caption '+(index+1)+' in (s)',cue.start_frame/24,n=>cue.start_frame=Math.round(n*24),{max:719/24});
    numberField(timing,'Caption '+(index+1)+' out (s)',cue.end_frame/24,n=>cue.end_frame=Math.round(n*24),{min:1/24});
    item.append(actions,text,timing);parent.append(item);
  }
  controls();
}
async function paintCaption(frame=null) {
  const serial=++captionSerial,image=$('caption-overlay'),player=$('short-output');
  const position=frame ?? (player.getAttribute('src') ? Math.floor(player.currentTime*24) : previewFrame);
  const cue=shortProject?.captions?.find(c=>c.start_frame<=position && position<c.end_frame);
  if(studioView!=='finish' || !cue?.text.trim()) {image.hidden=true;return;}
  const settings={text:cue.text,frame_format:shortProject.frame_format,style:shortProject.caption_style || 'clean',position:shortProject.caption_position || 'lower'};
  const key=JSON.stringify(settings);let url=captionImages.get(key);
  if(!url) {
    const data=await api('/api/caption-previews',{method:'POST',headers:{'Content-Type':'application/json'},body:key});
    url=data.url;captionImages.set(key,url);if(captionImages.size>256) captionImages.delete(captionImages.keys().next().value);
  }
  if(serial!==captionSerial) return;
  if(image.getAttribute('src')!==url) image.src=url;image.hidden=false;
}
function loadFinish() {
  if(shortProject) {shortProject.captions ||= []; $('caption-style').value=shortProject.caption_style || 'clean';$('caption-position').value=shortProject.caption_position || 'lower';}
  renderSound('music');renderSound('voiceover');renderCaptions();layoutFinish();paintCaption().catch(e=>error(e.message));
}
finishingHooks={loaded:loadFinish,controls:layoutFinish,uploading:()=>soundUploading,preview:()=>{layoutFinish();paintCaption().catch(e=>error(e.message));}};
$('shot-tab').onclick=()=>selectStudioView('shot');$('finish-tab').onclick=()=>selectStudioView('finish');
for(const [id,key] of [['caption-style','caption_style'],['caption-position','caption_position']]) $(id).onchange=()=>{if(shortProject) {shortProject[key]=$(id).value;changedFinish();}};
$('add-caption').onclick=()=>{
  if(!shortProject || shortProject.captions.length>=30) return;
  const start=shortProject.captions.reduce((n,c)=>Math.max(n,c.end_frame),0),end=Math.min(projectFrames(),start+48);
  if(start>=end) {error('There is no remaining space after the last caption. Adjust its timing first.');return;}
  shortProject.captions.push({id:crypto.randomUUID().replaceAll('-',''),text:shortProject.title.slice(0,160),start_frame:start,end_frame:end});changedFinish();renderCaptions();
};
for(const event of ['timeupdate','seeked','loadedmetadata','ended']) $('short-output').addEventListener(event,()=>paintCaption().catch(e=>error(e.message)));
boardReady.then(loadFinish).catch(e=>error(e.message));
