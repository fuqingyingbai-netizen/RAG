const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
const response=(data,ok=true)=>({ok,json:async()=>data});
function fixture(confirm=async()=>{}){
 const messages=[];
 const component=vm.runInNewContext(fs.readFileSync(process.env.KNOWLEDGE_DELETE_SOURCE||'frontend/company-knowledge.js','utf8')+';CompanyKnowledge',{ElementPlus:{ElMessage:{success:x=>messages.push(x),error:x=>messages.push(x)},ElMessageBox:{confirm}}});
 const state=component.data();for(const[k,v]of Object.entries(component.methods))state[k]=v.bind(state);
 const doc={id:'copy',title:'Copy.txt',state:'ready',can_manage:true,can_read:true};
 Object.assign(state,{service:{username:'alice'},cloudDocuments:[doc,{id:'source'}],selectedIds:['copy','source'],uploadResults:[{id:'copy'}],versionRows:[doc],loadDocuments:async()=>{},loadMyProjects:async()=>{},newConversation:()=>{},invalidateContentSearch:()=>{},apiFetch:async()=>response({deleted:true})});
 return{state,doc,messages};
}
test('confirmed delete disappears before catalogue refresh and preserves source',async()=>{
 const{state,doc,messages}=fixture(),refresh=deferred();state.loadDocuments=()=>refresh.promise;
 const pending=state.deleteDocument(doc);await new Promise(setImmediate);
 try{
  assert.deepEqual(Array.from(state.cloudDocuments,x=>x.id),['source']);assert.deepEqual(Array.from(state.selectedIds),['source']);
  assert.equal(state.uploadResults.length,0);assert.equal(state.versionRows.length,0);assert.match(messages.at(-1),/已移入回收站/);assert.equal(state.operationPending('delete:copy'),false);
 }finally{refresh.resolve();await pending;}
});
test('duplicate click is suppressed while confirming and while DELETE waits',async()=>{
 const confirm=deferred(),save=deferred();const{state,doc}=fixture(()=>confirm.promise);let calls=0;state.apiFetch=()=>{calls++;return save.promise;};
 const pending=state.deleteDocument(doc);await state.deleteDocument(doc);assert.equal(calls,0);
 confirm.resolve();await new Promise(setImmediate);assert.equal(state.operationPending('delete:copy'),true);assert.match(state.knowledgeState(doc),/删除中/);
 await state.deleteDocument(doc);assert.equal(calls,1);assert.equal(state.cloudDocuments.length,2);save.resolve(response({deleted:true}));await pending;assert.equal(state.documentDeleteIds.length,0);
});
test('cancel and server rejection retain the file and release busy status',async()=>{
 const canceled=fixture(async()=>{throw 'cancel'});let calls=0;canceled.state.apiFetch=async()=>{calls++;};await canceled.state.deleteDocument(canceled.doc);assert.equal(calls,0);assert.equal(canceled.state.cloudDocuments.length,2);
 for(const detail of ['正在建立检索索引，本次未删除','没有管理权限','云端索引移除结果尚未确认']){
  const{state,doc,messages}=fixture();state.apiFetch=async()=>response({detail},false);await state.deleteDocument(doc);assert.equal(state.cloudDocuments.length,2);assert.equal(messages.at(-1),detail);assert.equal(state.operationPending('delete:copy'),false);
 }
});
test('lost delete response can be retried without hiding an unconfirmed file',async()=>{
 const{state,doc,messages}=fixture();state.apiFetch=async()=>{throw Error('network')};await state.deleteDocument(doc);assert.equal(state.cloudDocuments.length,2);assert.match(messages.at(-1),/尚未确认/);
 state.apiFetch=async()=>response({deleted:true});await state.deleteDocument(doc);assert.equal(state.cloudDocuments.length,1);
});
test('account change does not mutate the next account catalogue',async()=>{
 const{state,doc}=fixture();state.apiFetch=async()=>{state.service.username='bob';return response({deleted:true});};await state.deleteDocument(doc);assert.equal(state.cloudDocuments.length,2);
});
test('slow stale catalogue response cannot bring back a confirmed deleted row',async()=>{
 const{state,doc}=fixture(),read=deferred();
 const component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+';CompanyKnowledge',{});
 state.loadDocuments=component.methods.loadDocuments.bind(state);state.loadProjectDirectories=async()=>{};state.serviceError='';state.libraryPageCount=1;
 let reads=0;state.apiFetch=async(url,options)=>{
  if(options?.method==='DELETE')return response({deleted:true});
  if(url.includes('/documents?')){if(++reads===1)return read.promise;return response({documents:[{id:'source'}],total_count:1});}
  return response({});
 };
 const pending=state.loadDocuments();await new Promise(setImmediate);await state.deleteDocument(doc);assert.equal(state.cloudDocuments.length,1);
 read.resolve(response({documents:[doc,{id:'source'}],total_count:2}));await pending;assert.deepEqual(Array.from(state.cloudDocuments,x=>x.id),['source']);
});
test('malformed success response never removes an unconfirmed file',async()=>{
 for(const result of [response({}),{ok:true,json:async()=>{throw Error('HTML')}}]){
  const{state,doc,messages}=fixture();state.apiFetch=async()=>result;await state.deleteDocument(doc);assert.equal(state.cloudDocuments.length,2);assert.match(messages.at(-1),/尚未确认/);
 }
});
