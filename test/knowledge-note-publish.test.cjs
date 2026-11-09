const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const sandbox={window:{},Vue:{},console};
vm.runInNewContext(fs.readFileSync('frontend/knowledge-note-editor.js','utf8'),sandbox);
const component=sandbox.window.KnowledgeNoteEditor;
function state(){
  const value=component.data();value.loading=false;
  for(const [name,method] of Object.entries(component.methods))value[name]=method.bind(value);
  for(const [name,get] of Object.entries(component.computed))Object.defineProperty(value,name,{get:()=>get.call(value)});
  return value;
}
test('a title-only note explains why publishing is unavailable without sending a request',async()=>{
  const value=state();value.title='仅有标题';let requests=0;
  value.request=async()=>{requests++;};value.editor={commands:{focus(){}}};
  assert.equal(value.empty,true);await value.publish();
  assert.equal(requests,0);assert.match(value.error,/正文或插入图片/);
});
test('text and image-only notes save first and publish the saved revision',async()=>{
  for(const content of [{words:5,assets:0},{words:0,assets:1}]){
    const value=state();Object.assign(value,content);let saved=false,changed=false;
    value.note={revision:1};value.save=async()=>{value.note={revision:2};saved=true;};
    value.request=async(path,options)=>{
      assert.equal(saved,true);assert.equal(path,'/publish');assert.equal(JSON.parse(options.body).revision,2);
      return {json:async()=>({revision:2,index_state:'queued'})};
    };
    value.$emit=()=>{changed=true;};await value.publish();
    assert.equal(value.note.index_state,'queued');assert.equal(value.publishing,false);assert.equal(changed,true);
  }
});


test('a committed publication with a lost response is confirmed by GET without another POST',async()=>{
  const value=state();value.words=5;value.note={revision:2};value.save=async()=>{};
  const calls=[];value.$emit=()=>{};
  value.request=async path=>{calls.push(path);if(path==='/publish')throw Error('network interrupted');return {json:async()=>({revision:2,published_revision:2,pending_document_id:'doc',index_state:'queued'})};};
  await value.publish();assert.deepEqual(calls,['/publish','']);assert.equal(value.error,'');assert.match(value.publishMessage,/发布提交成功/);
  assert.equal(value.publishLabel,'已提交发布');await value.publish();assert.equal(calls.length,2);
});

test('an unknown outcome only queries status and allows retry after the server confirms not published',async()=>{
  const value=state();value.words=5;value.note={revision:2};value.save=async()=>{};value.$emit=()=>{};
  let posts=0,online=false;
  value.request=async path=>{if(path==='/publish'){posts++;throw Error('offline');}if(!online)throw Error('offline');return {json:async()=>({revision:2,published_revision:0,current_document_id:'',index_state:''})};};
  await value.publish();assert.equal(value.publishUncertain,true);assert.equal(value.publishLabel,'查询发布状态');
  await value.publish();assert.equal(posts,1);online=true;await value.publish();assert.equal(posts,1);
  assert.equal(value.publishUncertain,false);assert.match(value.error,/可点击发布重试/);
});

test('a save error never submits publication and says the draft must be saved first',async()=>{
  const value=state();value.words=5;let requests=0;value.save=async()=>{throw Error('格式有误');};value.request=async()=>requests++;
  await value.publish();assert.equal(requests,0);assert.match(value.error,/草稿尚未保存，未提交发布/);
});
