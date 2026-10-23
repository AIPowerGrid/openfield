// Event-handler regression, not a substitute for real browser/media checks.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {readFileSync} = require('node:fs');

const elements = new Map();
let created = 0;
function element(id) {
  if (!elements.has(id)) {
    const attributes = new Map();
    elements.set(id, {
      value: '', textContent: '', style: {}, dataset: {}, paused: true,
      currentTime: 0, readyState: 4, classList: {toggle() {}},
      getAttribute(name) { return attributes.get(name) || null; },
      setAttribute(name, value) { attributes.set(name, value); },
      removeAttribute(name) { attributes.delete(name); },
      querySelector() { return element(id + '-child'); },
      replaceChildren() {}, append() {}, load() {},
      focus() {}, checkValidity() { return true; },
      pause() { this.paused = true; this.onpause?.(); },
      async play() { this.paused = false; this.onplay?.(); },
    });
  }
  return elements.get(id);
}
const storage = new Map();
const requests = [];
const cloudLook = process.argv.includes('--cloud-look');
const context = vm.createContext({
  studioSession: {mode:'local'},
  document: {getElementById: element, querySelector: element, querySelectorAll: () => [], createElement: () => element('created-' + created++)},
  localStorage: {
    getItem: key => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  },
  setInterval() {},
  crypto: {randomUUID: () => '12345678-1234-1234-1234-123456789abc'},
  requests,
  storage,
  fetch: async (path,options) => ({
    ok: true,
    json: async () => {
      if(options?.method==='POST') {
        const body=JSON.parse(options.body); requests.push({path,body});
        return {...body,id:body.request_id,status:'preparing'};
      }
      return path === '/api/config' ? {connected: true,look_connected:true,closing_supported:true,
        ...(cloudLook ? {look_engine:'klein-cloud',look_model:'FLUX.2 Klein 4B FP8',look_presets:{warm:'Tested warm Cloud palette',blue:'Tested blue Cloud palette'}} : {})} : [];
    },
  }),
  assert,
  cloudLook,
});
vm.runInContext(readFileSync(0, 'utf8'), context);

