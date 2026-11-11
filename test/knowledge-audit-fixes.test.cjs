const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(){
 const warnings=[];
 const component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+';CompanyKnowledge',{ElementPlus:{ElMessage:{warning:message=>warnings.push(message)}},AbortController,File,FormData,setTimeout,clearTimeout});
 const state=component.data();for(const [name,method] of Object.entries(component.methods))state[name]=method.bind(state);
 for(const [name,get] of Object.entries(component.computed))Object.defineProperty(state,name,{get:()=>get.call(state)});
 return {state,warnings};
}
test('description requiredness follows root media, mixed batches, target changes, quick capture, and reupload destination',()=>{
 const {state:s}=fixture();s.uploadTargetProjectId='';s.stagedFiles=[{name:'录音.WAV'}];assert.equal(s.uploadDescriptionRequired,true);
 s.stagedFiles=[{name:'报告.docx'}];assert.equal(s.uploadDescriptionRequired,false);
 s.stagedFiles.push({name:'video.mp4'});assert.equal(s.uploadDescriptionRequired,true);
 s.uploadTargetProjectId='p';assert.equal(s.uploadDescriptionRequired,false);
 s.uploadTargetProjectId='';s.quickCapture=true;assert.equal(s.uploadDescriptionRequired,false);
 s.quickCapture=false;s.reuploadContext={project_id:'p'};assert.equal(s.uploadDescriptionRequired,false);
 s.reuploadContext={project_id:''};s.uploadTargetProjectId='p';assert.equal(s.uploadDescriptionRequired,true);
});
test('root media preflight prevents a submission until description is present',async()=>{
 const {state:s}=fixture();s.stagedFiles=[{name:'录音.wav'}];s.uploadForm.description='  ';let requests=0;s.apiFetch=async()=>{requests++;};
 await s.uploadFiles();assert.equal(requests,0);assert.match(s.uploadError,/根目录音视频需要填写文字说明/);
});
test('a file exception does not create a directory link or change browsing state',()=>{
 const {state:s,warnings}=fixture();s.projectDirectories=[{id:'readable'}];s.mode='library';const doc={knowledge_project_id:'private'};
 assert.equal(s.canOpenDocumentDirectory(doc),false);assert.match(s.documentDirectoryReason(doc),/文件阅读权.*没有.*目录权限/);s.openDocumentDirectory(doc);
 assert.equal(s.mode,'library');assert.equal(warnings.length,1);assert.equal(s.canOpenDocumentDirectory({knowledge_project_id:'readable'}),true);assert.equal(s.canOpenDocumentDirectory({is_root:1}),true);
});
