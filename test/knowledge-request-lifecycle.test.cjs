const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const tick = () => new Promise(setImmediate);
function deferred() { let resolve, reject; const promise = new Promise((a,b)=>{resolve=a;reject=b;}); return {promise,resolve,reject}; }
function fixture(fetcher) {
  let token='owner', downloads=0, timerId=0;
  const timers=new Map(), notices=[];
  const component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+'\nCompanyKnowledge;',{
    fetch:fetcher, AbortController, TextDecoder,
    localStorage:{getItem:()=>token,setItem(){}},
    setTimeout(fn,ms){const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),
    setInterval(){return 1;},clearInterval(){},
    URL:{createObjectURL(){return 'blob:synthetic';},revokeObjectURL(){}},
    document:{body:{appendChild(){}},createElement(){return {click(){downloads++;},remove(){}};}},
    ElementPlus:{ElMessage:Object.fromEntries(['success','error','info','warning'].map(kind=>[kind,message=>notices.push({kind,message})]))},
  });
  const state=component.data();
  for(const [name,method] of Object.entries(component.methods))state[name]=method.bind(state);
  state.allReferences=[];state.service={username:'owner'};
  return {state,component,timers,notices,switchAccount(){token='other';},downloads:()=>downloads};
}

test('saved answer exports download only for the same account and conversation',async()=>{
  const body=deferred();let request;
  const f=fixture(async(url,options)=>{request={url,options};return {ok:true,status:200,blob:()=>body.promise};});
  f.state.chatSessionId='thread-a';f.state.chatGeneration=1;
  const message={id:42,complete:true,text:'table',references:[{id:'1'}]};
  const pending=f.state.exportAnswer(message,'xlsx',2);await tick();
  f.switchAccount();body.resolve(new Blob(['workbook']));await pending;
  assert.equal(f.downloads(),0);assert.equal(message.exportBusy,false);
  assert.match(request.url,/thread-a\/messages\/42\/export$/);
  assert.deepEqual(JSON.parse(request.options.body),{format:'xlsx',table_index:2,value_column:null});
});

test('switching conversations during export discards a late file',async()=>{
  const body=deferred();const f=fixture(async()=>({ok:true,status:200,blob:()=>body.promise}));
  f.state.chatSessionId='thread-a';f.state.chatGeneration=1;
  const pending=f.state.exportAnswer({id:42,complete:true},'docx');await tick();
  f.state.chatSessionId='thread-b';f.state.chatGeneration=2;body.resolve(new Blob(['old']));await pending;
  assert.equal(f.downloads(),0);
});

test('redacted or unsaved answers cannot request exports and server refusal never downloads',async()=>{
  let calls=0;const f=fixture(async()=>{calls++;return new Response('{"detail":"资料版本已变化"}',{status:409,headers:{'Content-Type':'application/json'}});});
  await f.state.exportAnswer({complete:true},'xlsx');
  await f.state.exportAnswer({id:1,complete:true,redacted:true},'docx');
  assert.equal(calls,0);
  f.state.chatSessionId='t';await f.state.exportAnswer({id:1,complete:true},'docx');
  assert.equal(calls,1);assert.equal(f.downloads(),0);assert.ok(f.notices.some(n=>n.message.includes('资料版本')));
});

test('body parsing preserves native Response methods and releases the read deadline',async()=>{
  const {state,timers}=fixture(async()=>new Response('{"ready":true}',{headers:{'Content-Type':'application/json'}}));
  const response=await state.apiFetch('/company-knowledge/status');
  assert.equal(response.headers.get('content-type'),'application/json');
  assert.equal((await response.json()).ready,true);
  assert.equal(timers.size,0);assert.equal(state.pendingReads.size,0);
});

for(const method of ['json','blob']) test(`account switch while ${method} body waits cannot restore old account data`,async()=>{
  const body=deferred(), f=fixture(async()=>({status:200,ok:true,[method]:()=>body.promise}));
  const response=await f.state.apiFetch('/company-knowledge/documents/old/original');
  const pending=response[method]();f.switchAccount();body.resolve(method==='json'?{private:'old'}:new Blob(['old']));
  await assert.rejects(pending,/账号已变更/);
  assert.equal(f.timers.size,0);
});

