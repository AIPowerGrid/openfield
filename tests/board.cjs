// Actual browser handlers against a small DOM/API double; native QA is separate.
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {readFileSync}=require('node:fs');
const elements=new Map(), storage=new Map(), calls=[];
const finishing=process.argv.includes('--finishing');
const auditions=process.argv.includes('--auditions');
const lookAdoption=process.argv.includes('--look-adoption');
let created=0, serial=100, failGeneration=false, conflictSave=false;
function element(id) {
  if(!elements.has(id)) {
    const attributes=new Map(),classes=new Set();
    elements.set(id,{value:'',textContent:'',style:{},dataset:{},children:[],paused:true,currentTime:0,readyState:4,
      classList:{toggle(name,on){if(on??!classes.has(name))classes.add(name);else classes.delete(name);},contains:name=>classes.has(name)},getAttribute:k=>attributes.get(k)||null,
      setAttribute:(k,v)=>attributes.set(k,v),removeAttribute:k=>attributes.delete(k),
      querySelector:()=>element(id+'-child'),replaceChildren(){this.children=[];},append(...items){this.children.push(...items);},
      addEventListener(){},focus(){},checkValidity(){return true;},load(){},pause(){this.paused=true;this.onpause?.();},
      async play(){this.paused=false;this.onplay?.();}});
  }
  return elements.get(id);
}
const pid='a'.repeat(32), ids=['1','2','3'].map(c=>c.repeat(32));
const draft={frame_format:'square',source_start:0,mode:'text',source_id:null,audio_id:null,prompt:'',art_direction:null,motion_prompt:null,seed:42,look_id:null,closing_id:null};
let server={version:1,id:pid,revision:0,title:'A short',frame_format:'square',art_direction:'Paper-cut miniature.',shots:ids.map((id,i)=>({id,title:['Hook','Reveal','Payoff'][i],beat:['hook','reveal','payoff'][i],draft:{...draft},direction_override:null,selected_take_id:null,trim_start:0,trim_end:120,volume:1}))};
let jobs=[], imageJobs=[];
let packageReplyLost=false, importReplyLost=false;
const packages=new Map(), imports=new Map(), downloads=[];
const context=vm.createContext({assert,calls,downloads,
  FormData:class {append(key,value){this[key]=value;}},
  byLabel:label=>Array.from(elements.values()).reverse().find(item=>item.getAttribute('aria-label')===label),
  document:{body:{append(node){downloads.push(node.href);node.click=()=>{};node.remove=()=>{};}},getElementById:element,querySelector:element,querySelectorAll:()=>[],createElement:()=>element('new-'+created++)},
  studioSession:{mode:'local'},
  localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
  crypto:{randomUUID:()=>(serial++).toString(16).padStart(32,'0')},
  setInterval(){},setTimeout(){return 1;},clearTimeout(){},
  fetch:async(path,options={})=>{
    const method=options.method || 'GET', body=typeof options.body==='string' ? JSON.parse(options.body) : options.body || null;
    calls.push({path,method,body});
    let status=200,result;
    if(path==='/api/config') result={connected:true,look_connected:auditions || lookAdoption,look_engine:'moss',closing_supported:true,backend:'self-hosted',max_renders:20,max_looks:10};
    else if(path==='/api/jobs') result=jobs;
    else if(path==='/api/look-jobs') {
      if(method==='POST') {
        let job=imageJobs.find(t=>t.id===body.request_id);
        if(!job) {job={...body,id:body.request_id,status:'running',active:true,model:'MOSS Image SFT BF16'};imageJobs.push(job);}
        if(failGeneration) {failGeneration=false;throw new Error('Response lost after acceptance');}
        result=job;
      } else result=imageJobs;
    }
    else if(/^\/api\/(jobs|look-jobs)\/[a-f0-9]{32}$/.test(path)) {
      result=(path.startsWith('/api/jobs/') ? jobs : imageJobs).find(item=>item.id===path.split('/').at(-1));
      if(!result) {status=404;result={detail:'Not found'};}
    }
    else if(/^\/api\/(sources|audio)\/[a-f0-9]{32}\/info$/.test(path)) result={duration:5,has_audio:false};
    else if(path.endsWith('/packages')) {
      result={...body,project_id:pid,id:body.request_id,status:'complete',download_url:'/api/project-packages/'+body.request_id+'/download'};
      packages.set(body.request_id,result);
      if(packageReplyLost) {packageReplyLost=false;throw new Error('Package reply lost');}
    }
    else if(path.startsWith('/api/project-packages/')) result=packages.get(path.split('/').at(-1));
    else if(path.startsWith('/api/project-imports/')) {
      const key=path.split('/').at(-1);
      if(method==='POST') {
        imports.set(key,{status:'complete',project:server});
        if(importReplyLost) {importReplyLost=false;throw new Error('Import reply lost');}
      }
      result=imports.get(key);
    }
    else if(path.endsWith('/exports')) result=[];
    else if(path==='/api/projects') result=[server];
    else if(path==='/api/caption-previews') result={url:'/api/caption-previews/'+String(serial++),layout:{}};
    else if(path==='/api/audio?purpose=soundtrack') result={audio_id:(serial++).toString(16).padStart(32,'0'),name:body.file.name,duration:.5};
    else if(path===`/api/projects/${pid}`) {
      if(method==='PUT') {
        if(conflictSave || body.revision!==server.revision) {status=409; result={detail:'Changed elsewhere'};}
        else {server={...body,revision:body.revision+1}; result=server;}
      } else result=server;
    } else if(path.endsWith('/generate')) {
      const shot=server.shots.find(s=>path.includes(s.id));
      let job=jobs.find(t=>t.id===body.request_id);
      if(!job) {job={...shot.draft,id:body.request_id,request_id:body.request_id,project_id:pid,shot_id:shot.id,project_revision:body.revision,prompt:server.art_direction+'\n\n'+shot.draft.prompt,status:'running',active:true}; jobs.push(job);}
      if(failGeneration) {failGeneration=false; throw new Error('Response lost after acceptance');}
      result=job;
    } else throw new Error('Unexpected test URL '+path);
    return {ok:status===200,status,json:async()=>JSON.parse(JSON.stringify(result))};
  },
  failNext:()=>{failGeneration=true;}, conflict:()=>{conflictSave=true;},
  setJobs:items=>{jobs=items;},
  setImageJobs:items=>{imageJobs=items;},
  losePackageReply:()=>{packageReplyLost=true;},loseImportReply:()=>{importReplyLost=true;},
});
vm.runInContext(readFileSync(0,'utf8'),context);
(async()=>{
  if(process.argv.includes('--creation-recovery')) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');
      const scenario='${process.argv.at(-1)}',originalFetch=fetch,receipts=new Map(),creationPosts=[],creationReads=[];
      let releasePost,releaseCheck,badReceipt=scenario==='mismatched',failList=['list-failed','list-missing'].includes(scenario);
      const baseline=JSON.parse(JSON.stringify(shortProject));
      fetch=async(path,options={})=>{
        const method=options.method || 'GET',body=options.body ? JSON.parse(options.body) : null;
        if(path.startsWith('/api/project-creations/')) {
          const id=path.split('/').at(-1);
          if(method==='POST') {
            creationPosts.push({path,body});
            if(scenario==='validation-failed') return {ok:false,status:422,json:async()=>({detail:'Choose valid new-short details.'})};
            if(scenario==='missing' && creationPosts.length===1) throw new Error('Lost before creation');
            const receipt={id,request:body,project:{...baseline,id,title:body.title,frame_format:body.frame_format,revision:0,shots:baseline.shots.map(s=>({...s,draft:{...s.draft,frame_format:body.frame_format}}))}};
            receipts.set(id,receipt);
            if(scenario==='double-submit') return new Promise(resolve=>releasePost=()=>resolve({ok:true,status:200,json:async()=>receipt}));
            if(creationPosts.length===1 && !['list-failed','list-missing'].includes(scenario)) throw new Error('Reply lost after creation');
            return {ok:true,status:200,json:async()=>receipt};
          }
          creationReads.push(path);const receipt=receipts.get(id);
          if(!receipt) return {ok:false,status:404,json:async()=>({detail:'New short request not found.'})};
          const reply=badReceipt ? {...receipt,request:{...receipt.request,title:'Wrong original title'}} : receipt;
          if(scenario==='double-check' && !releaseCheck) return new Promise(resolve=>releaseCheck=()=>resolve({ok:true,status:200,json:async()=>reply}));
          return {ok:true,status:200,json:async()=>reply};
        }
        if(path==='/api/projects' && method==='GET') {
          if(failList && receipts.size) {failList=false;if(scenario==='list-missing') return {ok:false,status:404,json:async()=>({detail:'List unavailable'})};throw new Error('List connection unavailable');}
          return {ok:true,status:200,json:async()=>[baseline,...[...receipts.values()].map(r=>r.project)]};
        }
        const receipt=[...receipts.values()].find(r=>path==='/api/projects/'+r.project.id);
        if(receipt) return {ok:true,status:200,json:async()=>JSON.parse(JSON.stringify(receipt.project))};
        if(path.endsWith('/exports') && [...receipts.values()].some(r=>path.includes(r.project.id))) return {ok:true,status:200,json:async()=>[]};
        return originalFetch(path,options);
      };
      $('new-project-title').value='One frozen short';$('new-project-format').value='portrait';$('new-project-structure').value='before-after';
      const submit=()=>$('project-form').onsubmit({preventDefault(){}});
      if(scenario==='initial-loading') {boardInitialized=false;controls();assert.equal($('create-project').disabled,true);await submit();assert.equal(creationPosts.length,0);assert.equal(pendingCreation,null);return;}
      const originalSet=studioStorage.setItem;
      if(scenario==='storage-failed') studioStorage.setItem=(key,value)=>{if(key==='studio-creation-pending') throw new Error('Browser storage unavailable');return originalSet(key,value);};
      const first=submit();
      if(scenario==='double-submit') {
        for(let i=0;i<100 && !releasePost;i++) await Promise.resolve();assert.ok(releasePost);
        await submit();assert.equal(creationPosts.length,1);assert.equal($('create-project').disabled,true);releasePost();
      }
      await first;studioStorage.setItem=originalSet;
      if(scenario==='storage-failed' || scenario==='validation-failed') {
        assert.equal(pendingCreation,null);assert.equal(creationBusy,false);assert.equal($('new-project-title').disabled,false);
        assert.equal(creationPosts.length,scenario==='storage-failed' ? 0 : 1);assert.equal(receipts.size,0);assert.equal(shortProject.id,baseline.id);return;
      }
      if(scenario==='double-submit') {assert.equal(pendingCreation,null);assert.equal(receipts.size,1);return;}
      assert.equal(creationPosts.length,1);assert.ok(pendingCreation);assert.equal($('create-project-label').textContent,'Check creation');
      assert.equal($('new-project-title').disabled,true);assert.equal($('project-create-state').hidden,false);
      if(scenario==='list-missing') {assert.equal(creationMissing,false);assert.equal($('retry-create-project').hidden,true);}
      const frozen=JSON.parse(studioStorage.getItem('studio-creation-pending')),pendingId=frozen.request_id;
      if(scenario==='reload') {pendingCreation=null;pendingCreation=saved('studio-creation-pending');showCreation();controls();assert.equal(pendingCreation.request_id,pendingId);}
      if(scenario==='later-edit') {receipts.get(pendingId).project.title='Later server edit';receipts.get(pendingId).project.revision=1;}
      if(scenario==='missing') {
        await submit();await submit();assert.equal(creationPosts.length,1);assert.equal(creationReads.length,2);
        assert.equal(creationMissing,true);assert.equal($('retry-create-project').hidden,false);
        $('new-project-title').value='Must not replace frozen details';await $('retry-create-project').onclick();
        assert.equal(creationPosts.length,2);assert.equal(JSON.stringify(creationPosts[0]),JSON.stringify(creationPosts[1]));
      } else {
        const check=submit();
        if(scenario==='double-check') {for(let i=0;i<100 && !releaseCheck;i++) await Promise.resolve();assert.ok(releaseCheck);await submit();assert.equal(creationReads.length,1);releaseCheck();}
        await check;
        if(scenario==='mismatched') {assert.equal(shortProject.id,baseline.id);assert.ok(pendingCreation);assert.ok($('error').textContent.includes('match'));badReceipt=false;await submit();}
        assert.equal(creationPosts.length,1);
      }
      assert.equal(pendingCreation,null);assert.equal(studioStorage.getItem('studio-creation-pending'),null);
      assert.equal(shortProject.id,pendingId);assert.equal(receipts.size,1);assert.equal(creationBusy,false);
      assert.equal(shortProject.title,scenario==='later-edit' ? 'Later server edit' : frozen.title);
      assert.equal($('project-form').hidden,true);assert.equal($('project-create-state').hidden,true);
      assert.equal(calls.filter(c=>c.method==='POST' && (c.path==='/api/jobs'||c.path==='/api/look-jobs'||c.path.endsWith('/generate'))).length,0);
    })()`,context);return;
  }
  if(process.argv.includes('--take-review')) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');
      const takeMode='${process.argv.at(-2)}',takeFormat='${process.argv.at(-1)}';
      const draftFormat=takeFormat==='square' ? 'portrait' : 'square';
      inputMode='audio';audioId='e'.repeat(32);sourceId=null;renderProfile='single-pass-audio';
      frameFormat=draftFormat;shortProject.frame_format=draftFormat;
      lookId='c'.repeat(32);closingId='d'.repeat(32);lookFrame=0;
      $('prompt').value='Keep this newer draft';$('motion-prompt').value='Keep this camera movement';restoreSeed('9223372036854775807');
      draftChanged();await saveBoard();
      const old={id:'b'.repeat(32),project_id:shortProject.id,shot_id:activeShotId,mode:takeMode,frame_format:takeFormat,source_id:takeMode==='video' ? 'f'.repeat(32) : null,audio_id:takeMode==='audio' ? 'a'.repeat(32) : null,source_start:0,look_id:takeMode==='text' ? null : '1'.repeat(32),closing_id:takeMode==='audio' ? '1'.repeat(32) : null,prompt:'Frozen original',seed:42,status:'succeeded',output_url:'/api/jobs/'+ 'b'.repeat(32)+'/output',source_url:takeMode==='video' ? '/api/sources/'+ 'f'.repeat(32) : null,...(takeMode==='video' ? {} : {render_profile:takeMode==='audio' ? 'single-pass-audio' : 'two-pass'})};
      setJobs([old]);await refresh();
      const editor=JSON.stringify(editorDraft()),project=JSON.stringify(shortProject),puts=calls.filter(c=>c.method==='PUT').length;
      const index=projectHooks.filter(takes).findIndex(t=>t.id===old.id);$('takes').children[index].onclick();
      assert.equal(selected,old.id);assert.equal(mode,'result');
      const dimensions=takeFormat==='portrait' ? '1152 × 2048' : takeFormat==='square' ? '1280 × 1280' : '1536 × 896';
      const sound=takeMode==='audio' ? 'supplied audio' : takeMode==='video' ? 'source audio' : 'generated audio';
      assert.equal($('media-spec').textContent,dimensions+' / 24 FPS / '+sound);
      assert.equal($('canvas').classList.contains('portrait'),takeFormat==='portrait');
      assert.equal($('canvas').classList.contains('square'),takeFormat==='square');
      assert.equal($('look-canvas').classList.contains('portrait'),draftFormat==='portrait');
      assert.equal($('look-canvas').classList.contains('square'),draftFormat==='square');
      assert.equal($('frame-format').value,draftFormat);
      assert.equal($('use-take').disabled,true);
      await $('use-take').onclick();assert.equal(activeShot().selected_take_id,null);
      assert.ok($('runtime').textContent.includes(takeMode==='audio' ? 'Single-pass speech' : 'Two-pass'));
      assert.equal($('normalized-source').hidden,!['audio','video'].includes(takeMode));
      assert.equal($('normalized-source').textContent,takeMode==='audio' ? 'Conditioning audio' : 'Workflow source clip');
      for(const [name,id] of [['look',old.look_id],['closing',old.closing_id]]) {
        assert.equal($('download-'+name).hidden,!id);
        if(id) assert.equal($('download-'+name).href,'/api/jobs/'+old.id+'/'+name);
        else assert.equal($('download-'+name).getAttribute('href'),null);
      }
      // A reference-panel refresh must not rebind the export menu to the draft.
      showLook();updateMetadata();
      assert.equal($('download-look').hidden,!old.look_id);
      if(old.look_id) assert.equal($('download-look').href,'/api/jobs/'+old.id+'/look');
      assert.equal(JSON.stringify(editorDraft()),editor);assert.equal(JSON.stringify(shortProject),project);
      const matching={...old,id:'9'.repeat(32),frame_format:draftFormat};setJobs([old,matching]);await refresh();
      projectHooks.viewTake(takes.find(t=>t.id===matching.id));assert.equal($('use-take').disabled,false);
      projectHooks.viewTake(null);setMode('compare');
      assert.equal($('canvas').classList.contains('portrait'),draftFormat==='portrait');
      assert.equal($('download-look').href,'/api/looks/'+lookId);assert.equal($('download-closing').href,'/api/looks/'+closingId);
      assert.equal(JSON.stringify(editorDraft()),editor);assert.equal(JSON.stringify(shortProject),project);
      await saveBoard();assert.equal(calls.filter(c=>c.method==='PUT').length,puts);
      assert.equal(calls.filter(c=>c.method==='POST' && (c.path==='/api/jobs'||c.path==='/api/look-jobs'||c.path.endsWith('/generate'))).length,0);
    })()`,context);return;
  }
  if(lookAdoption) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');
      inputMode='video';sourceId='e'.repeat(32);frameFormat='square';sourceStart=0;lookId=null;closingId=null;lookFrame=0;
      $('prompt').value='The requested image appearance';$('motion-prompt').value='Original movement';$('look-strength').value='0.65';restoreSeed(42);
      const scenario='${process.argv.at(-1)}';
      draftChanged();await saveBoard();if(scenario==='lost-reply') failNext();await $('generate-look').onclick();
      const id=awaitingLook || pendingLook?.request_id;assert.ok(id);
      if(scenario==='lost-reply') {assert.equal(pendingLookChoice.request_id,id);await checkSubmission();assert.equal(pendingLook,null);assert.equal(studioStorage.getItem('openreshoot-pending-look-choice'),null);}
      const completed={...lookJobs.find(t=>t.id===id),active:false,status:'succeeded',output_url:'/api/looks/'+id};
      if(scenario==='manual') {chooseLook('f'.repeat(32),0);chooseLook('a'.repeat(32),120);lookFrame=0;showLook();await saveBoard();}
      if(scenario==='shot') {shortProject.shots[1].draft={...activeShot().draft};markBoard();await saveBoard();activeShotId=shortProject.shots[1].id;await showShot();}
      if(scenario==='prompt') {$('prompt').value='A newer image direction';draftChanged();await saveBoard();}
      if(scenario==='motion') {$('motion-prompt').value='A newer movement';draftChanged();await saveBoard();}
      if(scenario==='roundtrip') {chooseLook('f'.repeat(32),0);chooseLook(null,0);await saveBoard();}
      if(scenario==='legacy') watchLook(id);
      if(scenario==='malformed') awaitingLookChoice={request_id:id};
      if(scenario==='restore') {awaitingLook=null;awaitingLookChoice=null;awaitingLook=studioStorage.getItem('openreshoot-awaiting-look');awaitingLookChoice=saved('openreshoot-awaiting-look-choice');assert.equal(awaitingLookChoice.request_id,id);}
      const before=JSON.stringify(editorDraft()), beforeProject=JSON.stringify(shortProject), posts=calls.filter(c=>c.path==='/api/look-jobs' && c.method==='POST').length;
      setImageJobs([completed]);
      if(scenario==='restore') {boardLoading=true;await refresh();assert.equal(awaitingLook,id);assert.equal(lookId,null);boardLoading=false;}
      await refresh();
      if(['unchanged','motion','restore','lost-reply'].includes(scenario)) {
        assert.equal(lookId,id);assert.equal($('prompt').value,'The requested image appearance');
        assert.equal($('motion-prompt').value,scenario==='motion' ? 'A newer movement' : 'Original movement');
        assert.equal(editorDraft().seed,42);
      } else {
        assert.equal(JSON.stringify(editorDraft()),before,'A late image must not replace a newer reference choice or another shot');
        assert.equal(JSON.stringify(shortProject),beforeProject);
        assert.ok($('look-status').textContent.includes('ready in history'));
      }
      assert.equal(awaitingLook,null);assert.equal(studioStorage.getItem('openreshoot-awaiting-look-choice'),null);
      assert.equal(lookJobs.find(t=>t.id===id).output_url,completed.output_url);
      assert.equal(calls.filter(c=>c.path==='/api/look-jobs' && c.method==='POST').length,posts);
    })()`,context);return;
  }
  if(process.argv.includes('--draft-completion')) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');
      const old={id:'b'.repeat(32),request_id:'b'.repeat(32),project_id:shortProject.id,shot_id:activeShotId,mode:'text',render_profile:'two-pass',source_id:null,audio_id:null,source_start:0,frame_format:'square',look_id:null,closing_id:null,seed:42,prompt:'Original scene',art_direction:'Original scene',motion_prompt:'Original motion',status:'running',active:true,output_url:null};
      setJobs([old]);await refresh();
      inputMode='image';lookId='c'.repeat(32);closingId='d'.repeat(32);
      $('prompt').value='A newer saved direction';$('motion-prompt').value='Newer camera movement';restoreSeed('9223372036854775807');
      draftChanged();await saveBoard();
      const takeIndex=projectHooks.filter(takes).findIndex(item=>item.id===old.id);
      $('takes').children[takeIndex].onclick();assert.equal(mode,'result');
      if(${process.argv.includes('--keep-frame')}) setMode('look');
      boardLoading=true;projectHooks.viewTake(old);assert.equal(boardLoading,true);boardLoading=false;
      const raw=JSON.stringify(activeShot().draft), editor=JSON.stringify(editorDraft()), project=JSON.stringify(shortProject), puts=calls.filter(c=>c.method==='PUT').length, previewMode=mode;
      assert.equal(selected,old.id);assert.equal(editorDraft().mode,'image');
      const complete={...old,active:false,status:'succeeded',output_url:'/api/jobs/'+old.id+'/output'};
      setJobs([complete]);await refresh(${process.argv.includes('--initial-completion')});
      assert.equal(outputVideo.src,complete.output_url);
      assert.equal(mode,previewMode);
      assert.equal(JSON.stringify(editorDraft()),editor,'Completing a viewed take must not restore its old settings');
      assert.equal(JSON.stringify(activeShot().draft),raw);assert.equal(JSON.stringify(shortProject),project);
      assert.equal(activeShot().selected_take_id,null);assert.equal(boardDirty,false);
      await saveBoard();assert.equal(calls.filter(c=>c.method==='PUT').length,puts);
      await loadBoard(shortProject.id,activeShotId,true);
      assert.equal(JSON.stringify(activeShot().draft),raw);
      assert.equal(calls.filter(c=>c.method==='POST' && (c.path==='/api/jobs'||c.path==='/api/look-jobs'||c.path.endsWith('/generate'))).length,0);
    })()`,context);return;
  }
  if(process.argv.includes('--missing-submission') || process.argv.includes('--missing-look')) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');
      const image=${process.argv.includes('--missing-look')}, originalFetch=fetch;
      const id='d'.repeat(32), shot=activeShot(), request={request_id:id,project_id:shortProject.id,shot_id:shot.id,project_revision:shortProject.revision,...shot.draft,prompt:'Frozen direction',seed:'9223372036854775807'};
      if(image) {Object.assign(request,{frame_index:0,look_input:'text',source_id:null,denoise:1});pendingLook=request;}
      else pending=request;
      const frozen=JSON.stringify(request);let checks=0,posts=[];
      fetch=async(path,options={})=>{
        if(path===(image ? '/api/look-jobs/' : '/api/jobs/')+id) {checks++;return {ok:false,status:404,json:async()=>({detail:'Not found'})};}
        if(options.method==='POST') {
          posts.push({path,body:JSON.parse(options.body)});
          return {ok:true,status:200,json:async()=>({...request,id,status:'failed',active:false})};
        }
        return originalFetch(path,options);
      };
      await checkSubmission();await checkSubmission();assert.equal(checks,2);assert.equal(posts.length,0);
      assert.equal($('retry-submission').hidden,false);
      if(image) config.look_connected=false;else config.connected=false;
      controls();assert.equal($('retry-submission').disabled,true);await checkSubmission(true);assert.equal(posts.length,0);
      config.connected=config.look_connected=true;connectionStatus(false);controls();
      await checkSubmission(true);assert.equal(posts.length,1);
      assert.equal(posts[0].path,image ? '/api/look-jobs' : '/api/projects/'+request.project_id+'/shots/'+request.shot_id+'/generate');
      assert.equal(JSON.stringify(posts[0].body),image ? frozen : JSON.stringify({request_id:id,revision:request.project_revision}));
      assert.equal(pending,null);assert.equal(pendingLook,null);
      assert.equal(JSON.stringify(activeShot().draft),JSON.stringify(shot.draft));
    })()`,context);return;
  }
  if(process.argv.includes('--takecompare')) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');
      const shot=activeShot(), before=JSON.stringify(shortProject), beforeDraft=JSON.stringify(editorDraft());
      const completed=(id,extra={})=>({id,project_id:shortProject.id,shot_id:shot.id,mode:'text',frame_format:'square',prompt:'Original test take',seed:42,status:'succeeded',output_url:'/api/jobs/'+id+'/output',...extra});
      takes=[completed('a'.repeat(32)),completed('b'.repeat(32),{seed:'9223372036854775807'}),completed('c'.repeat(32)),completed('d'.repeat(32),{shot_id:'other'}),completed('e'.repeat(32),{status:'failed'})];
      controls();assert.equal(comparisonCandidates().length,3);
      $('compare-takes').onclick();assert.equal(mode,'takes');
      assert.equal(JSON.stringify(shortProject),before);assert.equal(JSON.stringify(editorDraft()),beforeDraft);
      assert.ok(takeVideoA.src);assert.ok(takeVideoB.src);assert.notEqual(takePair.a,takePair.b);
      const initialA=takePair.a, initialB=takePair.b;
      $('take-compare-swap').onclick();assert.equal(takePair.a,initialB);assert.equal(takePair.b,initialA);
      $('take-compare-swap').onclick();
      $('take-compare-b').value='b'.repeat(32);$('take-compare-b').onchange();
      assert.equal(takePair.b,'b'.repeat(32));
      assert.equal(JSON.stringify(editorDraft()),beforeDraft);
      await $('take-compare-play').onclick();assert.equal(takeVideoA.paused,false);assert.equal(takeVideoB.paused,false);
      assert.equal(takeVideoA.muted,true);assert.equal(takeVideoB.muted,false);
      $('take-compare-sound').value='a';$('take-compare-sound').onchange();assert.equal(takeVideoA.muted,false);assert.equal(takeVideoB.muted,true);
      $('take-compare-sound').value='off';$('take-compare-sound').onchange();assert.equal(takeVideoA.muted,true);assert.equal(takeVideoB.muted,true);
      $('take-compare-seek').value='2.5';$('take-compare-seek').oninput();assert.equal(takeVideoA.currentTime,2.5);assert.equal(takeVideoB.currentTime,2.5);
      takeVideoB.currentTime=3;takeVideoA.currentTime=2;takeVideoB.ontimeupdate();assert.equal(takeVideoA.currentTime,3);
      takeVideoB.currentTime=5;takeVideoB.onended();assert.equal(takeVideoA.paused,true);assert.equal(takeVideoB.paused,true);assert.equal($('take-compare-time').textContent,'0:05 / 0:05');
      await $('take-compare-play').onclick();assert.equal(takeVideoB.currentTime,0);setMode('result');assert.equal(takeVideoA.paused,true);assert.equal(takeVideoB.paused,true);
      $('compare-takes').onclick();assert.equal(takePair.b,'b'.repeat(32));
      const realPlay=takeVideoB.play;let releasePlay;
      takeVideoB.play=function(){this.paused=false;return new Promise(resolve=>releasePlay=resolve);};
      const latePlay=$('take-compare-play').onclick();assert.ok(releasePlay);
      stopTakeComparison();takeVideoB.play=realPlay;await $('take-compare-play').onclick();
      releasePlay();await latePlay;assert.equal(takeVideoB.paused,false);stopTakeComparison();
      pending={request_id:'uncertain'};controls();assert.equal($('take-compare-use-b').disabled,true);
      assert.equal($('take-compare-seed-b').disabled,true);$('take-compare-seed-b').onclick();assert.equal(editorDraft().seed,42);
      pending=null;controls();$('take-compare-seed-b').onclick();assert.equal(editorDraft().seed,'9223372036854775807');
      assert.equal($('motion-settings').open,true);
      assert.equal(editorDraft().prompt,JSON.parse(beforeDraft).prompt);
      await saveBoard();const raw=JSON.stringify(activeShot().draft);
      $('compare-takes').onclick();await $('take-compare-use-b').onclick();assert.equal(activeShot().selected_take_id,'b'.repeat(32));
      assert.equal(JSON.stringify(activeShot().draft),raw);
      assert.equal(mode,'result');assert.equal(selected,'b'.repeat(32));
      assert.equal($('take-compare-use-b').disabled,true);
      $('compare-takes').onclick();$('take-compare-swap').onclick();
      assert.equal($('take-compare-use-a').disabled,true);assert.equal($('take-compare-use-b').disabled,false);
      assert.equal(activeShot().selected_take_id,'b'.repeat(32));
      activeShotId=shortProject.shots[1].id;await showShot();controls();assert.equal($('compare-takes').disabled,true);
      assert.equal(takeVideoA.getAttribute('src'),null);assert.equal(takeVideoB.getAttribute('src'),null);
      const intact=JSON.stringify(activeShot().draft);selected=null;$('seed').value='bad-seed';
      projectHooks.newTake();assert.equal(JSON.stringify(activeShot().draft),intact);
      assert.ok($('error').textContent.includes('seed'));
      assert.equal(calls.filter(c=>c.method==='POST' && (c.path==='/api/jobs' || c.path==='/api/look-jobs' || c.path.endsWith('/generate'))).length,0);
    })()`,context);return;
  }
  if(process.argv.includes('--packaging')) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');
      assert.equal(transfersReady,true);
      losePackageReply();await packageProject({preventDefault(){}});
      const packageKey=pendingPackage.request_id;
      assert.equal(saved('studio-package-pending').request_id,packageKey);
      pendingPackage=saved('studio-package-pending');await recoverTransfer();
      assert.equal(pendingPackage,null);assert.equal(downloads.length,1);
      assert.equal(calls.filter(c=>c.path.endsWith('/packages')).length,1);
      assert.ok(calls.some(c=>c.path==='/api/project-packages/'+packageKey && c.method==='GET'));
      loseImportReply();$('project-file').files=[{name:'example.aipg.zip',size:100}];
      await $('project-file').onchange();const importKey=pendingImport.id;
      assert.equal(saved('studio-import-pending').id,importKey);
      pendingImport=saved('studio-import-pending');await recoverTransfer();
      assert.equal(pendingImport,null);
      assert.equal(calls.filter(c=>c.path.startsWith('/api/project-imports/') && c.method==='POST').length,1);
      pendingPackage={request_id:packageKey,project_id:'wrong',revision:0};
      assert.throws(()=>downloadPackage({id:packageKey,project_id:'other',revision:0,status:'complete',download_url:'/api/project-packages/'+packageKey+'/download'}));
      assert.equal(downloads.length,1);
      assert.equal(calls.filter(c=>c.path.endsWith('/generate') || (c.path==='/api/jobs' && c.method==='POST') || c.path==='/api/look-jobs').filter(c=>c.method==='POST').length,0);
    })()`,context);
    return;
  }
  if(process.argv.includes('--submission-reload')) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');
      $('prompt').value='An original red paper boat';draftChanged();await saveBoard();
      const originalFetch=fetch;let release;
      fetch=async(path,options)=>{
        if(path==='/api/config' && !options?.method) return {ok:true,status:200,json:()=>new Promise(resolve=>release=resolve)};
        return originalFetch(path,options);
      };
      const submission=generateBoardShot();
      for(let attempt=0;attempt<100 && !release;attempt++) await Promise.resolve();
      assert.ok(release,'Post-acceptance refresh must still be pending');
      const requestId=calls.findLast(call=>call.path.endsWith('/generate')).body.request_id;
      assert.equal(studioStorage.getItem('openreshoot-selected'),requestId);
      assert.equal(selected,requestId);
      assert.equal(pending,null);
      release({connected:true,look_connected:false,closing_supported:true});await submission;
      fetch=originalFetch;
      assert.equal(activeShot().selected_take_id,null);
      await loadBoard('${pid}','${ids[0]}',true);
      assert.equal(selected,requestId);
      assert.equal(activeShot().selected_take_id,null);
      activeShotId='${ids[1]}';await showShot();
      assert.equal(selected,null,'Another shot must not inherit the preview');
      assert.equal(calls.filter(call=>call.path.endsWith('/generate')).length,1);
    })()`,context);
    return;
  }
  if(process.argv.includes('--ending-anchor')) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');
      inputMode='image';chooseLook('opening-a',0);
      $('reuse-opening-end').checked=true;$('reuse-opening-end').onchange();
      await saveBoard();
      assert.equal(activeShot().draft.closing_id,'opening-a');
      activeShotId='${ids[1]}';await showShot();
      assert.equal($('reuse-opening-end').checked,false);
      activeShotId='${ids[0]}';await showShot();
      assert.equal($('reuse-opening-end').checked,true);
      await loadBoard('${pid}','${ids[0]}',true);
      assert.equal($('reuse-opening-end').checked,true);
      assert.equal(editorDraft().closing_id,'opening-a');
      chooseLook('opening-b',0);await saveBoard();
      assert.equal(activeShot().draft.look_id,'opening-b');
      assert.equal(activeShot().draft.closing_id,'opening-b');
      $('reuse-opening-end').checked=false;$('reuse-opening-end').onchange();
      await saveBoard();assert.equal(activeShot().draft.closing_id,null);
      assert.equal(calls.filter(c=>c.path.endsWith('/generate') || c.path==='/api/jobs' && c.method==='POST').length,0);
    })()`,context);return;
  }
  if(auditions) {
    await vm.runInContext(`(async()=>{
      await boardReady;await loadBoard('${pid}');$('auditions-tab').onclick();
      const importedAudition=activeShot().audition;
      importedAudition.input_key='["text",null,0.0,"square"]';
      assert.equal(auditionState(),importedAudition);
      importedAudition.input_key='["video","wrong-source",0,"square"]';
      assert.equal(auditionState(),null);
      importedAudition.input_key=auditionInputKey();
      $('audition-direction').value='A coral paper flower';$('audition-direction').oninput();
      $('audition-seed').value='72';$('audition-seed').oninput();await saveBoard();
      assert.equal(activeShot().audition.direction,'A coral paper flower');
      failNext();await generateAudition();
      const first=pendingLook.request_id;assert.equal(pendingLook.look_input,'text');
      await generateAudition();assert.equal(pendingLook,null);
      lookJobs=await api('/api/look-jobs');
      assert.equal(lookJobs.length,1);assert.equal(lookJobs[0].id,first);
      const ready={...lookJobs[0],active:false,status:'succeeded',output_url:'/api/looks/'+first};
      lookJobs[0]=ready;auditionLoaded=false;updateLooks();assert.equal(awaitingLook,first);
      auditionLoaded=true;updateLooks();assert.equal(awaitingLook,null);
      assert.equal(activeShot().audition.left_id,first);assert.equal(lookId,null);
      assert.equal(activeShot().selected_take_id,null);
      await applyAudition('left');assert.equal(lookId,first);
      assert.equal(activeShot().selected_take_id,null);
      $('auditions-tab').onclick();changeAuditionReference(first);await saveBoard();
      const pinned=activeShot().audition.reference_id;
      const candidate={...ready,id:'e'.repeat(32),look_input:'image',image_id:pinned,source_id:null};
      lookJobs.push(candidate);auditionComplete(candidate);
      assert.equal(activeShot().audition.right_id,candidate.id);
      await applyAudition('right');$('auditions-tab').onclick();
      assert.equal(activeShot().audition.reference_id,pinned);
      assert.equal(auditionRequest(activeShot().audition,'f'.repeat(32)).image_id,pinned);
      await saveBoard();await loadBoard('${pid}',activeShotId,true);
      assert.equal(activeShot().audition.reference_id,pinned);
      assert.equal(activeShot().audition.right_id,candidate.id);
      // An earlier shot's late result cannot change another shot or its video reference.
      activeShotId='${ids[1]}';await showShot();
      const prior=JSON.stringify(activeShot());auditionComplete(ready);
      assert.equal(JSON.stringify(activeShot()),prior);assert.equal(lookId,null);
      assert.equal(calls.filter(c=>c.path.endsWith('/generate') || c.path==='/api/jobs' && c.method==='POST').length,0);
      assert.equal(calls.filter(c=>c.path==='/api/look-jobs' && c.method==='POST').length,1);
      assert.ok(calls.some(c=>c.path==='/api/look-jobs/'+first && c.method==='GET'));
    })()`,context);return;
  }
  if(finishing) {
    await vm.runInContext(`(async()=>{
      await boardReady; await loadBoard('${pid}');
      $('finish-tab').onclick(); assert.equal($('shot-workspace').hidden,true);
      assert.equal($('finish-controls').hidden,false);
      $('add-caption').onclick(); assert.equal(shortProject.captions.length,1);
      let text=byLabel('Caption 1');text.value='A tiny beginning.';text.oninput();
      await saveBoard(); const cue=shortProject.captions[0];
      // A save acknowledgement must not orphan the still-visible controls.
      text.value='A revised beginning.';text.oninput();await saveBoard();
      assert.equal(shortProject.captions[0],cue); assert.equal(cue.text,'A revised beginning.');
      const out=byLabel('Caption 1 out (s)');out.value='4';out.oninput();await saveBoard();
      assert.equal(shortProject.captions[0].end_frame,96);
      $('caption-style').value='bold';$('caption-style').onchange();await paintCaption(0);await saveBoard();
      assert.equal(shortProject.caption_style,'bold');
      assert.equal($('caption-overlay').hidden,false);
      await paintCaption(97);assert.equal($('caption-overlay').hidden,true);
      await uploadSound('music',{name:'Original beat.wav'});
      assert.equal(shortProject.music.loop,true);assert.equal(shortProject.music.duration_frames,360);
      const volume=byLabel('Music volume');volume.value='0.45';volume.oninput();await saveBoard();
      volume.value='0.6';volume.oninput();await saveBoard();assert.equal(shortProject.music.volume,.6);
      const mute=byLabel('Mute music');mute.checked=true;mute.onchange();await saveBoard();assert.equal(shortProject.music.volume,0);
      mute.checked=false;mute.onchange();await saveBoard();assert.equal(shortProject.music.volume,.6);
      await uploadSound('voiceover',{name:'Original voice.wav'});
      assert.equal(shortProject.voiceover.loop,false);assert.equal(shortProject.voiceover.duration_frames,12);
      await loadBoard('${pid}',activeShotId,true);
      assert.equal(shortProject.captions[0].text,'A revised beginning.');assert.equal(shortProject.music.volume,.6);
      byLabel('Remove voiceover').onclick();await saveBoard();assert.equal(shortProject.voiceover,null);
      $('shot-tab').onclick();assert.equal($('finish-controls').hidden,true);
      assert.equal(calls.filter(c=>c.path.endsWith('/generate') || c.path==='/api/jobs' && c.method==='POST').length,0);
      assert.equal(calls.filter(c=>c.path.endsWith('/exports') && c.method==='POST').length,0);
    })()`,context);return;
  }
  await vm.runInContext(`(async()=>{
    await boardReady;
    await loadBoard('${pid}');
    assert.equal(activeShotId,'${ids[0]}');
    assert.equal(boardDirty,false);
    assert.equal(calls.filter(x=>x.method==='PUT').length,0);
    // Different property order after a server round trip must not autosave forever.
    captureShot(); assert.equal(boardDirty,false);
    $('prompt').value='A red paper boat appears.'; $('prompt').oninput();
    assert.equal(boardDirty,true); await saveBoard();
    assert.equal(shortProject.revision,1);
    assert.ok(shortProject.shots[0].draft.prompt.includes('A red paper boat'));
    assert.equal(shortProject.shots[1].draft.prompt,'');
    await $('shot-duplicate').onclick();
    assert.equal(shortProject.shots.length,4);
    const duplicate=activeShotId;
    assert.notEqual(duplicate,'${ids[0]}');
    assert.ok(activeShot().draft.prompt.includes('A red paper boat'));
    await $('shot-left').onclick();
    assert.equal(shortProject.shots[0].id,duplicate);
    await $('shot-remove').onclick();
    assert.equal(shortProject.shots.length,3);
    assert.equal(calls.filter(x=>x.path.endsWith('/generate')).length,0);
    // One uncertain submission keeps its ID; checking it cannot become another take.
    failNext(); await generateBoardShot();
    assert.ok(pending?.project_id); const id=pending.request_id;
    assert.equal(JSON.parse(localStorage.getItem('openreshoot-pending')).request_id,id);
    await generateBoardShot();
    assert.equal(pending,null);
    const submissions=calls.filter(x=>x.path.endsWith('/generate'));
    assert.equal(submissions.length,1);
    assert.equal(submissions[0].body.request_id,id);
    assert.ok(calls.some(c=>c.path==='/api/jobs/'+id && c.method==='GET'));
    assert.equal(takes.length,1);
    assert.equal(activeShot().selected_take_id,null);
    // A preview must not rewrite the saved draft with the shared direction prefix.
    assert.equal(activeShot().draft.prompt.includes('Paper-cut miniature.'),false);
    const before=calls.filter(x=>x.path.endsWith('/generate')).length;
    $('prompt').value='An edited scene'; $('prompt').oninput();
    conflict(); await saveBoard().catch(()=>{});
    assert.equal(boardConflict,true);
    assert.ok(localStorage.getItem('studio-project-draft:${pid}'));
    await generateBoardShot();
    assert.equal(calls.filter(x=>x.path.endsWith('/generate')).length,before);
    await loadBoard('${pid}',activeShotId,true);
    assert.equal(boardConflict,false);
    assert.ok(localStorage.getItem('studio-project-recovery:${pid}'));
    assert.equal(calls.filter(x=>x.path.endsWith('/generate')).length,before);
  })()`,context);
})().catch(e=>{console.error(e);process.exitCode=1;});
