const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function deferred() { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; }
const tick = () => new Promise(setImmediate);
function app(fetcher) {
  let definition, nextTimer=0, downloads=0;
  const notices=[], timers=new Map(), expansions=[];
  const component={component(){return this;},use(){return this;},mount(){}};
  vm.runInNewContext(fs.readFileSync('frontend/script.js','utf8'),{
    Vue:{createApp(value){definition=value;return component;}},
    fetch:fetcher,
    AccountManagement:{},PersonalHome:{},ReportVersions:{},CompanyKnowledge:{},
    localStorage:{getItem(){return null;},setItem(){},removeItem(){}},
    ElementPlus:{ElMessage:Object.fromEntries(['success','error','warning','info'].map(kind=>[kind,text=>notices.push([kind,text])]))},
    setTimeout(fn,ms){const id=++nextTimer;timers.set(id,{fn,ms});return id;},clearTimeout(id){timers.delete(id);},
    setInterval(){return 1;},clearInterval(){},AbortController,TextDecoder,
    FormData:class{append(){}},
    URL:{createObjectURL(){return 'blob:test';},revokeObjectURL(){}},
    document:{body:{appendChild(){}},createElement(){return {click(){downloads++;},remove(){}};}},
  });
  const state=definition.data();
  for(const [name,method] of Object.entries(definition.methods))state[name]=method.bind(state);
  for(const [name,get] of Object.entries(definition.computed))Object.defineProperty(state,name,{get:get.bind(state),configurable:true});
  state.token='owner';state.currentUser={username:'owner',role:'user'};
  state.$refs={reviewTable:{toggleRowExpansion(p,expanded){expansions.push([p.id,expanded]);}},taskTable:{toggleRowExpansion(p,expanded){expansions.push([p.id,expanded]);}}};
  state.$nextTick=callback=>{callback?.();return Promise.resolve();};
  return {state,notices,timers,expansions,downloads:()=>downloads};
}
function json(data,ok=true){return {ok,json:async()=>data};}

function originalTraceMerge(initial,incoming) {
  let list=[...initial];const key=e=>[e.timestamp||'',e.stage||'',e.agent||'',e.label||'',e.detail||'',e.status||'',e.section||''].join('|');
  for(const event of incoming){if(!list.some(row=>key(row)===key(event)))list.push(event);list=list.slice(-500);}
  return list;
}

test('batch progress merge preserves order, bounded deduplication and eviction semantics',()=>{
  const event=i=>({timestamp:String(i),stage:i%3?'report':'cleaning',detail:'event '+i,status:'done'});
  for(const [size,count]of [[0,20],[500,400],[550,40],[500,1100]]){
    const {state}=app(),initial=Array.from({length:size},(_,i)=>event(i%510));
    const incoming=Array.from({length:count},(_,i)=>event((i*97)%850));
    const expected=originalTraceMerge(initial,incoming);
    state.traceByProject[1]=initial;state.mergeTraceList(1,incoming);
    assert.equal(JSON.stringify(state.traceByProject[1]),JSON.stringify(expected));
    assert.ok(state.traceByProject[1].length<=500);
  }
});

test('repeated progress snapshots do not rescan long event details for each incoming row',()=>{
  const {state}=app();let reads=0;
  const events=Array.from({length:300},(_,i)=>({timestamp:String(i),get detail(){reads++;return 'long synthetic detail'.repeat(100);}}));
  state.traceByProject[1]=[...events];state.mergeTraceList(1,events);
  assert.ok(reads<=600);assert.equal(state.traceByProject[1].length,300);
  const before=state.traceByProject[1];state.mergeTraceList(1,[]);assert.equal(state.traceByProject[1],before);
});

test('account change during a response body cannot restore user data even if a legacy caller catches JSON errors',async()=>{
  const body=deferred(),{state}=app(async()=>({ok:true,status:200,headers:{get:()=>null},json:()=>body.promise}));
  const response=await state.authFetch('/research/projects/1/artifacts');
  const pending=response.json().catch(()=>[]);
  state.handleLogout();body.resolve([{content:'OLD_PRIVATE_BODY'}]);await pending;
  assert.throws(()=>response.ok,/账号已变更/);
  assert.equal(Object.keys(state.artifactsByProject).length,0);
});

