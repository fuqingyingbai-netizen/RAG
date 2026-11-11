const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(confirm,recyclable=false){
 const calls=[];
 const component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+';CompanyKnowledge',{ElementPlus:{ElMessageBox:{confirm}},AbortController,File,FormData,setTimeout,clearTimeout});
 const scope={name:'合成目录',folder_count:2,document_count:3,note_count:1,recyclable,confirmation:'a'.repeat(64)};
 const state={editingFolder:{id:'folder',name:scope.name},activeProject:{id:'project'},folderSaving:false,folderError:'',folderEditorOpen:true,catalogueMutation:0,selectedFolderIds:['folder'],selectedIds:['file'],documents:[],projectFolders:[],apiFetch:async(url,options={})=>{calls.push([url,options.method||'GET',options.body]);return{ok:true,json:async()=>options.method==='DELETE'?{deleted:true}:scope};},loadProjectDirectories:async()=>calls.push('refresh-folders'),loadDocuments:async()=>calls.push('refresh-documents'),loadNotes:async()=>calls.push('refresh-notes'),loadMyProjects:async()=>calls.push('refresh-projects')};
 return{state,calls,scope,remove:()=>component.methods.deleteEmptyFolder.call(state)};
}

test('cancel or close folder confirmation only reads scope and never deletes',async()=>{
 for(const action of ['cancel','close']){
  const {state,calls,remove}=fixture(async()=>{throw action});await remove();
  assert.equal(calls.length,1);assert.match(calls[0][0],/deletion-preview$/);assert.equal(calls[0][1],'GET');assert.equal(state.folderEditorOpen,true);assert.equal(state.folderSaving,false);assert.equal(state.folderError,'');
 }
});
test('empty folders explicitly confirm permanent deletion, nonempty folders confirm scoped ten-day recovery',async()=>{
 for(const recyclable of [false,true]){
  const {state,calls,scope,remove}=fixture(async(text,title,options)=>{
   assert.match(text,/合成目录/);assert.equal(options.cancelButtonText,'取消');
   if(recyclable){assert.match(text,/2 个子目录、3 份文件/);assert.match(text,/1 篇笔记或草稿/);assert.match(text,/保留 10 天/);assert.match(text,/恢复目录结构/);assert.equal(title,'删除目录及内容');}
   else {assert.match(text,/无法恢复/);assert.match(text,/不会进入回收站/);assert.equal(title,'删除空目录');}
   assert.equal(state.folderSaving,true);assert.equal(calls.length,1);
  },recyclable);
  await remove();assert.equal(calls[1][1],'DELETE');assert.deepEqual(JSON.parse(calls[1][2]),{confirmation:scope.confirmation});assert.equal(calls.length,6);assert.equal(state.folderEditorOpen,false);assert.equal(state.folderSaving,false);assert.equal(state.selectedFolderIds.length,0);assert.equal(state.selectedIds.length,0);
 }
});
test('preview failure or stale server confirmation keeps editor open with the actionable reason',async()=>{
 for(const failPreview of [true,false]){
  const {state,remove}=fixture(async()=>{});let deletes=0;
  state.apiFetch=async(url,options={})=>{if(options.method==='DELETE')deletes++;return{ok:!failPreview&&options.method!=='DELETE',json:async()=>({detail:'目录内容已变化，请重新确认',confirmation:'a'.repeat(64)})};};
  await remove();assert.equal(state.folderError,'目录内容已变化，请重新确认');assert.equal(state.folderEditorOpen,true);assert.equal(state.folderSaving,false);assert.equal(deletes,failPreview?0:1);
 }
});
