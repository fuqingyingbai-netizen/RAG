/** Capture immutable native report candidates; never grant semantic approval. */
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import http from 'node:http';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const run=path.join(root,'work/company-phase1-20261028');
const sha=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
const inside=(parent,child)=>{
  const relative=path.relative(parent,child);
  return relative!==''&&!relative.startsWith('..'+path.sep)&&relative!=='..'&&!path.isAbsolute(relative);
};
const require=createRequire(path.resolve(path.dirname(process.execPath),'../node_modules/__codex_require__.js'));

export async function validateCandidate(directory){
  const candidate=await fs.realpath(directory);
  if(!inside(path.join(run,'review-candidates'),candidate))throw Error('Candidate must be in the isolated review-candidates directory.');
  const manifestBytes=await fs.readFile(path.join(candidate,'candidate-manifest.json'));
  const manifest=JSON.parse(manifestBytes);
  if(manifest.version!=='company-phase1-review-candidate-v1'||!['haitian','kingsoft','holdout'].includes(manifest.case)
      ||! /^[a-f0-9]{64}$/.test(manifest.candidate_id)||path.basename(candidate)!==manifest.candidate_id
      ||path.basename(path.dirname(candidate))!==manifest.case)throw Error('Invalid immutable candidate identity.');
  const contract=manifest.native_content_and_export_contract;
  if(contract?.status!=='passed'||contract.export_status!=='passed'||contract.delivery_ready!==true
      ||contract.errors?.length||contract.report_sha256!==manifest.report_sha256)throw Error('Native content/export contract has not passed.');
  const files=new Map();
  for(const [name,record] of Object.entries(manifest.files??{})){
    const filename=path.resolve(candidate,name);
    if(!inside(candidate,filename)||!inside(candidate,await fs.realpath(filename)))throw Error('Escaped candidate asset.');
    const bytes=await fs.readFile(filename);
    if(sha(bytes)!==record.sha256||bytes.length!==record.bytes)throw Error('Candidate file hash/size mismatch: '+name);
    files.set(name.split(path.sep).join('/'),bytes);
  }
  for(const name of ['报告.md','报告.html','分析主报告.docx','完整证据附件.html','原生交付包.zip']){
    if(!files.has(name))throw Error('Missing candidate delivery file: '+name);
  }
  if(sha(files.get('报告.md'))!==manifest.report_sha256)throw Error('Report Markdown hash mismatch.');
  const native=path.join(run,'native',manifest.case);
  const proofNames=Object.keys(manifest.native_run_proofs??{});
  if(proofNames.length!==3||!proofNames.some(n=>/^bounded-plan-.*\.json$/.test(n))
      ||!proofNames.some(n=>/^bounded-result-.*\.json$/.test(n))||!proofNames.includes('acceptance.json'))throw Error('Missing native run proof.');
  for(const [name,digest] of Object.entries(manifest.native_run_proofs)){
    const filename=path.resolve(native,name);
    if(path.dirname(filename)!==native||sha(await fs.readFile(filename))!==digest)throw Error('Native run proof changed: '+name);
  }
  return {candidate,manifest,manifest_sha256:sha(manifestBytes),files};
}

export async function captureTiles(page,view,destination){
  const documentHeight=await page.evaluate(()=>document.documentElement.scrollHeight);
  const step=view.height-100,maxTop=Math.max(0,documentHeight-view.height);
  if(step<=0)throw Error('Viewport is too short for overlapping screenshot coverage.');
  const positions=[],screenshots=[];
  for(let y=0;y<maxTop;y+=step)positions.push(y);
  if(positions.at(-1)!==maxTop)positions.push(maxTop);
  for(const [index,y] of positions.entries()){
    await page.evaluate(top=>scrollTo(0,top),y);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const actual=await page.evaluate(()=>scrollY);
    const name=view.name+'-'+String(index+1).padStart(4,'0')+'.png';
    const bytes=await page.screenshot({path:path.join(destination,name),animations:'disabled'});
    screenshots.push({name,scroll_y:actual,sha256:sha(bytes),visual_review:'pending'});
  }
  return screenshots;
}