test('account change while profile JSON waits never restores the former account',async()=>{
  const body=deferred(),{state}=app(async()=>({ok:true,status:200,headers:{get:()=>null},json:()=>body.promise}));
  const pending=state.fetchMe();await tick();state.handleLogout();body.resolve({username:'old-private'});
  await assert.rejects(pending,/账号已变更/);assert.equal(state.currentUser,null);
});

test('caller can cancel a body read even when transport ignores abort and the deadline is removed',async()=>{
  const {state,timers}=app(),body=deferred(),controller=new AbortController();let signal;
  state.authFetch=async(url,options)=>{signal=options.signal;return {ok:true,json:()=>body.promise};};
  const pending=state.readJSON('/research/home','首页读取失败',30000,{signal:controller.signal});
  await tick();controller.abort();await assert.rejects(pending,error=>error.name==='AbortError');
  assert.equal(signal.aborted,true);assert.equal(timers.size,0);body.resolve({});
});

test('already cancelled reads never send a request',async()=>{
  const {state}=app(),controller=new AbortController();let calls=0;
  state.authFetch=async()=>{calls++;};controller.abort();
  await assert.rejects(state.readJSON('/research/home','首页读取失败',30000,{signal:controller.signal}),error=>error.name==='AbortError');
  assert.equal(calls,0);
});

test('read failures explain network or unreadable service responses without exposing raw HTML or parser internals',async()=>{
  const {state}=app();
  state.authFetch=async()=>{throw new TypeError('Failed to fetch');};
  await assert.rejects(state.readJSON('/research/home','首页读取失败'),/首页读取失败：网络连接失败/);
  state.authFetch=async()=>({ok:false,json:async()=>{throw new SyntaxError('PRIVATE_HTML_FRAGMENT');}});
  await assert.rejects(state.readJSON('/research/home','首页读取失败'),error=>/服务暂时不可用/.test(error.message)&&!error.message.includes('PRIVATE_'));
  state.authFetch=async()=>({ok:true,json:async()=>{throw new SyntaxError('PRIVATE_HTML_FRAGMENT');}});
  await assert.rejects(state.readJSON('/research/home','首页读取失败'),/响应内容暂时无法读取/);
  state.authFetch=async()=>({ok:false,json:async()=>null});
  await assert.rejects(state.readJSON('/research/home','首页读取失败'),/首页读取失败/);
});

function eventResponse(chunks) {
  let reads=0,cancelled=false,released=false;
  return {response:{body:{getReader(){return {
    async read(){return reads<chunks.length?{done:false,value:chunks[reads++]}:{done:true};},
    async cancel(){cancelled=true;},releaseLock(){released=true;},
  };}}},closed:()=>cancelled&&released};
}

test('workflow events survive UTF8 byte boundaries, CRLF boundaries and SSE comments and fields',async()=>{
  const {state}=app(),events=[];
  const bytes=Buffer.from(': keepalive\r\nevent: progress\r\ndata:{"type":"trace_step",\r\ndata: "label":"正在精洗"}\r\n\r\ndata: {"type":"result"}\r\n\r\n');
  const stream=eventResponse(Array.from(bytes,value=>Uint8Array.of(value)));
  assert.equal(await state.readWorkflowEvents(stream.response,state.token,event=>events.push(event)),'result');
  assert.equal(events.length,2);assert.equal(events[0].label,'正在精洗');assert.equal(stream.closed(),true);
});

test('a final confirmed event without a trailing separator is processed before EOF',async()=>{
  const {state}=app(),stream=eventResponse([Buffer.from('data: {"type":"result"}')]);let result;
  assert.equal(await state.readWorkflowEvents(stream.response,state.token,event=>{result=event;}),'result');
  assert.equal(result.type,'result');assert.equal(stream.closed(),true);
});

test('completion feedback does not wait for the transport to close and releases its reader',async()=>{
  const {state}=app();let reads=0,cancelled=false;
  const response={body:{getReader(){return {read(){reads++;return Promise.resolve({done:false,value:Buffer.from('data: {"type":"result"}\n\n')});},async cancel(){cancelled=true;},releaseLock(){}};}}};
  assert.equal(await state.readWorkflowEvents(response,state.token,()=>{}),'result');
  assert.equal(reads,1);assert.equal(cancelled,true);
});