test('a timed out body aborts only the read and never automatically retries',async()=>{
  let calls=0,signal;const body=deferred();
  const f=fixture(async(url,options)=>{calls++;signal=options.signal;return {status:200,ok:true,json:()=>body.promise};});
  const response=await f.state.apiFetch('/company-knowledge/documents');const pending=response.json();
  [...f.timers.values()].find(timer=>timer.ms===30000).fn();
  await assert.rejects(pending,/读取超时/);assert.equal(signal.aborted,true);assert.equal(calls,1);
  body.resolve({documents:[]});await tick();assert.equal(f.state.pendingReads.size,0);
});

test('leaving the component cancels both header and body reads without leaving spinners indefinitely',async()=>{
  const body=deferred(),header=deferred();let calls=0;
  const f=fixture(async()=>++calls===1?{status:200,ok:true,json:()=>body.promise}:header.promise);
  const response=await f.state.apiFetch('/company-knowledge/status');const first=response.json();
  const second=f.state.apiFetch('/company-knowledge/documents');
  const assertion1=assert.rejects(first,/读取已停止/),assertion2=assert.rejects(second,/读取已停止/);
  f.component.beforeUnmount.call(f.state);
  await Promise.all([assertion1,assertion2]);assert.equal(f.timers.size,0);assert.equal(f.state.pendingReads.size,0);
  body.resolve({});header.resolve({status:200});await tick();
  await assert.rejects(f.state.apiFetch('/company-knowledge/status'),/已离开/);assert.equal(calls,2);
});

test('writes have no automatic deadline, cancellation or retries and still verify the account after parsing',async()=>{
  const body=deferred();let calls=0,options;
  const f=fixture(async(url,input)=>{calls++;options=input;return {status:200,ok:true,json:()=>body.promise};});
  const response=await f.state.apiFetch('/company-knowledge/uploads',{method:'POST',body:'synthetic'});
  assert.equal(f.timers.size,0);assert.equal(options.signal,undefined);assert.equal(calls,1);
  const pending=response.json();f.switchAccount();body.resolve({id:'old'});
  await assert.rejects(pending,/账号已变更/);assert.equal(calls,1);
});

test('original download cannot start after an account change during its blob response',async()=>{
  const body=deferred(),f=fixture(async()=>({status:200,ok:true,blob:()=>body.promise}));
  const pending=f.state.downloadOriginal({id:'old',title:'Synthetic original'});
  await tick();f.switchAccount();body.resolve(new Blob(['private']));await pending;
  assert.equal(f.downloads(),0);assert.ok(f.notices.some(n=>n.kind==='error'&&/账号已变更/.test(n.message)));
});

test('an already started original download survives ordinary navigation in the same account',async()=>{
  const body=deferred(),f=fixture(async()=>({status:200,ok:true,blob:()=>body.promise}));
  const pending=f.state.downloadOriginal({id:'same',title:'Synthetic original'});await tick();
  f.component.beforeUnmount.call(f.state);body.resolve(new Blob(['synthetic']));await pending;
  assert.equal(f.downloads(),1);assert.ok(f.notices.some(n=>n.kind==='success'));
});

test('failed watermarked export clears progress and allows the next download',async()=>{
  let calls=0;
  const f=fixture(async()=>++calls===1
    ? {status:503,ok:false,json:async()=>({detail:'转换失败'})}
    : {status:200,ok:true,blob:async()=>new Blob(['marked'])});
  await f.state.downloadOriginal({id:'doc',title:'sample.pdf'});
  assert.equal(f.downloads(),0);assert.equal(Object.keys(f.state.downloadProgress).length,0);
  assert.ok(f.notices.some(n=>n.kind==='error'&&/转换失败/.test(n.message)));
  await f.state.downloadOriginal({id:'doc',title:'sample.pdf'});
  assert.equal(f.downloads(),1);assert.equal(Object.keys(f.state.downloadProgress).length,0);
});

