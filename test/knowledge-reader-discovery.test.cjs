const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('the generated opaque Word frame contains valid executable source-search code', async () => {
  const window = { addEventListener() {} };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../frontend/knowledge-document-viewer.js'),'utf8'), {
    window, Blob, document: {baseURI:'http://127.0.0.1/'}, URL, crypto:require('node:crypto').webcrypto,
    setTimeout:()=>0, clearTimeout() {},
  });
  const viewer = window.KnowledgeDocumentViewer;
  const context = {...viewer.data(),...viewer.methods,format:'DOCX',blob:{}};
  await viewer.methods.start.call(context);
  const scripts = [...context.source.matchAll(/<script(?: nonce="[^"]+")?>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length,1);
  assert.doesNotThrow(()=>new vm.Script(scripts[0][1]));
  assert.ok(scripts[0][1].includes("split('\\n')"));
  assert.equal(context.source.includes("connect-src 'none'"),true);
});
