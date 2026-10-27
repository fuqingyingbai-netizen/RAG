const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function context() {
  let definition;
  const app = {component() {return this;}, use() {return this;}, mount() {}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/script.js'), 'utf8'), {
    Vue: {createApp(value) {definition = value; return app;}}, ElementPlus: {},
    AccountManagement: {}, PersonalHome: {}, CompanyKnowledge: {}, ReportVersions: {},
    localStorage: {getItem() {return null;}},
  });
  const state = definition.data();
  for (const [name, method] of Object.entries(definition.methods)) state[name] = method.bind(state);
  for (const [name, getter] of Object.entries(definition.computed)) Object.defineProperty(state, name, {get: () => getter.call(state)});
  state.projects = [
    {id: 1, title: '北方项目', target_name: '甲企业', target_type: 'company', status: 'completed', industry: '制造'},
    {id: 2, title: '南方项目', target_name: '李某', target_type: 'person', status: 'failed'},
    {id: 3, title: '北方行业', target_type: 'industry', status: 'cleaning', industry: '机器人'},
    {id: 4, title: '北方人物', target_type: 'person', status: 'paused'},
    {id: 5, title: '新任务', target_type: 'industry', status: 'draft'},
    {id: 6, title: '历史诊断', target_type: 'industry', status: 'diagnostic'},
    {id: 7, title: '兼容任务', target_type: 'company', status: 'future_status'},
  ];
  return {state, watch: definition.watch};
}

test('status, research type and keyword filters combine, including Chinese states', () => {
  const {state} = context();
  assert.equal(state.filteredProjects.length, 7);
  state.taskTargetFilter = 'person';
  assert.deepEqual(Array.from(state.filteredProjects, p => p.id), [2, 4]);
  state.taskStatusFilter = 'paused'; state.taskSearch = '北方';
  assert.deepEqual(Array.from(state.filteredProjects, p => p.id), [4]);
  state.taskSearch = '不存在'; assert.equal(state.filteredProjects.length, 0);
  state.resetTaskFilters(); state.taskSearch = ' 已完成 ';
  assert.deepEqual(Array.from(state.filteredProjects, p => p.id), [1]);
  state.taskSearch = '进行中'; assert.deepEqual(Array.from(state.filteredProjects, p => p.id), [3]);
  state.taskSearch = 'FAILED'; assert.deepEqual(Array.from(state.filteredProjects, p => p.id), [2]);
  state.taskSearch = '机器人'; assert.deepEqual(Array.from(state.filteredProjects, p => p.id), [3]);
  state.resetTaskFilters(); state.taskStatusFilter = 'other';
  assert.deepEqual(Array.from(state.filteredProjects, p => p.id), [7]);
});

test('every known workflow stage is searchable as active and has a Chinese label', () => {
  const {state} = context();
  for (const status of ['planning', 'collecting', 'searching', 'source_assessing', 'cleaning', 'risk_scoring', 'risk_assessing', 'report_generating', 'proposal_generating', 'pausing']) {
    assert.equal(state.taskStatusGroup(status), 'active');
    assert.match(state.taskStatusLabel(status), /[\u4e00-\u9fff]/);
    assert.equal(state.statusType(status), 'warning');
  }
  for (const [status, label] of Object.entries({completed: '已完成', failed: '执行失败', paused: '已暂停', draft: '未开始', diagnostic: '待检查'})) {
    assert.equal(state.taskStatusLabel(status), label);
    assert.equal(state.taskStatusGroup(status), status);
  }
  for (const status of ['future_status', null, 'constructor', '__proto__']) {
    assert.equal(state.taskStatusGroup(status), 'other');
    assert.equal(state.taskStatusLabel(status), '待处理');
  }
});

test('filter changes reset pagination and shrinking results clamp the current page', () => {
  const {state, watch} = context();
  for (const field of ['taskSearch', 'taskStatusFilter', 'taskTargetFilter', 'taskPageSize']) {
    state.taskPage = 6; watch[field].call(state); assert.equal(state.taskPage, 1);
  }
  state.taskPageSize = 2; state.taskPage = 4;
  watch.filteredProjects.call(state, state.projects.slice(0, 3)); assert.equal(state.taskPage, 2);
  watch.filteredProjects.call(state, []); assert.equal(state.taskPage, 1);
  state.taskPage = 2; assert.deepEqual(Array.from(state.pagedProjects, p => p.id), [3, 4]);
  state.taskSearch = '有内容'; state.taskStatusFilter = 'failed'; state.taskTargetFilter = 'person';
  assert.equal(state.hasTaskFilters, true); state.resetTaskFilters();
  assert.equal(state.hasTaskFilters, false); assert.equal(state.taskPage, 1);
});

test('filtering out the review selection clears pending files and prevents acting on a hidden task', () => {
  const {state, watch} = context();
  state.reviewProjectId = 1;
  state.reviewReportFiles = ['report']; state.reviewProposalFiles = ['proposal']; state.fieldSourceFiles = ['interview'];
  watch.pagedProjects.call(state, state.projects);
  assert.equal(state.reviewProjectId, 1); assert.equal(state.reviewReportFiles.length, 1);
  watch.pagedProjects.call(state, state.projects.slice(1));
  assert.equal(state.reviewProjectId, '');
  assert.equal(state.reviewReportFiles.length + state.reviewProposalFiles.length + state.fieldSourceFiles.length, 0);
  state.reviewProjectId = 7; state.taskPageSize = 2; state.taskPage = 1;
  watch.pagedProjects.call(state, state.pagedProjects);
  assert.equal(state.reviewProjectId, '');
});
