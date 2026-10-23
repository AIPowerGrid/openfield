/* Portable transfers preserve IDs on recovery and never submit inference. */
let transferBusy=false, transfersReady=false, pendingImport=saved('studio-import-pending'), pendingPackage=saved('studio-package-pending');
function transferMessage(message) {boardMessage(message);}
function transferControls(frozen) {
  $('import-project').disabled=frozen || !transfersReady || !!pendingPackage;
  $('recover-project-transfer').hidden=!pendingImport && !pendingPackage;
  $('recover-project-transfer').disabled=transferBusy || !!pending || submitting;
  for(const id of ['package-project','package-project-finish']) {
    const link=$(id);link.hidden=!shortProject;
    if(shortProject && !frozen && !pendingImport) link.href='#'; else link.removeAttribute('href');
  }
}
projectTransferHooks={busy:()=>transferBusy,controls:transferControls};
function rememberTransfer(key,value) {
  if(value) studioStorage.setItem(key,JSON.stringify(value));else studioStorage.removeItem(key);
}
function downloadPackage(receipt) {
  if(pendingPackage && (receipt.id!==pendingPackage.request_id || receipt.project_id!==pendingPackage.project_id || receipt.revision!==pendingPackage.revision)) throw new Error('This saved package belongs to different project settings.');
  if(receipt.status!=='complete' || !/^\/api\/project-packages\/[0-9a-f]{32}\/download$/.test(receipt.download_url || '')) throw new Error('The project package is not ready. Check this transfer again.');
  const link=document.createElement('a');link.href=receipt.download_url;link.download='';link.hidden=true;
  document.body.append(link);link.click();link.remove();
  pendingPackage=null;rememberTransfer('studio-package-pending',null);transferMessage('Project package ready');
}
async function finishImport(receipt) {
  const project=receipt.project;
  if(receipt.status!=='complete' || !/^[0-9a-f]{32}$/.test(project?.id || '')) throw new Error('The project import is not confirmed. Check this transfer again.');
  await refresh();boardOptions(await api('/api/projects'));await loadBoard(project.id);
  pendingImport=null;rememberTransfer('studio-import-pending',null);transferMessage('Project imported');
}
async function recoverTransfer() {
  if(transferBusy) return;
  transferBusy=true;controls();error('');
  try {
    if(pendingImport) await finishImport(await api(`/api/project-imports/${pendingImport.id}`));
    else if(pendingPackage) {
      let receipt;
      try {receipt=await api(`/api/project-packages/${pendingPackage.request_id}`);}
      catch(e) {if(e.status!==404) throw e;}
      if(!receipt || receipt.status!=='complete') receipt=await api(`/api/projects/${pendingPackage.project_id}/packages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:pendingPackage.request_id,revision:pendingPackage.revision})});
      downloadPackage(receipt);
    }
  } catch(e) {transferMessage('Transfer needs review');error(e.message);}
  finally {transferBusy=false;controls();}
}
$('recover-project-transfer').onclick=recoverTransfer;
$('import-project').onclick=()=>{if(!transferBusy) $('project-file').click();};
$('project-file').onchange=async()=>{
  const file=$('project-file').files[0];if(!file || transferBusy || !transfersReady) return;
  if(file.size>538968064) {error('Choose a project package smaller than 514 MB.');return;}
  if(pendingImport && (pendingImport.name!==file.name || pendingImport.size!==file.size)) {error('Check the pending import or choose the same package again.');$('project-file').value='';return;}
  transferBusy=true;controls();error('');
  try {
    captureShot();await saveBoard();
    pendingImport ||= {id:crypto.randomUUID().replaceAll('-',''),name:file.name,size:file.size};
    rememberTransfer('studio-import-pending',pendingImport);transferMessage('Importing project');
    const receipt=await api(`/api/project-imports/${pendingImport.id}`,{method:'POST',headers:{'Content-Type':'application/zip'},body:file});
    await finishImport(receipt);
  } catch(e) {
    if(e.status && e.status<500 && e.status!==409) {pendingImport=null;rememberTransfer('studio-import-pending',null);}
    transferMessage('Import needs review');error(e.message);
  } finally {transferBusy=false;$('project-file').value='';controls();}
};
async function packageProject(event) {
  event?.preventDefault();if(transferBusy || !transfersReady || pendingImport || !shortProject) return;
  if(pendingPackage) {await recoverTransfer();return;}
  transferBusy=true;controls();error('');
  try {
    captureShot();await saveBoard();
    pendingPackage={request_id:crypto.randomUUID().replaceAll('-',''),project_id:shortProject.id,revision:shortProject.revision};
    rememberTransfer('studio-package-pending',pendingPackage);transferMessage('Packaging project');
    const receipt=await api(`/api/projects/${pendingPackage.project_id}/packages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:pendingPackage.request_id,revision:pendingPackage.revision})});
    downloadPackage(receipt);
  } catch(e) {
    if(e.status && e.status<500 && e.status!==409) {pendingPackage=null;rememberTransfer('studio-package-pending',null);}
    transferMessage('Package needs review');error(e.message);
  } finally {transferBusy=false;controls();}
}
$('package-project').onclick=$('package-project-finish').onclick=packageProject;
boardReady.then(()=>{transfersReady=true;controls();if(pendingImport || pendingPackage) transferMessage('Transfer needs review');});
