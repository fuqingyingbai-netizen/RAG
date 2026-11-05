const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let definition, available = true;
const registry = JSON.parse(fs.readFileSync(path.join(__dirname, '../backend/company_chapters.json'), 'utf8'));
const config = {version:'test-template-v1', chapters:registry.chapters.filter(c=>c.chapter<=12).map(c=>({
  chapter:c.chapter,value:c.id,label:c.chapter+'. '+c.short_title,title:c.title,selectable:c.selectable,mode:c.mode
})), defaults:registry.chapters.filter(c=>c.selectable).map(c=>c.id)};
const app = {component(){return this;},use(){return this;},mount(){}};
const warnings=[];
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/script.js'),'utf8'), {
  Vue:{createApp(value){definition=value;return app;}},
  ElementPlus:{ElMessage:{warning(v){warnings.push(v);},success(){},error(v){throw Error(v);},info(){}}},
  CompanyKnowledge:{},AccountManagement:{},PersonalHome:{},ReportVersions:{},
  localStorage:{getItem(){return null;},setItem(){},removeItem(){}},Date,JSON,TextDecoder,
  setInterval(){return 1;},clearInterval(){},
  fetch:async url=>{assert.equal(url,'/research/company-chapters');return {ok:available,json:async()=>config};}
});
const state=definition.data();
for(const [key,method] of Object.entries(definition.methods)) state[key]=method.bind(state);
Object.defineProperty(state,'ddTypes',{get(){return definition.computed.ddTypes.call(state);}});
const calls=[];
const project={id:1,title:'公司章节测试',target_name:'示例制造有限公司',target_type:'company'};
state.authFetch=async(url,options)=>{
  calls.push({url,payload:options?.body?JSON.parse(options.body):null});
  return {ok:true,json:async()=>project,body:{getReader(){let done=false;return {async read(){
    if(done)return {done:true}; done=true;
    return {done:false,value:Buffer.from('data: '+JSON.stringify({type:'result',project,artifacts:[]})+'\n\n')};
  }};}}};
};
state.loadProjects=state.loadProjectDetail=async()=>{};
state.switchView=()=>{};
state.selectedFiles=[];
state.form.projectName=project.title;
state.form.companyName=project.target_name;
(async()=>{
  available=false;
  await state.submitTask();
  assert.equal(calls.length,0);assert.ok(warnings.length);
  available=true;
  assert.equal(await state.loadCompanyChapters(),true);
  assert.equal(state.modulesByTarget.company.length,12);
  assert.equal(state.modulesByTarget.company.filter(c=>c.selectable).length,10);
  assert.equal(JSON.stringify(state.form.modules),JSON.stringify(config.defaults));
  state.form.modules=['company.ch05','company.ch09'];
  await state.submitTask();
  const saved=calls.find(c=>c.url==='/research/projects').payload.metadata;
  assert.equal(saved.company_template_version,config.version);
  assert.equal(JSON.stringify(saved.focus_modules),'["company.ch05","company.ch09"]');
  await state.runExistingWorkflow(project,saved);
  const fresh=calls.find(c=>c.url.endsWith('/run/stream')).payload;
  assert.equal(fresh.company_template_version,config.version);
  assert.equal(JSON.stringify(fresh.focus_modules),JSON.stringify(saved.focus_modules));
  await state.runExistingWorkflow(project,{...saved,focus_modules:[]});
  assert.equal(calls.at(-1).payload.company_template_version,config.version);
  assert.equal(JSON.stringify(calls.at(-1).payload.focus_modules),'[]');
  state.projects=[project];state.reviewProjectId=project.id;
  state.projectDetails[project.id]={intake:saved};
  await state.runSecondStage();
  assert.equal(calls.find(c=>c.url.includes('/second-stage/')).payload.company_template_version,config.version);
  await state.runExistingWorkflow(project,{focus_modules:['收入情况']});
  assert.equal(calls.at(-1).payload.company_template_version,undefined);
  state.form.modules=[];
  await state.loadCompanyChapters();
  assert.equal(JSON.stringify(state.form.modules),'[]'); // reload preserves explicit empty focus
  assert.equal(JSON.stringify(state.companyRunFields('person')),'{}');
  definition.watch['form.targetType'].call(state,'person');
  assert.ok(!state.form.modules.includes('company.ch02'));
  definition.watch['form.targetType'].call(state,'company');
  assert.equal(JSON.stringify(state.form.modules),JSON.stringify(config.defaults));
  console.log('Company chapter load, create, run, resume, review and legacy isolation passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
