/* Make the whole short: one press runs each missing step in order, one job
   at a time, through the same buttons a person would use. It shows the total
   estimate first, never retries a failed step and stops when asked. */
let autopilotRunning=false, autopilotStop=false;
function autopilotPlan(project=productProject()) {
  if(!project) return null;
  const steps=[];
  for(const shot of project.shots) {
    if(shot.selected_take_id) continue;
    if(isPackshot(shot)) { steps.push({kind:'packshot',shot}); continue; }
    if(!shot.draft.look_id) steps.push({kind:'look',shot});
    steps.push({kind:'take',shot,resume:!!resumableTake(shot)});
  }
  if(config.autobrief && !project.music) steps.push({kind:'music'});
  steps.push({kind:'export'});
  return steps;
}
function autopilotEstimate(steps) {
  const e=config.estimates; if(!e) return '';
  const looks=steps.filter(s=>s.kind==='look').length, renders=steps.filter(s=>s.kind==='take' && !s.resume).length;
  const parts=[];
  const credits=(e.look.credits || 0)*looks+(e.take.credits || 0)*renders;
  const seconds=(e.look.seconds || 0)*looks+(e.take.seconds || 0)*renders;
  if(credits) parts.push(`~${credits} Cloud credits`);
  if(seconds) parts.push(`~${seconds<120 ? seconds+' s' : Math.round(seconds/60)+' min'} on your GPU`);
  if(steps.some(s=>s.kind==='music')) parts.push(e.music.label.replace(' (est.)',''));
  return parts.length ? parts.join(' + ')+' (est.)' : 'No renders needed';
}
function drawAutopilot() {
  const project=productProject(), steps=autopilotPlan(project);
  $('make-short').hidden=!project;
  if(!project) { if(!autopilotRunning) autopilotStatus(''); return; }
  const renders=steps.filter(s=>['look','take','packshot'].includes(s.kind)).length;
  const exported=sequenceExport?.status==='succeeded' && sequenceExport.project_id===project.id;
  $('make-short-label').textContent=autopilotRunning ? 'Making your short' : renders ? 'Make the whole short' : exported ? 'Export again' : 'Finish the short';
  $('make-short').classList.toggle('quiet',!renders && !autopilotRunning);
  $('make-short-estimate').textContent=autopilotRunning ? '' : autopilotEstimate(steps);
  $('make-short').disabled=autopilotRunning || variantBusy || productBusy || !!pending || submitting || !config.connected && steps.some(s=>s.kind==='take') || !config.look_connected && steps.some(s=>s.kind==='look');
  $('stop-short').hidden=!autopilotRunning;
}
function autopilotStatus(text) { $('autopilot-status').textContent=text || ''; $('autopilot-status').hidden=!text; }
async function openShot(shotId) {
  if(activeShotId===shotId) return;
  captureShot(); await saveBoard(); activeShotId=shotId; await showShot();
}
function currentShot(id) { return shortProject?.shots.find(s=>s.id===id); }
async function waitForLook() {
  while(productLook) { if(autopilotStop) throw new Error('Stopped. The running look finishes and stays in its shot.'); await sleep(2000); }
}
async function waitForTake(id) {
  for(;;) {
    await sleep(4000); await refresh();
    const take=takes.find(t=>t.id===id);
    if(take && !take.active && ['succeeded','failed','cancelled','needs_review'].includes(take.status)) return take;
  }
}
function resumableTake(shot) {
  if(!shot?.draft.look_id) return null;
  const mine=takes.filter(t=>t.project_id===shortProject.id && t.shot_id===shot.id && t.look_id===shot.draft.look_id);
  return mine.find(t=>t.active || !['succeeded','failed','cancelled','needs_review'].includes(t.status))
    || mine.find(t=>t.status==='succeeded' && t.output_url) || null;
}
async function runStep(step,index,total) {
  const label=`Step ${index+1} of ${total}`;
  if(step.kind==='look') {
    await openShot(step.shot.id);
    autopilotStatus(`${label}: product look for "${step.shot.title}"`);
    await $('product-look').onclick(); await waitForLook();
    if(!currentShot(step.shot.id)?.draft.look_id) throw new Error(`The look for "${step.shot.title}" did not finish. Nothing was retried.`);
  } else if(step.kind==='take') {
    await openShot(step.shot.id);
    autopilotStatus(`${label}: rendering "${step.shot.title}"`);
    // Resume instead of re-rendering: a take of this shot's current look that is
    // still running or already finished (say, after the tab closed) is used.
    await refresh();
    let take=resumableTake(currentShot(step.shot.id));
    if(!take) {
      const before=new Set(takes.map(t=>t.id));
      await generateBoardShot();
      if(pending) throw new Error('The render request is not confirmed yet. Use Check status; nothing was resent.');
      await refresh();
      take=takes.find(t=>!before.has(t.id) && t.shot_id===step.shot.id);
      if(!take) throw new Error(`"${step.shot.title}" could not start. Nothing was retried.`);
    }
    const done=take.active || !['succeeded','failed','cancelled','needs_review'].includes(take.status) ? await waitForTake(take.id) : take;
    if(done.status!=='succeeded' || !done.output_url) throw new Error(`"${step.shot.title}" did not render (${states[done.status] || done.status}). Nothing was retried.`);
    const shot=currentShot(step.shot.id); shot.selected_take_id=done.id; markBoard(); await saveBoard(); drawBoard(true);
  } else if(step.kind==='packshot') {
    await openShot(step.shot.id);
    autopilotStatus(`${label}: composing the packshot`);
    await $('product-packshot').onclick();
    if(!currentShot(step.shot.id)?.selected_take_id) throw new Error('The packshot was not built. Nothing was retried.');
  } else if(step.kind==='music') {
    autopilotStatus(`${label}: composing music with ACE-Step`);
    await $('generate-music').onclick();
    if(!shortProject.music) throw new Error('Music was not made. The short can still be exported without it.');
  } else {
    autopilotStatus(`${label}: exporting your short`);
    await $('export-short').onclick();
    $('finish-tab').click();
  }
}
$('make-short').onclick=async()=>{
  const steps=autopilotPlan();
  if(autopilotRunning || !steps) return;
  autopilotRunning=true; autopilotStop=false; error(''); controls();
  try {
    for(const [index,step] of steps.entries()) {
      if(autopilotStop) throw new Error('Stopped. Finished steps are kept; press again to continue.');
      await runStep(step,index,steps.length);
    }
    autopilotStatus('Your short is ready. Review it in Finish.');
  } catch(e) { autopilotStatus(''); error(e.message); }
  finally { autopilotRunning=false; controls(); }
};
$('stop-short').onclick=()=>{autopilotStop=true; autopilotStatus('Stopping after the current step');};
const baseAutopilotControls=productHooks.controls;
productHooks.controls=frozen=>{baseAutopilotControls(frozen || autopilotRunning); drawAutopilot();};
