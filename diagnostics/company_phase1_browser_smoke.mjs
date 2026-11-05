import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {captureTiles,validateCandidate} from './company_phase1_browser_review.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const directory=path.join(root,'work/company-phase1-20261028');
const out=path.join(directory,'browser-capture-smoke-'+Date.now());
await fs.mkdir(out,{recursive:true});
const require=createRequire(path.resolve(path.dirname(process.execPath),'../node_modules/__codex_require__.js'));
const {chromium}=require('playwright');
const exe=path.join(directory,'render-runtime/playwright/chromium-1228/chrome-win64/chrome.exe');
const browser=await chromium.launch({executablePath:exe,headless:true});
const views=[];
try{
  for(const view of [{name:'desktop',width:1440,height:1000},{name:'mobile',width:390,height:844}]){
    const page=await browser.newPage({viewport:{width:view.width,height:view.height},deviceScaleFactor:1});
    await page.setContent('<!doctype html><meta charset="utf-8"><style>body{margin:0;font:18px/1.8 "Microsoft YaHei";color:#111}main{max-width:900px;margin:auto;padding:24px}section{min-height:290px;border-bottom:1px solid #aaa}h2{font-size:24px}</style><main>'+Array.from({length:14},(_,i)=>'<section><h2 id="chapter-'+(i+1)+'">'+(i+1)+'. 中文长页截图自检</h2><p>这是合成排版样例，只测试截图覆盖，不是企业报告，也不构成报告验收。</p><p>原文、期间、金额：2025 年 0 元。第 '+(i+1)+' 章。</p></section>').join('')+'</main>');
    await page.evaluate(()=>document.fonts.ready);
    const height=await page.evaluate(()=>document.documentElement.scrollHeight);
    const screenshots=await captureTiles(page,view,out);
    assert.equal(screenshots[0].scroll_y,0);
    assert.equal(screenshots.at(-1).scroll_y,Math.max(0,height-view.height));
    for(let i=1;i<screenshots.length;i++)assert(screenshots[i].scroll_y<=screenshots[i-1].scroll_y+view.height);
    assert(screenshots.length>1);
    for(const shot of screenshots){
      const bytes=await fs.readFile(path.join(out,shot.name));
      assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),shot.sha256);
      assert.equal(shot.visual_review,'pending');
    }
    views.push({...view,document_height:height,coverage_verified:true,screenshots});
    await page.close();
  }
  await assert.rejects(validateCandidate(root),/review-candidates directory/);
  const fixture=crypto.randomBytes(32).toString('hex');
  const fixtureDirectory=path.join(directory,'review-candidates/haitian',fixture);
  await fs.mkdir(fixtureDirectory,{recursive:true});
  const manifest=path.join(fixtureDirectory,'candidate-manifest.json');
  try{
    // Intentionally unapproved synthetic manifest; no native database or proof is written.
    await fs.writeFile(manifest,JSON.stringify({version:'company-phase1-review-candidate-v1',case:'haitian',candidate_id:fixture,
      native_content_and_export_contract:{status:'needs_repair'},synthetic_validation_fixture:true}));
    await assert.rejects(validateCandidate(fixtureDirectory),/contract has not passed/);
  }finally{
    assert(path.dirname(fixtureDirectory)===path.join(directory,'review-candidates/haitian'));
    await fs.unlink(manifest);await fs.rmdir(fixtureDirectory);
  }
  const script=path.join(root,'diagnostics/company_phase1_browser_review.mjs');
  const proof={at:new Date().toISOString(),scope:'synthetic long-page capture and rejection smoke only',
    script_sha256:crypto.createHash('sha256').update(await fs.readFile(script)).digest('hex'),
    smoke_script_sha256:crypto.createHash('sha256').update(await fs.readFile(fileURLToPath(import.meta.url))).digest('hex'),
    browser_version:browser.version(),views,candidate_outside_root_rejected:true,unapproved_candidate_rejected:true,
    native_business_files_modified:false,final_report_capture_executed:false,final_report_accepted:false,
    visual_review:'pending'};
  await fs.writeFile(path.join(out,'smoke-proof.json'),JSON.stringify(proof,null,2)+'\n');
  console.log(JSON.stringify({out,screenshots:views.map(v=>({view:v.name,count:v.screenshots.length,height:v.document_height})),
    candidate_rejection_checks:2,final_report_accepted:false}));
}finally{await browser.close();}
