/* Persistent shot editing. Only the explicit Generate action dispatches work. */
let shortProject=null, activeShotId=null, boardLoading=false, boardDirty=false;
let boardSaving=null, boardTimer=null, boardEdits=0, boardConflict=false, boardFingerprint='';
let sequencePending=saved('studio-export-pending'), sequenceExport=null, sequenceSubmitting=false, sequencePolling=false;
let finishingHooks=null;
let pendingCreation=saved('studio-creation-pending'), creationBusy=false, creationMissing=false, boardInitialized=false;
function activeShot() { return shortProject?.shots.find(s=>s.id===activeShotId) || null; }
function selectableTake(take) { return !!shortProject && !!take?.output_url && (take.frame_format || 'landscape')===shortProject.frame_format; }
function boardMessage(message) { $('project-state').textContent=message; }
function cacheBoard() {
  if(shortProject) studioStorage.setItem(`studio-project-draft:${shortProject.id}`,JSON.stringify(shortProject));
}
function markBoard() {
  if(boardLoading || !shortProject) return;
  boardDirty=true; boardEdits++; cacheBoard(); boardMessage('Unsaved');
  clearTimeout(boardTimer); boardTimer=setTimeout(()=>saveBoard().catch(e=>error(e.message)),500);
}
function captureShot() {
  if(boardLoading || !activeShot()) return;
  const next=editorDraft();
  const current={...activeShot().draft,render_profile:activeShot().draft.render_profile || 'two-pass',art_direction:activeShot().draft.art_direction ?? activeShot().draft.prompt,motion_prompt:activeShot().draft.motion_prompt ?? ''};
  if(Object.keys(next).some(key=>current[key]!==next[key])) { activeShot().draft=next; markBoard(); }
}
async function saveBoard() {
  clearTimeout(boardTimer);
  if(boardSaving) await boardSaving;
  if(!shortProject || !boardDirty) return;
  if(boardConflict) throw new Error('This project has a save conflict. Reopen the saved project before generating.');
  if(!shortProject.title.trim() || shortProject.shots.some(s=>!s.title.trim())) {boardMessage('Name required'); throw new Error('Name the project and its shots before saving.');}
  const version=boardEdits, body=JSON.parse(JSON.stringify(shortProject));
  boardMessage('Saving');
  boardSaving=api(`/api/projects/${body.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  try {
    const result=await boardSaving;
    if(shortProject?.id!==body.id) return;
    shortProject.revision=result.revision;
    boardDirty=version!==boardEdits;
    // Retain the objects used by visible editing controls after acknowledgement.
    if(!boardDirty) { studioStorage.removeItem(`studio-project-draft:${body.id}`); }
    else cacheBoard();
    boardMessage(boardDirty ? 'Unsaved' : 'Saved');
  } catch(e) { boardConflict=!e.status || e.status===409 || e.status>=500; cacheBoard(); boardMessage('Save needs review'); throw e; }
  finally { boardSaving=null; }
  if(boardDirty) await saveBoard();
}
function boardOptions(items) {
  const menu=$('project-select'); menu.replaceChildren();
  const single=document.createElement('option'); single.value=''; single.textContent='Single shot'; menu.append(single);
  for(const project of items) { const option=document.createElement('option'); option.value=project.id; option.textContent=project.title; menu.append(option); }
  menu.value=shortProject?.id || '';
}
async function loadBoard(projectId,shotId=null,discard=false) {
  if(shortProject && !discard) { captureShot(); await saveBoard(); }
  if(!projectId) {
    shortProject=null; activeShotId=null; studioStorage.removeItem('studio-project'); studioStorage.removeItem('studio-shot');
    drawBoard(); controls(); return;
  }
  const project=await api(`/api/projects/${projectId}`), unsaved=saved(`studio-project-draft:${projectId}`);
  if(discard) {
    if(unsaved) studioStorage.setItem(`studio-project-recovery:${projectId}`,JSON.stringify(unsaved));
    studioStorage.removeItem(`studio-project-draft:${projectId}`);
  }
  shortProject=!discard && unsaved?.revision===project.revision ? unsaved : project;
  boardDirty=shortProject===unsaved; boardConflict=false;
  if(!discard && unsaved && unsaved.revision!==project.revision) {
    studioStorage.setItem(`studio-project-recovery:${projectId}`,JSON.stringify(unsaved));
    boardMessage('Saved project reopened; unsaved copy retained in this browser');
  } else boardMessage(boardDirty ? 'Unsaved' : 'Saved');
  studioStorage.setItem('studio-project',projectId);
  activeShotId=shortProject.shots.some(s=>s.id===shotId) ? shotId : shortProject.shots[0]?.id || null;
  await showShot();
}
async function showShot() {
  boardLoading=true;
  try {
    const shot=activeShot();
    $('project-title').value=shortProject?.title || '';
    $('shared-direction').value=shortProject?.art_direction || '';
    if(shot) {
      studioStorage.setItem('studio-shot',shot.id);
      const settings=shot.draft;
      inputMode=settings.mode; sourceId=settings.source_id; audioId=settings.audio_id;
      renderProfile=settings.render_profile || 'two-pass'; sourceHasAudio=false;
      frameFormat=shortProject.frame_format; sourceStart=settings.source_start;
      lookId=settings.look_id; closingId=settings.closing_id; lookFrame=0;
      $('prompt').value=settings.art_direction ?? settings.prompt;
      $('motion-prompt').value=settings.motion_prompt ?? '';
      restoreSeed(settings.seed); sourceName='Source clip'; audioName=audioId ? 'Source audio' : '';
      $('shot-title').value=shot.title; $('shot-beat').value=shot.beat;
      $('inherit-direction').checked=shot.direction_override===null;
      $('shot-override').value=shot.direction_override || '';
      $('shot-override').hidden=shot.direction_override===null;
      $('trim-start').value=(shot.trim_start/24).toFixed(3);
      $('trim-end').value=(shot.trim_end/24).toFixed(3);
      $('shot-volume').value=shot.volume;
      draftTouched=true;
      const remembered=studioStorage.getItem('openreshoot-selected');
      const preview=takes.find(t=>t.id===remembered && t.project_id===shortProject.id && t.shot_id===shot.id) || takes.find(t=>t.id===shot.selected_take_id);
      showTake(preview || null,false); setMode(preview?.output_url ? 'result' : 'compare');
    } else showTake(null);
    drawBoard(true); drawTakes(); controls();
    await refreshSequence();
    finishingHooks?.loaded();
    productHooks?.loaded();
    auditionHooks?.loaded();
  } finally { boardLoading=false; }
}
function drawBoard(force=false) {
  const project=shortProject, shot=activeShot();
  for(const id of ['project-fields','save-project','reload-project','sequence-tools']) $(id).hidden=!project;
  $('shot-editor').hidden=!shot;
  $('mobile-shot').hidden=!project;
  $('use-take').hidden=!shot;
  if(!project) { $('project-state').textContent=''; $('shot-board').replaceChildren(); return; }
  const duration=project.shots.reduce((n,s)=>n+s.trim_end-s.trim_start,0)/24;
  $('project-duration').textContent=`${project.shots.length} / 6 shots / ${duration.toFixed(2)}s`;
  $('project-duration').title=$('project-duration').textContent;
  $('project-select').value=project.id;
  const fingerprint=JSON.stringify([project,activeShotId,takes.map(t=>[t.id,t.output_url]),globalThis.shotStatusKey?.()]);
  if(!force && fingerprint===boardFingerprint) return;
  boardFingerprint=fingerprint; $('shot-board').replaceChildren(); $('shot-board').className='shot-board '+project.frame_format;
  $('mobile-shot').replaceChildren();
  project.shots.forEach((item,index)=>{
    const navigation=document.createElement('option'); navigation.value=item.id; navigation.textContent=`${index+1}. ${item.title}`; $('mobile-shot').append(navigation);
    const button=document.createElement('button'); button.className='shot-cell'+(item.id===activeShotId ? ' active' : '');
    button.setAttribute('aria-label',`Open shot ${index+1}: ${item.title}`);
    button.setAttribute('aria-pressed',String(item.id===activeShotId));
    const take=takes.find(t=>t.id===item.selected_take_id);
    const look=!take?.output_url && item.draft.look_id;
    const media=document.createElement(take?.output_url ? 'video' : look ? 'img' : 'div');
    if(take?.output_url) { media.src=take.output_url+'#t=1'; media.muted=true; media.preload='metadata'; }
    else if(look) { media.className='shot-look'; media.src=`/api/looks/${look}`; media.alt=''; }
    else { media.className='shot-placeholder'; }
    const text=document.createElement('span'); text.className='shot-label';
    const title=document.createElement('strong'); title.textContent=item.title;
    const preset=(config.presets || []).find(p=>p.id===(item.camera || '').split('@')[0]);
    const detail=document.createElement('small'); detail.textContent=[`${((item.trim_end-item.trim_start)/24).toFixed(1)} s`,preset?.name].filter(Boolean).join(' · ');
    const slate=document.createElement('span'); slate.className='slate mono'; slate.textContent=String(index+1).padStart(2,'0');
    text.append(title,detail); button.append(media,slate,text);
    const status=globalThis.shotStatus?.(item,take);
    if(status) { const chip=document.createElement('span'); chip.className='shot-status '+status[1]; chip.textContent=status[0]; button.append(chip); }
    button.disabled=!!pending || !!pendingLook || submitting || lookSubmitting || lookUploading || uploading;
    button.onclick=async()=>{if(pending || pendingLook || submitting || lookSubmitting || lookUploading || uploading) return; try { captureShot(); await saveBoard(); activeShotId=item.id; await showShot(); } catch(e){error(e.message);} };
    $('shot-board').append(button);
  });
  $('mobile-shot').value=activeShotId || '';
  const takeMenu=$('shot-take'); takeMenu.replaceChildren();
  const empty=document.createElement('option'); empty.value=''; empty.textContent='No selected take'; takeMenu.append(empty);
  for(const [index,take] of takes.entries()) {
    if(!selectableTake(take)) continue;
    const option=document.createElement('option'); option.value=take.id;
    option.textContent=`Take ${String(index+1).padStart(2,'0')} / ${(take.art_direction || take.prompt).slice(0,50)}`;
    takeMenu.append(option);
  }
  takeMenu.value=shot?.selected_take_id || '';
}
function boardControls(frozen) {
  frozen ||= !!finishingHooks?.uploading() || !!auditionHooks?.uploading();
  const shot=activeShot(), position=shortProject?.shots.findIndex(s=>s.id===activeShotId) ?? -1;
  for(const id of ['project-select','new-project','save-project','reload-project','add-shot','shot-left','shot-right','shot-duplicate','shot-remove','shot-title','shot-beat','shot-take','trim-start','trim-end','shot-volume','inherit-direction','shot-override','project-title','shared-direction']) $(id).disabled=frozen;
  for(const button of document.querySelectorAll('#shot-board button')) button.disabled=frozen;
  $('mobile-shot').disabled=frozen;
  for(const id of ['new-project-title','new-project-format','new-project-structure']) $(id).disabled=frozen || !!pendingCreation;
  $('create-project').disabled=frozen || creationBusy;
  $('retry-create-project').disabled=frozen || creationBusy || !creationMissing;
  if(shortProject) {
    $('add-shot').disabled=frozen || shortProject.shots.length>=6;
    $('shot-duplicate').disabled=frozen || !shot || shortProject.shots.length>=6;
    $('shot-left').disabled=frozen || position<=0;
    $('shot-right').disabled=frozen || position<0 || position>=shortProject.shots.length-1;
    $('use-take').disabled=frozen || boardConflict || !shot || !selectableTake(takes.find(t=>t.id===selected));
    if(boardConflict || !shot) $('generate').disabled=true;
    $('export-short').disabled=frozen || sequenceSubmitting || boardConflict || sequenceExport?.active || !shortProject.shots.length || shortProject.shots.some(s=>!s.selected_take_id);
  }
  finishingHooks?.controls(frozen);
  productHooks?.controls(frozen);
}
async function editBoard(action) {
  try { captureShot(); action(); markBoard(); drawBoard(true); await saveBoard(); await showShot(); }
  catch(e){error(e.message);}
}
function newShot() {
  return {id:crypto.randomUUID().replaceAll('-',''),title:'New shot',beat:'detail',draft:{mode:'text',render_profile:'two-pass',source_id:null,audio_id:null,look_id:null,closing_id:null,prompt:'',art_direction:'',motion_prompt:'One continuous shot. No cuts, subtitles, logos or watermarks.',seed:42,frame_format:shortProject.frame_format,source_start:0},direction_override:null,selected_take_id:null,trim_start:0,trim_end:120,volume:1};
}
async function generateBoardShot() {
  if(pending) return checkSubmission();
  if(submitting || !validSettings()) return;
  submitting=true; controls(); error('');
  try {
    if(!pending) {
      captureShot(); await saveBoard();
      const shot=activeShot(); if(!shot) throw new Error('Choose a shot.');
      pending={request_id:crypto.randomUUID().replaceAll('-',''),project_id:shortProject.id,shot_id:shot.id,project_revision:shortProject.revision,...editorDraft()};
      studioStorage.setItem('openreshoot-pending',JSON.stringify(pending));
    }
    const take=await api(`/api/projects/${pending.project_id}/shots/${pending.shot_id}/generate`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:pending.request_id,revision:pending.project_revision})});
    selected=take.id; studioStorage.setItem('openreshoot-selected',take.id);
    pending=null; studioStorage.removeItem('openreshoot-pending'); await refresh();
    boardLoading=true; try { showTake(take,false); } finally {boardLoading=false;}
    setMode(inputMode==='video' || lookId ? 'compare' : 'result');
  } catch(e) {
    if(e.status && e.status<500) { pending=null; studioStorage.removeItem('openreshoot-pending'); }
    error(e.message);
  } finally { submitting=false; controls(); }
}
projectHooks={
  active:()=>!!shortProject,
  busy:()=>creationBusy || !boardInitialized,
  context:()=>shortProject ? {project_id:shortProject.id,shot_id:activeShotId} : null,
  ready:()=>!boardLoading,
  changed:captureShot,
  controls:boardControls,
  filter:items=>shortProject ? items.filter(t=>(t.project_id===shortProject.id && t.shot_id===activeShotId) || t.id===activeShot()?.selected_take_id) : items,
  viewTake:take=>{const loading=boardLoading;boardLoading=true;try {showTake(take,false);} finally {boardLoading=loading;}},
  preview:()=>{$('use-take').hidden=!activeShot();},
  refreshed:()=>{drawBoard(); refreshSequence().catch(e=>error(e.message));},
  generate:generateBoardShot,
  newTake:()=>{
    try {
      const take=takes.find(t=>t.id===selected);
      const seed=nextSeed(take?.seed ?? $('seed').value);
      boardLoading=true;
      try { if(take) showTake(take); } finally {boardLoading=false;}
      restoreSeed(seed);showTake(null); captureShot(); $('prompt').focus();
    } catch(e) {error(e.message);}
  },
};
function rememberCreation(value) {
  if(value) studioStorage.setItem('studio-creation-pending',JSON.stringify(value));else studioStorage.removeItem('studio-creation-pending');
  pendingCreation=value;
}
function showCreation() {
  $('project-create-state').hidden=!pendingCreation;
  $('retry-create-project').hidden=!pendingCreation || !creationMissing;
  $('create-project-label').textContent=pendingCreation ? 'Check creation' : 'Create short';
  $('create-project').querySelector('img').src=pendingCreation ? '/icons/rotate-ccw.svg' : '/icons/plus.svg';
  $('project-create-message').textContent=creationMissing ? 'New short not found.' : 'New short not confirmed.';
  if(pendingCreation) {
    $('project-form').hidden=false;
    for(const [id,key] of [['new-project-title','title'],['new-project-format','frame_format'],['new-project-structure','structure']]) $(id).value=pendingCreation[key];
  }
}
async function finishCreation(receipt) {
  if(!pendingCreation || receipt.id!==pendingCreation.request_id || receipt.project?.id!==pendingCreation.request_id || !['title','frame_format','structure'].every(key=>receipt.request?.[key]===pendingCreation[key])) throw new Error('This new short does not match the saved creation request.');
  boardOptions(await api('/api/projects'));await loadBoard(receipt.project.id);
  rememberCreation(null);creationMissing=false;$('project-form').hidden=true;
}
async function createOrCheckProject(retry=false) {
  if(!boardInitialized || creationBusy || pending || pendingLook || submitting || lookSubmitting || uploading || lookUploading || projectTransferHooks?.busy()) return;
  if(retry && (!pendingCreation || !creationMissing)) return;
  creationBusy=true;controls();error('');let posted=false, checkingReceipt=false;
  try {
    captureShot();await saveBoard();
    const checking=!!pendingCreation && !retry;
    if(!pendingCreation) {
      const title=$('new-project-title').value.trim();if(!title) throw new Error('Name this short before creating it.');
      // Product shorts add their uploaded photos, brief and template here.
      const extra=await productHooks?.prepare() || {};
      rememberCreation({request_id:crypto.randomUUID().replaceAll('-',''),title,frame_format:$('new-project-format').value,structure:$('new-project-structure').value,...extra});
    }
    if(!/^[0-9a-f]{32}$/.test(pendingCreation.request_id || '')) throw new Error('The saved new-short request needs review.');
    creationMissing=false;showCreation();
    const path=`/api/project-creations/${pendingCreation.request_id}`;
    let receipt;
    if(checking) {checkingReceipt=true;receipt=await api(path);checkingReceipt=false;}
    else {posted=true;const {request_id,...body}=pendingCreation;receipt=await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
    await finishCreation(receipt);
  } catch(e) {
    if(checkingReceipt && e.status===404 && pendingCreation) creationMissing=true;
    if(posted && [400,422].includes(e.status)) rememberCreation(null);
    error(e.message);
  } finally {creationBusy=false;showCreation();controls();}
}
$('new-project').onclick=()=>{if(pendingCreation) {showCreation();return;}$('project-form').hidden=!$('project-form').hidden; $('new-project-format').value=frameFormat;};
$('project-form').onsubmit=async event=>{event.preventDefault();await createOrCheckProject();};
$('retry-create-project').onclick=()=>createOrCheckProject(true);
$('project-select').onchange=async()=>{try {await loadBoard($('project-select').value);} catch(e){error(e.message);} };
$('mobile-shot').onchange=async()=>{try {captureShot(); await saveBoard(); activeShotId=$('mobile-shot').value; await showShot();} catch(e){error(e.message);} };
$('save-project').onclick=()=>{captureShot(); saveBoard().catch(e=>error(e.message));};
$('reload-project').onclick=()=>{if(shortProject) loadBoard(shortProject.id,activeShotId,true).catch(e=>error(e.message));};
$('project-title').oninput=()=>{shortProject.title=$('project-title').value; markBoard();};
$('shared-direction').oninput=()=>{shortProject.art_direction=$('shared-direction').value; markBoard();};
$('shot-title').oninput=()=>{if(activeShot()) {activeShot().title=$('shot-title').value; markBoard(); drawBoard();}};
$('shot-beat').onchange=()=>{if(activeShot()) {activeShot().beat=$('shot-beat').value; markBoard(); drawBoard();}};
$('inherit-direction').onchange=()=>{if(activeShot()) {activeShot().direction_override=$('inherit-direction').checked ? null : $('shot-override').value; $('shot-override').hidden=$('inherit-direction').checked; markBoard();}};
$('shot-override').oninput=()=>{if(activeShot()) {activeShot().direction_override=$('shot-override').value; markBoard();}};
$('add-shot').onclick=()=>editBoard(()=>{if(shortProject.shots.length>=6) return; const shot=newShot(); shortProject.shots.push(shot); activeShotId=shot.id;});
for(const [id,offset] of [['shot-left',-1],['shot-right',1]]) $(id).onclick=()=>editBoard(()=>{
  const i=shortProject.shots.findIndex(s=>s.id===activeShotId), j=i+offset;
  if(j>=0 && j<shortProject.shots.length) [shortProject.shots[i],shortProject.shots[j]]=[shortProject.shots[j],shortProject.shots[i]];
});
$('shot-duplicate').onclick=()=>editBoard(()=>{if(!activeShot() || shortProject.shots.length>=6) return; const clone=JSON.parse(JSON.stringify(activeShot())); clone.id=crypto.randomUUID().replaceAll('-',''); clone.title=(clone.title+' copy').slice(0,80); const i=shortProject.shots.findIndex(s=>s.id===activeShotId); shortProject.shots.splice(i+1,0,clone); activeShotId=clone.id;});
$('shot-remove').onclick=()=>editBoard(()=>{const i=shortProject.shots.findIndex(s=>s.id===activeShotId); if(i<0) return; shortProject.shots.splice(i,1); activeShotId=shortProject.shots[Math.min(i,shortProject.shots.length-1)]?.id || null;});
$('shot-take').onchange=()=>editBoard(()=>{if(activeShot()) activeShot().selected_take_id=$('shot-take').value || null;});
$('use-take').onclick=()=>{if($('use-take').disabled) return;return editBoard(()=>{if(activeShot() && selectableTake(takes.find(t=>t.id===selected))) activeShot().selected_take_id=selected;});};
for(const id of ['trim-start','trim-end']) $(id).onchange=()=>{
  const start=Math.round(Number($('trim-start').value)*24), end=Math.round(Number($('trim-end').value)*24);
  if(!Number.isFinite(start) || !Number.isFinite(end) || start<0 || end>120 || start>=end) {error('Keep a trim of at least one frame within the five-second take.'); return;}
  if(activeShot()) {activeShot().trim_start=start; activeShot().trim_end=end; markBoard(); drawBoard();}
};
$('shot-volume').oninput=()=>{if(activeShot()) {activeShot().volume=Number($('shot-volume').value); markBoard();}};
function showSequence(item) {
  sequenceExport=item;
  const output=$('short-output');
  const preview=item?.preview_url || (shortProject?.captions?.length ? null : item?.output_url);
  output.hidden=!preview;
  if(preview && output.getAttribute('src')!==preview) output.src=preview;
  if(!preview) output.removeAttribute('src');
  for(const [id,url] of [['download-short',item?.output_url],['download-manifest',item?.manifest_url],['download-captions',item?.captions_url]]) {
    $(id).hidden=!url; if(url) $(id).href=url; else $(id).removeAttribute('href');
  }
  $('short-state').textContent=item ? `${item.status==='succeeded' ? 'Ready' : item.status==='queued' ? 'Preparing export' : item.status==='running' ? 'Exporting locally' : 'Export needs recovery'}${item.revision!==shortProject?.revision ? ' / earlier saved edit' : ''}` : '';
  $('recover-short').hidden=!item || item.active || !!item.output_url;
  if(item?.error) error(item.error);
  finishingHooks?.preview();
  controls();
}
async function refreshSequence() {
  if(!shortProject || sequencePolling) return;
  sequencePolling=true;
  const id=shortProject.id;
  try {
    const items=await api(`/api/projects/${id}/exports`);
    if(shortProject?.id===id) showSequence(items.at(-1) || null);
  } finally {sequencePolling=false;}
}
$('export-short').onclick=async()=>{
  if(sequenceSubmitting || !shortProject) return;
  sequenceSubmitting=true; controls(); error('');
  try {
    captureShot(); await saveBoard();
    sequencePending ||= {project_id:shortProject.id,revision:shortProject.revision,request_id:crypto.randomUUID().replaceAll('-','')};
    if(sequencePending.project_id!==shortProject.id) throw new Error('Resolve the pending local export in its original project first.');
    studioStorage.setItem('studio-export-pending',JSON.stringify(sequencePending));
    const item=await api(`/api/projects/${sequencePending.project_id}/exports`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:sequencePending.request_id,revision:sequencePending.revision})});
    sequencePending=null; studioStorage.removeItem('studio-export-pending'); showSequence(item);
  } catch(e) {
    if(e.status && e.status<500) {sequencePending=null; studioStorage.removeItem('studio-export-pending');}
    error(e.message);
  } finally {sequenceSubmitting=false; controls();}
};
$('recover-short').onclick=async()=>{
  if(!sequenceExport) return;
  try {showSequence(await api(`/api/exports/${sequenceExport.id}/resume`,{method:'POST'}));}
  catch(e){error(e.message);}
};
async function startBoard() {
  await refreshing;
  boardOptions(await api('/api/projects'));
  // Openfield opens on Home; only work still in flight reopens its project.
  const projectId=pending?.project_id || pendingLook?.project_id || sequencePending?.project_id || globalThis.pendingProductProject?.() || null;
  if(projectId) await loadBoard(projectId,pending?.shot_id || pendingLook?.shot_id || studioStorage.getItem('studio-shot'));
  showCreation();controls();
}
showCreation();
const boardReady=startBoard().catch(e=>error(e.message)).finally(()=>{boardInitialized=true;showCreation();controls();});
