const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const wait=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
function app(){
 let component;const messages=[];
 const context={Vue:{createApp(value){component=value;return {component(){return this;},use(){return this;},mount(){}};}},ElementPlus:{ElMessage:{info:m=>messages.push(m)}},AccountManagement:{},PersonalHome:{},ReportVersions:{},CompanyKnowledge:{},localStorage:{getItem:()=>null,setItem(){}},window:{innerWidth:1440,innerHeight:1000},URL,URLSearchParams,setTimeout,clearTimeout,setInterval,clearInterval};
 vm.runInNewContext(fs.readFileSync('frontend/script.js','utf8'),context);
 const state=component.data();for(const [name,fn] of Object.entries(component.methods))state[name]=fn.bind(state);
 const calls=[];const workspace={service:{configured:true,access_allowed:true},initialWorkspaceLoad:Promise.resolve(),openHomeLibrary:()=>calls.push('read'),startUpload:()=>calls.push('upload'),browseMyNotes:()=>calls.push('note')};
 Object.assign(state,{token:'a',$refs:{knowledgeWorkspace:workspace},$nextTick:async()=>{},switchView:view=>{state.activeView=view;calls.push(view);}});
 return {state,workspace,calls,messages};
}
test('reading and upload entries wait for initialization and do not create a task or upload',async()=>{
 const {state,workspace,calls}=app(),ready=wait();workspace.initialWorkspaceLoad=ready.promise;
 const action=state.openPointsAction('upload');await Promise.resolve();assert.deepEqual(calls,['company-knowledge']);
 ready.resolve();await action;assert.deepEqual(calls,['company-knowledge','read','upload']);
});
test('the note shortcut opens personal notes without silently creating an empty note',async()=>{
 const {state,calls}=app();await state.openPointsAction('note');assert.deepEqual(calls,['company-knowledge','note']);
});
test('account changes while knowledge initializes discard the old action',async()=>{
 const {state,workspace,calls}=app(),ready=wait();workspace.initialWorkspaceLoad=ready.promise;
 const action=state.openPointsAction('upload');await Promise.resolve();state.token='b';ready.resolve();await action;
 assert.deepEqual(calls,['company-knowledge']);
});
test('leaving or replacing the workspace prevents an old navigation result reopening upload',async()=>{
 for(const replace of [false,true]){const {state,workspace,calls}=app(),ready=wait();workspace.initialWorkspaceLoad=ready.promise;
 const action=state.openPointsAction('upload');await Promise.resolve();if(replace)state.$refs.knowledgeWorkspace={};else state.activeView='home';ready.resolve();await action;
 assert.deepEqual(calls,['company-knowledge']);}
});
test('rapid action changes only execute the latest action',async()=>{
 const {state,workspace,calls}=app(),ready=wait();workspace.initialWorkspaceLoad=ready.promise;
 const old=state.openPointsAction('upload'),latest=state.openPointsAction('read');ready.resolve();await Promise.all([old,latest]);
 assert.equal(calls.filter(x=>x==='upload').length,0);assert.equal(calls.filter(x=>x==='read').length,1);
});
test('inaccessible or unconfigured knowledge never opens an upload dialog',async()=>{
 for(const service of [{configured:false,access_allowed:true},{configured:true,access_allowed:false}]){
 const {state,workspace,calls}=app();workspace.service=service;await state.openPointsAction('upload');assert.deepEqual(calls,['company-knowledge']);}
});
test('a running answer and unknown action do not change navigation',async()=>{
 const {state,workspace,calls,messages}=app();await state.openPointsAction('due-diligence');assert.equal(calls.length,0);
 workspace.busy=true;await state.openPointsAction('read');assert.equal(calls.length,0);assert.equal(messages.length,1);
});
test('home refresh failure preserves the confirmed balance and successful retry clears stale state',async()=>{
 const context={localStorage:{getItem:()=> 'a'},window:{},document:{hidden:false},setInterval:()=>1,clearInterval(){}};
 const c=vm.runInNewContext(fs.readFileSync('frontend/knowledge-points.js','utf8')+'\nPointsHomeCard;',context);
 const state=c.data();state.points={total:12};let fail=true;
 state.pointsAPI=async()=>{if(fail)throw Error('offline');return {total:20};};
 await c.methods.reload.call(state);assert.equal(state.points.total,12);assert.equal(state.unavailable,true);assert.equal(state.busy,false);
 fail=false;await c.methods.reload.call(state);assert.equal(state.points.total,20);assert.equal(state.unavailable,false);
});
