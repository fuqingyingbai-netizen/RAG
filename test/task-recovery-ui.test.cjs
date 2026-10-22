const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function context() {
  let definition;
  const notices = [];
  const element = {ElMessage: {error: value => notices.push(value), success() {}, warning() {}}, ElMessageBox: {confirm: async () => {}}};
  const app = {component() {return this;}, use() {return this;}, mount() {}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/script.js'), 'utf8'), {
    Vue: {createApp(value) {definition = value; return app;}}, ElementPlus: element,
    AccountManagement: {}, PersonalHome: {}, CompanyKnowledge: {}, ReportVersions: {},
    localStorage: {getItem() {return null;}, setItem() {}}, TextDecoder, setInterval() {return 1;}, clearInterval() {},
  });
  const state = definition.data();
  for (const [name, method] of Object.entries(definition.methods)) state[name] = method.bind(state);
  state.token = 'current-account';
  state.projectDetails[1] = {project: {id: 1, status: 'failed'}, recovery: {running: false, run_notice: 'May run paid services'}};
  state.artifactsByProject[1] = [{id: 7, project_id: 1}];
  return {state, element, notices};
}

test('recovery uses a confirmed matching project snapshot and hides stale advice', () => {
  const {state} = context();
  assert.equal(state.recoveryFor({id: 1, status: 'failed'}).running, false);
  assert.equal(state.recoveryFor({id: 1, status: 'collecting'}), null);
  assert.equal(state.recoveryFor({id: 99, status: 'failed'}), null);
});

test('research starts only after explicit confirmation and never twice while pending', async () => {
  const {state, element} = context(); let release, runs = 0, prompts = 0;
  element.ElMessageBox.confirm = () => {prompts++; return new Promise(resolve => {release = resolve;});};
  state.rerunProject = async () => {runs++;};
  const project = {id: 1, status: 'failed'};
  const pending = state.runRecoveryAction(project, {kind: 'run', label: '继续任务', description: 'Paid services may be used'});
  await state.runRecoveryAction(project, {kind: 'run'});
  assert.equal(runs, 0); assert.equal(prompts, 1);
  release(); await pending;
  assert.equal(runs, 1); assert.equal(state.recoveryBusy[1], undefined);
  element.ElMessageBox.confirm = async () => {throw new Error('cancel');};
  await state.runRecoveryAction(project, {kind: 'run'});
  assert.equal(runs, 1);
});

test('a running project or an account change during confirmation cannot launch research', async () => {
  const {state, element} = context(); let runs = 0, prompts = 0, release;
  state.rerunProject = async () => {runs++;};
  element.ElMessageBox.confirm = () => {prompts++; return new Promise(resolve => {release = resolve;});};
  state.projectDetails[1].recovery.running = true;
  await state.runRecoveryAction({id: 1, status: 'failed'}, {kind: 'run'});
  assert.equal(prompts, 0);
  state.projectDetails[1].recovery.running = false;
  const pending = state.runRecoveryAction({id: 1, status: 'failed'}, {kind: 'run'});
  state.token = 'new-account'; state.recoveryBusy = {99: true};
  release(); await pending;
  assert.equal(runs, 0); assert.equal(state.recoveryBusy[99], true);
});

test('download and knowledge retry use only the loaded project artifact and never rerun research', async () => {
  const {state, notices} = context(); const calls = [];
  state.downloadArtifact = async row => calls.push(['download', row.id]);
  state.retryKnowledge = async row => calls.push(['knowledge', row.id]);
  state.loadProjectDetail = async row => calls.push(['detail', row.id]);
  state.rerunProject = async () => assert.fail('must not run research');
  await state.runRecoveryAction({id: 1}, {kind: 'download', artifact_id: 7});
  await state.runRecoveryAction({id: 1}, {kind: 'retry_knowledge', artifact_id: 7});
  assert.deepEqual(calls, [['download', 7], ['knowledge', 7]]);
  await state.runRecoveryAction({id: 1}, {kind: 'download', artifact_id: 999});
  assert.match(notices[0], /记录已变化/);
  assert.equal(calls.length, 2);
});

