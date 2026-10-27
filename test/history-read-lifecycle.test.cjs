const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function instance(name,props={}){
  const definition=vm.runInNewContext(fs.readFileSync('frontend/'+(name==='ReportVersions'?'report-versions':'personal-home')+'.js','utf8')+'\n'+name+';',
    {AbortController,clearInterval(){},ElementPlus:{ElMessage:{error(){}}}});
  const state=Object.assign(definition.data.call(props),props);
  for(const [key,method]of Object.entries(definition.methods))state[key]=method.bind(state);
  return {state,definition};
}
const record=id=>({id,record_label:'记录 '+id,can_download:true});

test('history list becomes usable before the first delayed preview, including download',async()=>{
  const body=deferred();let downloads=0;
  const {state}=instance('ReportVersions',{project:{id:1},initialType:'desktop_report',download:async()=>{downloads++;}});
  state.read=async url=>url.includes('/preview')?body.promise:{records:[record(3)],total:1};
  const loading=state.loadRecords();await tick();
  assert.equal(state.records.length,1);assert.equal(state.loading,false);assert.equal(state.previewLoading,true);
  await state.downloadRecord(state.records[0]);assert.equal(downloads,1);
  body.resolve({id:3,content:'confirmed'});await loading;assert.equal(state.preview.content,'confirmed');
});

test('repeated selection shares one preview and selecting another record aborts the first read',async()=>{
  const a=deferred(),b=deferred(),signals=[];
  const {state}=instance('ReportVersions');
  state.read=(url,message,timeout,options)=>{signals.push(options.signal);assert.equal(timeout,30000);return url.includes('/1/')?a.promise:b.promise;};
  const first=state.selectRecord(record(1)),repeat=state.selectRecord(record(1));
  assert.equal(first,repeat);assert.equal(signals.length,1);
  const second=state.selectRecord(record(2));assert.equal(signals[0].aborted,true);
  a.reject(new Error('cancelled A'));await first;
  assert.equal(state.previewLoading,true);assert.equal(state.previewError,'');
  b.resolve({id:2,content:'B'});await second;assert.equal(state.preview.id,2);assert.equal(state.previewLoading,false);
});

test('closing history aborts active reads and late replies never restore the closed dialog',async()=>{
  const body=deferred();let signal;
  const {state,definition}=instance('ReportVersions',{project:{id:1}});
  state.read=(url,message,timeout,options)=>{signal=options.signal;return body.promise;};
  const pending=state.loadRecords();definition.beforeUnmount.call(state);
  assert.equal(signal.aborted,true);body.resolve({records:[record(1)],total:1});await pending;
  assert.equal(state.records.length,0);assert.equal(state.selected,null);
});

test('refreshing history cancels the current preview and a late reply cannot replace new records',async()=>{
  const old=deferred();let previewSignal;
  const {state}=instance('ReportVersions',{project:{id:1}});
  state.read=(url,message,timeout,options)=>{previewSignal=options.signal;return old.promise;};
  const first=state.selectRecord(record(1));
  state.read=async url=>url.includes('/preview')?{id:2,content:'new'}:{records:[record(2)],total:1};
  await state.loadRecords();assert.equal(previewSignal.aborted,true);
  old.resolve({id:1,content:'stale'});await first;
  assert.equal(state.preview.id,2);assert.equal(state.records[0].id,2);
});

test('preview timeout keeps the list usable and manual retry clears the error',async()=>{
  const {state}=instance('ReportVersions',{project:{id:1}});
  state.read=async url=>{if(url.includes('/preview'))throw new Error('读取超时');return {records:[record(1)],total:1};};
  await state.loadRecords();assert.equal(state.loading,false);assert.equal(state.previewLoading,false);
  assert.equal(state.records.length,1);assert.match(state.previewError,/读取超时/);
  state.read=async()=>({id:1,content:'retried'});await state.selectRecord(record(1));
  assert.equal(state.previewError,'');assert.equal(state.preview.content,'retried');
});

test('home reads share the bounded reader, abort on replacement and retain confirmed data after failure',async()=>{
  const a=deferred(),b=deferred(),signals=[];
  const {state}=instance('PersonalHome');
  state.read=(url,message,timeout,options)=>{assert.equal(timeout,30000);signals.push(options.signal);return signals.length===1?a.promise:b.promise;};
  const first=state.loadHome(),second=state.loadHome();assert.equal(signals[0].aborted,true);
  b.resolve({id:'new'});await second;a.resolve({id:'old'});await first;assert.equal(state.home.id,'new');
  state.read=async()=>{throw new Error('读取超时');};await state.loadHome();
  assert.equal(state.home.id,'new');assert.match(state.error,/上次加载的数据.*读取超时/);assert.equal(state.loading,false);
});

test('leaving home aborts its read and prevents a late result from restoring the page',async()=>{
  const body=deferred();let signal;
  const {state,definition}=instance('PersonalHome');
  state.read=(url,message,timeout,options)=>{signal=options.signal;return body.promise;};
  const pending=state.loadHome();definition.beforeUnmount.call(state);assert.equal(signal.aborted,true);
  body.resolve({id:'late'});await pending;assert.equal(state.home,null);
});