test('an in-flight write may confirm after navigation but the departed component cannot send another write',async()=>{
  const body=deferred();let calls=0;
  const f=fixture(async()=>{calls++;return {status:200,ok:true,json:()=>body.promise};});
  const response=await f.state.apiFetch('/company-knowledge/uploads',{method:'POST'});
  const pending=response.json();f.component.beforeUnmount.call(f.state);body.resolve({id:'confirmed'});
  assert.equal((await pending).id,'confirmed');
  await assert.rejects(f.state.apiFetch('/company-knowledge/uploads',{method:'POST'}),/已离开/);assert.equal(calls,1);
});

test('a late error from preview A cannot clear the loading state of newly opened preview B',async()=>{
  const a=deferred(),b=deferred(),f=fixture(async url=>url.includes('/a/')?a.promise:b.promise);
  const first=f.state.openDocument({id:'a',can_read:true,has_original:false});
  const second=f.state.openDocument({id:'b',can_read:true,has_original:false});
  a.reject(new Error('late A failure'));await first;
  assert.equal(f.state.selectedDoc.id,'b');assert.equal(f.state.readerLoading,true);assert.equal(f.state.readerError,'');
  b.resolve({ok:true,json:async()=>({references:[],total:0,message:''})});await second;
  assert.equal(f.state.readerLoading,false);assert.equal(f.state.readerError,'');
});

test('closing and reopening the same preview does not accept an older response for that file',async()=>{
  const first=deferred(),second=deferred();let calls=0;
  const f=fixture(async()=>++calls===1?first.promise:second.promise);
  const doc={id:'same',can_read:true,has_original:false};
  const a=f.state.openDocument(doc),b=f.state.openDocument(doc);
  second.resolve({ok:true,json:async()=>({references:[{text:'new'}],total:1,message:''})});await b;
  first.resolve({ok:true,json:async()=>({references:[{text:'old'}],total:8,message:'old'})});await a;
  assert.equal(f.state.selectedDoc.references[0].text,'new');assert.equal(f.state.readerTotal,1);assert.equal(f.state.readerError,'');
});

test('a failed cloud chunk service does not block the complete original document',async()=>{
  const f=fixture(async url=>{
    if(url.endsWith('/preview'))throw new Error('cloud unavailable');
    return new Response('complete document body',{headers:{'X-Watermark-Trace':'trace-b'}});
  });
  await f.state.openDocument({id:'word',format:'TXT',has_original:true,can_read:true});
  assert.equal(await f.state.readerBlob.text(),'complete document body');
  assert.equal(f.state.readerMode,'original');assert.equal(f.state.readerError,'');
  assert.equal(f.state.readerTrace,'trace-b');assert.equal(f.state.readerOriginalLoading,false);
});

test('a late original cannot replace the text document currently being read',async()=>{
  const old=deferred(),f=fixture(async url=>{
    if(url.endsWith('/preview'))return new Response('{"references":[],"total":0}');
    if(url.includes('/a/'))return old.promise;
    return new Response('new document',{headers:{'X-Watermark-Trace':'new-trace'}});
  });
  const first=f.state.openDocument({id:'a',format:'TXT',has_original:true,can_read:true});
  await f.state.openDocument({id:'b',format:'TXT',has_original:true,can_read:true});
  old.resolve(new Response('old document'));await first;
  assert.equal(await f.state.readerBlob.text(),'new document');
  assert.equal(f.state.readerTrace,'new-trace');assert.equal(f.state.readerOriginalLoading,false);
});

test('caller cancellation remains effective for read requests and rejects even if transport ignores abort',async()=>{
  const body=deferred(),f=fixture(async()=>({status:200,json:()=>body.promise}));
  const controller=new AbortController();const response=await f.state.apiFetch('/company-knowledge/status',{signal:controller.signal});
  const pending=response.json();controller.abort();await assert.rejects(pending,/读取已停止/);
  body.resolve({});assert.equal(f.state.pendingReads.size,0);
});