test('a failed stream refreshes persisted outcomes without hiding its original error', async () => {
  const {state} = context(); let lists = 0, details = 0;
  state.authFetch = async () => ({ok: true, body: {getReader: () => ({read: async () => {throw new Error('stream interrupted');}})}});
  state.loadProjects = async () => {lists++; throw new Error('list refresh failed');};
  state.loadProjectDetail = async () => {details++; throw new Error('detail refresh failed');};
  await assert.rejects(state.runExistingWorkflow({id: 1, target_type: 'company'}, {}), /stream interrupted/);
  assert.equal(lists, 1); assert.equal(details, 1);
  state.token = 'next-account';
  await state.refreshAfterWorkflow({id: 1}, 'current-account');
  assert.equal(lists, 1); assert.equal(details, 1);
});

test('progress reaching a terminal state refreshes recovery data for an expanded task', async () => {
  const {state} = context(); let details = 0;
  state.projects = [{id: 1, status: 'report_generating'}];
  state.authFetch = async () => ({ok: true, json: async () => ({project: {id: 1, status: 'failed'}, trace: []})});
  state.loadProjectDetail = async row => {details++; assert.equal(row.status, 'failed');};
  await state.refreshProjectProgress(state.projects[0]);
  assert.equal(details, 1); assert.equal(state.projects[0].status, 'failed');
});

test('retrying knowledge from either entry refreshes an expanded snapshot without running research', async () => {
  const {state} = context(); let details = 0;
  const artifact = state.artifactsByProject[1][0];
  state.authFetch = async url => {
    assert.equal(url, '/research/artifacts/7/knowledge/retry');
    return {ok: true, json: async () => ({metadata: {knowledge_sync_status: 'queued'}})};
  };
  state.loadProjectDetail = async row => {assert.equal(row.id, 1); details++;};
  state.rerunProject = async () => assert.fail('must not run research');
  await state.retryKnowledge(artifact);
  assert.equal(details, 1); assert.equal(artifact.metadata.knowledge_sync_status, 'queued');
});

test('second-stage failure refreshes stored outcomes while preserving the reported cause', async () => {
  const {state, notices} = context(); let refreshes = 0;
  state.reviewProjectId = 1; state.projects = [{id: 1, target_type: 'company'}];
  state.authFetch = async () => ({ok: false, json: async () => ({detail: 'second-stage provider unavailable'})});
  state.refreshAfterWorkflow = async (row, token) => {assert.equal(row.id, 1); assert.equal(token, state.token); refreshes++;};
  await state.runSecondStage();
  assert.equal(refreshes, 1); assert.equal(state.secondStageRunning, false);
  assert.match(notices[0], /second-stage provider unavailable/);
});

test('an upload rejected before a source row exists gets guidance without inventing saved data', async () => {
  const {state} = context(); let reads = 0;
  state.projectDetails[1].recovery.saved = {source_records: 0, report_text_records: 0, proposal_text_records: 0};
  state.projectDetails[1].recovery.issues = [];
  state.authFetch = async () => ({ok: false, json: async () => ({detail: '文档解析失败 PRIVATE_EXCEPTION'})});
  state.loadProjectDetail = async () => {reads++;};
  await assert.rejects(state.postTaskUpload(1, '/synthetic-upload', {}), /文档解析失败/);
  const recovery = state.recoveryFor({id: 1, status: 'failed'});
  assert.equal(reads, 1); assert.equal(recovery.saved.source_records, 0);
  assert.match(recovery.issues[0].title, /文件解析/);
  assert.ok(!JSON.stringify(recovery.issues).includes('PRIVATE_EXCEPTION'));
  state.authFetch = async () => ({ok: true, json: async () => ({message: 'saved'})});
  await state.postTaskUpload(1, '/synthetic-upload', {});
  assert.equal(state.taskUploadIssues[1], undefined);
});

test('a late upload response cannot add an issue to the next account', async () => {
  const {state} = context();
  state.authFetch = async () => ({ok: false, json: async () => {state.token = 'different-account'; return {detail: 'old error'};}});
  await assert.rejects(state.postTaskUpload(1, '/synthetic-upload', {}), /账号已变更/);
  assert.equal(state.taskUploadIssues[1], undefined);
});
