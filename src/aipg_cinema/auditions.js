/* Still-image comparison. Selecting a candidate never dispatches video. */
let auditionUploading=false, singleAudition=null, auditionFingerprint='', auditionLoaded=false;
function auditionInputKey() {return JSON.stringify([inputMode,activeSourceId(),sourceStart,frameFormat]);}
function auditionInputMatches(key) {try {return JSON.stringify(JSON.parse(key))===auditionInputKey();} catch {return false;}}
function auditionStorageKey() {return 'studio-look-audition:'+auditionInputKey();}
function auditionState(create=false) {
  const shot=activeShot();
  let value=shot ? shot.audition : singleAudition;
  if(!auditionInputMatches(value?.input_key)) value=null;
  if(!value && create) {
    const shared=shot ? shot.direction_override ?? shortProject.art_direction : '';
    value={input_key:auditionInputKey(),direction:[shared,$('prompt').value].filter(x=>x?.trim()).join('\n\n'),seed:editorSeed(),denoise:.65,reference_id:inputMode==='video' ? null : lookId,left_id:null,right_id:null,frame_index:0};
    if(shot) {shot.audition=value; markBoard();}
    else {singleAudition=saved(auditionStorageKey()) || value; value=singleAudition; studioStorage.setItem(auditionStorageKey(),JSON.stringify(value));}
  }
  return value;
}
function saveAudition() {
  if(activeShot()) {markBoard(); drawBoard();}
  else if(singleAudition) studioStorage.setItem(auditionStorageKey(),JSON.stringify(singleAudition));
}
function auditionRequest(a,requestId) {
  const kind=inputMode==='video' ? 'video' : a.reference_id ? 'image' : 'text';
  return {request_id:requestId,look_input:kind,source_id:kind==='video' ? sourceId : null,image_id:kind==='image' ? a.reference_id : null,source_start:kind==='video' ? sourceStart : 0,frame_format:frameFormat,frame_index:a.frame_index,prompt:a.direction,seed:a.seed,denoise:/^klein/.test(config.look_engine||'') ? null : kind==='text' ? 1 : a.denoise,audition:true,...(shortProject ? {project_id:shortProject.id,shot_id:activeShotId,project_revision:shortProject.revision} : {})};
}
function auditionMatches(item,a) {
  if(!a) return false;
  const expected=auditionRequest(a,'0'.repeat(32));
  return !!item.audition && ['look_input','source_id','image_id','source_start','frame_format','frame_index','project_id','shot_id'].every(key=>(item[key] ?? null)===(expected[key] ?? null));
}
function auditionReference(a) {
  if(inputMode==='video' && sourceId) return `/api/sources/${sourceId}/frame?frame_format=${frameFormat}&source_start=${sourceStart}&frame_index=${a.frame_index}`;
  return a.reference_id ? `/api/looks/${a.reference_id}` : null;
}
function auditionCandidates(a) {return lookJobs.filter(item=>auditionMatches(item,a) && item.output_url);}
function auditionComplete(item) {
  const a=auditionState();
  if(!auditionMatches(item,a)) return;
  if(a.left_id===item.id || a.right_id===item.id) return;
  if(!auditionReference(a) && !a.left_id) a.left_id=item.id;
  else {if(a.right_id && !a.left_id) a.left_id=a.right_id; a.right_id=item.id;}
  saveAudition(); drawAuditions(true);
}
function loadAudition() {
  if(studioView!=='looks' || shortProject && !activeShot()) return;
  const a=auditionState(true);
  $('audition-direction').value=a.direction; $('audition-seed').value=a.seed;
  $('audition-strength').value=a.denoise; $('audition-role').value=a.frame_index;
  drawAuditions(true);
}
function drawAuditions(force=false) {
  if(studioView!=='looks') return;
  const a=auditionState(); if(!a) return;
  const candidates=auditionCandidates(a), reference=auditionReference(a);
  const fingerprint=JSON.stringify([a,candidates,reference,config.look_engine]);
  if(!force && fingerprint===auditionFingerprint) return;
  auditionFingerprint=fingerprint;
  $('audition-workspace').className=frameFormat;
  $('audition-reference').hidden=!reference;
  if(reference) $('audition-reference').src=reference; else $('audition-reference').removeAttribute('src');
  $('audition-upload').hidden=$('audition-use-reference').hidden=$('audition-remove-reference').hidden=inputMode==='video';
  $('audition-strength-field').hidden=!reference || /^klein/.test(config.look_engine||'');
  for(const side of ['left','right']) {
    const id=a[side+'_id'], item=lookJobs.find(t=>t.id===id);
    const menu=$('audition-'+side); menu.replaceChildren();
    const baseline=finishNode('option',{},reference ? 'Pinned reference' : 'No image selected'); baseline.value=''; menu.append(baseline);
    const visible=[...candidates]; if(item?.output_url && !visible.includes(item)) visible.push(item);
    for(const [index,candidate] of visible.entries()) {const option=finishNode('option',{},`Look ${index+1} / seed ${candidate.seed}`);option.value=candidate.id;menu.append(option);}
    menu.value=id || '';
    const url=id ? item?.output_url : reference, image=$(`audition-${side}-image`);
    image.hidden=!url; $(`audition-${side}-empty`).hidden=!!url;
    if(url) image.src=url; else image.removeAttribute('src');
    $(`audition-${side}-prompt`).textContent=item?.prompt || (url ? 'Pinned reference' : '');
    $(`audition-${side}-meta`).textContent=item ? `${lookName(item)} / seed ${item.seed}${item.denoise==null ? '' : ` / denoise ${item.denoise}`}` : url ? 'Pinned reference' : '';
    $(`audition-${side}-apply`).querySelector('span').textContent=a.frame_index===120 ? 'Use ending' : 'Use opening';
    for(const [name,path] of [['download',url],['settings',item?.output_url ? `/api/look-jobs/${item.id}/settings` : null],['workflow',item?.output_url ? `/api/look-jobs/${item.id}/workflow` : null]]) {
      const link=$(`audition-${side}-${name}`);link.hidden=!path;
      if(path) link.href=path; else link.removeAttribute('href');
    }
  }
  $('audition-history').replaceChildren();
  candidates.forEach((item,index)=>{
    const button=finishNode('button',{type:'button',title:`Compare look ${index+1}`,'aria-label':`Compare look ${index+1}`});
    button.append(finishNode('img',{src:item.output_url,alt:`Look ${index+1}`}),finishNode('span',{},`Look ${index+1} / ${item.seed}`));
    button.onclick=()=>{if(pendingLook || lookSubmitting || auditionUploading) return; a.right_id=item.id; saveAudition();drawAuditions(true);};
    $('audition-history').append(button);
  });
  auditionControls();
}
function auditionControls(frozen=false) {
  if(studioView!=='looks') return;
  const a=auditionState(), blocked=frozen || auditionUploading || !!pending || !!pendingLook || submitting || lookSubmitting;
  for(const field of document.querySelectorAll('#audition-controls input,#audition-controls textarea,#audition-controls select,#audition-controls button,#audition-workspace select,#audition-workspace button')) field.disabled=blocked;
  const latest=lookJobs.filter(item=>auditionMatches(item,a)).at(-1);
  const working=lookJobs.some(t=>t.active || !['succeeded','failed','cancelled'].includes(t.status));
  const videoBusy=takes.some(t=>t.active || !['succeeded','failed','cancelled'].includes(t.status));
  $('audition-generate').disabled=auditionUploading || lookSubmitting || !!pending || submitting || (!pendingLook && (!a || !config.look_connected || connectionLost || boardConflict || working || videoBusy || (config.looks_used || 0)>=(config.max_looks || 12) || (inputMode==='video' && !sourceId)));
  $('audition-generate').querySelector('span').textContent=pendingLook ? 'Check look' : 'Generate look';
  $('audition-state').textContent=latest && latest.status!=='succeeded' ? `${lookName(latest)} / ${states[latest.status] || latest.status}` : `${lookName()} / ${config.looks_used || 0} of ${config.max_looks || 12} looks${config.look_connected ? '' : ' / offline'}`;
  $('audition-recover').hidden=latest?.status!=='needs_recovery';
  $('audition-recover').disabled=blocked; $('audition-recover').dataset.id=latest?.id || '';
  $('audition-use-reference').disabled=blocked || !currentLookId();
  for(const side of ['left','right']) {
    const id=a?.[side+'_id'] || a?.reference_id;
    const item=lookJobs.find(t=>t.id===id);
    $(`audition-${side}-apply`).disabled=blocked || !id || inputMode==='video' && !auditionMatches(item,a) || a?.frame_index===120 && (!lookId || !config.closing_supported);
  }
  if(auditionUploading) $('generate').disabled=$('export-short').disabled=true;
}
async function generateAudition() {
  if(pendingLook) return checkSubmission();
  if(lookSubmitting || auditionUploading) return;
  const a=auditionState(true);
  if(!pendingLook) {try {a.seed=parseSeed($('audition-seed').value);if(!$('audition-seed').checkValidity() || !a.direction.trim() || a.direction.length>4000) throw new Error();} catch {error('Add an image direction and a seed from 0 to 9223372036854775807.');return;}}
  lookSubmitting=true;controls();error('');
  try {
    if(!pendingLook) {
      captureShot(); await saveBoard();
      rememberPendingLook(auditionRequest(a,crypto.randomUUID().replaceAll('-','')));
    }
    const item=await api('/api/look-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pendingLook)});
    watchLook(item.id);rememberPendingLook(null);await refresh();
  } catch(e) {
    if(e.status && e.status<500) rememberPendingLook(null);
    error(e.message);
  } finally {lookSubmitting=false;controls();}
}
async function applyAudition(side) {
  const a=auditionState(), id=a?.[side+'_id'] || a?.reference_id;
  if(!a || !id || pendingLook || lookSubmitting || auditionUploading) return;
  const item=lookJobs.find(t=>t.id===id);
  if(item) $('prompt').value=item.prompt;
  chooseLook(id,a.frame_index); captureShot(); await saveBoard(); selectStudioView('shot');
}
function changeAuditionReference(id) {
  const a=auditionState(true);a.reference_id=id;a.left_id=a.right_id=null;
  saveAudition();drawAuditions(true);
}
$('auditions-tab').onclick=()=>selectStudioView('looks');
$('audition-generate').onclick=generateAudition;
for(const side of ['left','right']) {
  $('audition-'+side).onchange=()=>{const a=auditionState();a[side+'_id']=$('audition-'+side).value || null;saveAudition();drawAuditions(true);};
  $(`audition-${side}-apply`).onclick=()=>applyAudition(side).catch(e=>error(e.message));
}
$('audition-direction').oninput=()=>{const a=auditionState(true);a.direction=$('audition-direction').value;saveAudition();};
$('audition-seed').oninput=()=>{try {auditionState(true).seed=parseSeed($('audition-seed').value);saveAudition();} catch {}};
$('audition-strength').onchange=()=>{auditionState(true).denoise=Number($('audition-strength').value);saveAudition();};
$('audition-role').onchange=()=>{const a=auditionState(true);a.frame_index=Number($('audition-role').value);a.left_id=a.right_id=null;saveAudition();drawAuditions(true);};
$('audition-use-reference').onclick=()=>changeAuditionReference(currentLookId());
$('audition-remove-reference').onclick=()=>changeAuditionReference(null);
$('audition-upload').onclick=()=>$('audition-file').click();
$('audition-file').onchange=async()=>{
  const file=$('audition-file').files[0]; if(!file || auditionUploading) return;
  const scope=auditionInputKey(), project=shortProject?.id, shot=activeShotId;
  auditionUploading=true;controls();error('');
  try {
    const form=new FormData();form.append('file',file);
    const result=await api(`/api/looks?frame_format=${frameFormat}`,{method:'POST',body:form});
    if(scope===auditionInputKey() && project===shortProject?.id && shot===activeShotId) changeAuditionReference(result.look_id);
  } catch(e) {error(e.message);} finally {auditionUploading=false;$('audition-file').value='';controls();}
};
$('audition-recover').onclick=async()=>{
  if(lookSubmitting || submitting || auditionUploading) return;
  lookSubmitting=true;controls();
  try {const id=$('audition-recover').dataset.id;await api(`/api/look-jobs/${id}/resume`,{method:'POST'});watchLook(id);await refresh();}
  catch(e){error(e.message);}finally{lookSubmitting=false;controls();}
};
auditionHooks={loaded:loadAudition,refresh:()=>drawAuditions(),controls:auditionControls,uploading:()=>auditionUploading,completed:auditionComplete,ready:()=>auditionLoaded};
boardReady.then(()=>{loadAudition();layoutFinish();auditionLoaded=true;updateLooks();}).catch(e=>error(e.message));
