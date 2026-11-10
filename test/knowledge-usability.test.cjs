const test=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
function fixture(){
 const notices=[],saved={};const component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+'\nCompanyKnowledge;',{
  AbortController,File,clearTimeout,setTimeout,sessionStorage:{setItem:(k,v)=>saved[k]=v},
  ElementPlus:{ElMessage:Object.fromEntries(['info','warning','error'].map(k=>[k,v=>notices.push(v)]))}});
 const state=component.data();for(const [k,f]of Object.entries(component.methods))state[k]=f.bind(state);
 for(const[k,f]of Object.entries(component.computed))Object.defineProperty(state,k,{get:()=>f.call(state)});
 state.$nextTick=async fn=>fn?.();state.$refs={documentTable:{scrollTop:140},composer:{focus(){}}};state.service={username:'alice'};
 state.mode='library';state.projectDirectories=[{id:'p',name:'项目甲',category:'项目原件'},{id:'q',name:'项目乙',category:'项目原件'}];
 state.projectFolders=[{id:'f',project_id:'p',name:'二级',parent_id:''},{id:'g',project_id:'p',name:'三级',parent_id:'f'}];
 state.cloudDocuments=[{id:'a',title:'A',can_read:true,state:'ready',category:'项目原件',knowledge_project_id:'p',folder_id:'g'}];
 state.loadChatHistory=()=>{};return {state,notices,saved};
}
test('arrow navigation immediately opens exactly one directory and clears obsolete search mode',()=>{
 const{state:s}=fixture();s.searchMode='content';s.openDirectory(s.projectDirectories[0],'g');
 assert.equal(s.mode,'library');assert.equal(s.activeFolderId,'g');assert.equal(s.searchMode,'metadata');assert.equal(s.visibleFolders.length,0);assert.equal(s.filteredDocuments.length,1);
 s.goUpDirectory();assert.equal(s.activeFolderId,'f');s.goUpDirectory();assert.equal(s.activeFolderId,'');s.goUpDirectory();assert.equal(s.activeProjectId,'');
});
test('every category entry leaves body-search state and stale project scope',()=>{
 const{state:s}=fixture();s.activeProjectId='p';s.activeFolderId='g';s.searchMode='content';s.selectCategory('研究成果');
 assert.equal(s.searchMode,'metadata');assert.equal(s.activeProjectId,'');assert.equal(s.category,'研究成果');assert.equal(s.projectDisplay,'projects');
 s.searchMode='content';s.selectFailed();assert.equal(s.searchMode,'metadata');assert.equal(s.statusFilter,'failed');assert.equal(s.projectDisplay,'files');
});
test('project selection resolves a union, enters chat, and returns to the exact prior folder and filters',async()=>{
 const{state:s,saved}=fixture();s.activeProjectId='p';s.activeFolderId='g';s.projectDisplay='contents';s.query='A';s.libraryLayout='list';s.selectedProjectIds=['q'];
 let body;s.apiFetch=async(_url,options)=>{body=JSON.parse(options.body);return {ok:true,json:async()=>({document_ids:['a'],document_count:1,skipped_count:0})}};
 await s.askLibrary();assert.deepEqual(body.project_ids,['q']);assert.equal(s.mode,'chat');assert.equal(s.returnLocation.view.activeFolderId,'g');assert.ok(saved['companyKnowledgeReturn:alice']);
 s.query='changed';await s.returnToBrowse();assert.equal(s.mode,'library');assert.equal(s.query,'A');assert.equal(s.activeFolderId,'g');assert.equal(s.$refs.documentTable.scrollTop,140);
});
test('an empty directory result never opens an unfiltered chat',async()=>{
 const{state:s,notices}=fixture();s.activeProjectId='p';s.activeFolderId='f';s.projectDisplay='contents';
 s.apiFetch=async()=>({ok:false,json:async()=>({detail:'没有可检索资料'})});await s.askLibrary();assert.equal(s.mode,'library');assert.equal(s.selectionBusy,false);assert.match(notices[0],/没有可检索资料/);
});
test('a selection response arriving after category navigation cannot steal focus back into chat',async()=>{
 const{state:s}=fixture();s.selectedProjectIds=['p'];let resolve;const body=new Promise(r=>resolve=r);s.apiFetch=async()=>({ok:true,json:()=>body});
 const pending=s.askLibrary();await Promise.resolve();s.selectCategory('研究成果');resolve({document_ids:['a'],skipped_count:0});await pending;
 assert.equal(s.mode,'library');assert.equal(s.category,'研究成果');assert.equal(s.selectionBusy,false);
});
test('a removed source folder falls back to its project when returning',async()=>{
 const{state:s}=fixture();s.openDirectory(s.projectDirectories[0],'g');s.askSelection();s.projectFolders=[];await s.returnToBrowse();assert.equal(s.activeProjectId,'p');assert.equal(s.activeFolderId,'');
});
test('revoked evidence is retained as an invalid explicit scope instead of becoming an all-library question',async()=>{
 const{state:s}=fixture();s.mode='chat';s.selectedIds=['a'];s.loadProjectDirectories=async()=>{};s.loadNotes=()=>{};
 s.apiFetch=async()=>({ok:true,json:async()=>({documents:[],total_count:0})});await s.loadDocuments();
 assert.deepEqual(Array.from(s.selectedIds),['a']);assert.equal(s.chatScopeUnavailable,true);assert.match(s.chatError,/权限/);
});
test('project list is requested before the first document page resolves and remaining pages run in bounded parallel batches',async()=>{
 const{state:s}=fixture();let directories=false,release;const first=new Promise(r=>release=r);let active=0,max=0;
 s.loadProjectDirectories=async()=>{directories=true;};s.loadNotes=()=>{};
 s.apiFetch=async url=>{const page=+new URL('http://local'+url).searchParams.get('page_number');if(page===1)await first;active++;max=Math.max(max,active);await new Promise(setImmediate);active--;return {ok:true,json:async()=>({documents:[{id:String(page),category:'项目原件'}],total_count:501})}};
 const pending=s.loadDocuments();assert.equal(directories,true);release();await pending;assert.equal(s.cloudDocuments.length,6);assert.equal(max,3);
});
