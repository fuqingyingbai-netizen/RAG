const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function context() {
  let definition;
  const notices = [];
  const app = {component() {return this;}, use() {return this;}, mount() {}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/script.js'), 'utf8'), {
    Vue: {createApp(value) {definition = value; return app;}},
    ElementPlus: {ElMessage: {success(text) {notices.push(['success', text]);}, error(text) {notices.push(['error', text]);}}},
    AccountManagement: {}, PersonalHome: {}, CompanyKnowledge: {}, ReportVersions: {},
    localStorage: {getItem() {return null;}}, TextDecoder,
    setInterval() {return 1;}, clearInterval() {},
  });
  const state = definition.data();
  for (const [name, method] of Object.entries(definition.methods)) state[name] = method.bind(state);
  state.loadProjects = async () => {};
  return {state, notices};
}

function deferred() {
  let resolve;
  const promise = new Promise(done => {resolve = done;});
  return {promise, resolve};
}

test('rerun immediately becomes busy and repeated clicks cannot submit a second request', async () => {
  const {state, notices} = context();
  const intake = deferred(), stream = deferred();
  const project = {id: 68, status: 'completed', target_type: 'industry'};
  let gets = 0, runs = 0, refreshes = 0;
  state.authFetch = async () => {gets++; return intake.promise;};
  state.refreshProjectProgress = async () => {refreshes++;};
  state.runExistingWorkflow = async (p, saved, connected) => {
    runs++; assert.equal(saved.marker, 'saved-input'); connected(); await stream.promise;
  };
  const running = state.rerunProject(project);
  assert.equal(state.startingProjects[68], true);
  await state.rerunProject(project);
  await new Promise(setImmediate);
  assert.equal(gets, 1); assert.equal(runs, 0);
  intake.resolve({ok: true, json: async () => ({intake: {marker: 'saved-input'}})});
  await new Promise(setImmediate);
  assert.equal(runs, 1); assert.equal(refreshes, 1);
  assert.equal(notices[0][0], 'success'); assert.match(notices[0][1], /请求已接收/);
  assert.equal(state.startingProjects[68], true);
  stream.resolve(); await running;
  assert.equal(state.startingProjects[68], undefined);
});

test('intake failure shows its reason and re-enables the button without launching a task', async () => {
  const {state, notices} = context();
  const project = {id: 68};
  let runs = 0;
  state.authFetch = async () => ({ok: false, json: async () => ({detail: '无权操作此项目'})});
  state.runExistingWorkflow = async () => {runs++;};
  await state.rerunProject(project);
  assert.equal(runs, 0); assert.equal(state.startingProjects[68], undefined);
  assert.deepEqual(notices, [['error', '无权操作此项目']]);
});

test('stream connection feedback is delivered before waiting for the entire research run', async () => {
  const {state} = context();
  const reading = deferred();
  let connected = false, finished = false;
  state.authFetch = async () => ({ok: true, body: {getReader() {return {read() {return reading.promise;}};}}});
  const promise = state.runExistingWorkflow({id: 68, target_type: 'industry'}, {}, () => {connected = true;})
    .then(() => {finished = true;});
  await new Promise(setImmediate);
  assert.equal(connected, true); assert.equal(finished, false);
  reading.resolve({done: false, value: Buffer.from('data: {"type":"result","project":{"id":68,"status":"completed"},"artifacts":[]}\n\n')}); await promise;
  assert.equal(finished, true);
});

test('a rejected stream is never announced as an accepted request', async () => {
  const {state} = context();
  let connected = false;
  state.authFetch = async () => ({ok: false, json: async () => ({detail: '任务启动被拒绝'})});
  await assert.rejects(state.runExistingWorkflow({id: 68, target_type: 'industry'}, {}, () => {connected = true;}), /任务启动被拒绝/);
  assert.equal(connected, false);
});
