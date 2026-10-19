const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function context() {
  let definition;
  const storage = new Map();
  const app = { component() { return this; }, use() { return this; }, mount() {} };
  const localStorage = { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/script.js'), 'utf8'), {
    Vue: { createApp(value) { definition = value; return app; } }, ElementPlus: {}, CompanyKnowledge: {}, localStorage, URL,
  });
  const state = definition.data();
  for (const [name, method] of Object.entries(definition.methods)) state[name] = method.bind(state);
  return { state, storage };
}

test('a newly signed-in account cannot inherit the previous account conversation', () => {
  const { state, storage } = context();
  state.currentUser = { username: 'alice' };
  state.assistantMessages = [{ text: 'Alice private message', isUser: true }];
  state.assistantContextSummary = 'Alice private summary';
  state.saveAssistantState();
  assert.ok(storage.has('systemGuide:v1:alice'));
  state.handleLogout();
  state.currentUser = { username: 'bob' };
  state.loadAssistantState();
  assert.equal(state.assistantContextSummary, '');
  assert.ok(!JSON.stringify(state.assistantMessages).includes('Alice'));
  state.currentUser = { username: 'alice' };
  state.loadAssistantState();
  assert.equal(state.assistantMessages[0].text, 'Alice private message');
});

test('source navigation accepts only public HTTP URLs without embedded credentials', () => {
  const { state } = context();
  for (const url of ['javascript:alert(1)', 'structured://qcc/company', 'https://user:secret@host.test', '//host.test']) {
    assert.equal(state.isExternalUrl(url), false);
  }
  assert.equal(state.isExternalUrl('https://issuer.test/report.pdf'), true);
});
