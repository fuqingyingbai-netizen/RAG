const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(confirm){
 const calls=[];
 const component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+';CompanyKnowledge',{ElementPlus:{ElMessageBox:{confirm}},AbortController,File,FormData,setTimeout,clearTimeout});
 const state={editingFolder:{id:'folder',name:'合成空目录'},activeProject:{id:'project'},folderSaving:false,folderError:'',folderEditorOpen:true,apiFetch:async(url,options)=>{calls.push([url,options.method]);return{ok:true,json:async()=>({deleted:true})};},loadProjectDirectories:async()=>calls.push('refresh')};
 return{state,calls,remove:()=>component.methods.deleteEmptyFolder.call(state)};
}
test('cancel or close empty folder confirmation sends no deletion request',async()=>{
 for(const action of ['cancel','close']){
  const {state,calls,remove}=fixture(async()=>{throw action});await remove();
  assert.deepEqual(calls,[]);assert.equal(state.folderEditorOpen,true);assert.equal(state.folderSaving,false);assert.equal(state.folderError,'');
 }
});
test('confirmed empty folder deletion explicitly explains irreversible deletion and refreshes only after success',async()=>{
 const {state,calls,remove}=fixture(async(text,title,options)=>{
  assert.match(text,/合成空目录/);assert.match(text,/无法恢复/);assert.match(text,/不会进入回收站/);assert.equal(title,'删除空目录');assert.equal(options.cancelButtonText,'取消');
  assert.equal(state.folderSaving,true);assert.deepEqual(calls,[]);
 });
 await remove();assert.deepEqual(calls,[['/company-knowledge/projects/project/folders/folder','DELETE'],'refresh']);assert.equal(state.folderEditorOpen,false);assert.equal(state.folderSaving,false);
});
test('server refusal keeps the folder editor and displays the reason',async()=>{
 const {state,calls,remove}=fixture(async()=>{});
 state.apiFetch=async()=>({ok:false,json:async()=>({detail:'目录不为空'})});
 await remove();assert.equal(state.folderError,'目录不为空');assert.equal(state.folderEditorOpen,true);assert.equal(state.folderSaving,false);assert.deepEqual(calls,[]);
});
