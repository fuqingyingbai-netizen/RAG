const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let appDefinition;
const messages = [];
const storage = new Map([['activeView', 'accounts']]);
const context = {
  Vue: {createApp(value) {appDefinition = value; return {component() {return this;}, use() {return this;}, mount() {}};}},
  PersonalHome: {}, AccountManagement: {}, ReportVersions: {}, CompanyKnowledge: {}, Date, JSON, URL, URLSearchParams,
  ElementPlus: {ElMessage: {error(value) {messages.push(value);}}},
  localStorage: {getItem(key) {return storage.get(key) || null;}, setItem(key, value) {storage.set(key, value);}, removeItem(key) {storage.delete(key);}},
  document: {visibilityState: 'visible'}, setInterval() {return 1;}, clearInterval() {},
};
vm.runInNewContext(fs.readFileSync('frontend/script.js', 'utf8'), context);
const homeDefinition = vm.runInNewContext(fs.readFileSync('frontend/personal-home.js', 'utf8') + '\nPersonalHome;', context);
function state(definition, props = {}) {
  const value = {...definition.data(), ...props};
  for (const [key, fn] of Object.entries(definition.methods)) value[key] = fn.bind(value);
  for (const [key, fn] of Object.entries(definition.computed || {})) Object.defineProperty(value, key, {get: () => fn.call(value)});
  return value;
}
function homeData(id) {return {user: {username: 'employee', display_name: '同事'}, summary: {total: 0, running: 0, completed: 0, attention: 0}, recent_projects: [], recent_reports: [], id};}
function deferred() {let resolve; const promise = new Promise(done => {resolve = done;}); return {promise, resolve};}
const watchdog = setTimeout(() => {console.error('Personal home tests did not finish'); process.exitCode = 1;}, 5000);
(async () => {
  const app = state(appDefinition);
  assert.equal(app.activeView, 'home'); // Ignore another account's last view.
  const workspace = state(appDefinition);
  workspace.loadProjects = async () => {}; workspace.refreshVisibleTaskProgress = () => {};
  let repositoryLoads = 0; workspace.loadRepository = async () => { repositoryLoads++; };
  workspace.switchView('submit');
  assert.equal(workspace.activeView, 'tasks'); assert.equal(workspace.taskCreateOpen, true);
  assert.equal(workspace.pageTitle, '尽调任务'); assert.equal(workspace.isTaskWorkspace, true);
  workspace.switchView('review'); assert.equal(workspace.taskCreateOpen, false); assert.equal(workspace.pageTitle, '尽调任务');
  workspace.switchView('sources'); assert.equal(repositoryLoads, 1); assert.equal(workspace.pageTitle, '尽调任务');
  assert.equal(workspace.workspaceLinkLabel({view:'review',label:'复核与一手资料'}), '尽调任务 · 资料整理与复核');
  workspace.switchView('home'); assert.equal(workspace.isTaskWorkspace, false);
  for (const [view,title] of [['workbench','工作台'],['research','研究任务']]) {
    workspace.switchView(view); assert.equal(workspace.activeView, view);
    assert.equal(workspace.pageTitle, title); assert.equal(workspace.isTaskWorkspace, false);
    workspace.ensureAllowedView(); assert.equal(workspace.activeView, view);
  }
  workspace.switchView('due-diligence'); assert.equal(workspace.activeView, 'tasks');
  assert.equal(workspace.pageTitle, '尽调任务'); assert.equal(workspace.isTaskWorkspace, true);
  workspace.activeView = 'due-diligence'; workspace.ensureAllowedView(); assert.equal(workspace.activeView, 'tasks');
  workspace.switchView('submit'); workspace.handleLogout(); assert.equal(workspace.taskCreateOpen, false);
  app.activeView = 'accounts'; app.loadAssistantState = () => {}; app.loadProjects = async () => {};
  await app.acceptAuthentication({access_token: 'employee', username: 'employee', role: 'user'});
  assert.equal(app.activeView, 'home');
  app.activeView = 'tasks';
  await app.acceptAuthentication({access_token: 'new-token', username: 'employee', role: 'user'}, {openHome: false});
  assert.equal(app.activeView, 'tasks');
  app.currentUser = {role: 'user'}; app.switchView('accounts'); assert.equal(app.activeView, 'tasks');
  app.projects = Array.from({length: 25}, (_, index) => ({id: index + 1}));
  app.taskSearch = 'old filter'; app.taskStatusFilter = 'failed'; app.taskTargetFilter = 'person'; app.taskPage = 1;
  let ticks = 0, selected;
  app.$nextTick = async () => {if (++ticks === 1) app.taskPage = 1;};
  app.viewProject = async project => {selected = project;};
  await app.openHomeProject({id: 20});
  assert.equal(app.taskSearch, ''); assert.equal(app.taskStatusFilter, ''); assert.equal(app.taskTargetFilter, '');
  assert.equal(app.taskPage, 2); assert.equal(selected.id, 20);
  app.activeView = 'home'; await app.openHomeProject({id: 999});
  assert.equal(app.activeView, 'home'); assert.match(messages.at(-1), /不存在|无法访问/);
  app.loadProjects = async () => {app.token = 'another-account';};
  selected = null; await app.openHomeProject({id: 20}); assert.equal(selected, null);
  app.form.projectName = 'private unfinished task'; app.reviewProjectId = '20'; app.fieldSourceFiles = [{name: 'private.pdf'}];
  app.openReportVersions({id:20, title:'Private report'}, 'proposal');
  assert.equal(app.reportVersionsOpen, true); assert.equal(app.reportVersionsType, 'proposal');
  app.handleLogout();
  assert.equal(app.reportVersionsOpen, false); assert.equal(app.reportVersionsProject, null);
  assert.equal(app.activeView, 'home'); assert.equal(app.form.projectName, '');
  assert.equal(app.taskStatusFilter, ''); assert.equal(app.taskTargetFilter, '');
  assert.equal(app.reviewProjectId, ''); assert.equal(app.fieldSourceFiles.length, 0);
  const late = state(appDefinition); late.token = 'before'; late.projects = [];
  late.authFetch = async () => ({ok: true, json: async () => {late.token = 'after'; return {projects: [{id: 88}]};}});
  await assert.rejects(late.loadProjects(), /账号已变更/); assert.equal(late.projects.length, 0);
  const home = state(homeDefinition, {currentUser: {username: 'employee'}});
  home.request = async () => ({ok: true, json: async () => homeData(1)});
  await home.loadHome(); assert.equal(home.displayName, '同事'); assert.equal(home.home.summary.total, 0);
  const tasks = [
    {id:1,status:'completed',is_running:false}, {id:2,status:'paused',is_running:false},
    {id:3,status:'searching',is_running:true}, {id:4,status:'failed',is_running:false},
  ];
  home.home.recent_projects = tasks;
  assert.deepEqual(Array.from(home.priorityProjects, row => row.id), [3,2,4,1]);
  assert.deepEqual(tasks.map(row => row.id), [1,2,3,4]); // Sorting must not mutate the response.
  const metricApp = state(appDefinition); const views = [];
  metricApp.projects = tasks; metricApp.switchView = view => views.push(view);
  metricApp.taskSearch = 'old search'; metricApp.taskTargetFilter = 'company'; metricApp.taskPage = 5;
  metricApp.openHomeTaskFilter('attention');
  assert.equal(metricApp.taskSearch, ''); assert.equal(metricApp.taskTargetFilter, ''); assert.equal(metricApp.taskPage, 1);
  assert.equal(metricApp.taskStatusFilter, 'attention');
  assert.deepEqual(Array.from(metricApp.filteredProjects, row => row.id), [2,4]);
  metricApp.openHomeTaskFilter('completed'); assert.deepEqual(Array.from(metricApp.filteredProjects, row => row.id), [1]);
  metricApp.openHomeTaskFilter('running'); assert.deepEqual(Array.from(metricApp.filteredProjects, row => row.id), [3]);
  metricApp.openHomeTaskFilter('total'); assert.equal(metricApp.filteredProjects.length, 4);
  metricApp.openHomeTaskFilter('unknown'); assert.equal(views.length, 4);
  home.request = async () => {throw new Error('connection failed');};
  await home.loadHome(); assert.equal(home.home.id, 1); assert.match(home.error, /上次加载的数据/);
  const blank = state(homeDefinition, {currentUser: {username: 'employee'}});
  blank.request = home.request; await blank.loadHome(); assert.equal(blank.home, null);
  const oldJson = deferred();
  home.request = async () => ({ok: true, json: () => oldJson.promise});
  const oldRequest = home.loadHome();
  home.request = async () => ({ok: true, json: async () => homeData(2)});
  await home.loadHome(); oldJson.resolve(homeData(0)); await oldRequest; assert.equal(home.home.id, 2);
  const unmountedJson = deferred();
  home.request = async () => ({ok: true, json: () => unmountedJson.promise});
  const unmounted = home.loadHome();
  homeDefinition.beforeUnmount.call(home); unmountedJson.resolve(homeData(99)); await unmounted;
  assert.equal(home.home.id, 2);
  let downloads = 0;
  home.download = async () => {downloads++;};
  await home.downloadReport({id: 1, can_download: false}); assert.equal(downloads, 0);
  await home.downloadReport({id: 2, can_download: true}); assert.equal(downloads, 1);
  console.log('Personal home: default navigation, task pagination, account isolation, failed refresh, stale responses and download checks passed');
})().catch(error => {console.error(error); process.exitCode = 1;}).finally(() => clearTimeout(watchdog));
