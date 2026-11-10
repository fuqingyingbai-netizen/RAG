const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const sandbox={AbortController,FormData,File,Blob,TextDecoder,URL:{createObjectURL:()=> 'blob:page',revokeObjectURL(){}},localStorage:{getItem:()=>'',setItem(){}},setTimeout,clearTimeout};
const component=vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+';CompanyKnowledge',sandbox);
function state(){const s=component.data();for(const [k,v] of Object.entries(component.methods))s[k]=v.bind(s);for(const [k,v] of Object.entries(component.computed))Object.defineProperty(s,k,{get:()=>v.call(s)});s.$nextTick=fn=>fn();s.$refs={};return s;}
const response=data=>({ok:true,status:200,json:async()=>data});
const tick=()=>new Promise(setImmediate);

test('large XLSX opens the row reader without starting a PDF conversion',async()=>{
 const s=state(),calls=[],table={mode:'table',page:1,values:[['first']]};
 s.apiFetch=async url=>{calls.push(url);return url.endsWith('/sheet')?new Response(JSON.stringify(table),{headers:{'Content-Type':'application/json','X-Watermark-Trace':'sheet-trace'}}):response({references:[],total:0});};
 await s.openDocument({id:'large',format:'XLSX',has_original:true,can_read:true});assert.equal(s.readerSheet.mode,'table');assert.equal(s.readerTrace,'sheet-trace');assert.ok(!calls.some(url=>url.includes('/page?')));assert.equal(s.readerOriginalLoading,false);
});

test('small XLSX preserves the existing PDF layout preview',async()=>{
 const s=state(),calls=[];s.apiFetch=async url=>{calls.push(url);return url.endsWith('/sheet')?new Response(JSON.stringify({mode:'pdf'})):url.endsWith('/preview')?response({references:[],total:0}):new Response('image',{headers:{'X-Document-Pages':'2'}});};
 await s.openDocument({id:'small',format:'XLSX',has_original:true,can_read:true});assert.equal(s.readerSheet,null);assert.equal(s.readerPDFPages,2);assert.ok(calls.some(url=>url.includes('/page?page=1')));
});

test('encrypted PDF preserves the specific password error separately from excerpts',async()=>{
 const s=state();s.apiFetch=async url=>url.endsWith('/preview')?response({references:[],total:0}):new Response(JSON.stringify({detail:'该 PDF 已加密，需要打开密码'}),{status:422,headers:{'X-Preview-Error':'pdf_encrypted'}});
 await s.openDocument({id:'protected',format:'PDF',has_original:true,can_read:true});assert.equal(s.readerOriginalCode,'pdf_encrypted');assert.match(s.readerOriginalError,/打开密码/);assert.equal(s.readerExcerptError,'');
});
test('upload completion keeps older ready files and new pending files visible',()=>{
 const s=state();s.mode='library';s.cloudDocuments=[{id:'old',category:'项目原件',state:'ready',title:'old'},{id:'new',category:'项目原件',state:'queued',title:'new'}];s.uploadResults=[{id:'new'}];s.recentUploadIds=['new'];s.query='stale';s.viewUploaded();
 assert.deepEqual(Array.from(s.filteredDocuments,d=>d.id),['old','new']);assert.equal(s.query,'');assert.equal(s.recentUploadIds.length,0);
});
test('a catalogue snapshot started before an upload cannot erase the newly registered row',async()=>{
 const s=state();s.service.access_allowed=true;s.loadNotes=()=>{};s.loadProjectDirectories=async()=>{};s.loadMyProjects=async()=>{};
 let release,catalogueCalls=0;const old={id:'old',category:'项目原件',state:'ready'},fresh={id:'new',category:'项目原件',state:'queued'};s.cloudDocuments=[old];
 s.apiFetch=async url=>{if(url.endsWith('/uploads'))return response(fresh);if(++catalogueCalls===1)return new Promise(resolve=>release=()=>resolve(response({documents:[old],total_count:1})));return response({documents:[old,fresh],total_count:2});};
 const reading=s.loadDocuments();await tick();s.activeProjectId='p';s.stagedFiles=[new File(['hello'],'new.txt')];await s.uploadFiles();assert.equal(s.cloudDocuments.length,2);
 release();await reading;assert.equal(s.cloudDocuments.length,2);assert.equal(catalogueCalls,2);
});
test('DOCX uses paged server preview and preserves the source download action',async()=>{
 const s=state(),calls=[];s.apiFetch=async url=>{calls.push(url);return url.endsWith('/preview')?response({references:[],total:0}):new Response('page',{headers:{'X-Document-Pages':'76'}});};
 await s.openDocument({id:'word',format:'DOCX',has_original:true,can_read:true});assert.ok(calls.some(u=>u.endsWith('/page?page=1')));assert.ok(!calls.some(u=>u.endsWith('/original')));assert.equal(s.readerPDFPages,76);assert.equal(s.readerUrl,'blob:page');
});
test('source search reads later chunk pages and highlights whitespace split OCR text',async()=>{
 const s=state();s.readerOpen=true;s.readerSequence=4;s.selectedDoc={id:'scan',format:'PNG',references:Array.from({length:20},(_,i)=>({id:String(i),text:'无关内容'}))};s.readerTotal=21;s.readerHasMore=true;s.previewPage=1;s.readerFind='终点';s.apiFetch=async()=>response({references:[{id:'21',text:'扫描件里的终 点在这里'}],total:21,has_more:false});
 await s.findInReader();assert.equal(s.readerMode,'excerpts');assert.equal(s.readerSequence,4);assert.equal(s.readerMatches.length,1);assert.equal(s.selectedDoc.references.length,21);assert.match(s.readerSearchStatus,/全部可用解析片段/);assert.equal(s.readerParts('终 点')[1].text,'终 点');assert.equal(s.readerParts('终 点')[1].match,true);
});
test('double clicking project, folder and file bodies opens them while controls do not',()=>{
 const s=state(),opened=[];s.dismissProjectPreview=()=>{};s.openDirectory=(p,f)=>opened.push([p.id,f]);s.openDocument=d=>opened.push(d.id);
 const body={target:{closest:()=>null}},control={target:{closest:()=>({})}};s.openFromDoubleClick({id:'p'},body);s.openFromDoubleClick({id:'p'},body,'f');s.openFileFromDoubleClick({id:'doc'},body);s.openFileFromDoubleClick({id:'other'},control);
 assert.deepEqual(opened,[['p',''],['p','f'],'doc']);
});
