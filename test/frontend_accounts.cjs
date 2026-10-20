const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
let definition, sent;
const messages = [];
const storage = new Map();
const context = {
  Vue: {createApp(value) { definition = value; return {component() {return this;}, use() {return this;}, mount() {}};}},
  ElementPlus: {ElMessage: {warning(value) {messages.push(value);}, info() {}, success() {}, error(value) {messages.push(value);}}},
  AccountManagement: {}, PersonalHome: {}, CompanyKnowledge: {}, Date, JSON, URL, URLSearchParams,
  localStorage: {getItem(key) {return storage.get(key) || null;}, setItem(key, value) {storage.set(key, value);}, removeItem(key) {storage.delete(key);}},
  window: {location: {href:'https://company.test/'}, history: {replaceState(...args) {context.replaced = args[2];}}},
  fetch: async (url, options) => {sent = {url, body:JSON.parse(options.body)}; return {ok:true, json:async()=>({access_token:'new',username:'employee',role:'user',must_change_password:false})};},
};
vm.runInNewContext(fs.readFileSync('frontend/script.js', 'utf8'), context);
function state() { const value = definition.data(); for (const [name, fn] of Object.entries(definition.methods)) value[name] = fn.bind(value); value.loadProjects = async () => {}; value.loadAssistantState = () => {}; return value; }
(async () => {
  const app = state(); app.authStep = 'form'; app.authMode = 'register';
  app.authForm = {username:' employee ',password:'Password-pass-123',confirm_password:'Password-pass-123',invitation:'https://company.test/#invite=token'};
  await app.handleAuthSubmit();
  assert.equal(sent.url, '/auth/register'); assert.equal(sent.body.username, 'employee');
  assert.equal(sent.body.invitation, 'https://company.test/#invite=token'); assert.equal(sent.body.confirm_password, 'Password-pass-123');
  assert.ok(!('role' in sent.body) && !('admin_code' in sent.body));
  assert.equal(app.currentUser.username, 'employee'); assert.equal(app.authForm.password, '');
  app.authMode = 'register'; app.authForm = {username:'employee',password:'a',confirm_password:'b',invitation:'token'};
  sent = null; await app.handleAuthSubmit(); assert.equal(sent, null); assert.ok(messages.includes('两次输入的密码不一致'));
  const legacy = state(); legacy.activeView='accounts'; legacy.currentUser={role:'user'}; legacy.ensureAllowedView(); assert.equal(legacy.activeView,'home');
  let loaded = false; legacy.loadProjects = async () => {loaded=true;};
  await legacy.acceptAuthentication({access_token:'forced',username:'employee',role:'user',must_change_password:true}); assert.equal(loaded,false);
  legacy.projectDetails={private:'old data'}; legacy.handleLogout(); assert.equal(Object.keys(legacy.projectDetails).length,0);
  const invitation = state(); invitation.checkInvitation=()=>{};
  context.window.location.href='https://company.test/?invite=query'; invitation.readInvitationFromUrl();
  assert.equal(invitation.authMode,'register'); assert.equal(invitation.authForm.invitation,'query'); assert.equal(context.replaced,'/');
  context.window.location.href='https://company.test/#invite=fragment'; invitation.readInvitationFromUrl(); assert.equal(invitation.authForm.invitation,'fragment');
  const stale = state(); stale.token='before'; context.fetch=async()=>{stale.token='after';return {};};
  await assert.rejects(stale.authFetch('/admin/users'), /登录账号已变更/);
  const page=fs.readFileSync('frontend/index.html','utf8');
  assert.ok(page.includes('currentUser.must_change_password')); assert.ok(page.includes("activeView === 'accounts' && currentUser?.role === 'admin'"));
  assert.ok(!page.includes('管理员邀请码'));
  let management;
  const managementContext = {
    URLSearchParams, Date, JSON,
    navigator: {clipboard: {async writeText(value) {managementContext.copied = value;}}},
    ElementPlus: {...context.ElementPlus, ElMessageBox: {async confirm() {}, async prompt() {return {value: 'Admin-password-123'};}}},
  };
  vm.runInNewContext(fs.readFileSync('frontend/account-management.js', 'utf8') + '\nthis.component = AccountManagement;', managementContext);
  management = managementContext.component;
  const account = management.data();
  for (const [name, fn] of Object.entries(management.methods)) account[name] = fn.bind(account);
  const requests = [];
  account.api = async (url, options) => {
    requests.push({url, options});
    if (url === '/auth/confirm-admin') return {confirmation_token: 'one-use-proof'};
    return {token: 'r'.repeat(43), role: account.inviteRole, expires_at: '2026-10-20T18:00:00Z'};
  };
  account.loadInvitations = async () => {};
  await account.createInvitation();
  assert.equal(account.secretValue, 'r'.repeat(43));
  assert.equal(account.secretTitle, '普通账号邀请码');
  await account.copySecret(); assert.equal(managementContext.copied, 'r'.repeat(43));
  account.inviteRole = 'admin'; requests.length = 0;
  await account.createInvitation();
  assert.equal(requests[0].url, '/auth/confirm-admin');
  assert.equal(JSON.parse(requests[0].options.body).action, 'create_admin_invitation');
  assert.equal(requests[1].options.headers['X-Admin-Confirmation'], 'one-use-proof');
  assert.ok(!requests[1].options.body.includes('password'));
  managementContext.ElementPlus.ElMessageBox.prompt = async () => {throw 'cancel';};
  requests.length = 0; await account.createInvitation(); assert.equal(requests.length, 0);
  managementContext.ElementPlus.ElMessageBox.prompt = async () => ({value: 'Admin-password-123'});
  account.$emit = event => {account.emitted = event;};
  account.loadUsers = async () => {throw new Error('should leave the expired session immediately');};
  account.api = async url => url === '/auth/confirm-admin' ? {confirmation_token: 'proof'} : {requires_relogin: true, message: 'done'};
  await account.demoteUser({id: 1, username: 'admin', is_self: true});
  assert.equal(account.emitted, 'session-invalidated');
  account.loadUsers = async () => {};
  let profileRequest;
  account.api = async (url, options) => {profileRequest = {url, options}; return {message: '账号资料已保存'};};
  account.editProfile({id: 2, username: 'employee', display_name: '同事', notes: '原备注'});
  account.profileForm.notes = '新备注'; await account.saveProfile();
  assert.equal(profileRequest.url, '/admin/users/2/profile');
  assert.deepEqual(JSON.parse(profileRequest.options.body), {display_name: '同事', notes: '新备注'});
  assert.equal(account.profileOpen, false);
  account.editProfile({id: 2, username: 'employee', display_name: '', notes: '保留待保存内容'});
  account.api = async () => {throw new Error('保存失败');};
  await account.saveProfile();
  assert.equal(account.profileOpen, true); assert.equal(account.profileError, '保存失败');
  assert.equal(account.profileForm.notes, '保留待保存内容');
  account.tab = 'audits'; account.auditPage = 4;
  account.auditRange = [new Date(2026, 9, 20), new Date(2026, 9, 21)];
  let auditParams;
  account.api = async url => {
    auditParams = new URL(url, 'https://company.test/').searchParams;
    return {items: [{id: 12}], total: 1, actions: []};
  };
  await account.loadAudits(true);
  assert.equal(auditParams.get('page'), '1');
  assert.equal(auditParams.get('start'), new Date(2026, 9, 20).toISOString());
  assert.equal(auditParams.get('end'), new Date(2026, 9, 22).toISOString());
  let resolveOld;
  account.api = () => new Promise(resolve => {resolveOld = resolve;});
  const oldAudit = account.loadAudits();
  account.api = async () => ({items: [{id: 22}], total: 1, actions: []});
  await account.loadAudits();
  resolveOld({items: [{id: 11}], total: 1, actions: []}); await oldAudit;
  assert.equal(account.audits[0].id, 22);
  const cleanupRequests = [];
  account.api = async (url, options) => {cleanupRequests.push({url, method: options.method}); return {message: '已完成'};};
  await account.deleteInvitation({id: 3, status: 'active'});
  await account.archiveUser({id: 2, is_active: true});
  await account.archiveUser({id: 1, is_active: false, is_self: true});
  assert.equal(cleanupRequests.length, 0);
  managementContext.ElementPlus.ElMessageBox.confirm = async () => {throw 'cancel';};
  await account.deleteInvitation({id: 3, status: 'used'});
  await account.archiveUser({id: 2, is_active: false});
  await account.restoreUser({id: 2, archived_at: '2026-10-20T00:00:00Z'});
  assert.equal(cleanupRequests.length, 0);
  managementContext.ElementPlus.ElMessageBox.confirm = async () => {};
  await account.deleteInvitation({id: 3, status: 'revoked'});
  await account.archiveUser({id: 2, is_active: false});
  await account.restoreUser({id: 2, archived_at: '2026-10-20T00:00:00Z'});
  assert.deepEqual(cleanupRequests, [
    {url: '/admin/invitations/3', method: 'DELETE'},
    {url: '/admin/users/2/archive', method: 'POST'},
    {url: '/admin/users/2/restore', method: 'POST'},
  ]);
  account.invitePage = 2;
  account.loadInvitations = management.methods.loadInvitations.bind(account);
  const pages = [];
  account.api = async url => {pages.push(new URL(url, 'https://company.test').searchParams.get('page')); return {items: [{id: 1}], total: 1};};
  await account.loadInvitations();
  assert.deepEqual(pages, ['2', '1']); assert.equal(account.invitePage, 1);
  console.log('Account registration, role navigation, forced password change and stale response checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
