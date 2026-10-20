const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
let definition;
const app = { component() { return this; }, use() { return this; }, mount() {} };
const message = { warning() {}, success() {}, error(value) { throw Error(value); }, info() {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/script.js'), 'utf8'), {
  Vue: { createApp(value) { definition = value; return app; } },
  ElementPlus: { ElMessage: message }, CompanyKnowledge: {}, AccountManagement: {}, PersonalHome: {}, ReportVersions: {},
  localStorage: { getItem() { return null; } }, Date, JSON, TextDecoder,
  setInterval() { return 1; }, clearInterval() {},
});
const state = definition.data();
for (const [key, method] of Object.entries(definition.methods)) state[key] = method.bind(state);
const calls = [];
const project = { id: 1, title: '人物定位测试', target_name: '林知远', target_type: 'person' };
state.authFetch = async (url, options) => {
  calls.push({ url, payload: options?.body ? JSON.parse(options.body) : null });
  return { ok: true, json: async () => project,
    body: { getReader() { return { async read() { return { done: true }; } }; } } };
};
state.loadProjects = state.loadProjectDetail = async () => {};
state.switchView = () => {};
state.form.projectName = '人物定位测试';
state.form.companyName = '林知远';
state.form.targetType = 'person';
state.form.targetContext = '恒川软件有限公司 / 原CTO';
state.form.personContext = '2018—2022年任职；教育：远山大学';
state.form.personAliases = 'Evan Lin\n林知遠';
state.form.focusQuestions = '核对历史任职';
state.form.aiSearchEnabled = false;
state.selectedFiles = [];

(async () => {
  const run = state.runWorkflow;
  state.runWorkflow = async () => {};
  await state.submitTask();
  const created = calls.find(c => c.url === '/research/projects').payload.metadata;
  assert.equal(created.person_context, state.form.personContext);
  assert.equal(JSON.stringify(created.person_aliases), JSON.stringify(['Evan Lin', '林知遠']));
  state.runWorkflow = run;
  await state.runWorkflow(project);
  const fresh = calls.find(c => c.url.endsWith('/run/stream')).payload;
  assert.equal(fresh.person_context, state.form.personContext);
  assert.equal(fresh.ai_search_enabled, false);
  const intake = { ...created, identity_anchors: '远山大学', as_of_date: '2026-10-20',
    uploaded_identity_clues: [{ subject: '林知远', provenance: 'uploaded_material_unverified' }],
    special_requirements: '核对历史任职及关联机构' };
  await state.runExistingWorkflow(project, intake);
  const resumed = calls.at(-1).payload;
  assert.equal(resumed.identity_anchors, intake.identity_anchors);
  assert.equal(resumed.person_context, intake.person_context);
  assert.equal(resumed.as_of_date, intake.as_of_date);
  assert.equal(resumed.uploaded_identity_clues.length, 1);
  state.projects = [project];
  state.reviewProjectId = project.id;
  state.projectDetails[project.id] = { intake };
  await state.runSecondStage();
  const reviewed = calls.find(c => c.url.includes('/second-stage/')).payload;
  assert.equal(reviewed.person_context, intake.person_context);
  assert.equal(reviewed.identity_anchors, intake.identity_anchors);
  assert.ok(reviewed.focus_questions.includes('核对历史任职'));
  assert.ok(reviewed.special_requirements.includes(intake.special_requirements));
  assert.equal(reviewed.ai_search_enabled, false);
  console.log('Person create, run, resume and second-stage context parameters passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
