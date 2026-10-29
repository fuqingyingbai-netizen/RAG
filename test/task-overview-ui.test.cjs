const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function context() {
  let definition;
  const app = {component(){return this;},use(){return this;},mount(){}};
  vm.runInNewContext(fs.readFileSync('frontend/script.js','utf8'), {
    Vue:{createApp(value){definition=value;return app;}},
    ElementPlus:{ElMessage:{error(){},success(){}}},
    AccountManagement:{},PersonalHome:{},CompanyKnowledge:{},ReportVersions:{},
    localStorage:{getItem(){return null;}}, Date, setInterval(){},clearInterval(){},
  });
  const state=definition.data();
  for(const [key,method] of Object.entries(definition.methods)) state[key]=method.bind(state);
  for(const [key,get] of Object.entries(definition.computed)) Object.defineProperty(state,key,{get:()=>get.call(state)});
  return state;
}
const heartbeat=(timestamp, extra={})=>({stage:'report',heartbeat:true,timestamp,...extra});

test('completed and stopped tasks never present historical heartbeats as stuck',()=>{
  const state=context(); state.nowTick=Date.parse('2026-10-26T06:00:00Z');
  const old=heartbeat('2026-10-26T01:00:00Z'); state.traceByProject[1]=[old];
  for(const status of ['completed','failed','paused','collecting']) {
    const project={id:1,status,is_running:false};
    assert.equal(state.heartbeatLabel(old,project),'历史记录');
    assert.equal(state.heartbeatStale(old,project),false);
    assert.equal(state.canPauseProject(project),false);
  }
  assert.equal(state.projectStateLabel({status:'collecting',is_running:false}),'待继续');
  assert.equal(state.traceFor({id:2,status:'collecting',is_running:false}).length,0);
});

test('only latest live heartbeat warns, based on actual backend activity',()=>{
  const state=context(); state.nowTick=Date.parse('2026-10-26T06:00:00Z');
  const project={id:1,status:'report_generating',is_running:true};
  const old=heartbeat('2026-10-26T05:40:00Z');
  const current=heartbeat('2026-10-26T05:59:55Z');
  state.traceByProject[1]=[old,{stage:'report',timestamp:'2026-10-26T05:59:50Z'},current];
  assert.equal(state.heartbeatLabel(old,project),'历史记录');
  assert.equal(state.heartbeatLabel(current,project),'活跃');
  state.traceByProject[1][1].timestamp='2026-10-26T05:54:59Z';
  assert.equal(state.heartbeatStale(current,project),true);
  state.traceByProject[1][1].timestamp='2026-10-26T05:59:20Z';
  current.timestamp='2026-10-26T05:58:20Z';
  assert.equal(state.heartbeatLabel(current,project),'进度连接延迟');
});

test('new init drops old run events and a late old response cannot bring them back',()=>{
  const state=context();
  const old={stage:'init',timestamp:'2026-10-25T00:00:00Z'};
  const next={stage:'init',timestamp:'2026-10-26T00:00:00Z'};
  state.mergeTraceList(1,[old,heartbeat('2026-10-25T00:10:00Z')]);
  state.mergeTraceList(1,[next,heartbeat('2026-10-26T00:00:10Z')]);
  state.mergeTraceList(1,[old,heartbeat('2026-10-25T00:10:00Z')]);
  assert.equal(state.traceByProject[1].length,2);
  assert.ok(state.traceByProject[1].every(e=>e.timestamp.startsWith('2026-10-26')));
});

test('persisted run identity and actual activity survive heartbeat-only compact previews',()=>{
  const state=context(); state.nowTick=Date.parse('2026-10-26T06:00:00Z');
  const current=heartbeat('2026-10-26T05:59:55Z');
  state.mergeTraceList(1,[current],{run_id:'new',run_started_at:'2026-10-26T05:00:00Z',last_backend_event_timestamp:'2026-10-26T05:50:00Z'});
  assert.equal(state.heartbeatStale(current,{id:1,is_running:true}),true);
  state.mergeTraceList(1,[heartbeat('2026-10-25T00:00:00Z')],{run_id:'old',run_started_at:'2026-10-25T00:00:00Z'});
  assert.equal(state.traceByProject[1].length,1);
  assert.equal(state.traceActivityByProject[1].run_id,'new');
});

test('worker states and source totals are independent of source search result size',()=>{
  const state=context();
  state.projects=[{status:'collecting',is_running:false},{status:'diagnostic',is_running:false},
    {status:'collecting',is_running:true},{status:'completed',is_running:false}];
  state.projectSummary={source_count:3001}; state.knowledgeResults=[];
  assert.equal(state.generatingCount,1); assert.equal(state.sourceCount,3001);
  state.knowledgeResults=[1,2]; assert.equal(state.sourceCount,3001);
  state.projectSummary={}; assert.equal(state.sourceCount,'—');
  state.taskStatusFilter='active'; assert.equal(state.filteredProjects.length,1);
  state.taskStatusFilter='waiting'; assert.equal(state.filteredProjects.length,1);
});

test('default artifacts show one latest report proposal diagnostic and history is fetched separately',async()=>{
  const state=context(), rows=[];
  for(let i=1;i<=40;i++) for(const type of ['desktop_report','proposal','report_quality_diagnostic','cleaned_facts'])
    rows.push({id:rows.length+1,artifact_type:type,version:i,created_at:'2026-10-26T00:00:00Z'});
  state.artifactsByProject[1]=rows;
  const visible=state.downloadableArtifacts({id:1});
  assert.equal(visible.length,3); assert.ok(visible.every(a=>a.version===40));
  state.runAction=async(key,label,action)=>action(); state.token='owner';
  let url;
  state.readJSON=async value=>{url=value;return {records:rows.slice(0,20),total:160,page:2};};
  await state.loadArtifactHistory({id:1},2);
  assert.equal(url,'/research/projects/1/artifact-history?page=2&page_size=20');
  assert.equal(state.artifactHistory[1].records.length,20);
  assert.equal(state.downloadableArtifacts({id:1}).length,3);
  state.readJSON=async()=>{state.token='different-account';return {records:rows};};
  state.artifactHistory={}; await state.loadArtifactHistory({id:1});
  assert.equal(state.artifactHistory[1],undefined);
});

test('compact source preview retains actual upload and total counts',()=>{
  const state=context();
  state.projectDetails[1]={source_count:3001,upload_count:7}; state.sourcesByProject[1]=[];
  assert.equal(state.uploadFileSummary({id:1}),'7 个文件（共 3001 个来源）');
  const html=fs.readFileSync('frontend/index.html','utf8');
  assert.ok(html.includes('heartbeatLabel(event, row)'));
  assert.ok(!html.includes('可能卡住'));
  assert.ok(html.includes('loadArtifactHistory(row, page)'));
});

test('closing history while its next page loads prevents the late response reopening it',async()=>{
  const state=context(); let release;
  state.token='owner'; state.runAction=async(key,label,action)=>action();
  state.readJSON=()=>new Promise(resolve=>{release=resolve;});
  state.artifactHistory[1]={records:[],page:1,total:22};
  const loading=state.loadArtifactHistory({id:1},2);
  state.closeArtifactHistory({id:1}); release({records:[{id:8}],page:2,total:22}); await loading;
  assert.equal(state.artifactHistory[1],undefined);
});
