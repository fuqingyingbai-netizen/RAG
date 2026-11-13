const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const defer=()=>{let resolve;return{promise:new Promise(r=>resolve=r),resolve};};
function fixture(confirm=async()=>{}){
 const messages=[],component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+';CompanyKnowledge',{ElementPlus:{ElMessage:{info:x=>messages.push(x),success:x=>messages.push(x),error:x=>messages.push(x)},ElMessageBox:{confirm}},crypto:{randomUUID:()=> 'request'},window:{}});
 const state=component.data();for(const[k,v]of Object.entries(component.methods))state[k]=v.bind(state);
 Object.assign(state,{service:{username:'alice'},canPasteFiles:true,currentCollection:'library',activeProjectId:'project',activeProject:{department:'market'},activeFolderId:'folder',loadDocuments:async()=>{},loadMyProjects:async()=>{}});
 state.putFileClipboard({id:'source',display_title:'Source_V2.txt',title:'Source.txt',modified_at:'snapshot',can_read:true,can_manage:true,has_original:true,state:'ready',category:'项目原件'},'copy');
 return{state,component,messages};
}
const response=data=>({ok:true,json:async()=>data});
test('pending row appears before server confirmation; real file and success do not wait for catalogue refresh',async()=>{
 const{state,messages}=fixture(),preview=defer(),save=defer(),refresh=defer();let calls=0;
 state.apiFetch=async()=>++calls===1?preview.promise:save.promise;state.loadDocuments=()=>refresh.promise;
 const pending=state.pasteFile();assert.equal(state.pasteTasks.length,1);assert.equal(state.pasteTasks[0].phase,'checking');assert.equal(state.cloudDocuments.length,0);
 preview.resolve(response({confirmation:'checked'}));await new Promise(setImmediate);assert.equal(state.pasteTasks[0].phase,'saving');
 save.resolve(response({document:{id:'clone',title:'Clone.txt',state:'queued',can_read:true}}));await pending;
 assert.equal(state.clipboardBusy,false);assert.equal(state.cloudDocuments[0].id,'clone');assert.equal(state.pasteTasks.length,0);assert.equal(state.fileClipboard.completed,true);assert.match(messages.at(-1),/文件已保存/);assert.match(state.pasteDocumentStatus(state.cloudDocuments[0]),/建立检索索引/);refresh.resolve();
});
test('uncertain network result retries the original request and consumes completed preview',async()=>{
 const{state}=fixture();let calls=0;
 state.apiFetch=async()=>{calls++;if(calls===1)return response({confirmation:'checked'});if(calls===2)throw Error('network');return response({completed:true,result:{document:{id:'clone',title:'Clone.txt',state:'ready'}}});};
 await state.pasteFile();assert.equal(state.pasteTasks[0].phase,'failed');assert.match(state.pasteTasks[0].message,/尚未确认/);const task=state.pasteTasks[0];await state.retryPasteTask(task);assert.equal(calls,3);assert.equal(state.cloudDocuments.length,1);assert.equal(state.pasteTasks.length,0);
});
test('permission cancellation removes placeholder and creates no file',async()=>{
 const{state}=fixture(async()=>{throw 'cancel'});let calls=0;state.apiFetch=async()=>{calls++;return response({access_changes:true});};await state.pasteFile();assert.equal(calls,1);assert.equal(state.pasteTasks.length,0);assert.equal(state.cloudDocuments.length,0);
});
test('index failure is labelled as saved and does not become paste failure',()=>{
 const{state}=fixture();state.pasteResults={clone:'copy'};assert.match(state.pasteDocumentStatus({id:'clone',state:'failed',can_read:true}),/文件已保存，索引失败/);assert.equal(state.pasteDocumentStatus({id:'clone',state:'ready',can_read:true}),'');
});
test('audit delete needs admin capability and explicit confirmation, then repairs an empty final page',async()=>{
 const{state}=fixture();let calls=0;state.apiFetch=async()=>{calls++;return response({deleted:true});};state.auditEvents=[{id:'event'}];state.auditTotal=31;state.auditPage=2;state.loadAudit=async()=>{};
 await state.deleteAuditEvent({id:'event',action:'document.preview'});assert.equal(calls,0);state.auditCanDelete=true;await state.deleteAuditEvent({id:'event',action:'document.preview'});assert.equal(calls,1);assert.equal(state.auditPage,1);assert.equal(state.auditTotal,30);assert.equal(state.auditDeleting,'');
 const canceled=fixture(async()=>{throw 'cancel'}).state;canceled.auditCanDelete=true;canceled.apiFetch=async()=>{throw Error('must not delete')};await canceled.deleteAuditEvent({id:'event',action:'document.preview'});assert.equal(canceled.auditDeleting,'');
});
