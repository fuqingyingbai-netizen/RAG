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

test('refresh retains loaded pages and selections across page boundaries', async () => {
  const context = {
    loading: false, serviceError: '', documentPage: 2, selectedIds: ['second'],
    cloudDocuments: [], apiFetch: async url => ({ ok: true, json: async () => ({
      documents: [{ id: url.includes('page_number=2') ? 'second' : 'first', category: '项目原件' }],
      total_count: 101,
    }) }),
  };
  await component.methods.loadDocuments.call(context);
  assert.deepEqual(Array.from(context.cloudDocuments.map(doc => doc.id)), ['first', 'second']);
  assert.deepEqual(Array.from(context.selectedIds), ['second']);
  assert.equal(context.documentPage, 2);
});

test('changing evidence scope starts a new conversation and never changes it mid-generation', () => {
  const context = { busy: false, selectedIds: [], reset: 0, newConversation() { this.reset++; } };
  component.methods.changeScope.call(context, ['one']);
  assert.equal(context.reset, 1);
  assert.deepEqual(context.selectedIds, ['one']);
  context.busy = true;
  component.methods.changeScope.call(context, ['two']);
  assert.deepEqual(context.selectedIds, ['one']);
});

test('filters combine project, industry, processing and review state', () => {
  const context = { recentUploadIds: [], query: 'report', category: '研究成果', projectFilter: 'P1', industryFilter: '汽车',
    statusFilter: 'ready', reviewFilter: '待复核', favoritesOnly: false, favorites: [], documents: [
      { id: 'a', title: 'Report', category: '研究成果', project: 'P1', industry: '汽车', state: 'ready', review: '待复核' },
      { id: 'b', title: 'Report', category: '研究成果', project: 'P2', industry: '汽车', state: 'ready', review: '待复核' },
      { id: 'c', title: 'Report', category: '研究成果', project: 'P1', industry: '汽车', state: 'indexing', review: '待复核' },
    ] };
  assert.deepEqual(Array.from(component.computed.filteredDocuments.call(context).map(doc => doc.id)), ['a']);
});

test('upload dialog follows actual document states by ID and offers retry on failure', () => {
  const context = { uploadResults: [{ id: 'one', name: 'Same.pdf', state: 'Waiting' },
    { id: 'two', name: 'Same.pdf', state: 'Waiting' }, { name: 'Rejected.exe', state: 'Unsupported' }],
    cloudDocuments: [{ id: 'one', state: 'parsing', label: 'Parsing', status_message: 'OCR in progress' },
      { id: 'two', state: 'ready', label: 'Ready', status_message: 'Indexed' }] };
  let results = component.computed.uploadDisplayResults.call(context);
  assert.equal(results[0].phase, 'parsing');
  assert.equal(results[1].state, 'Ready');
  assert.equal(results[2].state, 'Unsupported');
  context.cloudDocuments[0] = { id: 'one', state: 'failed', label: 'Failed', status_message: 'Parse failed', can_manage: true, has_original: true };
  results = component.computed.uploadDisplayResults.call(context);
  assert.equal(results[0].can_retry, true);
  context.cloudDocuments[0] = { id: 'one', state: 'ready', label: 'Ready', status_message: 'Indexed' };
  assert.equal(component.computed.uploadDisplayResults.call(context)[0].state, 'Ready');
});

function libraryContext() {
  const context = component.data();
  for (const [name, method] of Object.entries(component.methods)) context[name] = method.bind(context);
  return context;
}
test('category navigation clears stale filters, while clearing filters retains category', () => {
  const context = libraryContext();
  Object.assign(context, {favoritesOnly: true, statusFilter: 'failed', query: 'old', projectFilter: 'P'});
  context.selectCategory('研究成果');
  assert.equal(context.category, '研究成果');
  assert.equal(context.favoritesOnly, false);
  assert.equal(context.statusFilter, '');
  assert.equal(context.query, '');
  context.resetFilters();
  assert.equal(context.category, '研究成果');
});
test('saved view restores category and filters per user', () => {
  const storage = new Map();
  const isolated = vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../frontend/company-knowledge.js'), 'utf8') + '\nCompanyKnowledge;', { localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)} });
  const original = {...isolated.data(), service: {username: 'alice'}, viewRestored: true, category: '研究成果', query: '报告', statusFilter: 'ready', libraryPage:3,libraryPageSize:20};
  original.libraryView = isolated.computed.libraryView.call(original);
  isolated.methods.saveLibraryView.call(original);
  const restored = {...isolated.data(), service: {username: 'alice'}};
  isolated.methods.restoreLibraryView.call(restored);
  assert.equal(restored.category, '研究成果');
  assert.equal(restored.query, '报告');
  assert.equal(restored.statusFilter, 'ready');
  assert.equal(restored.libraryPage,3); assert.equal(restored.libraryPageSize,20);
  const other = {...isolated.data(), service: {username: 'bob'}};
  isolated.methods.restoreLibraryView.call(other);
  assert.equal(other.category, '全部资料');
});
test('upload completion shows uploaded documents despite previous filters', () => {
  const context = libraryContext();
  Object.assign(context, {category:'研究成果', favoritesOnly:true, statusFilter:'failed', uploadOpen:true, uploadResults:[{id:'new'}, {name:'failed'}]});
  context.viewUploaded();
  assert.equal(context.uploadOpen, false);
  assert.equal(context.category, '全部资料');
  context.documents = [{id:'new', title:'New'}, {id:'old', title:'Old'}];
  assert.deepEqual(Array.from(component.computed.filteredDocuments.call(context).map(doc => doc.id)), ['new']);
});
test('upload summary distinguishes ready, processing and failure', () => {
  const summary = component.computed.uploadSummary.call({uploadDisplayResults:[{id:'a',phase:'ready'},{id:'b',phase:'parsing'},{name:'bad'}]});
  assert.match(summary, /1 份资料已可检索/);
  assert.match(summary, /1 份后台处理中/);
  assert.match(summary, /1 份失败/);
});

