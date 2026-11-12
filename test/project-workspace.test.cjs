const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function context(){
  let definition;const storage=new Map(),notices=[];
  const app={component(){return this;},use(){return this;},mount(){}};
  const sandbox={Vue:{createApp(value){definition=value;return app;}},ElementPlus:{ElMessage:Object.fromEntries(['error','success','warning','info'].map(k=>[k,text=>notices.push([k,text])])),ElMessageBox:{confirm:async()=>{}}},AccountManagement:{},PersonalHome:{},CompanyKnowledge:{},ReportVersions:{},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},Date,AbortController,setTimeout,clearTimeout,TextDecoder,setInterval(){return 1;},clearInterval(){}};
  vm.createContext(sandbox);
  for(const file of ['project-workspace.js','script.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend',file),'utf8'),sandbox);
  const state=definition.data();for(const [k,f]of Object.entries(definition.methods))state[k]=f.bind(state);
  for(const [k,f]of Object.entries(definition.computed))Object.defineProperty(state,k,{get:()=>f.call(state)});
  state.currentUser={id:7,username:'analyst',role:'user'};state.token='account-7';state.$nextTick=async cb=>cb?.();state.$refs={};
  return {state,storage,notices};
}

test('business categories use persisted research_type while legacy single-target projects remain available',()=>{
  const {state}=context();state.activeView='tasks';
  state.projects=[{id:1,target_type:'person',status:'draft'},{id:2,target_type:'industry',status:'draft'},{id:3,target_type:'company',status:'draft'}];
  state.workspaceIntakes[3]={research_type:'AI公司尽调'};
  assert.deepEqual(state.projects.map(p=>state.projectFamily(p)),['background','research','ai']);
  state.workspaceFamily='background';assert.equal(state.filteredProjects.length,1);
  state.workspaceFamily='ai';assert.equal(state.filteredProjects[0].id,3);
  state.workspaceTypeFilter='VC项目';assert.equal(state.filteredProjects.length,0);
  state.resetTaskFilters();assert.equal(state.workspaceFamily,'ai');assert.equal(state.workspaceTypeFilter,'');
});

test('metadata errors are visible in all projects and never silently assigned to another category',async()=>{
  const {state}=context();state.readJSON=async url=>{if(url==='/research/projects')return {projects:[{id:1,target_type:'company'}]};throw Error('offline');};
  await state.loadProjects();assert.equal(state.projects.length,1);assert.equal(state.projectFamily(state.projects[0]),'unclassified');assert.equal(state.workspaceMetaLoading,false);
  state.readJSON=async url=>url==='/research/projects'?{projects:state.projects}:{intake:{research_type:'AI专项研究'}};
  await state.loadProjects();assert.equal(state.projectFamily(state.projects[0]),'ai');assert.equal(Object.keys(state.workspaceMetaErrors).length,0);
});

test('a late metadata response cannot populate the next account',async()=>{
  const {state}=context();let release;const pending=new Promise(resolve=>release=resolve);
  state.readJSON=async url=>url==='/research/projects'?{projects:[{id:1,target_type:'company'}]}:pending;
  const loading=state.loadProjects();await new Promise(setImmediate);state.token='different-account';release({intake:{research_type:'VC项目'}});await loading;
  assert.equal(state.workspaceIntakes[1],undefined);
});

test('one primary business type and multiple focus areas create exactly one server project through the existing endpoint',async()=>{
  const {state}=context();state.openProjectCreate('background');Object.assign(state.form,{projectName:'背景调查',companyName:'目标公司',ddType:'VC项目',focusAreas:['创始人背景','高管背景'],keyQuestions:'核对公开任职经历'});
  let payload,calls=0;const project={id:9,title:'背景调查',target_name:'目标公司',target_type:'company',status:'draft'};
  state.authFetch=async(url,options)=>{assert.equal(url,'/research/projects');assert.equal(options.method,'POST');payload=JSON.parse(options.body);calls++;return {ok:true,json:async()=>project};};
  state.switchView=()=>{state.taskCreateOpen=false;};state.loadProjects=async()=>{};
  await state.submitTask();assert.equal(calls,1);assert.equal(payload.target_name,'目标公司');assert.equal(payload.target_type,'company');assert.equal(payload.metadata.research_type,'VC项目');
  assert.deepEqual(payload.metadata.focus_questions,['核对公开任职经历','重点模块：创始人背景','重点模块：高管背景']);assert.ok(!('tasks' in payload));assert.ok(!('targets' in payload));
});

test('AI application drafts never call a server endpoint, retain their type when reopened and remain account scoped',async()=>{
  const {state,storage}=context();state.openProjectCreate('ai');Object.assign(state.form,{projectName:'知识库建设',companyName:'内部检索',ddType:'AI应用建设'});
  state.authFetch=()=>{throw Error('Unexpected server write');};state.switchView=()=>{};
  await state.submitTask();assert.equal(state.localProjectDrafts.length,1);assert.ok(storage.has('project-workspace:drafts:analyst'));
  const draft=state.localProjectDrafts[0];state.editLocalProjectDraft(draft);assert.equal(state.form.ddType,'AI应用建设');
  state.currentUser={username:'other'};state.loadLocalProjectDrafts();assert.equal(state.localProjectDrafts.length,0);
  state.currentUser={username:'analyst'};state.loadLocalProjectDrafts();assert.equal(state.localProjectDrafts.length,1);
});

test('project details expand on the unified list and category navigation does not force a workflow stage',async()=>{
  const {state}=context();state.activeView='tasks';state.projects=[{id:1}];let expanded=false;
  state.$refs.taskTable={toggleRowExpansion(p,value){assert.equal(p.id,1);expanded=value;}};state.loadProjectDetail=async()=>({});
  await state.viewProject(state.projects[0]);assert.equal(expanded,true);
  state.loadProjects=async()=>{};state.refreshVisibleTaskProgress=()=>{};state.switchView('research');assert.equal(state.activeView,'tasks');assert.equal(state.workspaceFamily,'research');
});
