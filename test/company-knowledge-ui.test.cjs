const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const component = vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/company-knowledge.js'), 'utf8') + '\nCompanyKnowledge;');

test('multiple chunks from one file become one card without losing citation IDs', () => {
  const references = [1, 2, 3, 4, 5].map(id => ({ id: String(id), document_id: 'file-a', title: 'Report' }));
  const groups = component.methods.referenceGroups(references);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].references.length, 5);
  assert.equal(component.methods.referenceIds(groups[0]), 'id_1、id_2、id_3、id_4、id_5');
});

test('different files with identical names are not merged', () => {
  const groups = component.methods.referenceGroups([
    { id: '1', document_id: 'file-a', title: 'Report' },
    { id: '2', document_id: 'file-b', title: 'Report' },
  ]);
  assert.equal(groups.length, 2);
});

test('progress updates finish a stage and preserve repeated retrieval rounds', () => {
  const answer = { progress: [] };
  const context = { answerStatus: '' };
  const update = event => component.methods.updateProgress.call(context, answer, event);
  update({ stage: 'connecting', label: 'Connecting' });
  update({ stage: 'retrieving', label: 'Searching' });
  update({ stage: 'retrieving', label: 'Found', finished: true });
  assert.equal(answer.progress.length, 2);
  assert.equal(answer.progress[0].state, 'done');
  update({ stage: 'retrieving', label: 'Searching again' });
  assert.equal(answer.progress.length, 3);
  component.methods.finishProgress(answer, true);
  assert.equal(answer.progress[2].state, 'error');
});