test('late workflow events from the old account never restore its projects or artifacts',async()=>{
  const {state}=app(),waiting=deferred();let cancelled=false,events=0;
  const response={body:{getReader(){return {read:()=>waiting.promise,async cancel(){cancelled=true;},releaseLock(){}};}}};
  const pending=state.readWorkflowEvents(response,state.token,()=>{events++;});
  state.handleLogout();waiting.resolve({done:false,value:Buffer.from('data: {"type":"result"}\n\n')});
  assert.equal(await pending,'account_changed');assert.equal(events,0);assert.equal(cancelled,true);
});

test('stream errors release the reader and EOF alone never claims a successful rerun',async()=>{
  const {state}=app(),stream=eventResponse([Buffer.from('data: {"type":"error","content":"Synthetic failure"}\n\n')]);
  await assert.rejects(state.readWorkflowEvents(stream.response,state.token,event=>{if(event.type==='error')throw new Error(event.content);}),/Synthetic failure/);
  assert.equal(stream.closed(),true);
  state.authFetch=async()=>({ok:true,...eventResponse([]).response});state.refreshAfterWorkflow=async()=>{};
  await assert.rejects(state.runExistingWorkflow({id:1,target_type:'industry'},{}),/尚未确认任务完成/);
});

test('overlapping progress timers share one read and recover after a failed poll',async()=>{
  const {state}=app(),first=deferred();let calls=0;
  state.authFetch=async()=>{calls++;return first.promise;};
  const project={id:1,status:'cleaning'};
  const a=state.refreshProjectProgress(project),b=state.refreshProjectProgress(project);
  assert.equal(a,b);await tick();assert.equal(calls,1);
  first.reject(new Error('Synthetic read failed'));
  await Promise.all([assert.rejects(a,/Synthetic/),assert.rejects(b,/Synthetic/)]);
  assert.equal(Object.keys(state.actionErrors).length,0);
  state.authFetch=async()=>{calls++;return json({project:{id:1,status:'cleaning'},trace:[]});};
  await state.refreshProjectProgress(project);assert.equal(calls,2);
});

test('rerun parameter timeout clears waiting feedback without ever starting research',async()=>{
  const {state,timers,notices}=app(),body=deferred();let runs=0;
  state.authFetch=async()=>({ok:true,json:()=>body.promise});
  state.runExistingWorkflow=async()=>{runs++;};
  const pending=state.rerunProject({id:1});await tick();
  assert.equal(state.startingProjects[1],true);
  assert.match(state.pendingActions['rerun:1'].phase,/读取重跑参数/);
  const timer=[...timers.values()].find(item=>item.ms===30000);assert.ok(timer);timer.fn();
  await pending;
  assert.equal(runs,0);assert.equal(state.startingProjects[1],undefined);
  assert.equal(state.pendingActions['rerun:1'],undefined);
  assert.match(state.actionErrors['rerun:1'].message,/加载重跑参数失败.*读取超时/);
  assert.match(state.actionErrors['rerun:1'].advice,/本次未启动研究/);
  assert.match(state.actionErrors['rerun:1'].advice,/读取成功后提交研究请求/);
  assert.ok(notices.some(([kind,text])=>kind==='error'&&/未启动任何研究任务/.test(text)));
  body.resolve({intake:{}});await tick();assert.equal(runs,0);
});

test('rerun feedback advances from parameters to submission and confirmed background processing',async()=>{
  const {state}=app(),body=deferred(),connected=deferred(),running=deferred();
  state.authFetch=async()=>({ok:true,json:()=>body.promise});
  state.refreshProjectProgress=async()=>{};
  state.runExistingWorkflow=async(project,intake,onConnected)=>{
    assert.equal(intake.marker,'saved');await connected.promise;onConnected();await running.promise;
  };
  const pending=state.rerunProject({id:1});await tick();
  assert.match(state.pendingActions['rerun:1'].phase,/读取重跑参数/);
  assert.equal(state.pendingActions['rerun:1'].readOnly,true);
  body.resolve({intake:{marker:'saved'}});await tick();
  assert.match(state.pendingActions['rerun:1'].phase,/提交重跑请求/);
  assert.equal(state.pendingActions['rerun:1'].readOnly,false);
  connected.resolve();await tick();assert.match(state.pendingActions['rerun:1'].phase,/后台执行/);
  running.resolve();await pending;assert.equal(state.pendingActions['rerun:1'],undefined);
});

