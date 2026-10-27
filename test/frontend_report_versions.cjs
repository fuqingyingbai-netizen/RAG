const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const window = {};
const definition = vm.runInNewContext(fs.readFileSync('frontend/report-versions.js', 'utf8') + '\nReportVersions;', {window, Date, ElementPlus: {ElMessage: {error() {}}}});
function state() {
  const props = {project:{id:1,title:'Own task'}, initialType:'desktop_report'};
  const value = {...definition.data.call(props), ...props};
  for (const [name, method] of Object.entries(definition.methods)) value[name] = method.bind(value);
  return value;
}
function deferred() { let resolve; const promise = new Promise(done => {resolve=done;}); return {promise,resolve}; }
const response = data => ({ok:true,json:async()=>data});
const record = {id:11, project_id:1, record_label:'记录 003', can_download:true};
(async () => {
  const history = state(); const urls=[];
  history.request = async url => {urls.push(url); return response(url.includes('/preview') ? {id:11, content:'THIRD',has_preview:true} : {records:[record],total:1});};
  await history.loadRecords();
  assert.equal(history.records[0].id,11); assert.equal(history.preview.content,'THIRD');
  assert.ok(urls[0].includes('artifact_type=desktop_report&page=1&page_size=10'));
  assert.equal(urls[1],'/research/artifacts/11/preview');
  let downloads=0;history.download=async row=>{assert.equal(row.id,11);downloads++;};
  await history.downloadRecord({...record,can_download:false});assert.equal(downloads,0);
  await history.downloadRecord(record);assert.equal(downloads,1);
  history.request=async()=>{throw Error('service unavailable');};
  await history.loadRecords();assert.match(history.error,/unavailable/);assert.equal(history.preview,null);assert.equal(history.records.length,0);
  const old=deferred();history.request=()=>old.promise;
  const previous=history.loadRecords();
  history.type='proposal';history.page=4;history.request=async url=>response(url.includes('/preview') ? {id:12,content:'PROPOSAL'} : {records:[{...record,id:12}],total:1});
  await history.changeType();assert.equal(history.page,1);
  old.resolve(response({records:[record],total:99}));await previous;
  assert.equal(history.records[0].id,12);assert.equal(history.preview.content,'PROPOSAL');
  history.page=4;await history.loadRecords();assert.equal(history.page,1);assert.equal(history.records[0].id,12);
  const oldPreview=deferred();history.request=()=>oldPreview.promise;
  const viewing=history.selectRecord(record);
  history.request=async()=>response({id:12,content:'LATEST_SELECTION'});
  await history.selectRecord({...record,id:12});oldPreview.resolve(response({id:11,content:'OLD_SELECTION'}));await viewing;
  assert.equal(history.preview.content,'LATEST_SELECTION');
  const closing=deferred();history.request=()=>closing.promise;const pending=history.loadRecords();
  definition.beforeUnmount.call(history);closing.resolve(response({records:[record],total:99}));await pending;
  assert.equal(history.records.length,0);
  const escaped=history.renderContent('<img src=x onerror=attack()>');assert.ok(escaped.includes('&lt;img'));assert.ok(!escaped.includes('<img'));
  window.SafeMarkdown={render:()=>'<p>safe preview</p>'};assert.equal(history.renderContent('<script>attack()</script>'),'<p>safe preview</p>');
  const html=fs.readFileSync('frontend/index.html','utf8');
  assert.ok(html.indexOf('src="report-versions.js"')<html.indexOf('src="script.js"'));
  assert.ok(html.includes('isAuthenticated && reportVersionsOpen'));
  assert.ok(!html.includes('v{{ artifact.version }}'));
  console.log('Report history: type/page loading, exact preview/download, failures, stale list/preview rejection, unmount and sanitizer checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
