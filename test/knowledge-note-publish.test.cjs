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
