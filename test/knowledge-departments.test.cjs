const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(){
 const notices=[],saved={};
 const c=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+';CompanyKnowledge',{
  AbortController,File,FormData,setTimeout,clearTimeout,sessionStorage:{getItem:k=>saved[k]??null,setItem:(k,v)=>saved[k]=v},
  ElementPlus:{ElMessage:Object.fromEntries(['info','error','warning','success'].map(k=>[k,m=>notices.push(m)]))}});
 const s=c.data();for(const[k,f]of Object.entries(c.methods))s[k]=f.bind(s);for(const[k,f]of Object.entries(c.computed))Object.defineProperty(s,k,{get:()=>f.call(s)});
 s.$refs={documentTable:{scrollTop:70},composer:{focus(){}}};s.$nextTick=async f=>f?.();s.service={username:'alice',configured:true,access_allowed:true};s.mode='library';
 s.projectDirectories=[{id:'m',name:'市场项目',department:'market',category:'项目原件',can_manage:true},{id:'p',name:'项目组项目',department:'project',category:'研究成果',can_manage:true},{id:'l',name:'旧项目',category:'项目原件'}];
 s.cloudDocuments=[{id:'a',title:'市场资料',department:'market',knowledge_project_id:'m',category:'项目原件',can_read:true,is_root:0,state:'ready'},
 {id:'b',title:'专家资料',department:'expert',category:'研究成果',can_read:true,is_root:1,state:'ready'},
 {id:'legacy',title:'历史资料',category:'项目原件',can_read:true,is_root:1,state:'ready'}];return{s,notices,saved};
}
test('department and existing category filters combine while total library remains complete',()=>{
 const{s}=fixture();s.openDepartment('market');assert.equal(s.mode,'library');assert.equal(s.visibleProjectDirectories.length,1);assert.equal(s.collectionDocuments.length,1);assert.equal(s.libraryCount,3);
 s.selectCategory('研究成果');assert.equal(s.visibleProjectDirectories.length,0);assert.equal(s.collectionDocuments.length,1);s.browseLibrary();assert.equal(s.departmentFilter,'');assert.equal(s.collectionDocuments.length,3);
 s.setDepartmentFilter('unassigned');assert.deepEqual(Array.from(s.filteredDocuments,d=>d.id),['legacy']);
});
test('department creation and nested upload inherit attribution without replacing original form fields',()=>{
 const{s}=fixture();s.openDepartment('market');s.startProjectEditor();assert.equal(s.projectForm.department,'market');assert.equal(s.projectForm.confidentiality,'internal');
 s.openDirectory(s.projectDirectories[0]);s.startUpload();assert.equal(s.uploadForm.department,'market');assert.equal(s.uploadTargetProjectId,'m');
 s.uploadTargetProjectId='p';s.setUploadTarget();assert.equal(s.uploadForm.department,'project');s.startProjectEditor(s.projectDirectories[2]);assert.equal(s.projectForm.department,'');
});
test('total-library new root uploads require attribution before any request is made',async()=>{
 const{s}=fixture();s.startUpload();s.stagedFiles=[new File(['sample'],'sample.txt')];let calls=0;s.apiFetch=async()=>{calls++;throw Error('unexpected write')};
 await s.uploadFiles();assert.match(s.uploadError,/所属部门/);assert.equal(calls,0);assert.equal(s.stagedFiles.length,1);assert.equal(s.uploadBusy,false);
});
test('department ask resolves explicit readable sources and returns to the original department',async()=>{
 const{s}=fixture();s.openDepartment('market');let sent;s.apiFetch=async(_url,options)=>{sent=JSON.parse(options.body);return{ok:true,json:async()=>({document_ids:['a'],document_count:1,skipped_count:0})}};
 await s.askLibrary();assert.equal(sent.department,'market');assert.deepEqual(sent.project_ids,[]);assert.equal(s.mode,'chat');assert.equal(s.scopeLabel,'总资料库 · 市场部 · 选中 1 份资料');
 s.departmentFilter='expert';await s.returnToBrowse();assert.equal(s.departmentFilter,'market');assert.deepEqual(Array.from(s.selectedIds),[]);
});
test('empty department cannot open an unrestricted chat and switching department clears prior selections',async()=>{
 const{s,notices}=fixture();s.openDepartment('policy');s.apiFetch=async()=>({ok:false,json:async()=>({detail:'没有可检索资料'})});await s.openChat();await new Promise(setImmediate);
 assert.equal(s.mode,'library');assert.match(notices.at(-1),/没有可检索资料/);s.selectedIds=['b'];s.selectedProjectIds=['p'];s.openDepartment('market');assert.equal(s.selectionCount,0);
});
test('clearing explicit department evidence cannot silently submit an all-library question',async()=>{
 const{s}=fixture();s.departmentFilter='market';s.mode='chat';s.draft='总结一下';let calls=0;s.apiFetch=async()=>{calls++};await s.sendQuestion();assert.equal(calls,0);assert.match(s.chatError,/部门资料范围/);
});
test('home and experience keep their existing global scope',()=>{
 const{s}=fixture();s.openDepartment('market');s.loadChatHistory=()=>{};s.browseCases();assert.equal(s.departmentFilter,'');assert.equal(s.currentCollection,'experience');s.openHome();assert.equal(s.mode,'home');assert.equal(s.departmentFilter,'');
});
test('late initialization cannot reapply a department after the user returns to the total catalogue',async()=>{
 const{s}=fixture();let finishHistory;const history=new Promise(resolve=>finishHistory=resolve);
 s.departmentEntry={department:'market'};s.restoreLibraryView=()=>{s.viewRestored=true};
 s.apiFetch=async()=>({ok:true,json:async()=>s.service});s.loadDocuments=async()=>{};s.loadMyProjects=async()=>{};s.loadAccessRequests=async()=>{};s.loadChatHistory=()=>history;
 const loading=s.loadService();await new Promise(setImmediate);assert.equal(s.departmentFilter,'market');s.browseLibrary();finishHistory();await loading;
 assert.equal(s.departmentFilter,'');s.startUpload();assert.equal(s.uploadForm.department,'');
});
test('department navigation during a slow status request survives initialization without restoring an old view',async()=>{
 const{s}=fixture();let finishStatus;const status=new Promise(resolve=>finishStatus=resolve);let restores=0;
 s.departmentEntry={department:'market'};s.restoreLibraryView=()=>{restores++;s.departmentFilter='market';s.viewRestored=true};
 s.apiFetch=()=>status;s.loadDocuments=async()=>{};s.loadMyProjects=async()=>{};s.loadAccessRequests=async()=>{};s.loadChatHistory=async()=>{};
 const loading=s.loadService();s.openDepartment('market');s.browseLibrary();finishStatus({ok:true,json:async()=>s.service});await loading;
 assert.equal(restores,0);assert.equal(s.departmentFilter,'');assert.equal(s.viewRestored,true);
});
test('initialization after department navigation refreshes conversation titles without restoring an unrelated scope',async()=>{
 const{s}=fixture();let finishProjects;const projects=new Promise(resolve=>finishProjects=resolve);let restored=0,listed=0;
 s.restoreLibraryView=()=>{s.viewRestored=true};s.apiFetch=async()=>({ok:true,json:async()=>s.service});
 s.loadDocuments=async()=>{};s.loadMyProjects=()=>projects;s.loadAccessRequests=async()=>{};
 s.loadChatHistory=async()=>{restored++;s.departmentFilter='';s.selectedIds=['foreign-session-file']};s.refreshChatSessions=async()=>{listed++};
 const loading=s.loadService();await new Promise(setImmediate);s.openDepartment('market');finishProjects();await loading;
 assert.equal(restored,0);assert.equal(listed,1);assert.equal(s.departmentFilter,'market');assert.equal(s.selectionCount,0);
});
