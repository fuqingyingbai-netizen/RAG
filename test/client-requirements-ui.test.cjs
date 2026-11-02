const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function fixture() {
  let definition; const notices=[];
  const app={component(){return this;},use(){return this;},mount(){}};
  vm.runInNewContext(fs.readFileSync('frontend/script.js','utf8'), {
    Vue:{createApp(d){definition=d;return app;}},AccountManagement:{},PersonalHome:{},ReportVersions:{},CompanyKnowledge:{},
    ElementPlus:{ElMessage:Object.fromEntries(['success','error','warning'].map(k=>[k,t=>notices.push([k,t])]))},
    localStorage:{getItem(){return null;},setItem(){},removeItem(){}},FormData,TextDecoder,
    setInterval(){return 1;},clearInterval(){},
  });
  const state=definition.data();
  for(const [k,v] of Object.entries(definition.methods))state[k]=v.bind(state);
  for(const [k,v] of Object.entries(definition.computed))Object.defineProperty(state,k,{get:()=>v.call(state)});
  state.token='owner';state.loadProjects=async()=>{};state.refreshVisibleTaskProgress=()=>{};
  return {state,notices};
}
test('step one saves a draft and customer requirements without starting generation',async()=>{
  const {state,notices}=fixture();state.form.projectName='测试任务';state.form.keyQuestions='报告范围';state.form.clientRequirements='关注交付计划';
  let requests=0;
  state.authFetch=async(url,options)=>{requests++;assert.equal(url,'/research/projects');
    const payload=JSON.parse(options.body);assert.equal(payload.metadata.client_requirements,'关注交付计划');assert.equal(payload.description,'报告范围');
    return {ok:true,json:async()=>({id:1,title:'测试任务',status:'draft'})};};
  state.runWorkflow=()=>assert.fail('saving a task must not start generation');
  await state.submitTask();
  assert.equal(requests,1);assert.equal(state.projects[0].status,'draft');assert.equal(state.taskCreateOpen,false);
  assert.equal(state.form.clientRequirements,'');assert.match(notices.at(-1)[1],/第一步已完成/);
});
test('requirements and report sources use separate upload endpoints and partial uploads retain only unconfirmed files',async()=>{
  const {state}=fixture();state.form.projectName='任务';
  const first=new File(['first'],'第一份.txt'),last=new File(['last'],'第二份.txt');
  state.clientRequirementFiles=[first,last];state.selectedFiles=[new File(['report'],'报告资料.txt')];
  state.authFetch=async()=>({ok:true,json:async()=>({id:1,status:'draft'})});
  const uploads=[];
  state.postTaskUpload=async(id,url,data)=>{uploads.push([url,data.get('file').name]);if(uploads.length===2)throw Error('synthetic upload failure');};
  state.readJSON=async()=>({intake:{client_requirements:'已保存'},client_requirement_files:[{id:4,title:first.name}]});
  await state.submitTask();
  assert.equal(state.projects.length,1);assert.equal(state.requirementsOpen,true);
  assert.equal(state.requirementsFiles.length,1);assert.equal(state.requirementsFiles[0].name,last.name);
  assert.equal(state.requirementsSources.length,1);assert.ok(uploads.every(([url])=>url.endsWith('/client-requirements')));
});
test('failed customer requirement read cannot overwrite saved requirements with a blank form',async()=>{
  const {state}=fixture();let writes=0;state.readJSON=async()=>{throw Error('read failed');};state.authFetch=async()=>{writes++;};
  await state.openClientRequirements({id:1});await state.saveClientRequirements();
  assert.equal(state.requirementsLoaded,false);assert.equal(writes,0);assert.equal(state.requirementsError,'read failed');
});
test('late customer requirement reads do not restore a former account',async()=>{
  const {state}=fixture();let resolve;state.readJSON=()=>new Promise(done=>{resolve=done;});
  const pending=state.openClientRequirements({id:1});state.token='another-owner';state.requirementsText='new account';
  resolve({intake:{client_requirements:'old private text'}});await pending;
  assert.equal(state.requirementsText,'new account');assert.equal(state.requirementsLoaded,false);
});
test('formal-plan request sends review notes without mutating report settings or starting research',async()=>{
  const {state}=fixture();state.reviewProjectId=1;state.projects=[{id:1,target_type:'industry',status:'completed',is_running:false}];
  state.reviewIntakes[1]={proposal_review_notes:'人工复核后缩减范围',special_requirements:'原报告重点',search_queries:['原关键词']};
  state.authFetch=async(url,options)=>{assert.match(url,/second-stage\/run\/stream$/);
    assert.deepEqual(JSON.parse(options.body),{proposal_review_notes:'人工复核后缩减范围'});
    return {ok:true};};
  state.readWorkflowEvents=async()=> 'result';state.refreshAfterWorkflow=async()=>{};
  await state.runSecondStage();assert.equal(state.secondStageRunning,false);
  assert.equal(state.reviewIntakes[1].special_requirements,'原报告重点');
});