test('unconfirmed rerun submission advises checking persisted status instead of read-only retry',async()=>{
  const {state}=app();state.authFetch=async()=>({ok:true,json:async()=>({intake:{}})});
  state.runExistingWorkflow=async()=>{throw new Error('Synthetic submission disconnected');};
  await state.rerunProject({id:1});
  assert.match(state.actionErrors['rerun:1'].advice,/先核对任务或资料的保存状态/);
  assert.doesNotMatch(state.actionErrors['rerun:1'].advice,/不会启动研究/);
});

test('old rerun completion cannot clear a new account busy flag or display its failure',async()=>{
  const {state,notices}=app(),body=deferred();let runs=0;
  state.authFetch=async()=>({ok:true,json:()=>body.promise});
  state.runExistingWorkflow=async()=>{runs++;};
  const pending=state.rerunProject({id:1});await tick();
  state.handleLogout();state.token='another';state.startingProjects[1]=true;
  body.resolve({intake:{private:'old'}});await pending;
  assert.equal(runs,0);assert.equal(state.startingProjects[1],true);
  assert.equal(notices.length,0);
});

test('review expands before a delayed request and never loads the historical detail body',async()=>{
  const {state,expansions}=app(), waiting=deferred(), requests=[];
  state.projects=[{id:1,title:'Task',status:'completed'}];
  state.authFetch=async url=>{requests.push(url);return waiting.promise;};
  const pending=state.selectReviewProject(state.projects[0]);
  assert.equal(state.reviewProjectId,1);assert.deepEqual(expansions,[[1,true]]);
  assert.equal(state.actionPending('review:1'),true);
  await tick();assert.deepEqual(requests,['/research/projects/1/run-intake']);
  waiting.resolve(json({intake:{marker:'saved'}}));await pending;
  assert.equal(state.reviewIntakes[1].marker,'saved');assert.equal(state.actionPending('review:1'),false);
});

test('repeated review clicks share one read and a late old selection cannot restore files or selection',async()=>{
  const {state}=app(),a=deferred(),b=deferred();let reads=0;
  state.projects=[{id:1,title:'A'},{id:2,title:'B'}];
  state.authFetch=async url=>{reads++;return url.includes('/1/')?a.promise:b.promise;};
  const first=state.selectReviewProject(state.projects[0]),repeat=state.selectReviewProject(state.projects[0]);
  state.reviewReportFiles=[{name:'A-private.docx'}];
  const second=state.selectReviewProject(state.projects[1]);
  assert.equal(state.reviewReportFiles.length,0);
  await tick();assert.equal(reads,2);
  b.resolve(json({intake:{owner:'B'}}));await second;
  a.resolve(json({intake:{owner:'A'}}));await Promise.all([first,repeat]);
  assert.equal(state.reviewProjectId,2);assert.equal(state.reviewIntakes[2].owner,'B');assert.equal(state.reviewIntakes[1],undefined);
});

test('failed review clears its spinner, retains a retryable error, and retry clears that error',async()=>{
  const {state}=app();state.projects=[{id:1}];
  state.authFetch=async()=>json({detail:'暂时无法读取'},false);
  await state.selectReviewProject(state.projects[0]);
  assert.equal(state.actionPending('review:1'),false);assert.match(state.actionErrors['review:1'].message,/暂时/);
  state.authFetch=async()=>json({intake:{ready:true}});
  await state.selectReviewProject(state.projects[0]);
  assert.equal(state.reviewIntakes[1].ready,true);assert.equal(state.actionErrors['review:1'],undefined);
});

test('read timeout includes response-body time, aborts only the read, and does not retry or run research',async()=>{
  const {state,timers}=app(),body=deferred();let calls=0,signal;
  state.authFetch=async(url,options)=>{calls++;signal=options.signal;return {ok:true,json:()=>body.promise};};
  const pending=state.readJSON('/research/projects/1/run-intake','读取复核参数失败',25);
  await tick();const timer=[...timers.values()].find(t=>t.ms===25);assert.ok(timer);
  timer.fn();await assert.rejects(pending,/读取超时.*未启动任何研究任务/);
  assert.equal(signal.aborted,true);assert.equal(calls,1);assert.equal(timers.size,0);
});

test('an old account response cannot reintroduce its review data or feedback',async()=>{
  const {state}=app(),wait=deferred();state.projects=[{id:1}];state.authFetch=async()=>wait.promise;
  const pending=state.selectReviewProject(state.projects[0]);await tick();
  state.token='next';state.pendingActions={};state.actionPromises={};state.actionErrors={};state.clearReviewSelection();
  wait.resolve(json({intake:{private:'OLD_ACCOUNT'}}));await pending;
  assert.equal(Object.keys(state.reviewIntakes).length,0);assert.equal(Object.keys(state.actionErrors).length,0);
});

