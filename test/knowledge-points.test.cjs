const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.resolve(__dirname,'..');

function load(){
  const store=new Map([['accessToken','account-a']]);
  const context=vm.createContext({console,localStorage:{getItem:k=>store.get(k)},setInterval:()=>91,clearInterval:()=>{},
    document:{hidden:false,hasFocus:()=>true},window:{},crypto:globalThis.crypto});
  vm.runInContext(fs.readFileSync(path.join(root,'frontend/knowledge-points.js'),'utf8')+'\nthis.parts={PointsRequest,PointsCenter,PointsAdmin,PointsHomeCard,KnowledgePointsReader};',context);
  return {parts:context.parts,context,store};
}
function instance(component,overrides={}){
  const target={};
  for(const mixin of component.mixins||[])Object.assign(target,mixin.data?.call(target));
  Object.assign(target,component.data?.call(target));
  for(const mixin of component.mixins||[])for(const [key,method] of Object.entries(mixin.methods||{}))target[key]=method.bind(target);
  for(const [key,method] of Object.entries(component.methods||{}))target[key]=method.bind(target);
  return Object.assign(target,overrides);
}
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}

test('changing accounts or destroying the page prevents even sending a late mutation',async()=>{
  const {parts,store}=load();let sent=0;
  const target=instance(parts.PointsCenter,{request:async()=>{sent++;return {ok:true,json:async()=>({})};}});
  store.set('accessToken','account-b');
  await assert.rejects(target.pointsAPI('/admin/points/users/1/adjustments',{method:'POST'}),/账号/);
  assert.equal(sent,0);
  store.set('accessToken','account-a');target.pointsDisposed=true;
  await assert.rejects(target.pointsAPI('/points/me'),/页面/);
  assert.equal(sent,0);
});

test('an account change during a response discards the returned data',async()=>{
  const {parts,store}=load();const gate=deferred();
  const target=instance(parts.PointsCenter,{request:()=>gate.promise});
  const result=target.pointsAPI('/points/me');
  store.set('accessToken','account-b');gate.resolve({ok:true,json:async()=>({total:999})});
  await assert.rejects(result,/账号/);
});

test('a home points failure is contained instead of failing the personal home',async()=>{
  const {parts}=load();const target=instance(parts.PointsHomeCard,{pointsAPI:async()=>{throw Error('offline');}});
  await parts.PointsHomeCard.mounted.call(target);
  assert.equal(target.unavailable,true);assert.equal(target.points,null);
});

test('the home card refreshes a settled upload without reopening and cleans up its timer',async()=>{
  const {parts,context}=load();let tick,cleared=false,total=0;
  context.setInterval=(callback,delay)=>{assert.equal(delay,15000);tick=callback;return 92;};
  context.clearInterval=id=>{assert.equal(id,92);cleared=true;};
  const target=instance(parts.PointsHomeCard,{pointsAPI:async()=>({total})});
  await parts.PointsHomeCard.mounted.call(target);assert.equal(target.points.total,0);
  total=10;tick();await new Promise(resolve=>setImmediate(resolve));assert.equal(target.points.total,10);
  context.document.hidden=true;total=20;await tick();assert.equal(target.points.total,10);
  parts.PointsHomeCard.beforeUnmount.call(target);assert.equal(cleared,true);
});

test('destroying a home card during loading discards the result and never starts polling',async()=>{
  const {parts,context}=load();const gate=deferred();let polls=0;
  context.setInterval=()=>{polls++;};
  const target=instance(parts.PointsHomeCard,{pointsAPI:()=>gate.promise});
  const mounted=parts.PointsHomeCard.mounted.call(target);target.pointsDisposed=true;
  gate.resolve({total:999});await mounted;assert.equal(target.points,null);assert.equal(polls,0);
});

test('late read-session creation cannot restart the timer after closing a document',async()=>{
  const {parts}=load();const gate=deferred();
  const target=instance(parts.KnowledgePointsReader,{apiFetch:()=>gate.promise});
  const started=target.beginPointsReading('document-a');target.stopPointsReading();
  gate.resolve({ok:true,json:async()=>({eligible:true,session_id:'old',heartbeat_seconds:10})});
  await started;assert.equal(target.pointsReadSession,null);assert.equal(target.pointsReadClock,null);
});

test('a late heartbeat never updates the next reader or clears its busy state',async()=>{
  const {parts}=load();const gate=deferred();
  const target=instance(parts.KnowledgePointsReader,{apiFetch:()=>gate.promise,pointsReadableIdentity:'a',
    pointsReadSession:{id:'old',sequence:0,document:'a'},pointsPreviouslyActive:true});
  const old=target.sendPointsHeartbeat(0);target.stopPointsReading();
  target.pointsReadBusy=true;target.pointsReaderMessage='new reader';
  gate.resolve({ok:true,json:async()=>({complete:true,awarded:2})});await old;
  assert.equal(target.pointsReaderMessage,'new reader');assert.equal(target.pointsReadBusy,true);
});

test('hidden or unfocused reader sends inactive state instead of earning foreground time',async()=>{
  const {parts,context}=load();context.document.hidden=true;let body;
  const target=instance(parts.KnowledgePointsReader,{pointsReadSession:{id:'read',sequence:0,document:'a'},
    pointsPreviouslyActive:true,pointsReadableIdentity:'a',apiFetch:async(path,options)=>{body=JSON.parse(options.body);return {ok:true,json:async()=>({complete:false,seconds:0})};}});
  await target.sendPointsHeartbeat(0);assert.equal(body.active,false);
});

test('failed preview, inaccessible data and media never look like loaded text',()=>{
  const {parts}=load();const component=parts.KnowledgePointsReader;
  const state={readerOpen:true,selectedDoc:{id:'a',can_read:true},readerMode:'original',readerLoading:false,readerOriginalLoading:false};
  assert.equal(component.computed.pointsReadableIdentity.call(state),'');
  state.readerBlob={};assert.equal(component.computed.pointsReadableIdentity.call(state),'a');
  state.selectedDoc.media_kind='video';assert.equal(component.computed.pointsReadableIdentity.call(state),'');
  state.selectedDoc.media_kind='';state.selectedDoc.can_read=false;assert.equal(component.computed.pointsReadableIdentity.call(state),'');
});

test('an older points page response cannot replace the latest view',async()=>{
  const {parts}=load();const first=deferred();let calls=0;
  const target=instance(parts.PointsCenter,{pointsAPI:async path=>{calls++;if(calls===1)return first.promise;if(path==='/points/me')return {total:20};return {items:[],total:0};}});
  const old=target.reload();target.tab='ledger';await target.reload();
  first.resolve({total:999});await old;assert.equal(target.summary.total,20);
});

test('integration includes points only as an independent optional feature',()=>{
  const index=fs.readFileSync(path.join(root,'frontend/index.html'),'utf8');
  const script=fs.readFileSync(path.join(root,'frontend/script.js'),'utf8');
  const account=fs.readFileSync(path.join(root,'frontend/account-management.js'),'utf8');
  assert.match(index,/points-center[^>]*activeView === 'points'/);
  assert.match(script,/'accounts', 'points'\]\.includes/);
  assert.match(account,/tab !== 'points'/);
  assert.match(account,/积分管理/);
});
