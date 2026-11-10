const test=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
function fixture(){
 const notices=[],saved={};const component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+'\nCompanyKnowledge;',{
  AbortController,File,FormData,clearTimeout,setTimeout,sessionStorage:{setItem:(k,v)=>saved[k]=v},
  ElementPlus:{ElMessage:Object.fromEntries(['info','warning','error','success'].map(k=>[k,v=>notices.push(v)]))}});
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

test('directory search includes descendants but never siblings or the project root',()=>{
 const{state:s}=fixture();s.projectFolders.push({id:'sibling',project_id:'p',parent_id:'',name:'同级分支'});
 s.cloudDocuments.push({id:'sibling-file',title:'same.txt',can_read:true,state:'ready',category:'项目原件',knowledge_project_id:'p',folder_id:'sibling'},
  {id:'root-file',title:'same.txt',can_read:true,state:'ready',category:'项目原件',knowledge_project_id:'p',folder_id:''});
 s.openDirectory(s.projectDirectories[0],'f');s.query='same';assert.equal(s.filteredDocuments.length,0);
 s.query='A';assert.deepEqual(Array.from(s.filteredDocuments,d=>d.id),['a']);
 s.query='三级';assert.deepEqual(Array.from(s.visibleFolders,f=>f.id),['g']);
 s.query='同级';assert.equal(s.visibleFolders.length,0);s.query='';assert.deepEqual(Array.from(s.visibleFolders,f=>f.id),['g']);
});

test('favorite counts follow the current library rather than all saved favorites',()=>{
 const{state:s}=fixture();s.cloudDocuments.push({id:'experience-file',title:'经验.txt',can_read:true,state:'ready',category:'项目经验'});
 s.favorites=['a','experience-file','removed-file'];assert.equal(s.collectionFavoritesCount,1);
 s.mode='cases';assert.equal(s.collectionFavoritesCount,1);s.favorites=['a'];assert.equal(s.collectionFavoritesCount,0);
});

test('my notes counts only personal experience and does not duplicate its published document',()=>{
 const{state:s}=fixture();s.projectDirectories.push({id:'xp',name:'我的经验',owner:'alice',category:'项目经验'});
 s.noteDrafts=[{id:'n',project_id:'xp',title:'我的笔记',created_by:'alice',folder_id:''}];
 s.cloudDocuments.push({id:'published',note_id:'n',title:'我的笔记',category:'项目经验',is_owner:true,state:'ready'},
  {id:'capture',title:'随手记录',category:'项目经验',is_owner:true,state:'failed'},
  {id:'other-xp',title:'他人经验',category:'项目经验',is_owner:false,state:'ready'});
 s.browseMyNotes();assert.equal(s.currentCollection,'experience');assert.equal(s.myExperienceCount,2);
 assert.deepEqual(Array.from(s.visibleNoteDrafts,n=>n.id),['n']);assert.deepEqual(Array.from(s.filteredDocuments,d=>d.id),['capture']);
 s.selectFailed();assert.equal(s.currentCollection,'experience');assert.deepEqual(Array.from(s.filteredDocuments,d=>d.id),['capture']);
});

test('my notes default question uses personal experience scope rather than the entire library',async()=>{
 const{state:s}=fixture();s.cloudDocuments.push({id:'mine',category:'项目经验',is_owner:true,can_read:true,state:'ready'});s.browseMyNotes();await s.askLibrary();assert.equal(s.chatScope,'my-experience');assert.equal(s.mode,'chat');assert.equal(s.returnLocation.view.mineOnly,true);assert.equal(s.selectedIds.length,0);
});

test('reupload pins original project folder and filename despite other current navigation',async()=>{
 const{state:s}=fixture();s.projectDirectories[0].can_manage=true;s.activeProjectId='q';
 const doc={id:'failed',title:'original.txt',state:'failed',can_manage:true,has_original:true,knowledge_project_id:'p',folder_id:'g',category:'项目原件'};
 s.startReupload(doc);assert.equal(s.uploadTargetProjectId,'p');assert.equal(s.uploadTargetFolderId,'g');
 s.uploadTargetProjectId='q';s.uploadTargetFolderId='';s.stagedFiles=[new File(['new content'],'local-name.txt')];
 let sent;s.apiFetch=async(url,options)=>{sent={url,form:options.body};return {ok:true,json:async()=>({...doc,id:'new-version',state:'ready'})}};
 s.loadDocuments=async()=>{};s.loadMyProjects=async()=>{};await s.uploadFiles();
 assert.equal(sent.form.get('project_id'),'p');assert.equal(sent.form.get('folder_id'),'g');assert.equal(sent.form.get('file').name,'original.txt');
});