test('opening and expanding the same task share a detail request and force refresh bypasses its short cache',async()=>{
  const {state}=app(),wait=deferred();let calls=0;const p={id:1,status:'completed'};state.projects=[p];
  state.authFetch=async()=>{calls++;return wait.promise;};
  const a=state.viewProject(p),b=state.onTaskExpand(p,[p]);await tick();assert.equal(calls,1);
  wait.resolve(json({project:p,intake:{},artifacts:[],sources:[]}));await Promise.all([a,b]);
  await state.loadProjectDetail(p);assert.equal(calls,1);
  await state.loadProjectDetail(p,{force:true});assert.equal(calls,2);
});

test('a failed action releases duplicate protection even if work throws synchronously',async()=>{
  const {state}=app();
  await assert.rejects(state.runAction('one','保存',()=>{throw Error('unavailable');}),/unavailable/);
  assert.equal(state.pendingActions.one,undefined);assert.equal(state.actionPromises.one,undefined);
  assert.equal(await state.runAction('one','保存',()=>42),42);assert.equal(state.actionErrors.one,undefined);
});

test('feedback uses real elapsed time and does not fabricate completion percentages',()=>{
  const {state}=app();state.nowTick=13000;
  const message=state.actionWaitText({label:'读取',startedAt:1000,readOnly:true});
  assert.match(message,/12 秒/);assert.match(message,/仍在读取/);assert.doesNotMatch(message,/%/);
});

test('partial multi-file upload retains only unconfirmed files and blocks duplicate writes and project switches',async()=>{
  const {state}=app(),first=deferred();state.reviewProjectId=1;state.projects=[{id:1},{id:2}];
  const a={name:'a.txt'},b={name:'b.txt'};state.fieldSourceFiles=[a,b];let writes=0;
  state.postTaskUpload=async()=>{writes++;if(writes===1)return first.promise;throw Error('network interrupted');};
  const pending=state.uploadFieldSources();await tick();
  await state.uploadFieldSources();await state.selectReviewProject(state.projects[1]);
  assert.equal(state.reviewProjectId,1);assert.equal(writes,1);
  first.resolve({});await pending;
  assert.deepEqual(Array.from(state.fieldSourceFiles),[b]);assert.equal(writes,2);
  assert.equal(state.reviewWriteBusy,false);assert.match(state.actionErrors['field-upload:1'].advice,/核对.*避免重复/);
});

test('download feedback lasts until the file body is received and repeated clicks download once',async()=>{
  const {state,downloads}=app(),body=deferred();let calls=0;
  state.authFetch=async()=>{calls++;return {ok:true,headers:{get(){return ''; }},blob:()=>body.promise};};
  const a=state.downloadArtifact({id:8}),b=state.downloadArtifact({id:8});await tick();
  assert.equal(state.actionPending('download-artifact:8'),true);assert.equal(calls,1);assert.equal(downloads(),0);
  body.resolve({});await Promise.all([a,b]);assert.equal(downloads(),1);assert.equal(state.actionPending('download-artifact:8'),false);
});

test('a slow older repository search cannot replace a later result',async()=>{
  const {state}=app(),a=deferred(),b=deferred();state.authFetch=async url=>url.includes('q=A')?a.promise:b.promise;
  const old=state.readRepository('A'),fresh=state.readRepository('B');
  b.resolve(json({results:[{title:'B'}]}));await fresh;a.resolve(json({results:[{title:'A'}]}));await old;
  assert.equal(state.knowledgeResults[0].title,'B');
});

test('second-stage stream ending without a confirmed result is not announced as generated',async()=>{
  const {state,notices}=app();state.projects=[{id:1,target_type:'industry'}];state.reviewProjectId=1;state.reviewIntakes[1]={};
  state.authFetch=async()=>({ok:true,body:{getReader(){return {read:async()=>({done:true})};}}});
  state.refreshAfterWorkflow=async()=>{};
  await state.runSecondStage();
  assert.equal(state.secondStageRunning,false);assert.ok(notices.some(([kind,text])=>kind==='error'&&text.includes('尚未确认')));
  assert.equal(notices.some(([kind,text])=>kind==='success'&&text.includes('已生成')),false);
});