test('project collections group only accessible loaded documents', () => {
  const context = {projectOptions:['Project B','Project A'],documents:[{project:'Project A',industry:'汽车'},{project:'Project A',industry:'汽车'},{project:'Project B',industry:'消费'}]};
  const projects = component.computed.projectCollections.call(context);
  assert.equal(projects[0].name,'Project A'); assert.equal(projects[0].count,2); assert.equal(projects[0].industry,'汽车');
});
test('recent reading ignores inaccessible or removed files and preserves reading order', () => {
  const context = {readingHistory:['missing','b','a'],documents:[{id:'a'},{id:'b'}]};
  assert.deepEqual(Array.from(component.computed.recentlyRead.call(context).map(doc => doc.id)),['b','a']);
});
test('sorting by recency preserves filtered list and handles missing dates', () => {
  const context = {sortOrder:'updated',filteredDocuments:[{title:'Old',modified_at:'2025-01-01'},{title:'Unknown'},{title:'New',modified_at:'2026-10-16'}]};
  assert.deepEqual(Array.from(component.computed.sortedDocuments.call(context).map(doc => doc.title)),['New','Old','Unknown']);
  assert.equal(context.filteredDocuments[0].title,'Old');
});

test('project research uses current ready files and preserves an explicit selection', () => {
 const context = libraryContext(); Object.assign(context,{libraryScopeFiltered:true,filteredDocuments:[{id:'a',state:'ready'},{id:'b',state:'parsing'}],$nextTick:callback => callback(),$refs:{}});
 context.askLibrary(); assert.deepEqual(Array.from(context.selectedIds),['a']); assert.equal(context.mode,'chat');
 context.selectedIds=['explicit']; context.askLibrary(); assert.deepEqual(Array.from(context.selectedIds),['explicit']);
});

function paginationContext(count, page = 1, size = 10) {
 const context = {sortedDocuments:Array.from({length:count},(_,id)=>({id})),libraryPage:page,libraryPageSize:size};
 for(const key of ['libraryPageCount','currentLibraryPage','pagedDocuments','libraryPageRange','libraryPageNumbers']) Object.defineProperty(context,key,{get:()=>component.computed[key].call(context)});
 return context;
}
test('pagination has disjoint pages, a partial last page and an empty range',()=>{
 const context = paginationContext(23,2);
 assert.deepEqual(Array.from(context.pagedDocuments.map(doc=>doc.id)),[10,11,12,13,14,15,16,17,18,19]);
 context.libraryPage=3; assert.deepEqual(Array.from(context.pagedDocuments.map(doc=>doc.id)),[20,21,22]);
 assert.equal(context.libraryPageRange.start,21); assert.equal(context.libraryPageRange.end,23);
 const empty = paginationContext(0,9); assert.equal(empty.currentLibraryPage,1); assert.equal(empty.libraryPageRange.start,0); assert.equal(empty.libraryPageRange.end,0);
});
test('filter changes reset page and list scroll without losing cross-page selection',()=>{
 const context = {libraryPage:3,restoringView:false,selectedIds:['other-page'],scrolls:0,scrollLibraryTop(){this.scrolls++}};
 component.watch.libraryFilterKey.call(context); assert.equal(context.libraryPage,1); assert.equal(context.scrolls,1); assert.deepEqual(context.selectedIds,['other-page']);
 context.libraryPage=3;context.restoringView=true;component.watch.libraryFilterKey.call(context);assert.equal(context.libraryPage,3);
});
test('page controls clamp to valid pages after the result set shrinks',()=>{
 const context = paginationContext(13,5);context.scrollLibraryTop=()=>{};
 component.methods.changeLibraryPage.call(context,5);assert.equal(context.libraryPage,2);
 component.methods.changeLibraryPage.call(context,-1);assert.equal(context.libraryPage,1);
});
test('catalog loading fetches beyond 100 files before local filtering and pagination',async()=>{
 const calls=[]; const context={loading:false,documentPage:0,selectedIds:['last'],cloudDocuments:[],apiFetch:async url=>{calls.push(url);return {ok:true,json:async()=>({documents:url.includes('page_number=2')?[{id:'last',category:'研究成果'}]:Array.from({length:100},(_,i)=>({id:String(i),category:'项目原件'})),total_count:101})}}};
 await component.methods.loadDocuments.call(context);assert.equal(calls.length,2);assert.equal(context.cloudDocuments.length,101);assert.deepEqual(Array.from(context.selectedIds),['last']);
});
