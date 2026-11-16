const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function bind(component,overrides={}){const s=component.data();for(const [key,fn] of Object.entries(component.methods))s[key]=fn.bind(s);for(const [key,fn] of Object.entries(component.computed||{}))Object.defineProperty(s,key,{get:()=>fn.call(s),configurable:true});return Object.assign(s,overrides);}
function knowledge(){return vm.runInNewContext(fs.readFileSync('frontend/company-knowledge.js','utf8')+'\nCompanyKnowledge;', {localStorage:{getItem:()=>''},window:{},URL,URLSearchParams,AbortController,setTimeout,clearTimeout});}
test('notes retain loading through their own response and only the latest read may replace the list',async()=>{
 const s=bind(knowledge()),first=deferred(),last=deferred();let n=0;
 s.mode='cases';s.apiFetch=()=>++n===1?first.promise:last.promise;
 const a=s.loadNotes();assert.equal(s.catalogueLoading,true);
 const b=s.loadNotes();first.resolve(new Response(JSON.stringify({notes:[{id:'old'}]})));await a;
 assert.equal(s.notesLoading,true);assert.equal(s.noteDrafts.length,0);
 last.resolve(new Response(JSON.stringify({notes:[{id:'new'}]})));await b;
 assert.equal(s.catalogueLoading,false);assert.equal(s.noteDrafts[0].id,'new');
});
test('failed notes reads stop loading, keep the confirmed snapshot and expose a retryable error',async()=>{
 const s=bind(knowledge());s.noteDrafts=[{id:'saved'}];s.apiFetch=async()=>new Response('{"detail":"笔记服务暂不可用"}',{status:503});
 await s.loadNotes();assert.equal(s.notesLoading,false);assert.match(s.noteError,/暂不可用/);assert.equal(s.noteDrafts[0].id,'saved');
});
test('account and invitation reads cannot clear each other\'s loading flag',async()=>{
 const component=vm.runInNewContext(fs.readFileSync('frontend/account-management.js','utf8')+'\nAccountManagement;',{URLSearchParams});
 const s=bind(component),users=deferred(),invites=deferred();s.api=url=>url.startsWith('/admin/users')?users.promise:invites.promise;
 const a=s.loadUsers();s.tab='invitations';const b=s.loadInvitations();
 users.resolve({items:[],total:0,active_admin_count:1});await a;
 assert.equal(s.usersLoading,false);assert.equal(s.invitationsLoading,true);
 invites.resolve({items:[{id:1}],total:1});await b;assert.equal(s.invitationsLoading,false);assert.equal(s.invitations.length,1);
});
test('a late failure from the previous account tab cannot replace current invitation feedback',async()=>{
 const component=vm.runInNewContext(fs.readFileSync('frontend/account-management.js','utf8')+'\nAccountManagement;',{URLSearchParams});
 const s=bind(component),old=deferred();s.api=()=>old.promise;const read=s.loadUsers();s.tab='invitations';s.error='';old.reject(Error('old users failure'));await read;
 assert.equal(s.error,'');assert.equal(s.usersLoading,false);
});
function pdf(){
 const revoked=[];const context={window:{},Blob,setTimeout,clearTimeout,document:{baseURI:'http://localhost/'},URL:class extends URL {static createObjectURL(){return 'blob:'+Math.random();}static revokeObjectURL(url){revoked.push(url);}},AbortController,requestAnimationFrame:fn=>{fn();return 1;},cancelAnimationFrame(){}};
 vm.runInNewContext(fs.readFileSync('frontend/knowledge-document-viewer.js','utf8'),context);
 const s=bind(context.window.KnowledgePdfViewer);Object.assign(s,{documentId:'doc',wanted:new Set(),queue:[],owned:new Set(),controllers:new Set(),activePages:new Map(),sheets:Array.from({length:24},(_,i)=>({number:i+1,url:i?'':'blob:first',state:i?'idle':'ready',error:''})),$refs:{scroll:{querySelector:()=>({scrollIntoView(){}})}}});
 return {s,revoked};
}
test('PDF jumps cancel offscreen reads and prioritize the target with bounded concurrency',async()=>{
 const {s}=pdf(),sent=[];let maximum=0;
 s.fetchPage=(url,options)=>{const wait=deferred();sent.push({url,options,wait});maximum=Math.max(maximum,s.activePages.size);options.signal.addEventListener('abort',()=>wait.reject(Error('cancelled')));return wait.promise;};
 for(const n of [2,3,4]){s.wanted.add(n);s.enqueue(n);}
 assert.equal(sent.length,1);s.jumpTo(24);await tick();
 assert.ok(sent[0].options.signal.aborted);
 assert.equal(sent.length,2);assert.match(sent[1].url,/page=24$/);assert.equal(sent[1].options.headers.Accept,'image/webp');
 assert.equal(s.sheets[1].state,'idle');assert.equal(s.sheets[3].state,'idle');assert.ok(maximum<=1);
 sent[1].wait.resolve(new Response('page'));await tick();assert.equal(s.sheets[23].state,'ready');assert.equal(s.activePages.size,0);
});
test('closing a PDF prevents late response bodies from creating object URLs',async()=>{
 const {s}=pdf(),body=deferred();s.fetchPage=async()=>({ok:true,blob:()=>body.promise});s.wanted.add(2);s.enqueue(2);await tick();s.disposed=true;
 for(const c of s.controllers)c.abort();body.resolve(new Blob(['old']));await tick();assert.equal(s.owned.size,0);assert.equal(s.activePages.size,0);
});
test('a failed PDF image has a retryable error and releases its owned object URL',()=>{
 const {s,revoked}=pdf(),sheet=s.sheets[1];sheet.url='blob:bad';s.owned.add(sheet.url);s.imageFailed(sheet);
 assert.equal(sheet.state,'error');assert.match(sheet.error,/重试/);assert.deepEqual(revoked,['blob:bad']);assert.equal(s.owned.size,0);
});
test('busy preview reads drain each response and retry at most twice without another operation',async()=>{
 const {s}=pdf(),delays=[];let calls=0,bodies=0;
 s.pageRetry=async(signal,ms)=>delays.push(ms);
 s.fetchPage=async()=>++calls<3?{ok:false,status:429,json:async()=>{bodies++;return {detail:'busy'};}}:new Response('image');
 s.wanted.add(2);s.enqueue(2);await tick();assert.equal(calls,3);assert.equal(bodies,2);assert.deepEqual(delays,[400,800]);assert.equal(s.sheets[1].state,'ready');
 const other=pdf().s;let failures=0;other.pageRetry=async()=>{};other.fetchPage=async()=>{failures++;return new Response('{"detail":"busy"}',{status:503});};
 other.wanted.add(2);other.enqueue(2);await tick();assert.equal(failures,3);assert.equal(other.sheets[1].state,'error');assert.equal(other.activePages.size,0);
});
test('a page change interrupts retry backoff instead of restarting an abandoned preview',async()=>{
 const {s}=pdf();let calls=0;
 s.fetchPage=async()=>{calls++;return new Response('{"detail":"busy"}',{status:429});};s.wanted.add(2);s.enqueue(2);await tick();
 assert.equal(s.sheets[1].waiting,true);s.activePages.get(2).abort();await tick();
 assert.equal(calls,1);assert.equal(s.sheets[1].state,'idle');assert.equal(s.sheets[1].waiting,false);
});
