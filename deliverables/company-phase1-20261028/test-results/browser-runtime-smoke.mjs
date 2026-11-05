import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
const require=createRequire('C:/Users/wangli/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/__codex_require__.js');
const {chromium}=require('playwright');
const directory=path.resolve(process.argv[2]??path.dirname(fileURLToPath(import.meta.url)));
const executablePath=path.join(directory,'render-runtime/playwright/chromium-1228/chrome-win64/chrome.exe');
const browser=await chromium.launch({executablePath,headless:true});
try {
  const page=await browser.newPage({viewport:{width:1280,height:960}});
  await page.setContent('<!doctype html><meta charset="utf-8"><title>浏览器环境自检</title><style>body{font:20px "Microsoft YaHei",sans-serif;margin:40px}</style><h1>浏览器环境自检</h1><p>仅验证本地中文排版与截图功能，不是报告验收。</p><table><tr><td>数值与期间</td><td>2025年 0元</td></tr></table>');
  await page.evaluate(()=>document.fonts.ready);
  const output=path.join(directory,'browser-runtime-smoke.png');
  await page.screenshot({path:output,fullPage:true});
  const result={browser_version:browser.version(),executable:executablePath,
    node_executable:process.execPath,
    script_sha256:crypto.createHash('sha256').update(await fs.readFile(fileURLToPath(import.meta.url))).digest('hex'),
    executable_sha256:crypto.createHash('sha256').update(await fs.readFile(executablePath)).digest('hex'),
    screenshot_sha256:crypto.createHash('sha256').update(await fs.readFile(output)).digest('hex'),
    displayed_text:await page.locator('body').innerText(),report_acceptance:false,
    note:'Local runtime smoke only; no report or semantic quality approval.'};
  await fs.writeFile(path.join(directory,'browser-runtime-proof.json'),JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify({browser_version:result.browser_version,screenshot:output,report_acceptance:false}));
} finally {await browser.close();}
