const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../frontend/company-knowledge.js'),'utf8');
function fixture(){
  let token='alice',last;
  class XHR{
    constructor(){this.upload={};last=this;}
    open(method,url){this.method=method;this.url=url;}
    setRequestHeader(key,value){this.header=[key,value];}
    send(form){this.form=form;}
    abort(){this.aborted=true;this.onabort?.();}
    complete(status,body){this.status=status;this.responseText=JSON.stringify(body);this.onload();}
  }
  const component=vm.runInNewContext(source+'\nCompanyKnowledge;',{
    XMLHttpRequest:XHR,localStorage:{getItem:()=>token},setTimeout,clearTimeout,setInterval,clearInterval,FormData,File,
    URL:{revokeObjectURL(){}},AbortController,
  });
  const context=component.data();for(const [name,method] of Object.entries(component.methods))context[name]=method.bind(context);
  context.allReferences=[];context.currentCollection='library';
  return {component,context,xhr:()=>last,account:value=>token=value};
}
test('upload distinguishes transport progress from server save, with explicit cancellation',async()=>{
  const f=fixture(),c=f.context,row={file:{size:100}};
  const pending=c.transferUpload('/uploads',{},row);const xhr=f.xhr();
  xhr.upload.onprogress({loaded:40,total:100,lengthComputable:true});
  assert.equal(row.percent,40);assert.equal(row.phase,'transferring');assert.ok(row.speed>0);
  xhr.upload.onload();assert.equal(row.percent,100);assert.equal(row.phase,'saving');assert.ok(row.saving);
  c.cancelUpload();assert.equal(c.uploadStopped,true);assert.ok(!xhr.aborted,'server commit must not be presented as cancellable');
  xhr.complete(202,{id:'saved'});assert.equal((await pending).status,202);assert.equal(c.uploadXHR,null);
});
test('stopping a transfer rejects it without claiming the server never saved it',async()=>{
  const f=fixture(),row={file:{size:100}},pending=f.context.transferUpload('/uploads',{},row);
  f.context.cancelUpload();await assert.rejects(pending,/核对是否已保存/);assert.equal(f.context.uploadXHR,null);
});
test('a delayed receipt cannot populate another logged-in account',async()=>{
  const f=fixture(),pending=f.context.transferUpload('/uploads',{}, {file:{size:100}});
  f.account('bob');f.xhr().complete(202,{id:'alice-file'});
  await assert.rejects(pending,/登录或页面已变化/);assert.equal(f.context.uploadStopped,true);
});
test('a failed connection is an uncertain receipt and is never automatically retried',async()=>{
  const f=fixture(),pending=f.context.transferUpload('/uploads',{}, {file:{size:100}});
  f.xhr().onerror();await assert.rejects(pending,/保存结果待核对/);
});
test('a hidden active upload is reopened without resetting files or its target',()=>{
  const f=fixture(),c=f.context;c.uploadBusy=true;c.uploadOpen=false;c.uploadTargetProjectId='original';c.stagedFiles=[{name:'large.mp4'}];
  for(const open of [()=>c.startUpload(),()=>c.openQuickCapture(),()=>c.startReupload({})]){
    open();assert.equal(c.uploadOpen,true);assert.equal(c.uploadTargetProjectId,'original');assert.equal(c.stagedFiles.length,1);
  }
});
test('queue cancellation stops the next file and keeps failures available for retry',async()=>{
  const f=fixture(),c=f.context;
  Object.assign(c,{uploadForm:{project:'',industry:'',category:'项目原件',review:'待复核',confidentiality:'internal',visibility:'members',readersText:'',tagsText:'',description:'',department:'market'},
    stagedFiles:[new File(['first'],'first.txt'),new File(['second'],'second.txt')],loadDocuments:async()=>{},loadMyProjects:async()=>{}});
  const pending=c.uploadFiles();c.cancelUpload();await pending;
  assert.equal(c.uploadBusy,false);assert.equal(c.stagedFiles.length,2);assert.equal(c.uploadResults.length,2);
  assert.equal(c.uploadResults[0].phase,'upload_failed');assert.equal(c.uploadResults[1].phase,'stopped');
});
test('metadata edits while uploading cannot change the next file destination',async()=>{
  const f=fixture(),c=f.context;
  Object.assign(c,{uploadForm:{project:'',industry:'',category:'项目原件',review:'待复核',confidentiality:'internal',visibility:'members',readersText:'',tagsText:'',description:'original',department:'market'},
    stagedFiles:[new File(['a'],'a.txt'),new File(['b'],'b.txt')],loadDocuments:async()=>{},loadMyProjects:async()=>{}});
  const pending=c.uploadFiles();c.uploadForm.description='other editor';c.uploadTargetProjectId='other-project';
  f.xhr().complete(202,{id:'a',state:'queued'});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.xhr().form.get('description'),'original');assert.equal(f.xhr().form.get('project_id'),null);
  f.xhr().complete(202,{id:'b',state:'queued'});await pending;assert.equal(c.stagedFiles.length,0);
});
test('closing media preparation releases its poll and ignores its delayed response',async()=>{
  const f=fixture(),c=f.context;let respond;
  c.apiFetch=()=>new Promise(resolve=>respond=resolve);let current=true;
  const pending=c.loadMediaPlayback({id:'a'},()=>current);
  current=false;c.releaseReader();respond({ok:true,status:200,json:async()=>({url:'/protected-stream'})});
  await pending;assert.equal(c.readerUrl,'');
});
test('media failure offers retry and raw download, with no fabricated transcript UI',()=>{
  assert.match(source,/重试播放/);assert.match(source,/下载原文件/);
  assert.match(source,/根据文字说明提问/);assert.match(source,/!selectedDoc.media_kind \|\| selectedDoc.description/);
  assert.equal(fixture().context.plainOriginal({format:'PNG'}),true);
  assert.equal(fixture().context.plainOriginal({format:'PDF'}),false);
});
test('media render branch excludes the image fallback and stale image errors cannot clear playback',()=>{
  assert.match(source,/<knowledge-sheet-viewer v-else-if=/);
  const c=fixture().context;c.selectedDoc={media_kind:'video'};c.readerUrl='/protected-stream';
  c.imagePreviewError({target:{src:'blob:old-image'}});assert.equal(c.readerUrl,'/protected-stream');
  c.selectedDoc={format:'PNG'};c.imagePreviewError({target:{src:'blob:old-image'}});assert.equal(c.readerUrl,'/protected-stream');
  c.mediaPlaybackError({target:{getAttribute:()=>'/old-video',error:{code:4}}});assert.equal(c.readerOriginalError,'');
});