test('missing original uses the repair route and readonly reupload stays blocked',async()=>{
 const{state:s}=fixture();s.projectDirectories[0].can_manage=true;
 const doc={id:'missing',title:'original.txt',state:'failed',can_manage:true,has_original:false,knowledge_project_id:'p',folder_id:'g',category:'项目原件'};
 s.startReupload(doc);s.stagedFiles=[new File(['repaired'],'original.txt')];let sent;
 s.apiFetch=async(url,options)=>{sent={url,form:options.body};return {ok:true,json:async()=>({...doc,has_original:true,state:'ready'})}};
 s.loadDocuments=async()=>{};s.loadMyProjects=async()=>{};await s.uploadFiles();assert.equal(sent.url,'/company-knowledge/documents/missing/original');assert.equal(sent.form.get('confirmation'),'missing');
 s.uploadOpen=false;s.startReupload({...doc,can_manage:false});assert.equal(s.uploadOpen,false);
});

test('owned project root and nested folders keep creation and upload in the current location',async()=>{
 const{state:s}=fixture();s.projectDirectories[0].can_manage=true;s.openDirectory(s.projectDirectories[0]);
 const requests=[];s.apiFetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({id:'created'})}};
 s.loadProjectDirectories=async()=>{};
 for(const parent of ['', 'f', 'g']){
  s.openDirectory(s.projectDirectories[0],parent);s.startFolderEditor();assert.equal(s.folderEditorOpen,true);s.folderName='新增目录';await s.saveFolder();
  assert.equal(requests.at(-1).url,'/company-knowledge/projects/p/folders');assert.equal(requests.at(-1).body.parent_id,parent);
  s.startUpload();assert.equal(s.uploadOpen,true);assert.equal(s.uploadTargetProjectId,'p');assert.equal(s.uploadTargetFolderId,parent);s.uploadOpen=false;
 }
});

test('readonly project cannot open creation or silently redirect an upload to the library root',async()=>{
 const{state:s,notices}=fixture();s.projectDirectories[0].can_manage=false;s.openDirectory(s.projectDirectories[0],'g');
 let writes=0;s.apiFetch=async()=>{writes++;throw Error('unexpected write')};s.startFolderEditor();s.startUpload();await s.saveFolder();
 assert.equal(s.folderEditorOpen,false);assert.equal(s.uploadOpen,false);assert.equal(writes,0);assert.equal(notices.length,2);assert.ok(notices.every(message=>message.includes('只读')));
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

test('private draft alone cannot silently expand a personal question to all experience',async()=>{
 const{state:s,notices}=fixture();s.browseMyNotes();await s.askLibrary();assert.equal(s.mode,'cases');assert.match(notices[0],/暂无可检索资料/);
});

test('experience note list follows its selected category and exposes only readable current published documents',()=>{
 const{state:s}=fixture();s.mode='cases';s.projectDirectories.push({id:'xp',name:'经验',owner:'alice',category:'项目经验'});s.noteDrafts=[{id:'n',title:'项目经验笔记',project_id:'xp'}];
 s.cloudDocuments.push({id:'published',note_id:'n',category:'项目经验',can_read:true,is_current:1},{id:'old',note_id:'n',category:'项目经验',can_read:true,is_current:0},{id:'locked',note_id:'private',category:'项目经验',can_read:false});
 s.category='案例复盘';assert.equal(s.visibleNoteDrafts.length,0);s.category='项目经验';assert.equal(s.visibleNoteDrafts.length,1);
 assert.equal(s.publishedNoteDocuments.n.id,'published');assert.equal(s.publishedNoteDocuments.private,undefined);s.category='案例复盘';s.browseMyNotes();assert.equal(s.category,'全部资料');assert.equal(s.visibleNoteDrafts.length,1);s.favorites=['published'];assert.equal(s.collectionFavoritesCount,1);
});

test('personal notes share one sorted paginated list with files and each publication appears once',()=>{
 const{state:s}=fixture();s.projectDirectories.push({id:'xp',name:'我的经验',owner:'alice',category:'项目经验'});
 s.noteDrafts=[{id:'draft',project_id:'xp',title:'B 草稿',updated_at:'2026-11-10'},{id:'published',project_id:'xp',title:'C 图文',updated_at:'2026-11-09',published_revision:1}];
 s.cloudDocuments.push({id:'note-doc',note_id:'published',title:'C 图文.docx',category:'项目经验',can_read:true,is_owner:true,is_current:1,state:'ready'},
 {id:'file',title:'A 文件',category:'项目经验',can_read:true,is_owner:true,state:'ready'});
 s.browseMyNotes();s.sortOrder='title';s.libraryPageSize=2;
 assert.equal(s.myExperienceCount,3);assert.equal(s.libraryPageRange.total,3);assert.equal(s.libraryPageCount,2);
 assert.deepEqual(Array.from(s.pagedLibraryRows,row=>row.title),['A 文件','B 草稿']);assert.equal(s.pagedLibraryRows[1].document,undefined);
 s.libraryPage=2;assert.equal(s.pagedLibraryRows.length,1);assert.equal(s.pagedLibraryRows[0].document.id,'note-doc');assert.equal(s.libraryPageRange.end,3);
 assert.equal(s.libraryRows.filter(row=>row.document?.id==='note-doc').length,1);
});