async function capture(directory){
  // Validate before launching Chromium or serving any content.
  const checked=await validateCandidate(directory);
  const {candidate,manifest,files}=checked;
  const executable=path.join(run,'render-runtime/playwright/chromium-1228/chrome-win64/chrome.exe');
  const {chromium}=require('playwright');
  const executableSha=sha(await fs.readFile(executable));
  const destination=path.join(run,'browser-reviews',manifest.case,manifest.candidate_id,
    new Date().toISOString().replace(/[:.]/g,'-'));
  await fs.mkdir(destination,{recursive:true});
  const types={'.html':'text/html; charset=utf-8','.md':'text/plain; charset=utf-8',
    '.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.svg':'image/svg+xml','.webp':'image/webp'};
  const server=http.createServer((request,response)=>{
    try{
      const name=decodeURIComponent(new URL(request.url,'http://localhost').pathname).slice(1);
      const bytes=files.get(name);
      if(request.method!=='GET'||!bytes){response.writeHead(404);response.end();return;}
      response.writeHead(200,{'Content-Type':types[path.extname(name)]??'application/octet-stream','Cache-Control':'no-store'});
      response.end(bytes);
    }catch{response.writeHead(400);response.end();}
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  const origin='http://127.0.0.1:'+server.address().port;
  let browser;
  const result={observed_at:new Date().toISOString(),case:manifest.case,candidate_id:manifest.candidate_id,
    candidate_directory:candidate,manifest_sha256:checked.manifest_sha256,report_sha256:manifest.report_sha256,
    native_code_commit:manifest.native_code_commit,source_files_verified:true,
    script_sha256:sha(await fs.readFile(fileURLToPath(import.meta.url))),
    chromium_sha256:executableSha,node_executable:process.execPath,
    views:[],browser_visual_review:'pending',human_semantic_review:'pending',final_accepted:false};
  try{
    browser=await chromium.launch({executablePath:executable,headless:true});
    result.browser_version=browser.version();
    for(const view of [{name:'desktop',width:1440,height:1000},{name:'mobile',width:390,height:844}]){
      const context=await browser.newContext({viewport:{width:view.width,height:view.height},deviceScaleFactor:1});
      const page=await context.newPage();
      const blocked=[],errors=[],badResponses=[];
      await page.route('**/*',route=>{
        const url=route.request().url();
        if(url.startsWith(origin+'/'))return route.continue();
        blocked.push(url);return route.abort();
      });
      page.on('pageerror',error=>errors.push(error.message));
      page.on('response',response=>{if(response.status()>=400)badResponses.push({url:response.url(),status:response.status()});});
      await page.goto(origin+'/'+encodeURIComponent('报告.html'),{waitUntil:'load',timeout:30000});
      await page.evaluate(()=>document.fonts.ready);
      const observed=await page.evaluate(()=>({
        markdown_sha256:document.querySelector('meta[name="source-markdown-sha256"]')?.content,
        headings:[...document.querySelectorAll('article h2')].map(e=>({id:e.id,text:e.textContent})),
        image_status:[...document.images].map(e=>({src:e.getAttribute('src'),complete:e.complete,width:e.naturalWidth})),
        viewport_width:innerWidth,document_width:document.documentElement.scrollWidth,
        document_height:document.documentElement.scrollHeight,
        internal_anchor_errors:[...document.querySelectorAll('a[href^="#"]')].map(e=>e.getAttribute('href')).filter(h=>!document.getElementById(h.slice(1))),
      }));
      if(observed.markdown_sha256!==manifest.report_sha256)throw Error('HTML is not bound to this Markdown.');
      const issues=[];
      const ids=observed.headings.map(e=>e.id);
      if(JSON.stringify(ids)!==JSON.stringify(Array.from({length:14},(_,i)=>'chapter-'+(i+1))))issues.push('Expected all 14 ordered report chapters.');
      if(observed.document_width>view.width+1)issues.push('Horizontal page overflow.');
      if(observed.image_status.some(i=>!i.complete||!i.width))issues.push('Missing/undecoded image.');
      if(observed.internal_anchor_errors.length)issues.push('Broken internal chapter anchors.');
      if(errors.length||badResponses.length||blocked.length)issues.push('Browser load errors or external asset requests require review.');
      // Overlapping viewport tiles cover the full page at 1:1 CSS pixels.
      const screenshots=await captureTiles(page,view,destination);
      result.views.push({...view,...observed,issues,blocked_requests:blocked,page_errors:errors,bad_responses:badResponses,screenshots});
      await context.close();
    }
    // Guard against a concurrent change while screenshots were being made.
    const after=await validateCandidate(candidate);
    if(after.manifest_sha256!==checked.manifest_sha256)throw Error('Candidate manifest changed during capture.');
    result.capture_completed=true;
    result.automated_layout_status=result.views.every(v=>v.issues.length===0)?'passed':'needs_review';
  }catch(error){result.capture_completed=false;result.error=String(error);throw error;}
  finally{
    await Promise.allSettled([browser?.close(),new Promise(resolve=>server.close(resolve))]);
    await fs.writeFile(path.join(destination,'browser-proof.json'),JSON.stringify(result,null,2)+'\n');
  }
  console.log(JSON.stringify({destination,automated_layout_status:result.automated_layout_status,
    screenshots:result.views.reduce((n,v)=>n+v.screenshots.length,0),browser_visual_review:'pending',final_accepted:false}));
}

if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  if(process.argv.length!==3)throw Error('Usage: bundled-node diagnostics/company_phase1_browser_review.mjs CANDIDATE_DIRECTORY');
  await capture(process.argv[2]);
}
