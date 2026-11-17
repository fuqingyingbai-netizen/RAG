const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let definition, fail = false;
const rows = JSON.parse(fs.readFileSync('backend/industry_chapters.json', 'utf8')).chapters;
const config = {version: 'test-v1', defaults: rows.filter(c => c.default_selected).map(c => c.id),
  chapters: rows.map(c => ({chapter:c.chapter, value:c.id, label:c.title, selectable:c.selectable}))};
const context = vm.createContext({Vue:{createApp(v){definition=v; return {component(){return this},use(){return this},mount(){}}}},
  ElementPlus:{}, CompanyKnowledge:{}, AccountManagement:{}, PersonalHome:{}, ReportVersions:{}, localStorage:{getItem(){return null}}, Date, JSON,
  fetch:async url => {assert.equal(url, '/research/industry-chapters'); return {ok:!fail,json:async()=>config}}});
vm.runInContext(fs.readFileSync('frontend/project-workspace.js','utf8'), context);
vm.runInContext(fs.readFileSync('frontend/script.js','utf8'), context);
(async () => {
  const state = definition.data();
  Object.assign(state, definition.methods);
  state.form.targetType='industry';
  assert.equal(await state.loadIndustryChapters(), true);
  assert.equal(state.modulesByTarget.industry.filter(c=>c.selectable).length,12);
  assert.equal(state.form.modules.length,9);
  assert.ok(!state.form.modules.includes('industry.ch01'));
  state.form.modules=['industry.ch04'];
  const payload=state.industryRunFields('industry');
  assert.equal(JSON.stringify(payload.industry_chapter_ids),'["industry.ch04"]');
  assert.equal(payload.industry_template_version,'test-v1');
  const resumed=state.industryRunFields('industry',payload);
  assert.equal(JSON.stringify(resumed.industry_chapter_ids),'["industry.ch04"]');
  assert.equal(state.industryRunFields('industry',{focus_modules:['市场规模与增长']}).industry_chapter_ids,undefined);
  assert.equal(JSON.stringify(state.industryRunFields('company')),'{}');
  await state.loadIndustryChapters();
  assert.equal(JSON.stringify(state.form.modules),'["industry.ch04"]');
  fail=true;
  assert.equal(await state.loadIndustryChapters(),false);
  assert.ok(state.industryChapterError);
  assert.equal(state.industryChaptersLoading,false);
  console.log('Industry chapter UI loading, retry, selection, legacy resume and isolation passed');
})().catch(e=>{console.error(e);process.exitCode=1});
