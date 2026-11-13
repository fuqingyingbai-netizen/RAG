const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(action='copy'){
 const calls=[],messages=[];
 const component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+';CompanyKnowledge',{ElementPlus:{ElMessage:{info:x=>messages.push(x),success:x=>messages.push(x),error:x=>messages.push(x)},ElMessageBox:{confirm:async()=>{}}},window:{getSelection:()=>''},crypto:{randomUUID:()=>String(Math.random())}});
 const doc={id:'source',title:'file.txt',display_title:'file_V2.txt',modified_at:'snapshot',has_original:true,can_read:true,can_manage:true,state:'ready'};
 const state={...component.data(),service:{username:'alice'},canPasteFiles:true,activeProjectId:'target',activeFolderId:'folder',loadDocuments:async()=>{},loadMyProjects:async()=>{},apiFetch:async(url,options)=>{calls.push([url,JSON.parse(options.body)]);return{ok:true,json:async()=>url.endsWith('preview')?{confirmation:'confirmed',access_changes:false}:{document:{id:'clone',title:'file.txt',state:'queued'}}};}};
 const apiFetch=state.apiFetch,loadDocuments=state.loadDocuments,loadMyProjects=state.loadMyProjects;
 for(const[name,method]of Object.entries(component.methods))state[name]=method.bind(state);
 Object.assign(state,{apiFetch,loadDocuments,loadMyProjects});
 state.putFileClipboard(doc,action);return{component,state,doc,calls,messages};
}
test('copy and cut only mark clipboard; successful cut clears and copy stays reusable',async()=>{
 for(const action of ['copy','cut']){const{state,calls}=fixture(action);assert.equal(calls.length,0);await state.pasteFile();assert.equal(calls.length,2);assert.equal(calls[1][1].expected_modified_at,'snapshot');assert.equal(calls[1][1].confirmation,'confirmed');assert.equal(calls[1][1].folder_id,'folder');assert.equal(!!state.fileClipboard,action==='copy');assert.equal(state.clipboardBusy,false);}
});
test('lost response retry reuses id and consumes completed preview without another mutation',async()=>{
 const{state,calls}=fixture('cut');let id;
 state.apiFetch=async(url,options)=>{const data=JSON.parse(options.body);calls.push(url);if(!id)id=data.request_id;assert.equal(data.request_id,id);if(calls.length===2)throw Error('network');return{ok:true,json:async()=>calls.length===1?{confirmation:'token'}:{completed:true,result:{document:{id:'source'}}}};};
 await state.pasteFile();assert.ok(state.fileClipboard);await state.pasteFile();assert.equal(calls.length,3);assert.equal(state.fileClipboard,null);
});
test('source rejection keeps clipboard and user switch clears before sending',async()=>{
 const{state,calls}=fixture();state.apiFetch=async()=>({ok:false,json:async()=>({detail:'文件已变化，请重新复制'})});await state.pasteFile();assert.ok(state.fileClipboard);state.service.username='bob';await state.pasteFile();assert.equal(state.fileClipboard,null);assert.equal(calls.length,0);
});
test('permission confirmation cancel prevents paste and read-only sources cannot be copied',async()=>{
 const{state,doc,component}=fixture();state.apiFetch=async()=>({ok:true,json:async()=>({access_changes:true})});let posted=0;state.apiFetch=async(url)=>{posted++;return{ok:true,json:async()=>({access_changes:true})};};
 // Confirmation rejects in an isolated component evaluation.
 const c=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+';CompanyKnowledge',{ElementPlus:{ElMessage:{error:()=>{}},ElMessageBox:{confirm:async()=>{throw 'cancel'}}}});
 await c.methods.pasteFile.call(state);assert.equal(posted,1);assert.ok(state.fileClipboard);assert.equal(state.canClipboardDocument({...doc,can_manage:false}),false);assert.equal(state.canClipboardDocument({...doc,state:'indexing'}),false);
});
test('keyboard shortcuts leave text inputs and selected text untouched',()=>{
 const{state,doc}=fixture();let count=0;state.putFileClipboard=()=>count++;
 state.fileRowKey(doc,{key:'c',ctrlKey:true,target:{closest:()=>({})}});assert.equal(count,0);
 state.fileRowKey(doc,{key:'x',ctrlKey:true,target:{closest:()=>null},preventDefault(){},stopPropagation(){}});assert.equal(count,1);
 state.pasteFile=()=>count++;state.directoryFileKey({key:'v',ctrlKey:true,target:{closest:()=>({})}});assert.equal(count,1);
});