(async () => {
  if(process.argv.includes('--source-preview')) {
    await vm.runInContext(`(async()=>{
      await refreshing;inputMode='video';selected=null;sourceId='source-a';lookId=null;closingId=null;
      sourceVideo.setAttribute('src','/api/sources/source-a');sourceVideo.readyState=0;sourceVideo.error=null;
      sourcePreview();
      assert.equal($('source-empty').hidden,false);assert.equal($('source-spinner').hidden,false);
      assert.equal($('source-message').textContent,'Loading source...');assert.equal($('retry-source').hidden,true);
      assert.equal($('source-panel').getAttribute('aria-busy'),'true');
      sourceVideo.readyState=4;sourceVideo.onloadeddata();
      assert.equal($('source-empty').hidden,true);assert.equal($('source-spinner').hidden,true);
      assert.equal($('source-panel').getAttribute('aria-busy'),'false');
      sourceVideo.error={message:'Do not display private media transport details'};sourceVideo.onerror();
      assert.equal($('source-empty').hidden,false);assert.equal($('retry-source').hidden,false);
      assert.equal($('source-message').textContent,'Source preview unavailable.');
      const savedDraft=JSON.stringify(editorDraft()), savedStorage=JSON.stringify([...storage.entries()]);
      error('Keep this unrelated form error.');let loads=0;
      sourceVideo.load=()=>{loads++;sourceVideo.readyState=0;sourceVideo.error=null;};
      $('retry-source').onclick();
      assert.equal(loads,1);assert.equal($('source-spinner').hidden,false);assert.equal($('retry-source').hidden,true);
      assert.equal($('error').textContent,'Keep this unrelated form error.');
      assert.equal(JSON.stringify(editorDraft()),savedDraft);assert.equal(JSON.stringify([...storage.entries()]),savedStorage);
      // A late ready event from the previous resource must not hide the new loader.
      sourceVideo.setAttribute('src','/api/sources/source-b');sourceVideo.onloadeddata();
      assert.equal($('source-empty').hidden,false);
      sourceVideo.readyState=4;sourceVideo.onloadeddata();assert.equal($('source-empty').hidden,true);
      sourceVideo.removeAttribute('src');sourceVideo.onemptied();
      assert.equal($('source-empty').hidden,false);assert.equal($('source-message').textContent,'Source clip');
      assert.equal($('source-spinner').hidden,true);assert.equal($('retry-source').hidden,true);
      inputMode='image';lookId='opening-a';configureInput();
      assert.equal($('source-empty').hidden,true);assert.equal($('source-video').hidden,true);
      assert.equal($('source-still').hidden,false);$('retry-source').onclick();assert.equal(loads,1);
      assert.equal(requests.length,0);
    })()`,context);return;
  }
  if(process.argv.includes('--reference-controls')) {
    await vm.runInContext(`(async()=>{
      await refreshing;inputMode='image';sourceId=null;lookId=null;closingId=null;lookFrame=0;
      config={connected:true,look_connected:true,closing_supported:true,look_engine:'moss',max_renders:6,max_looks:12};
      $('prompt').value='An original paper boat';$('motion-prompt').value='Drift gently';
      showTake(null);assert.equal($('reference-optionality').textContent,'Opening required');
      assert.equal($('reuse-opening-end').checked,false);assert.equal($('preview-look').hidden,true);
      chooseLook('opening-a');
      assert.equal($('preview-look').hidden,false);assert.equal($('preview-look').getAttribute('aria-label'),'View opening frame');
      assert.equal($('upload-look').getAttribute('aria-label'),'Replace opening frame');
      const draftBefore=JSON.stringify(editorDraft());$('preview-look').onclick();
      assert.equal(mode,'look');assert.equal(JSON.stringify(editorDraft()),draftBefore);
      $('reference-help').open=true;let prevented=false;
      $('reference-help').onkeydown({key:'Escape',preventDefault(){prevented=true;}});
      assert.equal($('reference-help').open,false);assert.equal(prevented,true);
      assert.equal(JSON.stringify(editorDraft()),draftBefore);
      $('reference-closing').onclick();chooseLook('ending-a');
      assert.equal($('preview-look').getAttribute('aria-label'),'View ending frame');
      assert.equal($('upload-look').getAttribute('aria-label'),'Replace ending frame');
      assert.equal($('generate-look').querySelector('span').textContent,'Generate ending');
      assert.equal(editorDraft().closing_id,'ending-a');assert.equal(editorDraft().look_id,'opening-a');
      assert.equal($('look-full').alt,'Selected ending frame');
      const saved=studioStorage.getItem('openreshoot-draft');
      pending={request_id:'uncertain'};controls();assert.equal($('preview-look').disabled,false);
      $('preview-look').onclick();assert.equal(mode,'look');assert.equal(studioStorage.getItem('openreshoot-draft'),saved);
      pending=null;controls();$('reference-opening').onclick();
      $('reuse-opening-end').checked=true;$('reuse-opening-end').onchange();
      assert.equal(editorDraft().closing_id,'opening-a');
      chooseLook('opening-b');assert.equal(editorDraft().closing_id,'opening-b');
      assert.equal($('reuse-opening-end').checked,true);
      assert.equal(requests.length,0);
    })()`,context);return;
  }
  if(process.argv.includes('--connection-recovery')) {
    await vm.runInContext(`(async()=>{
      await refreshing;
      inputMode='text';sourceId=null;lookId=null;closingId=null;pending=null;pendingLook=null;
      $('source-start').value='0';$('frame-format').value=frameFormat;
      $('prompt').value='A paper boat';$('motion-prompt').value='Drift gently';
      const originalFetch=fetch, postCalls=[], reads=[];
      const request={request_id:'a'.repeat(32),mode:'text',frame_format:'portrait',source_start:0,seed:'9223372036854775807',prompt:'Frozen boat',art_direction:'Frozen boat',motion_prompt:'Drift',look_id:null,closing_id:null};
      const take={...request,id:request.request_id,status:'failed',active:false,error:'Render failed.'};
      let disconnected=true, missing=false, mismatch=false, releaseRead;
      fetch=async(path,options={})=>{
        if(options.method==='POST') {postCalls.push({path,body:JSON.parse(options.body || '{}')});return {ok:true,status:200,json:async()=>take};}
        reads.push(path);
        if(path==='/api/config' && disconnected) throw new Error('Socket unavailable');
        if(path==='/api/jobs/'+request.request_id) {
          if(releaseRead===false) return new Promise(resolve=>releaseRead=()=>resolve({ok:true,status:200,json:async()=>take}));
          return {ok:!missing,status:missing ? 404 : 200,json:async()=>missing ? {detail:'Not found'} : mismatch ? {...take,shot_id:'wrong'} : take};
        }
        return originalFetch(path,options);
      };
      error('Keep this validation error.');
      await refresh().catch(()=>{});
      assert.equal(connectionLost,true);assert.equal($('connection-notice').hidden,false);
      assert.equal($('error').textContent,'Keep this validation error.');
      assert.equal($('generate').disabled,true);
      disconnected=false;await $('check-connection').onclick();
      assert.equal(connectionLost,false);assert.equal($('connection-notice').hidden,true);
      assert.equal($('error').textContent,'Keep this validation error.');
      assert.equal(postCalls.length,0);
      pending={...request};studioStorage.setItem('openreshoot-pending',JSON.stringify(pending));
      config.connected=false;connectionStatus(true);controls();
      assert.equal($('generate').disabled,false);assert.equal($('check-submission').disabled,false);
      await $('generate').onclick();
      assert.equal(pending,null);assert.equal(selected,request.request_id);assert.equal(postCalls.length,0);
      assert.equal($('settings').href,'/api/jobs/'+request.request_id+'/settings');
      assert.equal($('download').getAttribute('href'),null);
      assert.ok(reads.includes('/api/jobs/'+request.request_id));
      assert.equal($('error').textContent,'Render failed.');
      pending={...request};missing=true;controls();await checkSubmission();
      assert.equal(pending.request_id,request.request_id);assert.equal($('retry-submission').hidden,false);
      assert.equal(postCalls.length,0);
      await checkSubmission();assert.equal(postCalls.length,0);
      missing=false;config.connected=true;connectionStatus(false);
      await $('retry-submission').onclick();
      assert.equal(pending,null);assert.equal(postCalls.length,1);
      assert.equal(postCalls[0].path,'/api/jobs');assert.equal(JSON.stringify(postCalls[0].body),JSON.stringify(request));
      assert.equal($('retry-submission').hidden,true);
      pending={...request};mismatch=true;await checkSubmission();
      assert.equal(pending.request_id,request.request_id);assert.ok($('error').textContent.includes('does not match'));
      mismatch=false;releaseRead=false;
      const first=checkSubmission();await Promise.resolve();const before=reads.length;
      const second=checkSubmission();assert.equal(reads.length,before);assert.equal($('check-submission').disabled,true);
      releaseRead();await first;await second;assert.equal(pending,null);
      assert.equal(postCalls.length,1);
      selected=request.request_id;
      let releaseResume;fetch=async(path,options={})=>{
        if(path.endsWith('/resume')) {postCalls.push({path});return new Promise(resolve=>releaseResume=()=>resolve({ok:true,status:200,json:async()=>take}));}
        return originalFetch(path,options);
      };
      const resume=$('recover').onclick();await Promise.resolve();await $('recover').onclick();
      assert.equal(postCalls.filter(c=>c.path.endsWith('/resume')).length,1);
      assert.equal($('recover').disabled,true);releaseResume();await resume;
      assert.equal($('recover').disabled,false);
      assert.equal(postCalls.filter(c=>c.path==='/api/jobs').length,1);
      takeError(take);takeError(take);assert.equal($('error').textContent,'Render failed.');
      error('Keep another form error.');takeError(take);
      assert.equal($('error').textContent,'Keep another form error.');
      takeError({...take,error:null});assert.equal($('error').textContent,'Keep another form error.');
      const look={request_id:'b'.repeat(32),source_id:null,frame_format:'portrait',frame_index:0,seed:42,prompt:'An original look'};
      pendingLook={...look};studioStorage.setItem('openreshoot-pending-look',JSON.stringify(look));
      let lookReads=0;
      fetch=async(path,options={})=>{
        if(path==='/api/look-jobs/'+look.request_id) {lookReads++;return {ok:true,status:200,json:async()=>({...look,id:look.request_id,status:'failed',active:false})};}
        if(options.method==='POST') throw new Error('Checking a look must not POST');
        return originalFetch(path,options);
      };
      config.look_connected=false;connectionStatus(true);controls();
      assert.equal($('generate-look').disabled,false);
      await $('generate-look').onclick();assert.equal(pendingLook,null);assert.equal(lookReads,1);
      assert.equal(studioStorage.getItem('openreshoot-pending-look'),null);
    })()`,context);return;
  }
  if(process.argv.includes('--seed-width')) {
    await vm.runInContext(`(async()=>{
      await refreshing;inputMode='text';lookId=null;closingId=null;sourceId=null;
      $('prompt').value='A paper boat';$('motion-prompt').value='Drift gently';
      assert.equal(parseSeed('0'),0);assert.equal(parseSeed('9007199254740991'),9007199254740991);
      assert.equal(parseSeed('9007199254740993'),'9007199254740993');
      const high='9223372036854775807';assert.equal(parseSeed(high),high);
      assert.throws(()=>parseSeed(Number(high)));assert.throws(()=>parseSeed('9223372036854775808'));
      restoreSeed(high);$('seed').oninput();assert.equal(editorDraft().seed,high);
      assert.equal(saved('openreshoot-draft').seed,high);
      await $('generate').onclick();assert.equal(requests.at(-1).body.seed,high);
      const count=requests.length;
      $('seed').value='9223372036854775808';$('seed').oninput();
      assert.equal(editorDraft().seed,high);await $('generate').onclick();assert.equal(requests.length,count);
      restoreSeed(high);$('new-take').onclick();assert.equal(String($('seed').value),'0');
      assert.equal(saved('openreshoot-draft').seed,0);
      assert.equal(nextSeed('9007199254740993'),'9007199254740994');
      const retained=studioStorage.getItem('openreshoot-draft');
      restoreSeed(Number(high));assert.equal($('seed').value,'');
      assert.throws(()=>editorDraft());saveDraft();
      assert.equal(studioStorage.getItem('openreshoot-draft'),retained);
      $('seed').value='17';$('seed').oninput();assert.equal(editorDraft().seed,17);
    })()`,context);return;
  }
  if(process.argv.includes('--submission-reload')) {
    await vm.runInContext(`(async()=>{
      await refreshing;
      inputMode='text';lookId=null;closingId=null;
      $('prompt').value='An original red paper boat';$('motion-prompt').value='Drift gently';
      const originalFetch=fetch;let release;
      fetch=async(path,options)=>{
        if(path==='/api/config' && !options?.method) return {ok:true,json:()=>new Promise(resolve=>release=resolve)};
        return originalFetch(path,options);
      };
      const submission=$('generate').onclick();
      for(let attempt=0;attempt<30 && !release;attempt++) await Promise.resolve();
      assert.ok(release,'Post-acceptance refresh must still be pending');
      const requestId=requests.at(-1).body.request_id;
      assert.equal(studioStorage.getItem('openreshoot-selected'),requestId);
      assert.equal(selected,requestId);
      assert.equal(pending,null);
      release({connected:true,look_connected:true,closing_supported:true});
      await submission;
      assert.equal(requests.filter(r=>r.path==='/api/jobs').length,1);
    })()`,context);
    return;
  }
  if(process.argv.includes('--speech')) {
    await vm.runInContext(`(async()=>{
      await refreshing;
      inputMode='audio';audioId='cccccccccccccccccccccccccccccccc';configureInput();
      $('render-profile').value='single-pass-audio';$('render-profile').onchange();
      assert.equal(editorDraft().render_profile,'single-pass-audio');
      assert.equal(saved('openreshoot-draft').render_profile,'single-pass-audio');
      assert.equal($('reference-closing').disabled,true);
      assert.equal($('reuse-opening-end').checked,false);
      assert.equal($('reuse-opening-end').disabled,true);
      chooseLook('opening-a',0);
      assert.equal($('reference-closing').disabled,false);
      assert.equal($('reuse-opening-end').disabled,false);
      $('reuse-opening-end').checked=true;$('reuse-opening-end').onchange();
      assert.equal(closingId,lookId);
      assert.equal(saved('openreshoot-draft').closing_id,'opening-a');
      assert.equal($('render-profile-single').disabled,false);
      chooseLook('opening-b',0);
      assert.equal(closingId,'opening-b');
      assert.equal($('reuse-opening-end').checked,true);
      $('reuse-opening-end').checked=false;$('reuse-opening-end').onchange();
      assert.equal(closingId,null);
      assert.equal(lookId,'opening-b');
      closingId='custom-end';showLook();
      assert.equal($('reuse-opening-end').checked,false);
      chooseLook('opening-c',0);assert.equal(closingId,null);
      pending={request_id:'uncertain'};controls();
      assert.equal($('reuse-opening-end').disabled,true);
      $('reuse-opening-end').checked=true;$('reuse-opening-end').onchange();
      assert.equal(closingId,null);pending=null;controls();
      setMode('compare');
      assert.ok($('runtime').textContent.includes('Single-pass speech / CPU 2×'));
      showTake({id:'reconnecting',mode:'audio',render_profile:'single-pass-audio',audio_id:audioId,prompt:'Speech',seed:42,status:'connection_lost',error:'Connection interrupted. Saved render retained.'});
      assert.equal($('error').hidden,false);
      takes=[{id:'reconnecting',mode:'audio',render_profile:'single-pass-audio',audio_id:audioId,prompt:'Speech',seed:42,status:'succeeded',elapsed_seconds:101.15}];
      showTake(takes[0]);
      assert.equal($('error').hidden,true);
      assert.ok($('runtime').textContent.includes('Single-pass speech / CPU 2× / 101.2s'));
      takeError({error:'Connection interrupted. Saved render retained.'});
      error('Choose a non-negative seed.');
      takeError({status:'succeeded'});
      assert.equal($('error').textContent,'Choose a non-negative seed.');
      $('input-mode').value='text';$('input-mode').onchange();
      assert.equal(renderProfile,'two-pass');assert.equal($('render-profile-field').hidden,true);
      inputMode='video';sourceId='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';sourceHasAudio=false;renderProfile='single-pass-audio';controls();
      assert.equal($('generate').disabled,true);assert.equal($('render-profile-single').disabled,true);
      inputMode='audio';sourceId=null;renderProfile='single-pass-audio';configureInput();
      chooseLook('opening-submission',0);
      $('reuse-opening-end').checked=true;$('reuse-opening-end').onchange();
      $('prompt').value='An original character speaks';$('seed').value='42';
      await $('generate').onclick();
      assert.equal(requests.find(x=>x.path==='/api/jobs').body.render_profile,'single-pass-audio');
      assert.equal(requests.find(x=>x.path==='/api/jobs').body.closing_id,'opening-submission');
      assert.equal(requests.filter(x=>x.path==='/api/jobs').length,1);
      showTake({id:'old',mode:'audio',audio_id:audioId,prompt:'Legacy take',seed:42,status:'succeeded'});
      assert.equal(renderProfile,'two-pass');assert.equal($('render-profile').value,'two-pass');
      assert.equal($('reuse-opening-end').checked,false);
      showTake({id:'anchored',mode:'audio',audio_id:audioId,look_id:'saved-opening',closing_id:'saved-opening',render_profile:'single-pass-audio',prompt:'Saved take',seed:42,status:'succeeded'});
      assert.equal($('reuse-opening-end').checked,true);
      assert.equal(editorDraft().closing_id,'saved-opening');
      chooseLook(null,0);assert.equal(closingId,null);
      assert.equal($('reuse-opening-end').checked,false);
    })()`,context);
    return;
  }
  await vm.runInContext(`(async () => {
    sourceVideo.src='source.mp4'; outputVideo.setAttribute('src','output.mp4');
    sourceVideo.currentTime=5.166667; sourceVideo.paused=false;
    outputVideo.currentTime=5.012; outputVideo.paused=false;
    outputVideo.onended();
    assert.equal(sourceVideo.paused,true); assert.equal(outputVideo.paused,true);
    assert.equal(sourceVideo.currentTime,5); assert.equal(outputVideo.currentTime,5);
    assert.equal($('time').textContent,'0:05 / 0:05');

    // Some browser seeks report the timestamp slightly below the requested end.
    sourceVideo.currentTime=4.999399; sourceVideo.ontimeupdate();
    assert.equal($('time').textContent,'0:05 / 0:05');
    assert.equal(Number($('scrubber').value),5);

    $('scrubber').value='2'; $('scrubber').oninput(); sourceVideo.ontimeupdate();
    assert.equal(sourceVideo.currentTime,2); assert.equal(outputVideo.currentTime,2);
    assert.equal($('time').textContent,'0:02 / 0:05');

    sourceVideo.currentTime=5; outputVideo.currentTime=5;
    await $('play').onclick();
    assert.equal(sourceVideo.currentTime,0); assert.equal(outputVideo.currentTime,0);
    assert.equal(sourceVideo.paused,false); assert.equal(outputVideo.paused,false);
    sourceVideo.currentTime=1; sourceVideo.ontimeupdate();
    assert.equal($('time').textContent,'0:01 / 0:05');
    sourceVideo.currentTime=5.1; sourceVideo.ontimeupdate();
    assert.equal(sourceVideo.paused,true); assert.equal(sourceVideo.currentTime,5);
    assert.equal($('play').getAttribute('aria-label'),'Play comparison');

    await refreshing;
    assert.equal(frameFormat,'portrait');
    frameFormat='landscape'; showFraming();
    if(cloudLook) {
      assert.equal($('prompt').value,'Tested warm Cloud palette');
      assert.equal($('look-strength').hidden,true);
    } else {
      assert.equal($('look-strength').hidden,false);
    }
    const savedDirection=$('prompt').value;
    config={look_engine:'klein-cloud',look_presets:{warm:'Cloud palette',blue:'Cloud blue'}};
    configureLookControls();
    assert.equal(presets.warm,'Cloud palette');
    config={look_engine:'moss'}; configureLookControls();
    assert.equal(presets.warm,mossPresets.warm);
    assert.equal($('look-strength').hidden,false);
    assert.equal($('prompt').value,savedDirection);
    config={}; sourceId=null; lookId=null; closingId=null; draftTouched=false;
    localStorage.removeItem('openreshoot-draft'); saveDraft();
    assert.equal(localStorage.getItem('openreshoot-draft'),null);
    $('prompt').value='A human typed this before configuration arrived';
    draftChanged();
    config={look_engine:'klein-cloud',look_presets:{warm:'Cloud palette'}};
    configureLookControls(true);
    assert.equal($('prompt').value,'A human typed this before configuration arrived');
    sourceId='source-a'; config={connected:true,look_connected:true,closing_supported:true,max_renders:6,max_looks:12};
    lookJobs=[
      {id:'open-a',source_id:sourceId,frame_index:0,output_url:'/opening',status:'succeeded'},
      {id:'close-a',source_id:sourceId,frame_index:120,output_url:'/closing',status:'succeeded'},
    ];
    lookFrame=0; chooseLook('open-a');
    $('reference-closing').onclick(); chooseLook('close-a');
    assert.equal(lookId,'open-a'); assert.equal(closingId,'close-a');
    assert.equal(currentLookId(),'close-a');
    assert.equal($('look-full').alt,'Selected ending frame');
    assert.equal(JSON.parse(localStorage.getItem('openreshoot-draft')).closing_id,'close-a');
    assert.equal(JSON.parse(localStorage.getItem('openreshoot-draft')).active_look_frame,120);

    // A late closing result must not replace an opening-frame selection.
    lookJobs.push({id:'late-close',source_id:sourceId,frame_index:120,output_url:'/late',status:'succeeded'});
    lookFrame=120;watchLook('late-close',lookChoice('late-close'));lookFrame=0;updateLooks();
    assert.equal(lookId,'open-a'); assert.equal(closingId,'close-a');
    assert.equal(awaitingLook,null);
    lookFrame=120;watchLook('late-close',lookChoice('late-close'));updateLooks();
    assert.equal(closingId,'late-close'); assert.equal(lookId,'open-a');

    // Results from a previous source remain in history without being selected.
    watchLook('late-close',lookChoice('late-close'));sourceId='source-b';updateLooks();
    assert.equal(closingId,'late-close'); assert.equal(awaitingLook,null);
    sourceId='source-a'; lookFrame=0; chooseLook('open-b');
    assert.equal(closingId,null);
    lookFrame=120; chooseLook('close-a'); lookFrame=0; chooseLook(null);
    assert.equal(lookId,null); assert.equal(closingId,null);
    assert.equal($('reference-closing').disabled,true);

    // Image descriptions and motion instructions are independent and persisted.
    $('prompt').value='A copper landscape in warm amber light.';
    $('motion-prompt').value='Follow the source cloud movement and timing.';
    assert.equal(videoPrompt(),$('prompt').value+'\\n\\n'+$('motion-prompt').value);
    lookId='open-a';
    assert.equal(videoPrompt(),$('motion-prompt').value);
    saveDraft();
    assert.equal(JSON.parse(localStorage.getItem('openreshoot-draft')).motion_prompt,$('motion-prompt').value);
    $('seed').value='42';
    await $('generate-look').onclick();
    assert.equal(requests.at(-1).path,'/api/look-jobs');
    assert.equal(requests.at(-1).body.prompt,'A copper landscape in warm amber light.');
    await $('generate').onclick();
    assert.equal(requests.at(-1).path,'/api/jobs');
    assert.equal(requests.at(-1).body.prompt,'Follow the source cloud movement and timing.');
    assert.equal(requests.at(-1).body.art_direction,'A copper landscape in warm amber light.');
    assert.equal(requests.at(-1).body.motion_prompt,'Follow the source cloud movement and timing.');

    // A legacy take is not silently reconstructed with new instructions.
    showTake({id:'legacy',source_id:'source-a',prompt:'Original exact video prompt',seed:42});
    assert.equal(videoPrompt(),'Original exact video prompt');
    lookJobs=[{id:'open-a',prompt:'Original exact image prompt'}];
    showTake({id:'legacy-look',source_id:'source-a',look_id:'open-a',prompt:'Original exact motion',seed:42});
    assert.equal($('prompt').value,'Original exact image prompt');
    assert.equal($('motion-prompt').value,'Original exact motion');
    assert.equal(videoPrompt(),'Original exact motion');
    $('new-take').onclick();
    assert.equal(videoPrompt(),'Original exact motion');
    assert.equal(Number($('seed').value),43);

    // Changing art direction warns, but never clears a reference or submits work.
    sourceId='source-a'; lookId='opening-old'; closingId='closing-old';
    lookJobs=[
      {id:'opening-old',source_id:sourceId,prompt:'Porcelain and cobalt'},
      {id:'closing-old',source_id:sourceId,prompt:'Porcelain and cobalt'},
      {id:'opening-new',source_id:sourceId,prompt:'Copper and amber'},
    ];
    const requestCount=requests.length;
    $('prompt').value='Porcelain and cobalt'; updateReferenceDirection();
    assert.equal($('reference-direction').hidden,true);
    $('motion-prompt').value='A slower pan'; draftChanged();
    assert.equal($('reference-direction').hidden,true);
    $('prompt').value='Copper and amber'; draftChanged();
    assert.equal($('reference-direction').hidden,false);
    assert.equal($('reference-direction').textContent,'opening + ending: earlier art direction');
    assert.equal(lookId,'opening-old'); assert.equal(closingId,'closing-old');
    assert.equal(requests.length,requestCount);
    chooseLook('opening-new',0);
    assert.equal(closingId,null); assert.equal($('reference-direction').hidden,true);
    lookId='uploaded-image'; updateReferenceDirection();
    assert.equal($('reference-direction').hidden,true);

    config.look_engine='klein-cloud'; config.look_model='FLUX.2 Klein 4B FP8';
    await $('generate-look').onclick();
    assert.equal(requests.at(-1).path,'/api/look-jobs');
    assert.equal(requests.at(-1).body.denoise,null);
    assert.equal(requests.at(-1).body.prompt,'Copper and amber');

    // Source/framing changes clear incompatible references without rendering.
    const beforeWindowChange=requests.length;
    sourceDuration=12;
    $('frame-format').value='portrait'; $('source-start').value='4.25';
    $('source-start').oninput();
    assert.equal($('generate').disabled,true);
    assert.equal($('generate-look').disabled,true);
    assert.equal($('apply-range').disabled,false);
    changeWindow();
    assert.equal(frameFormat,'portrait'); assert.equal(sourceStart,4.25);
    assert.equal(lookId,null); assert.equal(closingId,null);
    assert.equal(requests.length,beforeWindowChange);
    assert.equal(JSON.parse(localStorage.getItem('openreshoot-draft')).source_start,4.25);
    assert.equal(JSON.parse(localStorage.getItem('openreshoot-draft')).frame_format,'portrait');
    assert.equal($('apply-range').disabled,true);
    assert.equal(sameWindow({frame_format:'portrait',source_start:0}),false);
    assert.equal(sameWindow({frame_format:'landscape',source_start:4.25}),false);
    assert.equal(sameWindow({frame_format:'portrait',source_start:4.25}),true);
    assert.match(sourceVideo.src,/frame_format=portrait&source_start=4.25/);
    sourceDuration=12;
    const lateLook={id:'wrong-window',source_id:sourceId,frame_index:0,output_url:'/look',frame_format:'portrait',source_start:0,status:'succeeded'};
    lookJobs=[lateLook];watchLook(lateLook.id,lookChoice(lateLook.id));updateLooks();
    assert.equal(lookId,null);
    $('source-start').value='9'; changeWindow();
    assert.equal(sourceStart,4.25);
    assert.match($('error').textContent,/five seconds/);
    sourceDuration=12; $('source-start').value='2'; $('frame-format').value='square';
    changeWindow();
    assert.equal(frameFormat,'square'); assert.equal(sourceStart,2);
    assert.equal(JSON.parse(localStorage.getItem('openreshoot-draft')).frame_format,'square');
    assert.match($('media-spec').textContent,/1280 × 1280/);

    // An idea needs no video. Unsupported source roles are not sent along.
    takes=[]; lookJobs=[]; pending=null; pendingLook=null;
    config={connected:true,look_connected:true,closing_supported:true,max_renders:6,max_looks:12};
    $('input-mode').value='text'; $('input-mode').onchange();
    assert.equal(inputMode,'text');
    assert.equal($('generate').disabled,false);
    assert.equal($('video-source-input').hidden,true);
    assert.equal($('look-generation-tools').hidden,true);
    await $('generate').onclick();
    assert.equal(requests.at(-1).body.mode,'text');
    assert.equal(requests.at(-1).body.source_id,null);
    assert.equal(requests.at(-1).body.audio_id,null);

    // Image mode requires an opening image and makes it visible beside video.
    $('input-mode').value='image'; $('input-mode').onchange();
    assert.equal($('generate').disabled,true);
    chooseLook('uploaded-opening');
    assert.equal($('source-still').hidden,false);
    assert.equal($('source-empty').hidden,true);
    assert.equal($('generate').disabled,false);
    await $('generate').onclick();
    assert.equal(requests.at(-1).body.mode,'image');
    assert.equal(requests.at(-1).body.look_id,'uploaded-opening');
    assert.equal(requests.at(-1).body.source_id,null);

    // Without a source video, output playback is the clock and is not muted.
    sourceVideo.pause(); sourceVideo.currentTime=1.7;
    outputVideo.src='result.mp4'; outputVideo.setAttribute('src','result.mp4');
    outputVideo.currentTime=0; outputVideo.pause();
    await $('play').onclick();
    assert.equal(outputVideo.paused,false); assert.equal(outputVideo.muted,false);
    assert.equal(sourceVideo.paused,true);
    outputVideo.currentTime=2; outputVideo.ontimeupdate();
    assert.equal(Number($('scrubber').value),2);
    $('scrubber').value='3'; $('scrubber').oninput();
    assert.equal(outputVideo.currentTime,3); assert.equal(sourceVideo.currentTime,1.7);

    $('input-mode').value='audio'; $('input-mode').onchange();
    assert.equal($('generate').disabled,true);
    audioId='uploaded-audio'; sourceDuration=12;
    $('source-start').value='2'; changeWindow();
    assert.equal($('audio-source-input').hidden,false);
    assert.match($('audio-preview').src,/source_start=2/);
    await $('generate').onclick();
    assert.equal(requests.at(-1).body.mode,'audio');
    assert.equal(requests.at(-1).body.audio_id,'uploaded-audio');
    assert.equal(requests.at(-1).body.source_id,null);
    assert.equal(requests.at(-1).body.source_start,2);
    assert.equal(JSON.parse(localStorage.getItem('openreshoot-draft')).mode,'audio');
  })()`, context);
})().catch(error => { console.error(error); process.exitCode=1; });