test('upload rows follow their snapshotted directory and disappear on server acknowledgement',async()=>{
  const f=fixture(),c=f.context;
  Object.assign(c,{uploadForm:{project:'',industry:'',category:'项目原件',review:'待复核',confidentiality:'internal',visibility:'members',readersText:'',tagsText:'',description:'',department:'market'},
    uploadTargetProjectId:'p',uploadTargetFolderId:'f',activeProjectId:'p',activeFolderId:'f',departmentActive:false,showingProjects:false,
    stagedFiles:[new File(['a'],'a.txt'),new File(['b'],'b.txt')],loadDocuments:async()=>{},loadMyProjects:async()=>{}});
  const visible=()=>f.component.computed.visibleUploadTasks.call(c);
  const pending=c.uploadFiles();assert.equal(visible().length,2);assert.equal(visible()[1].phase,'waiting');
  c.uploadTargetFolderId='edited-form';c.activeFolderId='other-folder';assert.equal(visible().length,0);
  c.activeFolderId='f';f.xhr().upload.onprogress({loaded:1,total:10,lengthComputable:true});assert.equal(visible()[0].percent,10);
  f.xhr().complete(202,{id:'saved-a',state:'queued'});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(visible().length,1);assert.equal(c.cloudDocuments.length,1);
  f.xhr().complete(202,{id:'saved-b',state:'queued'});await pending;assert.equal(visible().length,0);
  c.uploadResults=[{name:'root.txt',destination:{project_id:'',folder_id:'',category:'项目原件',department:'market'}}];
  c.activeProjectId='';c.showingProjects=true;c.departmentActive=true;c.departmentFilter='project';assert.equal(visible().length,0);
  c.departmentFilter='market';assert.equal(visible().length,1);c.currentCollection='experience';assert.equal(visible().length,0);
});

test('minimizing closes the upload dialog and opens the frozen upload destination',()=>{
  const c=fixture().context;let opened;
  Object.assign(c,{uploadOpen:true,uploadBatchDestination:{project_id:'p',folder_id:'f',category:'项目原件',department:'market'},
    uploadTargetProjectId:'edited-form',projectDirectories:[{id:'p'}],showProjectRoot(){this.activeProjectId='';},openDirectory(p,f){opened=[p.id,f];}});
  c.minimizeUpload();assert.equal(c.uploadOpen,false);assert.deepEqual(opened,['p','f']);assert.equal(c.mode,'library');
  assert.equal(c.departmentFilter,'market');assert.match(source,/@click="minimizeUpload">收起，继续操作/);
});

test('media loading lasts until playable data arrives and ignores an old player',()=>{
  const c=fixture().context;c.selectedDoc={media_kind:'audio'};c.readerUrl='/current-stream';
  const event=(type,readyState=0,url=c.readerUrl)=>({type,target:{readyState,getAttribute:()=>url}});
  c.mediaPlaybackStatus(event('loadstart'));assert.match(c.readerMediaMessage,/加载/);
  c.mediaPlaybackStatus(event('loadeddata',2));assert.match(c.readerMediaMessage,/加载/);
  c.mediaPlaybackStatus(event('canplay',3));assert.equal(c.readerMediaMessage,'');
  c.mediaPlaybackStatus(event('waiting',2));assert.match(c.readerMediaMessage,/缓冲/);
  c.mediaPlaybackStatus(event('playing',4,'/stale'));assert.match(c.readerMediaMessage,/缓冲/);
  c.mediaPlaybackStatus(event('playing',4));assert.equal(c.readerMediaMessage,'');
  c.mediaPlaybackStatus(event('stalled',4));assert.equal(c.readerMediaMessage,'');
  c.mediaPlaybackError({target:{getAttribute:()=>c.readerUrl,error:{code:4}}});assert.equal(c.readerMediaMessage,'');assert.ok(c.readerOriginalError);
  assert.match(source,/class="ckb-media-loading" role="status"/);
});
