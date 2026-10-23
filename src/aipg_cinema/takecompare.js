/* Comparing media changes browser view state only; winner/seed actions are explicit. */
let takePair=null, takePairScope='', takePairFingerprint='', choosingTake=false, takePairFinished=false, takePlaySerial=0;
const takeVideoA=$('take-compare-video-a'), takeVideoB=$('take-compare-video-b');
function comparisonCandidates() {
  return (projectHooks?.filter(takes) || takes).filter(t=>t.status==='succeeded' && t.output_url && (t.frame_format || 'landscape')===frameFormat);
}
function comparisonScope() {return `studio-take-pair:${shortProject?.id || 'single'}:${activeShotId || frameFormat}`;}
function comparisonNotice(message='') {const node=$('take-compare-error');node.textContent=message;node.hidden=!message;}
function stopTakeComparison() {
  takePlaySerial++;takeVideoA.pause();takeVideoB.pause();
  $('take-compare-play').querySelector('img').src='/icons/play.svg';
  $('take-compare-play').setAttribute('aria-label','Play take comparison');
  $('take-compare-play').title='Play take comparison';
}
function saveTakePair() {if(takePair) studioStorage.setItem(takePairScope,JSON.stringify(takePair));}
function comparisonSound() {takeVideoA.muted=takePair?.sound!=='a';takeVideoB.muted=takePair?.sound!=='b';}
function pairItem(side) {return comparisonCandidates().find(t=>t.id===takePair?.[side]) || null;}
function pairName(item) {
  const visible=projectHooks?.filter(takes) || takes;
  return `Take ${String(visible.findIndex(t=>t.id===item.id)+1).padStart(2,'0')}`;
}
function compareMode(next) {
  const active=next==='takes';
  if(!active) stopTakeComparison();
  $('take-compare-workspace').hidden=!active;
  $('shot-workspace').classList.toggle('comparing',active);
  $('compare-takes').classList.toggle('active',active);$('compare-takes').setAttribute('aria-pressed',String(active));
  $('single-take-metadata').hidden=active;
  if(active) {$('canvas').hidden=true;$('look-canvas').hidden=true;$('transport').hidden=true;refreshTakePair();}
}
function refreshTakePair() {
  const scope=comparisonScope(), candidates=comparisonCandidates();
  $('compare-takes').disabled=candidates.length<2;
  $('compare-takes').title=candidates.length<2 ? 'Two completed takes in this framing are needed' : 'Compare two completed video takes';
  if(scope!==takePairScope) {
    stopTakeComparison();takePairScope=scope;takePair=saved(scope);takePairFingerprint='';
    comparisonNotice();
    for(const video of [takeVideoA,takeVideoB]) {video.removeAttribute('src');video.load();}
  }
  if(candidates.length<2) {
    if(mode==='takes') {setMode('result');comparisonNotice();}
    return;
  }
  const ids=new Set(candidates.map(t=>t.id));
  const b=ids.has(takePair?.b) ? takePair.b : ids.has(selected) ? selected : candidates.at(-1).id;
  const a=ids.has(takePair?.a) && takePair.a!==b ? takePair.a : candidates.find(t=>t.id!==b).id;
  takePair={a,b,sound:['a','b','off'].includes(takePair?.sound) ? takePair.sound : 'b'};
  const fingerprint=JSON.stringify([scope,mode==='takes',takePair,candidates.map(t=>[t.id,t.output_url,t.seed,t.render_profile]),activeShot()?.selected_take_id]);
  if(fingerprint===takePairFingerprint) return;
  takePairFingerprint=fingerprint;
  for(const side of ['a','b']) {
    const menu=$(`take-compare-${side}`);menu.replaceChildren();
    for(const item of candidates) {const option=document.createElement('option');option.value=item.id;option.textContent=pairName(item);option.disabled=item.id===takePair[side==='a' ? 'b' : 'a'];menu.append(option);}
    menu.value=takePair[side];
    const item=pairItem(side), video=side==='a' ? takeVideoA : takeVideoB;
    if(mode==='takes' && video.getAttribute('src')!==item.output_url) {stopTakeComparison();takePairFinished=false;video.src=item.output_url;video.load();}
    const profile=item.render_profile==='single-pass-audio' ? 'Single-pass speech' : 'Two-pass';
    $(`take-compare-meta-${side}`).textContent=`Seed ${item.seed} / ${profile}${activeShot()?.selected_take_id===item.id ? ' / selected' : ''}`;
    $(`take-compare-use-${side}`).querySelector('span').textContent=shortProject ? `Use ${side.toUpperCase()}` : `View ${side.toUpperCase()}`;
    $(`take-compare-use-${side}`).title=shortProject ? `Choose take ${side.toUpperCase()} for this shot` : `Preview take ${side.toUpperCase()}`;
  }
  $('take-compare-canvas').classList.toggle('portrait',frameFormat==='portrait');
  $('take-compare-canvas').classList.toggle('square',frameFormat==='square');
  $('take-compare-sound').value=takePair.sound;comparisonSound();saveTakePair();
}
function pairControls(frozen) {
  refreshTakePair();
  $('take-compare-swap').disabled=frozen || choosingTake || comparisonCandidates().length<2;
  for(const side of ['a','b']) {
    $(`take-compare-${side}`).disabled=frozen || choosingTake;
    for(const action of ['use','seed']) $(`take-compare-${action}-${side}`).disabled=frozen || choosingTake || !pairItem(side) || !!boardConflict;
    if(shortProject && activeShot()?.selected_take_id===pairItem(side)?.id) $(`take-compare-use-${side}`).disabled=true;
  }
}
// The pair plays to the shorter take's end (takes run 5, 10 or 15 s).
function pairSeconds() { return Math.min(pairItem('a')?.seconds || 5,pairItem('b')?.seconds || 5); }
function pairClock(value) { return `0:${String(Math.floor(value)).padStart(2,'0')} / 0:${String(pairSeconds()).padStart(2,'0')}`; }
function comparisonSeek(value) {
  takePairFinished=false;
  for(const video of [takeVideoA,takeVideoB]) if(video.readyState) video.currentTime=value;
  $('take-compare-seek').max=pairSeconds(); $('take-compare-seek').value=value;
  $('take-compare-time').textContent=pairClock(value);
}
function finishTakeComparison() {stopTakeComparison();comparisonSeek(pairSeconds());takePairFinished=true;}
function updateTakeComparison() {
  if(takePairFinished) return;
  const time=takeVideoB.currentTime;
  if(time>=pairSeconds()) {finishTakeComparison();return;}
  if(takeVideoA.readyState && Math.abs(takeVideoA.currentTime-time)>.15) takeVideoA.currentTime=time;
  $('take-compare-seek').value=time;$('take-compare-time').textContent=pairClock(time);
}
takeCompareHooks={refresh:refreshTakePair,mode:compareMode,controls:pairControls,pause:stopTakeComparison};
$('compare-takes').onclick=()=>{if(comparisonCandidates().length<2) return;pause();setMode('takes');controls();};
for(const side of ['a','b']) {
  $(`take-compare-${side}`).onchange=()=>{
    const next=$(`take-compare-${side}`).value, opposite=side==='a' ? 'b' : 'a';
    if(!comparisonCandidates().some(t=>t.id===next) || next===takePair?.[opposite]) return;
    stopTakeComparison();takePair[side]=next;comparisonNotice();saveTakePair();refreshTakePair();comparisonSeek(0);controls();
  };
  $(`take-compare-use-${side}`).onclick=async()=>{
    if($(`take-compare-use-${side}`).disabled) return;
    const item=pairItem(side);if(!item) return;
    stopTakeComparison();choosingTake=true;controls();
    try {
      if(shortProject) {studioStorage.setItem('openreshoot-selected',item.id);await editBoard(()=>{activeShot().selected_take_id=item.id;});}
      else {showTake(item,false);setMode('result');}
    } finally {choosingTake=false;controls();}
  };
  $(`take-compare-seed-${side}`).onclick=()=>{
    if($(`take-compare-seed-${side}`).disabled) return;
    const item=pairItem(side);if(!item) return;
    stopTakeComparison();restoreSeed(item.seed);draftChanged();setMode('result');$('motion-settings').open=true;$('seed').focus();
  };
}
$('take-compare-sound').onchange=()=>{if(!takePair) return;takePair.sound=$('take-compare-sound').value;comparisonSound();saveTakePair();};
$('take-compare-swap').onclick=()=>{if($('take-compare-swap').disabled || !takePair) return;stopTakeComparison();[takePair.a,takePair.b]=[takePair.b,takePair.a];comparisonNotice();saveTakePair();refreshTakePair();comparisonSeek(0);controls();};
$('take-compare-seek').oninput=()=>comparisonSeek(Number($('take-compare-seek').value));
$('take-compare-play').onclick=async()=>{
  if(!takeVideoB.paused) {stopTakeComparison();return;}
  if(!pairItem('a') || !pairItem('b')) return;
  pause();$('audio-preview').pause();comparisonNotice();
  if(takePairFinished || takeVideoB.currentTime>=pairSeconds()-0.01) comparisonSeek(0);
  else comparisonSeek(takeVideoB.currentTime);
  const serial=takePlaySerial;
  try {
    await Promise.all([takeVideoA.play(),takeVideoB.play()]);
    if(serial!==takePlaySerial || mode!=='takes') return;
    $('take-compare-play').querySelector('img').src='/icons/pause.svg';$('take-compare-play').setAttribute('aria-label','Pause take comparison');
    $('take-compare-play').title='Pause take comparison';
  } catch {if(serial!==takePlaySerial) return;stopTakeComparison();comparisonNotice('Playback could not start. Check both completed takes.');}
};
takeVideoB.ontimeupdate=updateTakeComparison;
takeVideoA.onended=takeVideoB.onended=finishTakeComparison;
for(const [video,side] of [[takeVideoA,'A'],[takeVideoB,'B']]) video.onerror=()=>{stopTakeComparison();comparisonNotice(`Take ${side} could not be loaded. Your saved project is unchanged.`);};
boardReady.then(()=>{refreshTakePair();controls();});
