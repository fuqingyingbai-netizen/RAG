/* Company knowledge uses the authenticated backend; cloud credentials stay on the server. */
const KnowledgeFileArtwork = {
  props: { format: String, kind: String, mediaKind: String },
  template: `<div class="ckb-file-object" aria-hidden="true"><span class="ckb-file-fold"></span><b>{{ format }}</b><div class="ckb-file-lines"><i></i><i></i><i></i></div><div v-if="kind === 'sheet'" class="ckb-file-cells"></div><div v-if="mediaKind" class="ckb-file-media"><i :class="mediaKind === 'audio' ? 'fa-solid fa-wave-square' : 'fa-solid fa-play'"></i></div></div>`,
};
const KnowledgeFolderArtwork = { template: `<div class="ckb-folder-object" aria-hidden="true"><span class="ckb-folder-back"></span><span class="ckb-folder-sheet one"></span><span class="ckb-folder-sheet two"></span><span class="ckb-folder-lid"><i class="fa-solid fa-layer-group"></i></span><span class="ckb-folder-tab"></span></div>` };
const knowledgePreviewLanes = [Promise.resolve(), Promise.resolve()]; let knowledgePreviewLane = 0;
const KnowledgeThumbnail = {
  props: { doc: Object, fetchImage: Function },
  data() { return { url: '', failed: false }; },
  mounted() { if (!this.doc.can_read || !this.doc.has_original || !['PDF','PNG','JPG','JPEG','MP4','WEBM'].includes(this.doc.format)) return; const start = () => { this.observer?.disconnect(); this.load(); }; if (typeof IntersectionObserver === 'undefined') start(); else { this.observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) start(); }); this.observer.observe(this.$el); } },
  beforeUnmount() { this.disposed = true; this.observer?.disconnect(); this.controller?.abort(); if (this.url) URL.revokeObjectURL(this.url); },
  methods: { async load() { const lane=knowledgePreviewLane++ % knowledgePreviewLanes.length; const task=knowledgePreviewLanes[lane].then(()=>this.loadImage());knowledgePreviewLanes[lane]=task.catch(()=>{});await task; }, async loadImage() { if(this.disposed)return; this.controller = new AbortController(); try { const response = await this.fetchImage('/company-knowledge/documents/' + encodeURIComponent(this.doc.id) + '/thumbnail', {signal:this.controller.signal}); if (!response.ok) throw Error(); const blob = await response.blob(); if (!this.disposed) this.url = URL.createObjectURL(blob); } catch { this.failed = true; } } },
  template: `<span class="ckb-content-thumbnail" :class="{'has-image':!!url}" aria-hidden="true"><img v-if="url" :src="url" alt=""></span>`,
};
const CompanyKnowledge = {
  components: { KnowledgeNoteEditor: typeof window !== 'undefined' ? window.KnowledgeNoteEditor : {}, KnowledgeThumbnail, KnowledgeFileArtwork, KnowledgeFolderArtwork, KnowledgeGlassSurface: typeof window !== 'undefined' ? window.KnowledgeGlassSurface : {}, KnowledgeDocumentViewer: typeof window !== 'undefined' ? window.KnowledgeDocumentViewer : {}, KnowledgePdfViewer: typeof window !== 'undefined' ? window.KnowledgePdfViewer : {} },
  props: { projects: { type: Array, default: () => [] },
    feedback: {type:Function, default:null}, operationState:{type:Object, default:() => ({})} },
  data() {
    return {
      noteEditorId: '', noteDrafts: [], noteError: '', noteCreating: false,
      searchMode: 'metadata', contentMatches: [], contentTotal: 0, contentPage: 1, contentBusy: false, contentError: '', contentSearched: false, searchSequence: 0, readerLocation: null, readerFind: '', readerFocus: false, locating: false, quickCapture: false, captureTitle: '', captureScene: '', captureMethod: '',
      projectDirectories: [], projectFolders: [], projectLoading: false, projectError: '', projectDisplay: 'projects', activeProjectId: '', activeFolderId: '', openingDirectoryId: '', directoryTimer: null, projectEditorOpen: false, editingProject: null, projectSaving: false, projectForm: {}, folderEditorOpen: false, editingFolder: null, folderName: '', folderSaving: false, folderError: '',
      theme: 'light', motionPaused: false, libraryLayout: 'grid', tabIndicatorStyle: { opacity: 0 },
      downloadProgress: {}, readerBlob: null, readerMode: 'original', readerTrace: '', readerOriginalLoading: false, chatAtBottom: true,
      auditOpen: false, auditLoading: false, auditEvents: [], auditTotal: 0, auditPage: 1, auditScope: {}, auditError: '', auditSequence: 0,
      tagFilter: '', dateFrom: '', dateTo: '', dateField: 'created_at', libraryIntent: '',
      caseCategories: ['项目经验', '案例复盘', '方法与模板', '培训分享', '现场照片', '手稿笔记', '影音随记'],
      allCategories: ['项目原件', '研究成果', '访谈纪要', '行业资料', '项目经验', '案例复盘', '方法与模板', '培训分享', '现场照片', '手稿笔记', '影音随记'],
      viewRestored: false, restoringView: false, libraryPage: 1, libraryPageSize: 10, projectPreview: {id:'', pendingId:'', pinned:false, blockedUntil:0, rearmOnMove:false, x:null, y:null, cursorX:null, cursorY:null, reference:null, openTimer:null, closeTimer:null}, advancedFiltersOpen: false, homeActivityTab: 'updated', homeSearch: '', homeQuestion: '', sortOrder: 'updated', readingHistory: [], recentUploadIds: [], mode: 'home', projectFilter: '', industryFilter: '', statusFilter: '', reviewFilter: '', selectedIds: [], pollClock: null, readerUrl: '', readerLoading: false, readerError: '', readerTotal: 0, previewPage: 1, readerPDFPages: 0, uploadBusy: false, uploadError: '', uploadResults: [], editingDoc: null, metadataOpen: false, uploadForm: { project: '', industry: '', category: '项目原件', review: '待复核', confidentiality: 'internal', visibility: 'members', readersText: '', tagsText: '', description: '' }, query: '', category: '全部资料', space: 'all', favoritesOnly: false, mineOnly: false,
      favorites: [], readerOpen: false, selectedDoc: null, readerPage: 0,
      uploadOpen: false, stagedFiles: [], draft: '', scope: 'all', chatScope: 'accessible', messages: [],
      chatSessionId: '', chatSessions: [], chatHasMore: false, chatHistoryBusy: false, chatGeneration: 0,
      chatScopeUnavailable: false, memoryStatus: '', chatError: '', chatDisposed: false,
      cloudDocuments: [], totalDocuments: 0, documentPage: 0, loading: false,
      service: { configured: false, access_allowed: false, is_admin: false }, serviceError: '',
      myProjects: { project_count: 0, document_count: 0, projects: [] }, accessRequests: [], requestCenterOpen: false, accessLoading: false,
      busy: false, answerStatus: '', controller: null, activityClock: null,
      requestsActive: true, pendingReads: new Set(), readerSequence: 0,
      categories: ['全部资料', '项目原件', '研究成果', '方法与模板'],
      suggestions: ['查找与新能源汽车竞争格局有关的历史研究，并标注来源', '根据资料梳理访谈提纲，区分已有依据和待确认问题', '比较资料中的主要结论，指出差异与待复核事项'],
    };
  },
  computed: {
    chatSuggestions() { return this.chatCollection === 'experience' ? ['查找类似场景的实践经验，说明适用条件和注意事项', '把这些复盘整理成可以复用的步骤，并标明依据', '根据照片、手稿的识别文字和音视频说明，总结已记录的经验与待确认事项'] : this.suggestions; },
    searchDocumentIds() { return this.filteredDocuments.filter(doc => doc.can_read && doc.state === 'ready' && doc.is_current !== 0).map(doc => doc.id); },
    chatCollection() { return ['experience','my-experience'].includes(this.chatScope) ? 'experience' : 'library'; },
    currentCollection() { return this.mode === 'cases' ? 'experience' : this.mode === 'chat' ? this.chatCollection : 'library'; },
    collectionDocuments() { return this.documents.filter(doc => this.caseCategories.includes(doc.category) === (this.currentCollection === 'experience')); },
    collectionProjects() { return this.projectDirectories.filter(project => this.caseCategories.includes(project.category) === (this.currentCollection === 'experience')); },
    libraryCount() { return this.documents.filter(doc => !this.caseCategories.includes(doc.category)).length; },
    collectionMineCount() { return this.collectionProjects.filter(project => project.owner === this.service.username).length; },
    collectionMineDocumentCount() { return this.collectionDocuments.filter(doc => doc.is_owner).length; },
    metadataCategoryOptions() { const experience = this.editingDoc ? this.caseCategories.includes(this.editingDoc.category) : this.currentCollection === 'experience'; return this.allCategories.filter(category => this.caseCategories.includes(category) === experience); },
    projectEditorIsCase() { return this.editingProject ? this.caseCategories.includes(this.editingProject.category) : this.mode === 'cases'; },
    projectCategoryOptions() { return this.projectEditorIsCase ? this.caseCategories : this.allCategories.filter(category => !this.caseCategories.includes(category)); },
    homeKnowledgeNodes() { return [
      { key: 'projects', label: '项目档案', caption: '背景 · 原件 · 访谈', count: this.collectionProjects.length, unit: '个项目', icon: 'fa-folder-open' },
      { key: 'results', label: '研究成果', caption: '让结论回到依据', count: this.readableDocuments.filter(doc => doc.category === '研究成果').length, unit: '份成果', icon: 'fa-file-lines' },
      { key: 'cases', label: '经验沉淀', caption: '复盘 · 经验 · 分享', count: this.documents.filter(doc => doc.can_read && this.caseCategories.includes(doc.category)).length, unit: '份资料', icon: 'fa-cubes' },
      { key: 'templates', label: '方法模板', caption: '从已有方法出发', count: this.readableDocuments.filter(doc => doc.category === '方法与模板').length, unit: '份模板', icon: 'fa-copy' },
    ]; },
    activeProject() { return this.projectDirectories.find(project => project.id === this.activeProjectId) || null; },
    directorySearchActive() { return !!(this.query || this.tagFilter || this.dateFrom || this.dateTo || this.statusFilter || this.reviewFilter || this.favoritesOnly); },
    showingProjects() { return this.searchMode !== 'content' && this.projectDisplay === 'projects' && !this.activeProjectId && !this.libraryIntent; },
    directoryBreadcrumbs() { const result = []; let id = this.activeFolderId; const seen = new Set(); while (id && !seen.has(id)) { seen.add(id); const folder = this.projectFolders.find(item => item.id === id && item.project_id === this.activeProjectId); if (!folder) break; result.unshift(folder); id = folder.parent_id; } return result; },
    visibleFolders() { if (!this.activeProjectId || this.directorySearchActive) return []; return this.projectFolders.filter(folder => folder.project_id === this.activeProjectId && folder.parent_id === this.activeFolderId); },
    visibleProjectDirectories() {
      const query = this.query.trim().toLowerCase();
      return this.projectDirectories.filter(project =>
        (this.caseCategories.includes(project.category) === (this.currentCollection === 'experience')) &&
        (this.category === '全部资料' || project.category === this.category) &&
        (!this.mineOnly || project.owner === this.service.username) &&
        (!this.projectFilter || project.name === this.projectFilter) &&
        (!this.industryFilter || project.industry === this.industryFilter) &&
        (!this.tagFilter || (project.tags || []).includes(this.tagFilter) || this.collectionDocuments.some(doc => doc.can_read && doc.knowledge_project_id === project.id && (doc.tags || []).includes(this.tagFilter))) &&
        (!this.reviewFilter || project.review === this.reviewFilter) &&
        (!this.statusFilter || this.collectionDocuments.some(doc => doc.knowledge_project_id === project.id && doc.state === this.statusFilter)) &&
        (!this.dateFrom && !this.dateTo || this.documentInDateRange(project)) &&
        (!query || [project.name, project.industry, project.description, ...(project.tags || [])].join(' ').toLowerCase().includes(query) || this.collectionDocuments.some(doc => doc.can_read && doc.knowledge_project_id === project.id && [doc.title, doc.description].join(' ').toLowerCase().includes(query))));
    },
    libraryView() { return { chatCollection: this.chatCollection, projectDisplay: this.projectDisplay, activeProjectId: this.activeProjectId, activeFolderId: this.activeFolderId, libraryLayout: this.libraryLayout, tagFilter: this.tagFilter, dateFrom: this.dateFrom, dateTo: this.dateTo, dateField: this.dateField, libraryPage: this.libraryPage, libraryPageSize: this.libraryPageSize, sortOrder: this.sortOrder, mode: this.mode, category: this.category, query: this.query, projectFilter: this.projectFilter, industryFilter: this.industryFilter, statusFilter: this.statusFilter, reviewFilter: this.reviewFilter, favoritesOnly: this.favoritesOnly, mineOnly: this.mineOnly }; },
    activeFilterLabel() { return [this.tagFilter && '标签：' + this.tagFilter, (this.dateFrom || this.dateTo) && (this.dateField === 'created_at' ? '上传' : '更新') + '：' + (this.dateFrom || '不限') + ' 至 ' + (this.dateTo || '不限'), this.mineOnly && '我的项目', this.query && '搜索：' + this.query, this.projectFilter, this.industryFilter, this.statusFilter && '状态：' + ({ready:'可检索',queued:'等待处理',uploading:'上传中',parsing:'解析中',indexing:'索引中',failed:'处理失败'}[this.statusFilter] || this.statusFilter), this.reviewFilter, this.favoritesOnly && '仅收藏', this.recentUploadIds.length && '本次上传'].filter(Boolean).join(' · '); },
    uploadSummary() { const rows = this.uploadDisplayResults; const ready = rows.filter(row => row.phase === 'ready').length; const archived = rows.filter(row => row.phase === 'archived').length; const failed = rows.filter(row => !row.id || row.phase === 'failed').length; const pending = rows.length - ready - archived - failed; return [ready && ready + ' 份资料已可检索', archived && archived + ' 份音视频已归档，可播放与下载', pending && pending + ' 份后台处理中', failed && failed + ' 份失败，请查看下方详情'].filter(Boolean).join('；'); },
    visibleCategories() { return this.mode === 'cases' ? ['全部资料', ...this.caseCategories] : this.categories.filter(item => !this.caseCategories.includes(item)); },
    caseCount() { return this.documents.filter(doc => this.caseCategories.includes(doc.category)).length; },
    tagOptions() { return [...new Set([...this.collectionDocuments.filter(doc => doc.can_read).flatMap(doc => doc.tags || []), ...this.collectionProjects.flatMap(project => project.tags || [])])].sort((a,b) => a.localeCompare(b, 'zh-CN')); },
    formTags() { return this.parseTags(this.uploadForm.tagsText); },
    documents() { return this.cloudDocuments.map(doc => ({ ...doc, summary: [doc.industry, doc.review, doc.status_message].filter(Boolean).join(' · '), date: doc.modified_at ? new Date(doc.modified_at).toLocaleDateString('zh-CN') : '' })); },
    filteredDocuments() {
      const keyword = this.query.trim().toLowerCase();
      return this.documents.filter(doc =>
        (!this.activeProjectId || doc.knowledge_project_id === this.activeProjectId) &&
        (!this.activeProjectId || this.directorySearchActive || (doc.folder_id || '') === this.activeFolderId) &&
        (this.caseCategories.includes(doc.category) === (this.currentCollection === 'experience')) &&
        (!this.tagFilter || (doc.tags || []).includes(this.tagFilter)) &&
        (!this.dateFrom && !this.dateTo || this.documentInDateRange(doc)) &&
        (!this.recentUploadIds.length || this.recentUploadIds.includes(doc.id)) &&
        (this.category === '全部资料' || doc.category === this.category) &&
        (!this.projectFilter || (doc.project || '未归类项目') === this.projectFilter) &&
        (!this.industryFilter || doc.industry === this.industryFilter) &&
        (!this.statusFilter || doc.state === this.statusFilter) &&
        (!this.reviewFilter || doc.review === this.reviewFilter) &&
        (!this.mineOnly || doc.is_owner) &&
        (!this.favoritesOnly || this.favorites.includes(doc.id)) &&
        (!keyword || this.searchMode === 'content' || [doc.title, doc.summary, doc.project, doc.format, doc.description, ...(doc.tags || [])].join(' ').toLowerCase().includes(keyword)));
    },
    sortedDocuments() { return [...this.filteredDocuments].sort((a, b) => this.sortOrder === 'title' ? a.title.localeCompare(b.title, 'zh-CN') : (Date.parse(b.modified_at) || 0) - (Date.parse(a.modified_at) || 0)); },
    libraryFilterKey() { return JSON.stringify([this.activeProjectId, this.activeFolderId, this.mode === 'cases', this.searchMode, this.tagFilter, this.dateFrom, this.dateTo, this.dateField, this.category, this.query, this.projectFilter, this.industryFilter, this.statusFilter, this.reviewFilter, this.favoritesOnly, this.mineOnly, this.recentUploadIds, this.sortOrder, this.libraryPageSize]); },
    libraryPageCount() { return Math.max(1, Math.ceil(this.sortedDocuments.length / this.libraryPageSize)); },
    currentLibraryPage() { return Math.min(Math.max(1, this.libraryPage), this.libraryPageCount); },
    pagedDocuments() { const start = (this.currentLibraryPage - 1) * this.libraryPageSize; return this.sortedDocuments.slice(start, start + this.libraryPageSize); },
    libraryPageRange() { const total = this.sortedDocuments.length; const start = total ? (this.currentLibraryPage - 1) * this.libraryPageSize + 1 : 0; return { start, end: Math.min(this.currentLibraryPage * this.libraryPageSize, total), total }; },
    libraryPageNumbers() { const start = Math.max(1, Math.min(this.currentLibraryPage - 2, this.libraryPageCount - 4)); return Array.from({ length: Math.min(5, this.libraryPageCount) }, (_, index) => start + index); },
    readableDocuments() { return this.collectionDocuments.filter(doc => doc.can_read); },
    advancedFilterCount() { return [!this.activeProject && this.projectFilter, this.statusFilter, this.tagFilter, this.dateFrom || this.dateTo].filter(Boolean).length; },
    homeActivityDocuments() { return this.homeActivityTab === 'viewed' ? this.recentlyRead : this.recentDocuments; },
    recentDocuments() { return [...this.readableDocuments].sort((a, b) => (Date.parse(b.modified_at) || 0) - (Date.parse(a.modified_at) || 0)).slice(0, 6); },
    recentlyRead() { return this.readingHistory.map(id => this.collectionDocuments.find(doc => doc.id === id && doc.can_read)).filter(Boolean).slice(0, 4); },
    projectCollections() { if (this.projectDirectories?.length) return this.collectionProjects.slice(0,4).map(project => ({...project, count:project.document_count})); return this.projectOptions.map(name => ({ name, count: this.readableDocuments.filter(doc => doc.project === name).length, industry: [...new Set(this.readableDocuments.filter(doc => doc.project === name).map(doc => doc.industry).filter(Boolean))].join(' / ') })).sort((a, b) => b.count - a.count).slice(0, 4); },
    libraryScopeFiltered() { return !!this.activeProjectId || this.category !== '全部资料' || Boolean(this.activeFilterLabel); },
    readyCount() { return this.readableDocuments.filter(doc => doc.state === 'ready').length; },
    reviewedCount() { return this.readableDocuments.filter(doc => doc.review === '已复核').length; },
    projectOptions() { return [...new Set([...this.readableDocuments.map(doc => doc.project).filter(Boolean), ...this.collectionProjects.map(project => project.name)])]; },
    industryOptions() { return [...new Set(this.collectionDocuments.map(doc => doc.industry).filter(Boolean))]; },
    pendingCount() { return this.collectionDocuments.filter(doc => ['queued', 'uploading', 'parsing', 'indexing'].includes(doc.state)).length; },
    failedCount() { return this.collectionDocuments.filter(doc => doc.state === 'failed').length; },
    scopeLabel() { const label = this.chatCollection === 'experience' ? '经验沉淀' : '资料库'; return this.selectedIds.length ? label + ' · 选中 ' + this.selectedIds.length + ' 份资料' : ['my-projects','my-experience'].includes(this.chatScope) ? label + ' · 我的项目' : label + ' · 全部可访问资料'; },
    selectedDocuments() { return this.documents.filter(doc => doc.can_read && this.selectedIds.includes(doc.id)); },
    myProjectMaxCount() { return Math.max(1, ...this.myProjects.projects.map(project => project.document_count || 0)); },
    pendingAccessCount() { return this.accessRequests.filter(request => request.status === 'pending').length; },
    uploadDisplayResults() {
      const documents = new Map(this.cloudDocuments.map(doc => [doc.id, doc]));
      return this.uploadResults.map(item => {
        const doc = documents.get(item.id);
        return doc ? { ...item, state: doc.label, phase: doc.state, detail: doc.status_message,
          can_retry: doc.can_manage && doc.state === 'failed' && doc.has_original } : item;
      });
    },
    canAsk() { return this.service.configured && this.service.access_allowed; },
    allReferences() { const references = new Map(); for (const message of this.messages) for (const reference of message.references || []) references.set((reference.document_id || reference.url) + ':' + reference.id, reference); return [...references.values()]; },
  },
  watch: {
    visibleProjectDirectories(rows) { if ((this.projectPreview.id && !rows.some(row => row.id === this.projectPreview.id)) || (this.projectPreview.pendingId && !rows.some(row => row.id === this.projectPreview.pendingId))) this.dismissProjectPreview(); },
    mode(value) { this.dismissProjectPreview?.(); this.$nextTick(() => this.syncTabIndicator()); if (value === 'chat') this.scrollChat(); },
    libraryView: { deep: true, handler() { this.saveLibraryView(); } },
    libraryFilterKey() { this.dismissProjectPreview?.(); this.invalidateContentSearch(); if (!this.restoringView) { this.libraryPage = 1; this.scrollLibraryTop(); } },
    libraryPageCount(count) { if (!this.loading && this.libraryPage > count) this.libraryPage = count; },
    readerOpen(open) { if (open) this.dismissProjectPreview?.(); if (!open) { this.readerSequence++; this.readerLoading = false; this.readerOriginalLoading = false; this.releaseReader(); } },
  },
  mounted() { this.installProjectPreviewListeners(); this.restoreTheme(); this.loadService(); this.$nextTick(() => { this.syncTabIndicator(); if (typeof ResizeObserver !== 'undefined') { this.tabObserver = new ResizeObserver(() => this.syncTabIndicator()); this.tabObserver.observe(this.$el.querySelector('.ckb-tabs')); } }); this.pollClock = setInterval(() => { if (this.canAsk && !document.hidden && (this.pendingCount || !this.lastCataloguePoll || Date.now() - this.lastCataloguePoll > 29000)) { this.lastCataloguePoll = Date.now(); this.loadDocuments(false, false); this.loadAccessRequests(); this.loadMyProjects(); } }, 6000); },
  beforeUnmount() { this.uninstallProjectPreviewListeners(); this.contentController?.abort(); this.searchSequence++; this.tabObserver?.disconnect(); clearTimeout(this.directoryTimer); if (typeof document !== 'undefined' && document.documentElement) delete document.documentElement.dataset.knowledgeTheme; this.chatDisposed = true; this.chatGeneration++; this.requestsActive = false; this.cancelPendingReads(); this.controller?.abort(); clearInterval(this.activityClock); clearInterval(this.pollClock); this.releaseReader(); },
  methods: {
    clearProjectPreview() {
      const state = this.projectPreview;
      clearTimeout(state.openTimer); clearTimeout(state.closeTimer);
      state.openTimer = null; state.closeTimer = null; state.pendingId = ''; state.id = ''; state.pinned = false;
    },
    dismissProjectPreview(restoreFocus = false) {
      const id = this.projectPreview.id;
      const focusInPreview = typeof document !== 'undefined' && document.activeElement?.closest?.('.ckb-project-detail-popover');
      this.clearProjectPreview(); this.projectPreview.blockedUntil = Date.now() + 500; this.projectPreview.rearmOnMove = true;
      if (restoreFocus && focusInPreview && id) {
        [...this.$el.querySelectorAll('[data-project-preview-trigger]')].find(el => el.dataset.projectPreviewTrigger === String(id))?.focus();
      }
    },
    installProjectPreviewListeners() {
      this.projectPreviewScrollListener = event => {
        if (event.target?.closest?.('.ckb-project-detail-popover')) return;
        if (typeof event.clientX === 'number') { this.projectPreview.x = event.clientX; this.projectPreview.y = event.clientY; }
        this.dismissProjectPreview();
      };
      this.projectPreviewOutsideListener = event => {
        if (event.target?.closest?.('.ckb-project-detail-popover') || this.$el.contains(event.target?.closest?.('[data-project-preview-trigger]'))) return;
        this.clearProjectPreview();
      };
      this.projectPreviewKeyListener = event => { if (event.key === 'Escape' && (this.projectPreview.id || this.projectPreview.pendingId)) this.dismissProjectPreview(true); };
      document.addEventListener('wheel', this.projectPreviewScrollListener, { capture: true, passive: true });
      document.addEventListener('scroll', this.projectPreviewScrollListener, { capture: true, passive: true });
      document.addEventListener('touchmove', this.projectPreviewScrollListener, { capture: true, passive: true });
      document.addEventListener('pointerdown', this.projectPreviewOutsideListener, true);
      document.addEventListener('keydown', this.projectPreviewKeyListener, true);
    },
    uninstallProjectPreviewListeners() {
      if (typeof document !== 'undefined') {
        if (this.projectPreviewScrollListener) {
          document.removeEventListener('wheel', this.projectPreviewScrollListener, true);
          document.removeEventListener('scroll', this.projectPreviewScrollListener, true);
          document.removeEventListener('touchmove', this.projectPreviewScrollListener, true);
        }
        if (this.projectPreviewOutsideListener) document.removeEventListener('pointerdown', this.projectPreviewOutsideListener, true);
        if (this.projectPreviewKeyListener) document.removeEventListener('keydown', this.projectPreviewKeyListener, true);
      }
      this.clearProjectPreview();
    },
    projectPreviewPoint(x, y) { return { getBoundingClientRect: () => ({x, y, left:x, right:x, top:y, bottom:y, width:0, height:0}) }; },
    queueProjectPreview(project, event) {
      if (event.pointerType && event.pointerType !== 'mouse') return;
      const state = this.projectPreview;
      state.cursorX = event.clientX; state.cursorY = event.clientY;
      if (state.pinned) return;
      const moved = state.x === null || Math.hypot(event.clientX - state.x, event.clientY - state.y) > 4;
      if (state.rearmOnMove && (event.type !== 'pointermove' || !moved)) return;
      if (state.rearmOnMove) state.rearmOnMove = false;
      clearTimeout(state.closeTimer);
      if (state.id === project.id || (state.pendingId === project.id && !moved)) return;
      clearTimeout(state.openTimer); state.id = ''; state.pendingId = project.id; state.x = event.clientX; state.y = event.clientY;
      state.openTimer = setTimeout(() => {
        if (state.pendingId !== project.id || Date.now() < state.blockedUntil || !this.$el?.isConnected || !['library', 'cases'].includes(this.mode)) return;
        state.reference = this.projectPreviewPoint(state.cursorX, state.cursorY);
        state.id = project.id; state.pendingId = ''; state.pinned = false;
      }, 400 + Math.max(0, state.blockedUntil - Date.now()));
    },
    focusProjectPreview(project, event) {
      if (!event.target?.matches?.(':focus-visible') || Date.now() < this.projectPreview.blockedUntil || this.projectPreview.pinned) return;
      const state = this.projectPreview;
      clearTimeout(state.openTimer); clearTimeout(state.closeTimer);
      state.id = ''; state.pendingId = project.id; state.reference = event.target;
      state.openTimer = setTimeout(() => {
        if (state.pendingId === project.id && this.$el?.isConnected && Date.now() >= state.blockedUntil) { state.id = project.id; state.pendingId = ''; state.pinned = false; }
      }, 200);
    },
    leaveProjectPreview(project, event) {
      const related = event?.relatedTarget;
      if (related && (event.currentTarget?.contains(related) || related.closest?.('.ckb-project-detail-popover') || related.closest?.('[data-project-preview-row]')?.dataset.projectPreviewRow === String(project.id))) return;
      const state = this.projectPreview;
      if (state.pendingId === project.id) { clearTimeout(state.openTimer); state.pendingId = ''; }
      if (state.pinned) return;
      clearTimeout(state.closeTimer);
      state.closeTimer = setTimeout(() => { if (state.id === project.id && !state.pinned) this.clearProjectPreview(); }, 180);
    },
    holdProjectPreview() { clearTimeout(this.projectPreview.closeTimer); },
    toggleProjectPreview(project, event) {
      if (this.projectPreview.id === project.id && this.projectPreview.pinned) { this.dismissProjectPreview(); return; }
      this.clearProjectPreview();
      this.projectPreview.reference = event?.detail > 0 ? this.projectPreviewPoint(event.clientX, event.clientY) : event?.currentTarget;
      this.projectPreview.id = project.id; this.projectPreview.pinned = true;
    },
    fileTypeKind(doc = {}) {
      const format = String(doc.format || '').toLowerCase().replace(/^\./, '');
      const extension = format && !format.includes('/') ? format : String(doc.title || '').split('.').pop().toLowerCase();
      if (doc.media_kind === 'audio' || ['mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'wma'].includes(extension)) return 'audio';
      if (doc.media_kind === 'video' || ['mp4', 'webm', 'mov', 'avi', 'mkv', 'wmv', 'm4v'].includes(extension)) return 'video';
      if (extension === 'pdf') return 'pdf';
      if (['doc', 'docx', 'rtf', 'odt'].includes(extension)) return 'word';
      if (['xls', 'xlsx', 'csv', 'ods'].includes(extension)) return 'sheet';
      if (['ppt', 'pptx', 'odp'].includes(extension)) return 'slides';
      if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'tif', 'tiff', 'heic'].includes(extension)) return 'image';
      if (['zip', 'rar', '7z', 'tar', 'gz', 'bz2'].includes(extension)) return 'archive';
      if (['json', 'xml', 'html', 'css', 'js', 'ts', 'py', 'sql', 'yaml', 'yml'].includes(extension)) return 'code';
      if (['txt', 'md', 'markdown', 'text'].includes(extension)) return 'text';
      return 'file';
    },
    fileTypeIcon(doc) { return 'fa-solid ' + ({pdf:'fa-file-pdf',word:'fa-file-word',sheet:'fa-file-excel',slides:'fa-file-powerpoint',image:'fa-file-image',audio:'fa-file-audio',video:'fa-file-video',archive:'fa-file-zipper',code:'fa-file-code',text:'fa-file-lines',file:'fa-file'}[this.fileTypeKind(doc)]); },
    assistantHelpContext() {
      return {mode:this.mode, project_id:this.activeProjectId || '', folder_id:this.activeFolderId || '',
        note_id:this.noteEditorId || '', collection:this.currentCollection,
        dialog:this.noteEditorId ? 'note' : this.uploadOpen ? (this.quickCapture ? 'capture' : 'upload') : this.projectEditorOpen ? 'project' : this.folderEditorOpen ? 'folder' : this.readerOpen ? 'reader' : ''};
    },
    invalidateContentSearch() { this.searchSequence++; this.contentController?.abort(); this.contentBusy = false; this.contentMatches = []; this.contentTotal = 0; this.contentSearched = false; this.contentError = ''; },
    setSearchMode(mode) { this.searchMode = mode; this.invalidateContentSearch(); },
    async searchContent(page = 1) {
      if (this.query.trim().length < 2) { this.contentError = '正文搜索至少输入两个字符。'; return; }
      const sequence = ++this.searchSequence; this.contentController?.abort(); this.contentController = new AbortController();
      this.contentBusy = true; this.contentError = ''; this.contentSearched = true; this.contentMatches = []; this.contentPage = page;
      try {
        const response = await this.apiFetch('/company-knowledge/search', {method:'POST', signal:this.contentController.signal, headers:{'Content-Type':'application/json'}, body:JSON.stringify({query:this.query.trim(), scope:this.currentCollection === 'experience' ? 'experience' : 'accessible', document_ids:this.searchDocumentIds, page, page_size:10})});
        const result = await response.json(); if (!response.ok) throw Error(result.detail || '正文搜索失败，请重试。');
        if (sequence !== this.searchSequence) return; this.contentMatches = result.matches || []; this.contentTotal = result.total || 0;
      } catch (error) { if (sequence === this.searchSequence && error.name !== 'AbortError') this.contentError = error.message; }
      finally { if (sequence === this.searchSequence) this.contentBusy = false; }
    },
    highlightedParts(text) { const value = String(text || '').slice(0,1200), query = this.query.trim(); if (!query) return [{text:value,match:false}]; const lower=value.toLocaleLowerCase(), needle=query.toLocaleLowerCase(), parts=[]; let start=0, index; while ((index=lower.indexOf(needle,start))>=0) { parts.push({text:value.slice(start,index),match:false},{text:value.slice(index,index+query.length),match:true}); start=index+query.length; } parts.push({text:value.slice(start),match:false}); return parts; },
    knowledgeState(doc) { return !doc.can_read ? '需要授权' : doc.state === 'ready' ? (doc.media_kind ? '说明可检索' : ['PNG','JPG','JPEG'].includes(doc.format) ? '识别文字可检索' : '正文可检索') : doc.label; },
    async locateReference(reference) {
      if (!this.selectedDoc?.id) return;
      const id = this.selectedDoc.id, sequence = this.readerSequence; this.locating = true; this.readerMode = 'original'; this.readerFind = reference.text || '';
      if(reference.text && !(this.selectedDoc.references || []).some(ref=>ref.text===reference.text))this.selectedDoc.references=[reference,...(this.selectedDoc.references || [])];
      if(!this.selectedDoc.has_original){this.locating=false;this.readerMode='excerpts';this.readerLocation={message:'历史资料未归档原件，请核对引用片段。'};return;}
      if(this.selectedDoc.media_kind){this.locating=false;this.readerLocation={message:'这条引用来自人工文字说明，音视频未自动转写。'};return;}
      if(['DOCX','TXT','MD','CSV'].includes(this.selectedDoc.format)){this.locating=false;this.readerLocation={message:'正在原文中匹配引用文字…'};this.$nextTick(()=>this.$refs.nativeReader?.findSource());return;}
      try { const response=await this.apiFetch('/company-knowledge/documents/'+encodeURIComponent(id)+'/locate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:reference.text || '',pages:(reference.pages || []).map(Number).filter(n=>Number.isInteger(n)&&n>0)})}); const result=await response.json(); if(!response.ok)throw Error(result.detail || '来源定位失败'); if(this.readerOpen&&this.selectedDoc?.id===id&&this.readerSequence===sequence) this.readerLocation=result; }
      catch(error) { if(this.readerOpen&&this.selectedDoc?.id===id&&this.readerSequence===sequence)this.readerLocation={message:error.message}; }
      finally { if(this.readerSequence===sequence)this.locating=false; }
    },
    findInReader() { const text=this.readerFind.trim(); if(text)this.locateReference({text,pages:[]}); },
    openQuickCapture() { this.quickCapture=true; this.captureTitle=''; this.captureScene=''; this.captureMethod=''; this.uploadForm={project:'',industry:'',category:'项目经验',review:'待复核',confidentiality:'internal',visibility:'members',readersText:'',tagsText:'',description:''}; this.stagedFiles=[];this.uploadResults=[];this.uploadError='';this.uploadOpen=true; },
    droppedFiles(event) { if(this.uploadBusy)return; this.stagedFiles=Array.from(event.dataTransfer?.files || []);this.uploadResults=[];this.uploadError=''; },
    prepareCaptureNote() {
      if(!this.quickCapture || !this.captureTitle.trim())return;
      const name=this.captureTitle.trim().replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').slice(0,150)+' · 经验笔记.md';
      if(this.stagedFiles.some(file=>file.name===name) || this.uploadResults.some(row=>row.id && row.name===name))return;
      const files=this.stagedFiles.map(file=>'- '+file.name).join('\n');
      const text=['# '+this.captureTitle.trim(),this.captureScene.trim()&&'## 适用场景\n'+this.captureScene.trim(),this.captureMethod.trim()&&'## 可复用做法\n'+this.captureMethod.trim(),this.uploadForm.description.trim()&&'## 补充说明\n'+this.uploadForm.description.trim(),files&&'## 同次归档附件\n'+files].filter(Boolean).join('\n\n');
      this.stagedFiles=[new File([text],name,{type:'text/markdown'}),...this.stagedFiles];
    },
    async loadNotes() {
      try { const response=await this.apiFetch('/company-knowledge/notes');const data=await response.json();if(!response.ok)throw Error(data.detail || '笔记列表加载失败');this.noteDrafts=data.notes || [];this.noteError=''; } catch(error) { this.noteError=error.message; }
    },
    async createRichNote() {
      if(this.noteCreating)return;this.noteCreating=true;this.noteError='';
      try {const projectId=this.activeProject?.can_manage&&this.caseCategories.includes(this.activeProject.category)?this.activeProject.id:await this.captureProject();
        const response=await this.apiFetch('/company-knowledge/notes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project_id:projectId,folder_id:projectId===this.activeProjectId?this.activeFolderId:''})});const note=await response.json();if(!response.ok)throw Error(note.detail || '笔记创建失败');this.noteEditorId=note.id;await this.loadNotes();await this.loadProjectDirectories();
      }catch(error){this.noteError=error.message;}finally{this.noteCreating=false;}
    },
    editRichNote(id) { this.readerOpen=false;this.noteEditorId=id; },
    noteChanged() {this.loadNotes();this.loadDocuments();},
    async captureProject() {
      const name='随手记录 · 待整理'; let project=this.projectDirectories.find(p=>p.name===name&&p.owner===this.service.username&&this.caseCategories.includes(p.category));
      if(project)return project.id;
      const response=await this.apiFetch('/company-knowledge/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,category:'项目经验',industry:'',tags:['待整理'],description:'照片、手稿、录音与实践记录的临时归档空间。',review:'待复核',confidentiality:'internal',visibility:'members',readers:[]})});
      const result=await response.json(); if(!response.ok) { if(response.status===409){await this.loadProjectDirectories();project=this.projectDirectories.find(p=>p.name===name&&p.owner===this.service.username&&this.caseCategories.includes(p.category));if(project)return project.id;} throw Error(result.detail || '待整理空间创建失败'); } return result.id;
    },
    activateChatCollection(collection) { if (this.busy || this.chatCollection === collection) return; this.newConversation(); this.selectedIds = []; this.chatSessions = []; this.chatScope = collection === 'experience' ? 'experience' : 'accessible'; this.loadChatHistory(); },
    openHome() { this.mode = 'home'; this.activateChatCollection('library'); },
    syncTabIndicator() { const tabs = this.$el?.querySelector('.ckb-tabs'), active = tabs?.querySelector('[aria-selected="true"]'); if (!active) return; const parent = tabs.getBoundingClientRect(), rect = active.getBoundingClientRect(); this.tabIndicatorStyle = { width: rect.width + 'px', transform: 'translateX(' + (rect.left - parent.left + tabs.scrollLeft) + 'px)', opacity: 1 }; },
    navigateTabs(event) { if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; const tabs = [...event.currentTarget.querySelectorAll('[role="tab"]')], index = tabs.indexOf(document.activeElement); if (index < 0) return; event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length; tabs[next].focus(); tabs[next].click(); },
    async openAudit(scope = {}) { this.auditScope = scope; this.auditPage = 1; this.auditEvents = []; this.auditOpen = true; await this.loadAudit(); },
    async loadAudit() {
      const sequence = ++this.auditSequence; this.auditLoading = true; this.auditError = '';
      try { const query = new URLSearchParams({ ...this.auditScope, page: String(this.auditPage) }); const response = await this.apiFetch('/company-knowledge/audit-events?' + query); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '操作记录加载失败'); if (sequence !== this.auditSequence) return; this.auditEvents = data.events || []; this.auditTotal = data.total || 0; }
      catch (error) { if (sequence === this.auditSequence) this.auditError = error.message; }
      finally { if (sequence === this.auditSequence) this.auditLoading = false; }
    },
    auditAction(action) { return ({'project.create':'创建项目','project.update':'修改项目','project.delete':'删除项目','folder.create':'创建目录','folder.update':'修改目录','folder.delete':'删除目录','document.upload':'上传文件','document.update':'修改文件信息','document.inherit':'同步项目属性','document.retry':'重试处理','document.access_decision':'权限审批','document.delete':'删除文件','document.download':'生成水印下载副本','document.preview':'生成带标记预览','document.export_failed':'水印导出失败'})[action] || action; },
    auditField(field) { return ({name:'项目/目录名称',title:'文件名称',industry:'行业',category:'分类',review:'复核状态',confidentiality:'保密等级',visibility:'授权范围',readers:'指定成员',tags:'标签',description:'说明',folder_id:'归档目录 ID',parent_id:'上级目录 ID',state:'处理状态',version:'版本'})[field] || field; },
    auditValue(value) { if (value === null || value === undefined || value === '') return '未设置'; return Array.isArray(value) ? value.join('，') || '无' : String(value); },
    async loadProjectDirectories() {
      if (this.projectLoading) return;
      this.projectLoading = true;
      try { const response = await this.apiFetch('/company-knowledge/projects'); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '项目目录加载失败'); this.projectDirectories = data.projects || []; this.projectFolders = data.folders || []; const active = this.projectDirectories.find(project => project.id === this.activeProjectId); if (active && ['library','cases'].includes(this.mode)) this.mode = this.caseCategories.includes(active.category) ? 'cases' : 'library'; if (this.activeFolderId && !this.projectFolders.some(folder => folder.id === this.activeFolderId && folder.project_id === this.activeProjectId)) this.activeFolderId = ''; this.projectError = ''; if (this.activeProjectId && !this.projectDirectories.some(p => p.id === this.activeProjectId)) { this.activeProjectId = ''; this.activeFolderId = ''; this.projectDisplay = 'projects'; } }
      catch (error) { this.projectError = error.message; }
      finally { this.projectLoading = false; }
    },
    async deleteProjectDirectory() {
      const project=this.editingProject;if(!project?.can_manage||this.projectSaving)return;
      this.projectSaving=true;this.projectError='';
      try {
        const previewResponse=await this.apiFetch('/company-knowledge/projects/'+encodeURIComponent(project.id)+'/deletion-preview');
        const preview=await previewResponse.json();if(!previewResponse.ok)throw Error(preview.detail||'删除范围加载失败');
        try {await ElementPlus.ElMessageBox.confirm('确定删除项目“'+preview.name+'”？将同时移除 '+preview.document_count+' 份资料（含历史版本）、'+preview.note_count+' 篇图文笔记和 '+preview.folder_count+' 个子目录。删除后将无法在页面中恢复，原件和操作记录仅保留为受控恢复副本。','删除整个项目',{type:'warning',confirmButtonText:'确认删除整个项目',cancelButtonText:'取消',closeOnClickModal:false});}
        catch {return;}
        const response=await this.apiFetch('/company-knowledge/projects/'+encodeURIComponent(project.id),{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:preview.confirmation})});
        const result=await response.json();if(!response.ok)throw Error(result.detail||'项目删除失败');
        if(this.noteDrafts.some(note=>note.id===this.noteEditorId&&note.project_id===project.id))this.noteEditorId='';
        this.projectEditorOpen=false;this.editingProject=null;this.selectedIds=[];this.dismissProjectPreview();this.showProjectRoot();
        await Promise.all([this.loadDocuments(),this.loadNotes(),this.loadMyProjects()]);
        ElementPlus.ElMessage.success('项目及其中的资料、笔记和子目录已移除。');
      }catch(error){this.projectError=error.message;}
      finally{this.projectSaving=false;}
    },
    folderLabel(folder) { const names = [folder.name]; const seen = new Set([folder.id]); let parent = folder.parent_id; while (parent && !seen.has(parent)) { seen.add(parent); const found = this.projectFolders.find(item => item.id === parent && item.project_id === folder.project_id); if (!found) break; names.unshift(found.name); parent = found.parent_id; } return names.join(' / '); },
    showProjectRoot() { this.searchMode='metadata'; this.activeProjectId = ''; this.activeFolderId = ''; this.projectDisplay = 'projects'; this.resetFilters(); this.libraryIntent = ''; this.scrollLibraryTop(); },
    showAllFiles() { this.activeProjectId = ''; this.activeFolderId = ''; this.projectDisplay = 'files'; this.scrollLibraryTop(); },
    openDirectory(project, folderId = '') {
      clearTimeout(this.directoryTimer); this.openingDirectoryId = folderId || project.id;
      const reveal = () => { this.activeProjectId = project.id; this.activeFolderId = folderId; this.projectDisplay = 'contents'; this.openingDirectoryId = ''; this.resetFilters(); this.scrollLibraryTop(); };
      if (this.motionPaused || typeof window === 'undefined' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) reveal();
      else this.directoryTimer = setTimeout(reveal, 210);
    },
    startProjectEditor(project = null) {
      this.editingProject = project; this.projectError = '';
      this.projectForm = { name: project?.name || '', industry: project?.industry || '', category: project?.category || (this.visibleCategories.includes(this.category) && this.category !== '全部资料' ? this.category : this.mode === 'cases' ? '项目经验' : '项目原件'), review: project?.review || '待复核', confidentiality: project?.confidentiality === 'confidential' ? 'secret' : project?.confidentiality || 'internal', visibility: project?.visibility || 'members', readersText: (project?.readers || []).join(', '), tagsText: (project?.tags || []).join('，'), description: project?.description || '' };
      this.projectEditorOpen = true;
    },
    async saveProjectDirectory() {
      if (this.projectSaving) return;
      this.projectSaving = true; this.projectError = '';
      try { const values = { ...this.projectForm, name: this.projectForm.name.trim(), tags: this.parseTags(this.projectForm.tagsText), readers: this.projectForm.readersText.split(/[,，\n]/).map(x => x.trim()).filter(Boolean) }; if (values.confidentiality !== 'internal') values.visibility = 'restricted'; const response = await this.apiFetch('/company-knowledge/projects' + (this.editingProject ? '/' + this.editingProject.id : ''), { method: this.editingProject ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '项目保存失败'); this.projectEditorOpen = false; await this.loadDocuments(); this.activeProjectId = result.id; this.activeFolderId = ''; this.projectDisplay = 'contents'; this.resetFilters(); }
      catch (error) { this.projectError = error.message; }
      finally { this.projectSaving = false; }
    },
    startFolderEditor(folder = null) { this.editingFolder = folder; this.folderName = folder?.name || ''; this.folderError = ''; this.folderEditorOpen = true; },
    async saveFolder() {
      if (!this.activeProject || this.folderSaving) return;
      this.folderSaving = true; this.folderError = '';
      try { const response = await this.apiFetch('/company-knowledge/projects/' + this.activeProject.id + '/folders' + (this.editingFolder ? '/' + this.editingFolder.id : ''), { method: this.editingFolder ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: this.folderName, parent_id: this.activeFolderId }) }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '目录保存失败'); this.folderEditorOpen = false; await this.loadProjectDirectories(); }
      catch (error) { this.folderError = error.message; }
      finally { this.folderSaving = false; }
    },
    async deleteEmptyFolder() { if (!this.editingFolder || this.folderSaving) return; this.folderSaving = true; this.folderError = ''; try { const response = await this.apiFetch('/company-knowledge/projects/' + this.activeProject.id + '/folders/' + this.editingFolder.id, {method:'DELETE'}); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '删除目录失败'); this.folderEditorOpen = false; await this.loadProjectDirectories(); } catch (error) { this.folderError = error.message; } finally { this.folderSaving = false; } },
    setTheme(value, persist = true) {
      if (!['light', 'dark'].includes(value)) return;
      this.theme = value;
      if (typeof document !== 'undefined' && document.documentElement) document.documentElement.dataset.knowledgeTheme = value;
      if (persist) { try { localStorage.setItem('companyKnowledgeTheme', value); } catch {} }
    },
    restoreTheme() {
      let saved; try { saved = localStorage.getItem('companyKnowledgeTheme'); } catch {}
      this.setTheme(saved === 'dark' ? 'dark' : 'light', false);
    },
    citationDocument(group) { const found = this.documents.find(doc => doc.cloud_id === group.document_id); if (found) return found; const extension = (group.title || '').match(/\.([a-z0-9]{1,5})$/i)?.[1]; return { title: group.title, format: extension?.toUpperCase() || 'DOC' }; },
    fileAppearance(doc) {
      const format = (doc.format || '').toUpperCase();
      if (doc.media_kind === 'audio') return 'audio';
      if (doc.media_kind === 'video') return 'video';
      if (format === 'PDF') return 'pdf';
      if (['DOC', 'DOCX'].includes(format)) return 'word';
      if (['XLS', 'XLSX', 'CSV'].includes(format)) return 'sheet';
      if (['PPT', 'PPTX'].includes(format)) return 'slides';
      if (['PNG', 'JPG', 'JPEG'].includes(format)) return 'image';
      return 'text';
    },
    parseTags(text) { return [...new Set((text || '').split(/[,，、;；\n]/).map(tag => tag.trim()).filter(Boolean))]; },
    documentInDateRange(doc) {
      if (!this.dateFrom && !this.dateTo) return true;
      const value = new Date(doc[this.dateField || 'created_at']);
      if (!Number.isFinite(value.getTime())) return false;
      const from = this.dateFrom ? new Date(this.dateFrom + 'T00:00:00').getTime() : -Infinity;
      const until = this.dateTo ? new Date(this.dateTo + 'T00:00:00').getTime() + 86400000 : Infinity;
      return value.getTime() >= from && value.getTime() < until;
    },
    browseCases(category = '全部资料') { this.showProjectRoot(); this.resetFilters(); this.category = category; this.mode = 'cases'; this.libraryIntent = ''; this.activateChatCollection('experience'); },
    withFeedback(key, label, work, options = {}) { return this.feedback ? this.feedback('knowledge:' + key, label, work, options) : work(() => {}); },
    operationPending(key) { return !!this.operationState?.['knowledge:' + key]; },
    cancelPendingReads() { for (const cancel of this.pendingReads || []) cancel(); },
    async apiFetch(url, options = {}) {
      const token = localStorage.getItem('accessToken');
      const readOnly = ['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase());
      const backgroundDownload = readOnly && (/\/original\?download=true(?:&|$)/.test(url) || /\/download(?:\?|$)/.test(url));
      if (this.requestsActive === false) throw new Error('已离开知识库页面，请重新打开后再试。');
      const assertCurrent = () => {
        if (readOnly && !backgroundDownload && this.requestsActive === false) throw new Error('已离开知识库页面，请重新打开后再试。');
        if (token !== localStorage.getItem('accessToken')) throw new Error('登录账号已变更，请重新打开资料。');
      };
      assertCurrent();
      // Only reads have a deadline. A timed-out mutation may already be saved;
      // never abort/retry an upload, approval or chat as if it had not happened.
      const controller = readOnly ? new AbortController() : null;
      let timer, cancel;
      const cleanup = () => { clearTimeout(timer); this.pendingReads?.delete(cancel); if (cancel) options.signal?.removeEventListener('abort', cancel); };
      const deadline = readOnly ? new Promise((_, reject) => {
        cancel = () => { cleanup(); controller.abort(); reject(new Error('读取已停止，请重新打开资料。')); };
        if (!backgroundDownload) this.pendingReads?.add(cancel);
        timer = setTimeout(() => { cleanup(); controller.abort(); reject(new Error('读取超时，请重试；未重复提交任何操作。')); }, backgroundDownload || url.includes('/original') || /\/notes\/[^/]+\/export/.test(url) ? 600000 : 30000);
        if (options.signal?.aborted) cancel(); else options.signal?.addEventListener('abort', cancel, {once:true});
      }) : null;
      const wait = promise => deadline ? Promise.race([promise, deadline]) : promise;
      try {
        const response = await wait(fetch(url, { ...options, ...(controller ? {signal:controller.signal} : {}), headers: { ...options.headers, Authorization: 'Bearer ' + (token || '') } }));
        assertCurrent();
        if (response.status === 401) throw new Error('登录已过期，请重新登录。');
        // Check again after body parsing, not just when the headers arrive.
        // Slow JSON/blob responses must never restore data or download a file
        // after the user signs into another account or leaves this component.
        for (const method of ['json', 'blob', 'text', 'arrayBuffer']) {
          if (typeof response[method] !== 'function') continue;
          const parse = response[method].bind(response);
          response[method] = async (...args) => {
            try { assertCurrent(); const value = await wait(parse(...args)); assertCurrent(); return value; }
            finally { cleanup(); }
          };
        }
        return response;
      } catch (error) { cleanup(); throw error; }
    },
    async loadService() {
      try {
        const response = await this.apiFetch('/company-knowledge/status');
        if (!response.ok) throw new Error('无法读取知识库状态。');
        this.service = await response.json();
        if (!this.service.access_allowed) throw new Error('当前账号不可使用公司知识库，请联系管理员检查账号状态。');
        if (!this.service.configured) throw new Error('公司知识库尚未配置，请联系管理员。');
        try { this.favorites = JSON.parse(localStorage.getItem('companyKnowledgeFavorites:' + this.service.username) || '[]'); } catch { this.favorites = []; }
        if (!this.viewRestored) this.restoreLibraryView();
        if (sessionStorage.getItem('companyKnowledgeOpenMyProjects') === '1') {
          sessionStorage.removeItem('companyKnowledgeOpenMyProjects');
          this.browseLibrary(); this.mineOnly = true;
        }
        await Promise.all([this.loadDocuments(), this.loadMyProjects(), this.loadAccessRequests()]);
        if (this.mode === 'cases') this.chatScope = 'experience';
        await this.loadChatHistory();
      } catch (error) { this.serviceError = error.message; }
    },
    async loadDocuments(more = false, refresh = false) {
      if (this.loading) return;
      const previousAccess = JSON.stringify(this.cloudDocuments.map(doc => [doc.id, doc.can_read, doc.version, doc.modified_at, doc.state]));
      this.loading = true; this.serviceError = '';
      try {
        let lastPage = more ? this.documentPage + 1 : Math.max(1, this.documentPage);
        const incoming = []; let result;
        for (let page = more ? lastPage : 1; page <= lastPage; page++) {
          const response = await this.apiFetch('/company-knowledge/documents?page_number=' + page + '&page_size=100&refresh=' + (refresh && page === 1));
          result = await response.json();
          if (response.status === 403) { this.newConversation(); this.chatSessions = []; this.service.access_allowed = false; }
          if (!response.ok) throw new Error(result.detail || '资料加载失败。');
          incoming.push(...result.documents);
          lastPage = Math.max(lastPage, Math.ceil(result.total_count / 100));
          if (!result.documents.length) break;
        }
        this.cloudDocuments = [...new Map((more ? [...this.cloudDocuments, ...incoming] : incoming).map(doc => [doc.id, doc])).values()];
        this.loadNotes?.(); this.totalDocuments = result.total_count; this.documentPage = lastPage; await this.loadProjectDirectories?.();
        this.categories = ['全部资料', ...new Set([...['项目原件', '研究成果', '方法与模板', '访谈纪要', '行业资料'], ...this.cloudDocuments.map(doc => doc.category)])]; this.serviceError = result.warning || ''; this.selectedIds = this.selectedIds.filter(id => this.cloudDocuments.some(doc => doc.id === id && doc.can_read !== false));
        const currentAccess = JSON.stringify(this.cloudDocuments.map(doc => [doc.id, doc.can_read, doc.version, doc.modified_at, doc.state]));
        if (previousAccess !== currentAccess) this.invalidateContentSearch?.();
        if (previousAccess !== currentAccess && this.chatSessionId && !this.busy && !this.chatHistoryBusy) await this.loadChatHistory(this.chatSessionId);
      } catch (error) { this.serviceError = error.message; }
      finally { this.loading = false; if (this.libraryPageCount) this.libraryPage = Math.min(this.libraryPage, this.libraryPageCount); }
    },
    async loadMyProjects() {
      try {
        const response = await this.apiFetch('/company-knowledge/my-projects');
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || '我的项目加载失败。');
        this.myProjects = result;
      } catch (error) { this.serviceError = this.serviceError || error.message; }
    },
    async loadAccessRequests() {
      if (!this.service.access_allowed || this.accessLoading) return;
      this.accessLoading = true;
      try {
        const endpoint = this.service.is_admin ? '/company-knowledge/access-requests' : '/company-knowledge/access-requests/mine';
        const response = await this.apiFetch(endpoint);
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || '权限申请加载失败。');
        this.accessRequests = result.requests || result;
      } catch (error) { this.serviceError = this.serviceError || error.message; }
      finally { this.accessLoading = false; }
    },
    saveLibraryView() { if (!this.viewRestored || !this.service.username) return; try { localStorage.setItem('companyKnowledgeView:' + this.service.username, JSON.stringify(this.libraryView)); } catch {} },
    restoreLibraryView() { this.restoringView = true; try { const saved = JSON.parse(localStorage.getItem('companyKnowledgeView:' + this.service.username) || '{}'); for (const key of ['category','query','projectFilter','industryFilter','statusFilter','reviewFilter','tagFilter','dateFrom','dateTo']) if (typeof saved[key] === 'string') this[key] = saved[key]; if (['projects','files','contents'].includes(saved.projectDisplay)) this.projectDisplay = saved.projectDisplay; if (typeof saved.activeProjectId === 'string') this.activeProjectId = saved.activeProjectId; if (typeof saved.activeFolderId === 'string') this.activeFolderId = saved.activeFolderId; if (['grid','list'].includes(saved.libraryLayout)) this.libraryLayout = saved.libraryLayout; if (['home','library','chat','cases'].includes(saved.mode)) this.mode = saved.mode; if (saved.mode === 'chat' && saved.chatCollection === 'experience') this.chatScope = 'experience'; if ([10,20,50].includes(saved.libraryPageSize)) this.libraryPageSize = saved.libraryPageSize; if (Number.isInteger(saved.libraryPage) && saved.libraryPage > 0) this.libraryPage = saved.libraryPage; if (['created_at','modified_at'].includes(saved.dateField)) this.dateField = saved.dateField; if (['updated','title'].includes(saved.sortOrder)) this.sortOrder = saved.sortOrder; if (typeof saved.favoritesOnly === 'boolean') this.favoritesOnly = saved.favoritesOnly; if (typeof saved.mineOnly === 'boolean') this.mineOnly = saved.mineOnly; } catch {} try { const history = JSON.parse(localStorage.getItem('companyKnowledgeReading:' + this.service.username) || '[]'); this.readingHistory = Array.isArray(history) ? history.filter(id => typeof id === 'string').slice(0, 12) : []; } catch {} this.viewRestored = true; if (this.$nextTick) this.$nextTick(() => { this.restoringView = false; }); else this.restoringView = false; },
    scrollLibraryTop() { this.$nextTick?.(() => { if (this.$refs?.documentTable) this.$refs.documentTable.scrollTop = 0; }); },
    changeLibraryPage(page) { this.libraryPage = Math.max(1, Math.min(page, this.libraryPageCount)); this.scrollLibraryTop(); },
    askLibrary() {
      if (this.busy) return;
      if (this.selectedDocuments.some(doc => this.caseCategories.includes(doc.category) !== (this.currentCollection === 'experience'))) this.changeScope([]);
      if (this.libraryIntent === 'compare') {
        if (this.selectedIds.length < 2) { ElementPlus.ElMessage.info('请先勾选至少两份可检索资料。'); return; }
        this.draft = '比较所选资料的结论差异，逐项列出依据与待复核事项。';
        this.libraryIntent = ''; this.askSelection(); return;
      }
      if (!this.selectedIds.length && this.libraryScopeFiltered) {
        const ids = this.filteredDocuments.filter(doc => doc.can_read && doc.state === 'ready' && doc.is_current !== 0).map(doc => doc.id);
        if (!ids.length) { ElementPlus.ElMessage.info('当前范围没有可检索资料。'); return; }
        if (ids.length > 20) { ElementPlus.ElMessage.info('当前范围超过 20 份资料，请先勾选需要研究的文件。'); return; }
        this.changeScope(ids);
      }
      if (!this.selectedIds.length) this.changeScope([]);
      this.askSelection();
    },
    browseProject(name) { const directory = this.projectDirectories.find(p => p.name === name); if (directory) { this.mode = 'library'; this.openDirectory(directory); return; } this.showAllFiles(); this.selectCategory('全部资料'); this.projectFilter = name; this.mode = 'library'; },
    browseMyProject(name = '') { const mode = this.currentCollection === 'experience' ? 'cases' : 'library'; this.showProjectRoot(); const directory = this.collectionProjects.find(p => p.name === name && p.owner === this.service.username); if (directory) { this.mode = mode; this.openDirectory(directory); return; } this.selectCategory('全部资料'); this.mineOnly = true; this.projectFilter = name; this.mode = mode; },
    summarizeMyProjects() { if (this.busy) return; const experience = this.currentCollection === 'experience'; this.newConversation(); this.selectedIds = []; this.chatScope = experience ? 'my-experience' : 'my-projects'; this.mode = 'chat'; this.sendQuestion(experience ? '请仅根据我在经验沉淀中的项目资料，总结我沉淀的实践经验，用 Markdown 表格列出主题、可复用方法和引用依据。' : '请根据我上传的项目资料，总结我参与过的项目、主要研究内容和可复用经验；先给出简短总结，再用 Markdown 表格列出项目、行业、资料数量和主要成果，并标注引用依据。'); },
    browseLibrary() { this.showProjectRoot(); this.selectCategory('全部资料'); this.mode = 'library'; this.libraryIntent = ''; this.activateChatCollection('library'); },
    browseHomeNode(key) {
      if (key === 'cases' || key === 'templates') { this.browseCases(key === 'templates' ? '方法与模板' : '全部资料'); return; }
      this.browseLibrary();
      if (key === 'results') { this.showAllFiles(); this.selectCategory('研究成果'); }
    },
    browseHomeStatus(kind) { this.browseLibrary(); this.showAllFiles(); if (kind === 'review') this.reviewFilter = '待复核'; else if (kind === 'attention') this.statusFilter = this.failedCount ? 'failed' : this.documents.find(doc => ['queued', 'uploading', 'parsing', 'indexing'].includes(doc.state))?.state || ''; else if (kind === 'ready') this.statusFilter = 'ready'; },
    openHomeLibrary() { this.browseLibrary(); this.showAllFiles?.(); },
    searchHomeDocuments() { this.openHomeLibrary(); this.query = this.homeSearch.trim(); this.libraryPage = 1; },
    projectCardDate(value, full = false) { if (!value) return '—'; const date = new Date(value); if (!Number.isFinite(date.getTime())) return '—'; return full ? date.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false}) : date.toLocaleDateString('zh-CN', {timeZone:'Asia/Shanghai'}); },
    beginResearch(question) { if (this.busy) return; const text = typeof question === 'string' ? question.trim() : this.homeQuestion.trim(); if (!text) return; this.changeScope([]); this.mode = 'chat'; this.homeQuestion = ''; this.sendQuestion(text); },
    prepareResearch(kind) {
      if (this.busy) return;
      if (kind === 'cases' || kind === 'templates') { this.browseCases(kind === 'templates' ? '方法与模板' : '全部资料'); return; }
      this.browseLibrary(); this.showAllFiles(); this.changeScope([]); this.libraryIntent = 'compare';
    },
    selectCategory(category) { this.resetFilters(); this.category = category; },
    selectFavorites() { this.showAllFiles(); const active = this.favoritesOnly; this.selectCategory('全部资料'); this.favoritesOnly = !active; },
    selectFailed() { this.showAllFiles(); const active = this.statusFilter === 'failed'; this.selectCategory('全部资料'); this.statusFilter = active ? '' : 'failed'; },
    viewUploaded() { this.searchMode='metadata'; const experience = this.quickCapture || (this.activeProject ? this.caseCategories.includes(this.activeProject.category) : this.currentCollection === 'experience'); if(this.quickCapture) { this.activeProjectId=this.projectDirectories.find(p=>p.name==='随手记录 · 待整理'&&p.owner===this.service.username&&this.caseCategories.includes(p.category))?.id || '';this.activeFolderId='';this.projectDisplay='contents'; } this.selectCategory('全部资料'); this.recentUploadIds = this.uploadResults.filter(row => row.id).map(row => row.id); this.mode = experience ? 'cases' : 'library'; this.uploadOpen = false; },
    showMode(mode) { this.mode = mode; },
    selectSpace(id) { this.space = this.space === id ? 'all' : id; },
    resetFilters() { this.tagFilter = ''; this.dateFrom = ''; this.dateTo = ''; this.recentUploadIds = []; this.query = ''; this.space = 'all'; this.favoritesOnly = false; this.mineOnly = false; this.projectFilter = ''; this.industryFilter = ''; this.statusFilter = ''; this.reviewFilter = ''; },
    toggleFavorite(id) { this.favorites = this.favorites.includes(id) ? this.favorites.filter(x => x !== id) : [...this.favorites, id]; try { localStorage.setItem('companyKnowledgeFavorites:' + this.service.username, JSON.stringify(this.favorites)); } catch {} },
    async openDocument(doc) {
      if (!doc.can_read) { await this.requestAccess(doc); return; }
      this.readingHistory = [doc.id, ...this.readingHistory.filter(id => id !== doc.id)].slice(0, 12);
      try { localStorage.setItem('companyKnowledgeReading:' + this.service.username, JSON.stringify(this.readingHistory)); } catch {}
      this.readerLocation = null; this.readerFind = ''; this.readerFocus = false; this.locating = false; this.releaseReader(); this.selectedDoc = { ...doc, references: this.allReferences.filter(ref => ref.document_id === doc.cloud_id) };
      this.readerMode = doc.has_original ? 'original' : 'excerpts'; this.readerTrace = ''; this.readerOriginalLoading = false;
      this.readerOpen = true; this.readerPDFPages = 0; this.previewPage = 1; this.readerTotal = 0; this.readerError = '';
      const id = doc.id, sequence = ++this.readerSequence;
      const current = () => this.selectedDoc?.id === id && this.readerOpen && this.readerSequence === sequence;
      this.readerLoading = true;
      const original = async () => {
        if (!doc.has_original && !doc.media_kind) return;
        if (!doc.media_kind && !['DOCX','DOC','XLS','XLSX','PPT','PPTX','TXT','MD','CSV','PDF','PNG','JPG','JPEG','WEBP','GIF','BMP'].includes(doc.format)) return;
        this.readerOriginalLoading = true;
        try {
          const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + (['PDF','DOC','XLS','XLSX','PPT','PPTX'].includes(doc.format) ? '/page?page=1' : '/original'));
          if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '原件预览暂不可用，请重试或下载水印副本。'); }
          const blob = await response.blob();
          if (!current()) return;
          this.readerTrace = response.headers?.get('X-Watermark-Trace') || '';
          if (['DOCX','TXT','MD','CSV'].includes(doc.format)) this.readerBlob = typeof Vue !== 'undefined' ? Vue.markRaw(blob) : blob;
          else { this.readerUrl = URL.createObjectURL(blob); if (['PDF','DOC','XLS','XLSX','PPT','PPTX'].includes(doc.format)) this.readerPDFPages = Number(response.headers.get('X-Document-Pages') || 1); }
        } catch (error) { if (current()) this.readerError = error.message; }
        finally { if (current()) this.readerOriginalLoading = false; }
      };
      const excerpts = async () => {
        if (doc.media_kind) { this.selectedDoc.references = []; return; }
        try {
          const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + '/preview');
          const result = await response.json();
          if (!response.ok) throw new Error(result.detail || '检索片段加载失败。');
          if (current()) { this.selectedDoc.references = result.references; this.readerTotal = result.total; if (result.message && !doc.has_original) this.readerError = result.message; }
        } catch (error) { if (current() && !doc.has_original) this.readerError = error.message; }
      };
      try { await Promise.all([original(), excerpts()]); }
      finally { if (current()) this.readerLoading = false; }
    },
    releaseReader() { if (this.readerUrl) URL.revokeObjectURL(this.readerUrl); this.readerUrl = ''; this.readerBlob = null; },
    async morePreview() {
      if (this.readerLoading || !this.selectedDoc?.id) return;
      this.readerLoading = true; const id = this.selectedDoc.id, sequence = ++this.readerSequence;
      const current = () => this.selectedDoc?.id === id && this.readerOpen && this.readerSequence === sequence;
      try {
        const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + '/preview?page=' + (this.previewPage + 1));
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '片段加载失败。');
        if (current()) { this.selectedDoc.references.push(...result.references); this.previewPage++; }
      } catch (error) { if (current()) this.readerError = error.message; } finally { if (current()) this.readerLoading = false; }
    },
    downloadPhase(doc) {
      const state = this.downloadProgress[doc.id];
      if (!state) return '转换并加水印中…';
      return ({preparing:'准备安全副本…',converting:'处理兼容格式中…',media:'处理音视频标记中…',
        stamping:state.total_pages ? '水印 ' + state.page + '/' + state.total_pages + (['PDF','PPT','PPTX'].includes(doc.format) ? ' 页' : ' 项') : '添加水印中…',
        packaging:'整理下载文件…',ready:'接收文件中…',receiving:'接收文件中…',handoff:'交给浏览器下载…',failed:'处理失败'})[state.stage] || '生成水印副本中…';
    },
    async downloadOriginal(doc) {
      try { await this.withFeedback('download:' + doc.id, '正在生成带水印下载副本', async phase => {
        const requestId = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(16) + Math.random().toString(16).slice(2);
        const path = '/company-knowledge/documents/' + encodeURIComponent(doc.id);
        const state = {stage:'preparing',page:0,total_pages:0,elapsed:0}; this.downloadProgress[doc.id] = state;
        const started = Date.now(); let polling = false, finished = false;
        const report = () => { if (!finished) phase(this.downloadPhase(doc)); };
        const clock = setInterval(async () => {
          if (this.requestsActive === false || finished) { clearInterval(clock); return; }
          this.downloadProgress[doc.id].elapsed = Math.floor((Date.now() - started) / 1000);
          if (polling) return;
          polling = true;
          try { const response = await this.apiFetch(path + '/export-status?request_id=' + requestId); const progress = await response.json(); if (!finished && response.ok && !['receiving','handoff'].includes(this.downloadProgress[doc.id]?.stage)) { Object.assign(this.downloadProgress[doc.id], progress); report(); } }
          catch {} finally { polling = false; }
        }, 1000);
        try {
          report();
          const response = await this.apiFetch(path + '/download?request_id=' + requestId);
          if (!response.ok) { const result = await response.json(); throw new Error(result.detail || '下载失败。'); }
          this.downloadProgress[doc.id].stage = 'receiving'; report();
          const blob = await response.blob();
          this.downloadProgress[doc.id].stage = 'handoff'; report();
          const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = decodeURIComponent(response.headers?.get('X-Download-Filename') || encodeURIComponent(doc.title)); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
          ElementPlus.ElMessage.success('带水印副本已交给浏览器下载，请查看下载列表');
        } finally { finished = true; clearInterval(clock); delete this.downloadProgress[doc.id]; }
      }, {readOnly:true}); } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    changeScope(ids) { if (this.busy) return; if (ids.length > 20) { ElementPlus.ElMessage.warning('一次最多选择 20 份资料。'); return; } const rows = ids.map(id => this.documents.find(doc => doc.id === id)).filter(Boolean); const experience = rows.length ? this.caseCategories.includes(rows[0].category) : this.currentCollection === 'experience'; if (rows.some(doc => this.caseCategories.includes(doc.category) !== experience)) { ElementPlus.ElMessage.warning('资料库与经验沉淀请分别提问，不能跨库选择资料。'); return; } this.selectedIds = ids; this.chatScope = experience ? 'experience' : 'accessible'; this.newConversation(); },
    toggleSelection(doc) { if (!doc.can_read || doc.state !== 'ready') return; const ids = this.selectedDocuments.filter(row => this.caseCategories.includes(row.category) === this.caseCategories.includes(doc.category)).map(row => row.id); this.changeScope(ids.includes(doc.id) ? ids.filter(id => id !== doc.id) : [...ids, doc.id]); },
    askWhileReading() { if (!this.selectedDoc?.id || this.busy) return; const question = this.draft; if (this.selectedIds.length !== 1 || this.selectedIds[0] !== this.selectedDoc.id) this.changeScope([this.selectedDoc.id]); this.sendQuestion(question); },
    askSelection() { this.mode = 'chat'; this.readerOpen = false; this.$nextTick(() => this.$refs.composer?.focus()); },
    chooseFiles(event) { this.stagedFiles = Array.from(event.target.files || []); this.uploadResults = []; this.uploadError = ''; },
    async uploadFiles() {
      if(!this.uploadBusy)this.prepareCaptureNote?.();
      if (this.uploadBusy || !this.stagedFiles.length) return;
      const tags = this.parseTags(this.uploadForm.tagsText);
      if (tags.length > 20 || tags.some(tag => tag.length > 40)) { this.uploadError = '最多添加 20 个标签，每个不超过 40 字，请修改后重试。'; return; }
      if (!this.quickCapture && !this.activeProjectId && this.stagedFiles.some(file => /\.(mp3|wav|m4a|ogg|flac|mp4|webm)$/i.test(file.name)) && !this.uploadForm.description.trim()) {
        this.uploadError = '请先填写音视频的文字说明，原件无需转写即可归档。'; return;
      }
      if (this.quickCapture && !this.captureTitle.trim()) { this.uploadError='请为这次经验起一个名字。'; return; }
      let captureProjectId='',captureDescription='';
      this.uploadBusy = true; this.uploadError = ''; this.uploadResults = this.uploadResults.filter(row => row.id);
      const failed = [];
      if(this.quickCapture) { try { captureProjectId=await this.captureProject(); captureDescription=[this.captureTitle.trim(),this.captureScene.trim()&&'适用场景：'+this.captureScene.trim(),this.captureMethod.trim()&&'可复用做法：'+this.captureMethod.trim(),this.uploadForm.description.trim()].filter(Boolean).join('\n\n'); } catch(error){this.uploadError=error.message;this.uploadBusy=false;return;} }
      for (const file of this.stagedFiles) {
        const row = { name: file.name, state: '上传中' }; this.uploadResults.push(row); const shown = this.uploadResults[this.uploadResults.length - 1];
        try {
          const media = /\.(mp3|wav|m4a|ogg|flac|mp4|webm)$/i.test(file.name);
          if (file.size > (media ? 128 : 32) * 1024 * 1024) throw new Error(media ? '音视频超过 128 MB 限制' : '超过 32 MB 限制');
          if (media && !captureProjectId && !this.activeProjectId && !this.uploadForm.description.trim()) throw new Error('请填写音视频的文字说明');
          const form = new FormData(); form.append('file', file);
          for (const key of ['project', 'industry', 'category', 'review', 'confidentiality', 'visibility']) form.append(key, this.uploadForm[key]);
          form.append('tags', JSON.stringify(this.parseTags(this.uploadForm.tagsText)));
          form.append('description', this.quickCapture ? captureDescription : this.uploadForm.description);
          if (captureProjectId || this.activeProjectId) { form.append('project_id', captureProjectId || this.activeProjectId); form.append('folder_id', captureProjectId ? '' : this.activeFolderId); }
          form.append('readers', JSON.stringify(this.uploadForm.readersText.split(/[,，\n]/).map(name => name.trim()).filter(Boolean)));
          const response = await this.apiFetch('/company-knowledge/uploads', { method: 'POST', body: form });
          const result = await response.json(); if (!response.ok) throw new Error(result.detail || '上传失败');
          shown.id = result.id; shown.phase = result.state; shown.state = result.label || '等待处理'; shown.detail = '原件已保存，处理状态会自动更新。';
        } catch (error) { shown.state = error.message; failed.push(file); }
      }
      this.stagedFiles = failed; this.uploadBusy = false; await Promise.all([this.loadDocuments(), this.loadMyProjects()]);
    },
    async retryDocument(doc) { try { await this.withFeedback('retry:' + doc.id, '正在重试知识库资料处理', async () => { const response = await this.apiFetch('/company-knowledge/documents/' + doc.id + '/retry', { method: 'POST' }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '重试失败'); ElementPlus.ElMessage.success('处理请求已提交，请查看资料状态'); await this.loadDocuments(); }); } catch (error) { ElementPlus.ElMessage.error(error.message); } },
    editDocument(doc) { if(doc.note_id){this.editRichNote(doc.note_id);return;} this.editingDoc = doc; this.uploadForm = { title: doc.title, folder_id: doc.folder_id || '', project: doc.project || '', industry: doc.industry || '', category: doc.category, review: doc.review, confidentiality: doc.confidentiality === 'confidential' ? 'secret' : doc.confidentiality || 'internal', tagsText: (doc.tags || []).join('，'), description: doc.description || '', visibility: doc.visibility, readersText: (doc.readers || []).join(', ') }; this.metadataOpen = true; },
    async saveMetadata() {
      try { await this.withFeedback('save:' + this.editingDoc.id, '正在保存资料信息', async () => {
        const response = await this.apiFetch('/company-knowledge/documents/' + this.editingDoc.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...this.uploadForm, tags: this.parseTags(this.uploadForm.tagsText), readers: this.uploadForm.readersText.split(/[,，\n]/).map(name => name.trim()).filter(Boolean) }) });
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '保存失败');
        this.metadataOpen = false; this.newConversation(); await Promise.all([this.loadDocuments(), this.loadMyProjects()]);
      }); } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    startUpload() { this.quickCapture=false; if (!this.activeProject) { this.mode = this.mode === 'cases' ? 'cases' : 'library'; this.showProjectRoot(); this.startProjectEditor(); return; } this.uploadForm = { project: this.projectFilter, industry: this.industryFilter, category: this.mode === 'cases' ? (this.category === '全部资料' ? '项目经验' : this.category) : '项目原件', review: '待复核', confidentiality: 'internal', visibility: 'members', readersText: '', tagsText: '', description: '' }; if (this.activeProject) Object.assign(this.uploadForm, { project: this.activeProject.name, industry: this.activeProject.industry, category: this.activeProject.category, review: this.activeProject.review, confidentiality: this.activeProject.confidentiality, visibility: this.activeProject.visibility, tagsText: (this.activeProject.tags || []).join('，'), readersText: (this.activeProject.readers || []).join(', ') }); this.stagedFiles = []; this.uploadResults = []; this.uploadError = ''; this.uploadOpen = true; },
    syncConfidentiality() { if (this.uploadForm.confidentiality !== 'internal') this.uploadForm.visibility = 'restricted'; },
    requestStatusLabel(status) { return ({ pending: '审批中', approved: '已批准', rejected: '已拒绝' })[status] || '未申请'; },
    async requestAccess(doc) {
      if (!doc.can_request && doc.request_status === 'pending') { ElementPlus.ElMessage.info('该资料的权限申请正在审批中。'); return; }
      try {
        const prompt = await ElementPlus.ElMessageBox.prompt('请说明需要阅读《' + doc.title + '》的原因，管理员将根据项目和保密等级审批。', '申请访问权限', { confirmButtonText: '提交申请', cancelButtonText: '取消', inputPlaceholder: '例如：新员工培训，需要学习项目方法', inputValidator: value => Boolean(value && value.trim()) || '请填写申请原因' });
        await this.withFeedback('access:' + doc.id, '正在提交访问权限申请', async () => {
        const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(doc.id) + '/access-requests', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: prompt.value.trim() }) });
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '申请提交失败。');
        ElementPlus.ElMessage.success('申请已提交，所有管理员可在权限审批中查看。'); await Promise.all([this.loadDocuments(), this.loadAccessRequests()]);
        });
      } catch (error) { if (error !== 'cancel' && error !== 'close') ElementPlus.ElMessage.error(error.message || '申请提交失败。'); }
    },
    async decideAccess(request, decision) {
      try {
        let note = '';
        if (decision === 'rejected') { const prompt = await ElementPlus.ElMessageBox.prompt('请填写拒绝原因。', '拒绝访问申请', { confirmButtonText: '确认拒绝', cancelButtonText: '取消', inputValidator: value => Boolean(value && value.trim()) || '请填写拒绝原因' }); note = prompt.value.trim(); }
        await this.withFeedback('decision:' + request.id, '正在保存权限审批结果', async () => {
        const response = await this.apiFetch('/company-knowledge/access-requests/' + request.id + '/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, note }) });
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '审批失败。');
        ElementPlus.ElMessage.success(decision === 'approved' ? '已批准访问。' : '已拒绝申请。'); await Promise.all([this.loadAccessRequests(), this.loadDocuments()]);
        });
      } catch (error) { if (error !== 'cancel' && error !== 'close') ElementPlus.ElMessage.error(error.message || '审批失败。'); }
    },
    async deleteDocument(doc) {
      try { await ElementPlus.ElMessageBox.confirm('从资料库和问答索引移除《' + doc.title + '》？', '删除资料', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }); } catch { return; }
      try { await this.withFeedback('delete:' + doc.id, '正在删除知识库资料', async () => { const response = await this.apiFetch('/company-knowledge/documents/' + doc.id, { method: 'DELETE' }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '删除失败'); this.readerOpen = false; this.metadataOpen = false; this.newConversation(); await Promise.all([this.loadDocuments(), this.loadMyProjects()]); }); } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    referenceGroups(references) {
      const groups = new Map();
      for (const reference of references || []) {
        // Same names may belong to different files; only a stable file ID can merge them.
        const key = reference.document_id || reference.url || 'fragment:' + reference.id;
        if (!groups.has(key)) groups.set(key, { key, document_id: reference.document_id, title: reference.title, references: [] });
        groups.get(key).references.push(reference);
      }
      return [...groups.values()];
    },
    async openCitation(group) { const doc = this.documents.find(doc => doc.cloud_id === group.document_id); if (doc) { await this.openDocument(doc); if(this.readerOpen&&this.selectedDoc?.id===doc.id)await this.locateReference(group.references[0] || {}); } else { this.releaseReader(); this.selectedDoc = { title: group.title, references: group.references }; this.readerOpen = true; } },
    referenceIds(group) { return group.references.map(reference => 'id_' + reference.id).join('、'); },
    answerBlocks(text) {
      const lines = (text || '').split('\n'); const blocks = []; let prose = [];
      const clean = value => value.replace(/<br\s*\/?\s*>/gi, '\n').replace(/\*\*(.+?)\*\*/g, '$1');
      const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => clean(cell.trim()));
      const flush = () => { if (prose.length) { blocks.push({ type: 'text', text: clean(prose.join('\n')) }); prose = []; } };
      for (let index = 0; index < lines.length; index++) {
        if (lines[index].includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])) {
          flush(); const headers = cells(lines[index]); const rows = []; index += 2;
          while (index < lines.length && lines[index].includes('|')) { rows.push(cells(lines[index])); index++; }
          index--; blocks.push({ type: 'table', headers, rows });
        } else prose.push(lines[index]);
      }
      flush(); return blocks;
    },
    updateProgress(answer, event) {
      const last = answer.progress[answer.progress.length - 1];
      if (last && last.stage === event.stage && (last.state === 'active' || event.finished)) {
        Object.assign(last, { label: event.label, detail: event.detail || '', state: event.finished ? 'done' : 'active' });
      } else {
        for (const step of answer.progress) if (step.state === 'active') step.state = 'done';
        answer.progress.push({ stage: event.stage, label: event.label, detail: event.detail || '', state: event.finished ? 'done' : 'active' });
      }
      this.answerStatus = event.label;
    },
    finishProgress(answer, failed = false) { for (const step of answer.progress) if (step.state === 'active') step.state = failed ? 'error' : 'done'; },
    askDocument() { if (!this.selectedDoc?.id || this.busy) return; this.changeScope([this.selectedDoc.id]); this.draft = '请根据《' + this.selectedDoc.title + '》回答：'; this.askSelection(); },
    originalUrl(value) { try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : ''; } catch { return ''; } },
    sizeLabel(bytes) { return bytes < 1048576 ? Math.max(1, Math.round(bytes / 1024)) + ' KB' : (bytes / 1048576).toFixed(1) + ' MB'; },
    newConversation() { this.chatGeneration++; this.controller?.abort(); this.messages = []; this.draft = ''; this.chatAtBottom = true; this.chatSessionId = ''; this.chatHasMore = false; this.chatHistoryBusy = false; this.chatScopeUnavailable = false; this.memoryStatus = ''; this.chatError = ''; },
    applyChatSnapshot(data, prepend = false) {
      this.chatSessionId = data.session_id || ''; this.chatSessions = data.sessions || [];
      this.chatHasMore = !!data.has_more; this.chatScopeUnavailable = !!data.scope_unavailable;
      this.memoryStatus = data.memory_status || ''; this.chatScope = data.scope || 'accessible';
      this.selectedIds = data.document_ids || [];
      const rows = (data.messages || []).map(row => ({ ...row, scope: this.scopeLabel, progress: row.progress || [], references: row.references || [] }));
      this.messages = prepend ? [...rows, ...this.messages.filter(row => !rows.some(previous => previous.id === row.id))] : rows;
      if (data.busy) this.memoryStatus = '该会话仍在生成回答，请稍后点击刷新对话。';
    },
    async loadChatHistory(sessionId = '', more = false) {
      if (this.busy || this.chatHistoryBusy) return;
      this.chatHistoryBusy = true; this.chatError = '';
      const generation = ++this.chatGeneration;
      try {
        let url = '/company-knowledge/conversations' + (sessionId ? '/' + encodeURIComponent(sessionId) : '?collection=' + this.chatCollection);
        if (more && this.messages[0]?.id) url += '?before_id=' + this.messages[0].id;
        const response = await this.apiFetch(url); const data = await response.json();
        if (!response.ok) throw new Error(data.detail || '研究历史加载失败。');
        if (this.chatDisposed || generation !== this.chatGeneration) return;
        this.applyChatSnapshot(data, more); if (!more) this.scrollChat();
      } catch (error) { if (generation === this.chatGeneration && !this.chatDisposed) this.chatError = error.message; }
      finally { if (generation === this.chatGeneration) this.chatHistoryBusy = false; }
    },
    async createChatSession() {
      const response = await this.apiFetch('/company-knowledge/conversations', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({scope:this.chatScope, document_ids:this.selectedIds})});
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || '无法创建研究对话。');
      return data;
    },
    async startConversation() {
      if (this.busy || this.chatHistoryBusy) return;
      this.newConversation(); const generation = this.chatGeneration; this.chatHistoryBusy = true;
      try { const data = await this.createChatSession(); if (!this.chatDisposed && generation === this.chatGeneration) this.applyChatSnapshot(data); }
      catch (error) { if (generation === this.chatGeneration) this.chatError = error.message; }
      finally { if (generation === this.chatGeneration) this.chatHistoryBusy = false; }
    },
    async deleteConversation() {
      if (!this.chatSessionId || this.busy || this.chatHistoryBusy) return;
      try { await ElementPlus.ElMessageBox.confirm('删除当前研究对话及其任务摘要？资料文件和其他会话不受影响。', '删除研究对话', {type:'warning',confirmButtonText:'删除',cancelButtonText:'取消'}); } catch { return; }
      const sessionId = this.chatSessionId, generation = ++this.chatGeneration; this.chatHistoryBusy = true;
      try { const response = await this.apiFetch('/company-knowledge/conversations/' + encodeURIComponent(sessionId), {method:'DELETE'}); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '删除失败。'); if (!this.chatDisposed && generation === this.chatGeneration) this.applyChatSnapshot(data); }
      catch (error) { if (generation === this.chatGeneration) this.chatError = error.message; }
      finally { if (generation === this.chatGeneration) this.chatHistoryBusy = false; }
    },
    scrollChat(force = false) { this.$nextTick(() => { const feed = this.$refs.chatFeed; if (feed && (force || this.chatAtBottom)) { feed.scrollTop = feed.scrollHeight; this.chatAtBottom = true; } }); },
    onChatScroll() { const feed = this.$refs.chatFeed; if (feed) this.chatAtBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 90; },
    async copyAnswer(message) { try { await navigator.clipboard.writeText(message.text); ElementPlus.ElMessage.success('回答已复制'); } catch (_) { ElementPlus.ElMessage.warning('浏览器未允许复制，请选中文字复制。'); } },
    async sendQuestion(question) {
      const content = (typeof question === 'string' ? question : this.draft).trim();
      if (!content || this.busy || this.chatHistoryBusy || !this.canAsk) return;
      if (content.length > 1500) { ElementPlus.ElMessage.warning('问题请控制在 1500 字以内。'); return; }
      if (this.chatScopeUnavailable) { this.chatError = '原资料范围已失效，请重新选择资料并开始新的研究对话。'; return; }
      if (!this.selectedIds.length && !['my-projects','my-experience'].includes(this.chatScope) && /(我的项目|我(?:曾经)?(?:做过|参与过|负责过|上传过|上传的).{0,12}(?:项目|资料|文件)|我.{0,6}(?:做了|做过|参与|负责|上传).{0,10}(?:哪些|什么).{0,6}(?:项目|资料|文件))/.test(content)) { const experience = this.chatCollection === 'experience'; this.newConversation(); this.chatScope = experience ? 'my-experience' : 'my-projects'; }
      const generation = this.chatGeneration;
      this.busy = true; this.chatError = ''; this.memoryStatus = '正在保存到账号…';
      try { if (!this.chatSessionId) { const data = await this.createChatSession(); if (this.chatDisposed || generation !== this.chatGeneration) return; this.chatSessionId = data.session_id; this.chatSessions = data.sessions; } }
      catch (error) { this.chatError = error.message; this.busy = false; return; }
      if (this.chatDisposed || generation !== this.chatGeneration) return;
      this.messages.push({ role: 'user', text: content, scope: this.scopeLabel });
      this.messages.push({ role: 'assistant', text: '', references: [], progress: [], elapsedSeconds: 0, scope: this.scopeLabel, complete: false });
      const answer = this.messages[this.messages.length - 1];
      this.busy = true; this.answerStatus = '正在连接云端知识库…'; this.draft = '';
      this.controller = new AbortController(); this.scrollChat(true);
      const sentToken = localStorage.getItem('accessToken');
      const started = Date.now();
      this.updateProgress(answer, { stage: 'connecting', label: '正在连接知识库', detail: '问题已提交，正在等待云端响应。' });
      this.activityClock = setInterval(() => { answer.elapsedSeconds = Math.max(answer.elapsedSeconds, Math.floor((Date.now() - started) / 1000)); }, 1000);
      let reader;
      try {
        const requestId = globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
        const response = await this.apiFetch('/company-knowledge/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: this.controller.signal, body: JSON.stringify({ message: content, session_id:this.chatSessionId, request_id:requestId, document_ids: this.selectedIds, scope: this.chatScope }) });
        if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '知识库请求失败。'); }
        if (!response.body) throw new Error('浏览器未收到流式回答。');
        reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
        const consume = block => {
          if (this.requestsActive === false || sentToken !== localStorage.getItem('accessToken')) throw new Error('登录或页面已变更，请重新打开知识库。');
          const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
          if (!data) return;
          const event = JSON.parse(data);
          if (this.chatDisposed || generation !== this.chatGeneration) return;
          if (event.type === 'memory') { this.memoryStatus = event.message; answer.memoryMessage = event.message; }
          if (event.type === 'saved') { answer.saved = true; this.memoryStatus = '已保存到当前账号 · ' + (answer.memoryMessage || '每轮回答重新检索资料'); }
          if (event.type === 'redacted') { this.messages.forEach(message => { message.text = event.message; message.references = []; message.redacted = true; }); this.chatScopeUnavailable = true; }
          if (Number.isFinite(event.elapsed_seconds)) answer.elapsedSeconds = Math.max(answer.elapsedSeconds, event.elapsed_seconds);
          if (event.type === 'heartbeat') return;
          if (event.type === 'progress') this.updateProgress(answer, event);
          if (event.type === 'answer_delta') answer.text += event.text;
          if (event.type === 'status') this.answerStatus = event.message;
          if (event.type === 'citations') { for (const reference of event.citations) { const existing = answer.references.findIndex(ref => ref.id === reference.id && ref.document_id === reference.document_id); if (existing >= 0) answer.references[existing] = reference; else answer.references.push(reference); } }
          if (event.type === 'done') { answer.complete = true; answer.usage = event.usage; this.finishProgress(answer); }
          if (event.type === 'error') throw new Error(event.message);
          this.scrollChat();
        };
        while (true) { const { value, done } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done }).replace(/\r\n/g, '\n'); let boundary; while ((boundary = buffer.indexOf('\n\n')) >= 0) { consume(buffer.slice(0, boundary)); buffer = buffer.slice(boundary + 2); } if (done) break; }
        if (buffer.trim()) consume(buffer);
        if (!answer.complete) throw new Error('回答中断，请重新提问。');
      } catch (error) { if (!this.chatDisposed && generation === this.chatGeneration) { answer.error = error.name === 'AbortError' ? '已停止生成。' : error.message; this.memoryStatus = '本次回答未完成，请刷新对话查看已保存记录。'; this.finishProgress(answer, true); } }
      finally { clearInterval(this.activityClock); this.activityClock = null; if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); } if (generation === this.chatGeneration) { this.busy = false; this.controller = null; this.answerStatus = ''; if (!this.chatDisposed) { this.scrollChat(); this.refreshChatSessions(); } } }
      return;
    },
    async refreshChatSessions() { try { const response = await this.apiFetch('/company-knowledge/conversations'); const data = await response.json(); if (response.ok && !this.chatDisposed) this.chatSessions = data.sessions || []; } catch {} },
    onComposerKey(event) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); this.sendQuestion(); } }
  },
  template: `
    <div class="ckb-workspace ckb-workbench" :data-simple-home="mode === 'home'" :class="['ckb-view-' + mode, { 'ckb-chat-workspace': mode === 'chat', 'ckb-motion-paused': motionPaused }]" :data-view="mode" :data-theme="theme">
      <nav class="ckb-navigation" aria-label="知识库导航"><div class="ckb-tabs" role="tablist" aria-label="知识库视图" @keydown="navigateTabs"><span class="ckb-tab-indicator" aria-hidden="true" :style="tabIndicatorStyle"></span>
        <button id="ckb-home-tab" role="tab" aria-label="知识库首页" :aria-selected="mode === 'home'" :tabindex="mode === 'home' ? 0 : -1" :class="{ active: mode === 'home' }" @click="openHome"><i class="fa-solid fa-compass" aria-hidden="true"></i><span class="ckb-tab-copy"><strong>知识库首页</strong></span></button>
        <button id="ckb-library-tab" role="tab" aria-label="资料库" :aria-selected="mode === 'library'" :tabindex="mode === 'library' ? 0 : -1" :class="{ active: mode === 'library' }" @click="browseLibrary"><i class="fa-solid fa-layer-group" aria-hidden="true"></i><span class="ckb-tab-copy"><strong>资料库</strong></span><em>{{ libraryCount }}</em></button>
        <button id="ckb-chat-tab" role="tab" aria-label="智能问答" :aria-selected="mode === 'chat'" :tabindex="mode === 'chat' ? 0 : -1" :class="{ active: mode === 'chat' }" @click="mode = 'chat'"><i class="fa-solid fa-wand-magic-sparkles" aria-hidden="true"></i><span class="ckb-tab-copy"><strong>智能问答</strong></span></button>
        <button id="ckb-cases-tab" role="tab" aria-label="经验沉淀" :aria-selected="mode === 'cases'" :tabindex="mode === 'cases' ? 0 : -1" :class="{ active: mode === 'cases' }" @click="browseCases()"><i class="fa-solid fa-cubes" aria-hidden="true"></i><span class="ckb-tab-copy"><strong><span class="ckb-experience-dot" aria-hidden="true"></span>经验沉淀</strong></span><em>{{ caseCount }}</em></button>
      </div><div class="ckb-nav-actions"><button class="ckb-theme-toggle" aria-label="切换知识库主题" :aria-pressed="theme === 'dark'" :title="theme === 'light' ? '切换为深色主题' : '切换为浅色主题'" @click="setTheme(theme === 'light' ? 'dark' : 'light')"><i :class="theme === 'light' ? 'fa-regular fa-moon' : 'fa-regular fa-sun'" aria-hidden="true"></i></button><button class="ckb-motion-toggle" :aria-pressed="motionPaused" :aria-label="motionPaused ? '开启动效' : '暂停动效'" @click="motionPaused = !motionPaused"><i aria-hidden="true" :class="motionPaused ? 'fa-solid fa-play' : 'fa-solid fa-pause'"></i></button><button v-if="service.is_admin" class="ckb-request-center-button" aria-label="操作记录" @click="openAudit()"><i aria-hidden="true" class="fa-solid fa-clock-rotate-left"></i>操作记录</button><button class="ckb-request-center-button" @click="requestCenterOpen = true; loadAccessRequests()"><i aria-hidden="true" class="fa-regular fa-bell"></i>{{ service.is_admin ? '权限审批' : '我的申请' }}<span v-if="pendingAccessCount">{{ pendingAccessCount }}</span></button><span class="ckb-connection" role="status" :title="canAsk ? '知识库已连接' : serviceError ? '连接未就绪' : '正在连接知识库'" :aria-label="canAsk ? '知识库已连接' : serviceError ? '连接未就绪' : '正在连接知识库'"><span :class="{ online: canAsk }"></span><span v-if="!canAsk">{{ serviceError ? '连接未就绪' : '正在连接知识库' }}</span></span></div></nav>
      <div v-if="serviceError" class="ckb-service-error" role="alert">{{ serviceError }} <button @click="loadService">重试</button></div>
      <section v-if="mode === 'home'" class="ckb-simple-home" role="tabpanel" aria-labelledby="ckb-home-tab">
        <section class="ckb-simple-search-panel" aria-label="查找资料">
          <form @submit.prevent="searchHomeDocuments">
            <label class="ckb-simple-search-label" for="ckb-home-search">搜索资料</label>
            <div class="ckb-simple-search-row"><input id="ckb-home-search" v-model="homeSearch" type="search" maxlength="200" placeholder="文件名、项目或行业" :disabled="!canAsk"><button type="submit" class="ckb-simple-button is-primary" aria-label="搜索资料" :disabled="!canAsk">搜索</button></div>
          </form>
          <div class="ckb-simple-tools-actions"><button class="ckb-simple-button is-primary" aria-label="选择项目上传" :disabled="!canAsk" @click="browseLibrary"><i class="fa-solid fa-plus" aria-hidden="true"></i>选择项目上传</button></div>
        </section>
        <div class="ckb-simple-overview">
        <section class="ckb-simple-recent" aria-label="最近资料" :aria-busy="loading">
          <header><div class="ckb-home-activity-tabs" role="group" aria-label="最近资料切换"><button type="button" :aria-pressed="homeActivityTab === 'updated'" @click="homeActivityTab = 'updated'">最近更新</button><button type="button" :aria-pressed="homeActivityTab === 'viewed'" @click="homeActivityTab = 'viewed'">最近浏览</button></div><button class="ckb-simple-link" @click="openHomeLibrary">查看全部</button></header>
          <ul v-if="homeActivityDocuments.length" class="ckb-simple-files">
            <li v-for="doc in homeActivityDocuments" :key="doc.id"><span class="ckb-simple-format" role="img" :aria-label="doc.format || '文件'" :title="doc.format || '文件'"><i :class="['ckb-file-type-icon', 'filetype-' + fileTypeKind(doc), fileTypeIcon(doc)]" aria-hidden="true"></i></span><button class="ckb-simple-file-name" :title="doc.title" @click="openDocument(doc)"><strong>{{ doc.title }}</strong><span>{{ doc.project || doc.category || '未归类' }}</span></button><div class="ckb-simple-file-meta"><span class="ckb-simple-review">{{ doc.review || '待复核' }}</span><time>{{ doc.date }}</time></div></li>
          </ul>
          <div v-else class="ckb-simple-empty"><strong>{{ loading ? '正在加载资料…' : homeActivityTab === 'viewed' ? '暂无浏览记录' : '暂无可访问资料' }}</strong><button class="ckb-simple-button" @click="openHomeLibrary">打开资料库</button></div>
        </section>
        <details class="ckb-simple-atlas" open><summary><strong>知识星图</strong></summary>          <aside class="ckb-knowledge-atlas" aria-label="知识导航">
            <header><span><i aria-hidden="true"></i> KNOWLEDGE ATLAS</span><small>你的知识，彼此连接</small></header>
            <div class="ckb-atlas-stage">
              <svg class="ckb-atlas-wiring" viewBox="0 0 560 360" fill="none" aria-hidden="true"><defs><radialGradient id="ckb-atlas-glow"><stop stop-color="currentColor" stop-opacity=".18"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></radialGradient></defs><ellipse cx="280" cy="180" rx="175" ry="160" fill="url(#ckb-atlas-glow)"/><g class="ckb-atlas-routes"><path d="M140 74H195L245 145M420 74H365L315 145M140 286H195L245 215M420 286H365L315 215"/><ellipse cx="280" cy="180" rx="142" ry="106"/><ellipse cx="280" cy="180" rx="190" ry="142"/></g><g class="ckb-orbit-runner"><circle cx="280" cy="74" r="3"/><circle cx="280" cy="286" r="3"/></g><path class="ckb-atlas-pulse" d="M140 74H195L245 145M420 286H365L315 215"/></svg>
              <div class="ckb-atlas-core"><div class="ckb-prism" aria-hidden="true"><i></i><i></i><i></i><b class="fa-solid fa-layer-group"></b></div><strong>{{ readableDocuments.length }}</strong><span>份可访问资料</span></div>
              <button v-for="node in homeKnowledgeNodes" :key="node.key" :class="['ckb-atlas-node', 'ckb-atlas-' + node.key]" @click="browseHomeNode(node.key)"><span><i aria-hidden="true" :class="'fa-regular ' + (node.key === 'cases' ? 'fa-folder-closed' : node.icon)"></i>{{ node.label }}<i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></span><strong>{{ node.count }}<small>{{ node.unit }}</small></strong><p>{{ node.caption }}</p></button>
            </div>
            <footer><span><i class="fa-solid fa-link" aria-hidden="true"></i> 原始资料 → 研究结论 → 可复用经验</span><small>{{ loading ? '正在同步资料…' : '基于当前可访问内容' }}</small></footer>
          </aside></details>
        </div>
      </section>
      <section v-if="mode === 'library' || mode === 'cases'" :key="mode" class="ckb-library-layout ckb-view-panel" :class="{ 'ckb-cases-layout': mode === 'cases' }" role="tabpanel" :aria-labelledby="mode === 'cases' ? 'ckb-cases-tab' : 'ckb-library-tab'">
        <aside class="ckb-library-sidebar"><div class="ckb-rail-brand"><span><i aria-hidden="true" :class="mode === 'cases' ? 'fa-solid fa-cubes' : 'fa-solid fa-layer-group'"></i></span><div>{{ mode === 'cases' ? '经验档案' : '资料空间' }}</div></div><span class="ckb-aside-label">知识分类</span>
          <button v-for="item in visibleCategories" :key="item" :class="{ active: category === item && !mineOnly && !favoritesOnly }" @click="selectCategory(item)">{{ item === '全部资料' && mode === 'cases' ? '全部经验' : item }}<small>{{ item === '全部资料' ? (mode === 'cases' ? caseCount : libraryCount) : collectionDocuments.filter(doc => doc.category === item).length }}</small></button>
          <div class="ckb-sidebar-divider"></div><span class="ckb-aside-label">我的工作</span>
          <button :class="{ active: mineOnly }" @click="browseMyProject()">我的项目<small>{{ collectionMineCount }}</small></button>
          <button :class="{ active: favoritesOnly }" @click="selectFavorites">我的收藏<small>{{ favorites.length }}</small></button>
          <button :class="{ active: statusFilter === 'failed' }" @click="selectFailed">处理失败<small>{{ failedCount }}</small></button>
          <p>资料按账号权限展示。项目和行业用于归类筛选。</p>
        </aside>
        <div class="ckb-library-content" :class="{'ckb-sparse-space': showingProjects ? visibleProjectDirectories.length &lt; 3 : filteredDocuments.length &lt; 3}"><div class="ckb-archive-scene" aria-hidden="true"><svg viewBox="0 0 600 500" fill="none"><g stroke="currentColor" stroke-width="1"><circle cx="310" cy="248" r="186" stroke-dasharray="3 12"/><circle cx="310" cy="248" r="150"/><path d="M85 248H535M310 23V473" stroke-dasharray="2 9"/><path d="M202 190V165Q202 153 214 153H273L296 174H409Q421 174 421 186V333Q421 345 409 345H214Q202 345 202 333Z"/><path d="M233 220V147Q233 139 241 139H341L374 171V220M341 139V174H374M255 181H312M255 195H344"/><path d="M190 220H432L416 337Q415 345 405 345H218Q208 345 207 336Z"/><path d="M280 273L310 257L340 273L310 289ZM280 285L310 301L340 285M280 297L310 313L340 297"/><path d="M116 178H164L190 220M432 272H473L500 302M292 345V389H358"/><circle cx="116" cy="178" r="4"/><circle cx="500" cy="302" r="4"/><circle cx="358" cy="389" r="4"/></g></svg></div><nav v-if="!showingProjects" class="ckb-directory-path" aria-label="项目目录路径"><button @click="showProjectRoot"><i class="fa-solid fa-boxes-stacked" aria-hidden="true"></i>项目空间</button><template v-if="activeProject"><i class="fa-solid fa-angle-right" aria-hidden="true"></i><button @click="openDirectory(activeProject)">{{ activeProject.name }}</button><template v-for="folder in directoryBreadcrumbs" :key="folder.id"><i class="fa-solid fa-angle-right" aria-hidden="true"></i><button @click="openDirectory(activeProject, folder.id)">{{ folder.name }}</button></template></template><span v-else-if="!showingProjects">/ 全部文件</span></nav><header class="ckb-library-heading"><div><h2>{{ searchMode === 'content' ? '正文搜索' : activeProject ? (directoryBreadcrumbs.at(-1)?.name || activeProject.name) : showingProjects ? (mineOnly ? '我的项目' : mode === 'cases' ? '经验空间' : '项目空间') : favoritesOnly ? '我的收藏' : '全部文件' }}</h2><span class="ckb-heading-count">{{ searchMode === 'content' ? (contentSearched ? contentTotal + ' 个片段' : '当前库') : showingProjects ? visibleProjectDirectories.length + ' 个' : filteredDocuments.length + ' 份资料' }}</span></div><div class="ckb-library-tools"><label class="ckb-search"><i aria-hidden="true" class="fa-solid fa-magnifying-glass"></i><input v-model="query" aria-label="搜索知识库资料" :placeholder="searchMode === 'content' ? '搜索正文内容，按 Enter 查看相关片段' : '搜索项目或文件'" @keydown.enter="searchMode === 'content' &amp;&amp; searchContent()"><button v-if="query" aria-label="清空搜索" @click="query = ''">×</button></label><button class="ckb-button ckb-button-outline" :disabled="loading || !canAsk" @click="loadDocuments(false, true)">{{ loading ? '加载中…' : '刷新' }}</button><template v-if="activeProject"><button v-if="activeProject.can_manage" class="ckb-button ckb-button-outline" @click="startFolderEditor()"><i class="fa-solid fa-folder-plus" aria-hidden="true"></i>新建目录</button><button v-if="activeProject.can_manage" class="ckb-directory-settings" aria-label="编辑项目" title="项目设置" @click="startProjectEditor(activeProject)"><i class="fa-solid fa-sliders" aria-hidden="true"></i></button><button v-if="activeProject.can_manage" class="ckb-button ckb-button-primary" aria-label="上传文件" :disabled="!canAsk" @click="startUpload"><i class="fa-solid fa-plus" aria-hidden="true"></i>上传文件</button></template><button v-else class="ckb-button ckb-button-primary" :disabled="!canAsk" @click="startProjectEditor()"><i class="fa-solid fa-plus" aria-hidden="true"></i>创建项目</button></div></header>
          <div v-if="mode === 'cases'" class="ckb-case-intro"><p>把照片、手稿、录音与视频，沉淀成可复用的经验。</p><span><i class="fa-regular fa-image" aria-hidden="true"></i>照片</span><span><i class="fa-solid fa-pen-nib" aria-hidden="true"></i>手稿</span><span><i class="fa-solid fa-wave-square" aria-hidden="true"></i>录音</span><span><i class="fa-solid fa-play" aria-hidden="true"></i>视频</span><small>照片与手稿识别文字 · 音视频检索说明</small><div class="ckb-note-tools"><button class="ckb-button ckb-button-outline" :disabled="noteCreating || !!openingDirectoryId || !canAsk || (activeProject && !activeProject.can_manage)" @click="createRichNote"><i class="fa-solid fa-pen-to-square" aria-hidden="true"></i>{{noteCreating?'正在创建…':'新建图文笔记'}}</button></div></div><p v-if="mode==='cases' && noteError" class="ckb-service-error" role="alert">{{noteError}}<button @click="loadNotes">重试</button></p><details v-if="mode==='cases' && noteDrafts.some(note=>!activeProjectId||note.project_id===activeProjectId)" class="ckb-note-drafts"><summary>我的笔记 · 草稿与已发布 <small>草稿仅项目创建者与管理员可见</small></summary><div><button v-for="note in noteDrafts.filter(note=>!activeProjectId||note.project_id===activeProjectId)" :key="note.id" @click="editRichNote(note.id)"><strong>{{note.title}}</strong><small>{{note.has_unpublished_changes?'有未发布修改':note.index_state==='failed'?'索引失败':note.indexed_revision?'已发布':'草稿'}} · {{new Date(note.updated_at).toLocaleDateString('zh-CN')}}</small></button></div></details>
          <div v-if="libraryIntent === 'compare'" class="ckb-compare-intent" role="status"><div><strong>先选择资料，再比较结论</strong><span>勾选至少 2 份可检索资料，下一步进入问答确认比较问题。</span></div><button @click="libraryIntent = ''">退出比较</button></div>
          <div v-if="mineOnly" class="ckb-inline-project-summary"><span>共 {{ collectionMineCount }} 个项目、{{ collectionMineDocumentCount }} 份资料，只统计当前库中本人上传的内容。</span><button class="ckb-button ckb-button-primary" :disabled="!collectionMineDocumentCount || busy" @click="summarizeMyProjects">AI 总结项目</button></div>

          <section class="ckb-catalog-controls" aria-label="搜索与筛选">
            <div class="ckb-catalog-toolbar"><div class="ckb-search-modes" role="group" aria-label="搜索方式"><button :aria-pressed="searchMode === 'metadata'" @click="setSearchMode('metadata')"><i class="fa-regular fa-folder-open" aria-hidden="true"></i>找文件</button><button title="搜索当前范围内可访问的正文和说明" :aria-pressed="searchMode === 'content'" @click="setSearchMode('content')"><i class="fa-solid fa-align-left" aria-hidden="true"></i>搜正文</button></div><select v-model="industryFilter" aria-label="筛选行业"><option value="">全部行业</option><option v-for="item in industryOptions" :key="item">{{ item }}</option></select><select v-model="reviewFilter" aria-label="筛选复核状态"><option value="">全部复核状态</option><option>待复核</option><option>已复核</option><option>参考资料</option></select><button type="button" class="ckb-more-filters" :aria-expanded="advancedFiltersOpen" aria-controls="ckb-catalog-advanced" @click="advancedFiltersOpen = !advancedFiltersOpen">更多筛选<span v-if="advancedFilterCount" class="ckb-filter-count">{{ advancedFilterCount }}</span><i class="fa-solid" :class="advancedFiltersOpen ? 'fa-chevron-up' : 'fa-chevron-down'" aria-hidden="true"></i></button><button type="button" class="ckb-clear-filters" aria-label="清空筛选" title="清空筛选" @click="resetFilters">清空</button><button v-if="searchMode === 'content'" class="ckb-button ckb-button-primary" :disabled="contentBusy || !canAsk" @click="searchContent()">{{ contentBusy ? '检索中…' : '搜索正文' }}</button><button v-if="mode === 'cases'" class="ckb-button ckb-button-outline" :disabled="!canAsk" @click="openQuickCapture"><i class="fa-solid fa-pen-nib" aria-hidden="true"></i>随手记录</button><button v-if="showingProjects" type="button" class="ckb-catalog-files" @click="showAllFiles">全部文件<i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></div>
            <div v-show="advancedFiltersOpen" id="ckb-catalog-advanced" class="ckb-catalog-advanced"><label v-if="!activeProject"><span>项目</span><select v-if="!activeProject" v-model="projectFilter" aria-label="筛选项目"><option value="">全部项目</option><option v-for="item in projectOptions" :key="item">{{ item }}</option></select></label><label><span>处理状态</span><select v-model="statusFilter" aria-label="筛选处理状态"><option value="">全部处理状态</option><option value="ready">可检索</option><option value="queued">等待处理</option><option value="uploading">上传中</option><option value="parsing">解析中</option><option value="indexing">索引中</option><option value="failed">处理失败</option><option value="archived">已归档（未检索）</option></select></label><label><span>标签</span><select v-model="tagFilter" aria-label="筛选标签"><option value="">全部标签</option><option v-for="item in tagOptions" :key="item">{{ item }}</option></select></label><div class="ckb-catalog-date"><span>时间范围</span><div class="ckb-date-filter"><select v-model="dateField" aria-label="时间类型"><option value="created_at">上传时间</option><option value="modified_at">更新时间</option></select><input type="date" v-model="dateFrom" aria-label="开始日期" :max="dateTo || undefined"><span>至</span><input type="date" v-model="dateTo" aria-label="结束日期" :min="dateFrom || undefined"></div></div></div>
          </section>

          <div v-if="!showingProjects && searchMode !== 'content'" class="ckb-selection-bar"><div v-if="mode === 'library'" class="ckb-view-switch" role="group" aria-label="资料展示方式"><button :aria-pressed="libraryLayout === 'grid'" @click="libraryLayout = 'grid'; scrollLibraryTop()"><i aria-hidden="true" class="fa-solid fa-border-all"></i> 卡片</button><button :aria-pressed="libraryLayout === 'list'" @click="libraryLayout = 'list'; scrollLibraryTop()"><i aria-hidden="true" class="fa-solid fa-list-ul"></i> 列表</button></div><span class="ckb-scope-counter"><i aria-hidden="true" class="fa-solid fa-crosshairs"></i>{{ selectedIds.length ? '已选 ' + selectedIds.length + ' 份 · 仅从所选资料检索' : '勾选资料，限定本轮问答范围' }}</span><div><select v-model="sortOrder" aria-label="资料排序"><option value="updated">最近更新</option><option value="title">名称排序</option></select><button v-if="selectedIds.length" :disabled="busy" @click="changeScope([])">取消选择</button><button class="ckb-button ckb-button-primary" :disabled="!canAsk || busy || (libraryIntent === 'compare' && selectedIds.length < 2)" @click="askLibrary">{{ libraryIntent === 'compare' ? '比较选中资料（' + selectedIds.length + '）' : selectedIds.length ? '向选中资料提问' : libraryScopeFiltered ? '向当前资料提问' : (mode === 'cases' ? '检索全部经验' : '检索全部资料') }} <i aria-hidden="true" class="fa-solid fa-arrow-right"></i></button></div></div>
          <section v-if="searchMode === 'content'" ref="documentTable" class="ckb-content-results ckb-table-scroll" aria-label="正文搜索结果" :aria-busy="contentBusy"><header><strong>正文与说明</strong><span v-if="contentSearched &amp;&amp; !contentBusy">{{ contentTotal }} 个相关片段 · 按语义相关度排序</span></header><p v-if="contentBusy" role="status"><i class="fa-solid fa-circle-notch fa-spin" aria-hidden="true"></i>正在当前范围中查找正文…</p><p v-else-if="contentError" role="alert">{{ contentError }}</p><div v-else-if="!contentMatches.length" class="ckb-search-welcome"><i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i><h3>{{ contentSearched ? '暂未找到相关正文' : '从正文中，找到线索。' }}</h3><p>{{ contentSearched ? '试试更具体的关键词，或调整项目与标签范围。' : '输入关键词并搜索，直接查看原文片段和来源。音视频仅搜索人工说明。' }}</p></div><article v-for="match in contentMatches" :key="match.reference.document_id + ':' + match.reference.id"><button class="ckb-search-result-title" @click="openCitation({document_id:match.reference.document_id,title:match.document.title,references:[match.reference]})"><span class="ckb-search-result-type">{{ match.document.format }}</span><strong>{{ match.document.title }}</strong><span>定位原文<i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></span></button><small>{{ match.document.project }} · {{ match.reference.pages?.length ? '来源页 '+match.reference.pages.join('、') : match.document.media_kind ? '人工填写的说明' : '正文片段' }}</small><p class="ckb-search-snippet"><template v-for="(part,index) in highlightedParts(match.reference.text)" :key="index"><mark v-if="part.match">{{ part.text }}</mark><span v-else>{{ part.text }}</span></template></p></article><nav v-if="contentTotal > 10" class="ckb-content-pagination" aria-label="正文结果分页"><button :disabled="contentBusy || contentPage===1" @click="searchContent(contentPage-1)">上一页</button><span>{{ contentPage }} / {{ Math.ceil(contentTotal/10) }}</span><button :disabled="contentBusy || contentPage*10>=contentTotal" @click="searchContent(contentPage+1)">下一页</button></nav></section>
          <div v-else-if="showingProjects" ref="documentTable" class="ckb-directory-grid ckb-table-scroll ckb-directory-stage" aria-label="项目目录" role="list">
            <div v-if="visibleProjectDirectories.length" class="ckb-project-list-head" aria-hidden="true"><span>项目名称</span><span>类别</span><span>时间</span><span>操作</span></div>
            <el-popover v-for="project in visibleProjectDirectories" :key="project.id" placement="right-start" strategy="fixed" transition="none" :reference-el="projectPreview.reference || undefined" :fallback-placements="['left-start','right-end','left-end','bottom-start','top-start']" :width="400" :visible="projectPreview.id === project.id" :trigger="[]" :show-after="0" :hide-after="0" :persistent="false" :show-arrow="false" :offset="14" :enterable="true" popper-class="ckb-project-detail-popover">
              <template #reference><article class="ckb-project-directory ckb-project-card-small ckb-project-row" role="listitem" :class="{ opening: openingDirectoryId === project.id }" :data-project-preview-row="project.id" tabindex="0" :aria-label="'项目详情：' + project.name" @pointerenter="queueProjectPreview(project, $event)" @pointermove="queueProjectPreview(project, $event)" @pointerleave="leaveProjectPreview(project, $event)" @focusin="focusProjectPreview(project, $event)" @focusout="leaveProjectPreview(project, $event)">
                <button type="button" class="ckb-project-door" :aria-label="'进入项目：' + project.name" @click.stop="dismissProjectPreview(); openDirectory(project)" @keydown.enter.stop @keydown.space.stop><h3 :title="project.name"><svg class="ckb-project-folder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M3.5 8.5V6.2c0-.9.7-1.7 1.7-1.7h4.1l2.1 2.1h7.4c.9 0 1.7.7 1.7 1.7v.2"/><path d="M4.2 8.5h15.6c1.1 0 1.9 1 1.6 2l-1.4 7.3c-.2.9-.9 1.5-1.8 1.5H5.8c-.9 0-1.6-.6-1.8-1.5l-1.4-7.3c-.3-1 .5-2 1.6-2Z"/></svg><span>{{ project.name }}</span></h3><div class="ckb-project-card-meta"><span>{{ project.category || '未分类' }}</span><time :datetime="project.updated_at || project.modified_at || project.created_at" :title="project.updated_at || project.modified_at ? '更新时间' : '创建时间'">{{ projectCardDate(project.updated_at || project.modified_at || project.created_at) }}</time></div></button>
                <div class="ckb-project-card-actions"><button type="button" class="ckb-project-info" :data-project-preview-trigger="project.id" :aria-label="'查看详情：' + project.name" :aria-expanded="projectPreview.id === project.id" :aria-controls="'ckb-project-preview-' + project.id" @click.stop="toggleProjectPreview(project, $event)" @keydown.enter.stop @keydown.space.stop><i class="fa-solid fa-circle-info" aria-hidden="true"></i></button><button v-if="project.can_manage" type="button" class="ckb-project-edit" :aria-label="'编辑项目：' + project.name" @click.stop="dismissProjectPreview(); startProjectEditor(project)" @keydown.enter.stop @keydown.space.stop><i class="fa-solid fa-ellipsis" aria-hidden="true"></i></button></div>
              </article></template>
              <section :id="'ckb-project-preview-' + project.id" class="ckb-project-preview" :aria-label="'项目详情：' + project.name" @pointerenter="holdProjectPreview" @pointerleave="leaveProjectPreview(project, $event)" @focusin="holdProjectPreview" @focusout="leaveProjectPreview(project, $event)">
                <header class="ckb-project-preview-header"><span class="ckb-preview-folder" aria-hidden="true"><svg class="ckb-preview-folder-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M3.5 8.5V6.2c0-.9.7-1.7 1.7-1.7h4.1l2.1 2.1h7.4c.9 0 1.7.7 1.7 1.7v.2"/><path d="M4.2 8.5h15.6c1.1 0 1.9 1 1.6 2l-1.4 7.3c-.2.9-.9 1.5-1.8 1.5H5.8c-.9 0-1.6-.6-1.8-1.5l-1.4-7.3c-.3-1 .5-2 1.6-2Z"/></svg></span><div><strong>{{ project.name }}</strong><div class="ckb-project-preview-labels"><span>{{ project.category || '未分类' }}</span><span v-if="project.confidentiality">{{ {internal:'内部',secret:'机密'}[project.confidentiality] || '机密' || project.confidentiality }}</span></div></div><button type="button" class="ckb-project-preview-close" aria-label="关闭项目简介" @click="dismissProjectPreview(true)"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button></header>
                <div class="ckb-project-preview-content"><p class="ckb-project-preview-description" :class="{'is-empty':!project.description}">{{ project.description || '暂无项目简介' }}</p><div class="ckb-project-preview-stats"><div><strong>{{ project.folder_count ?? '—' }}</strong><span>目录</span></div><div><strong>{{ project.document_count ?? '—' }}</strong><span>资料</span></div></div><dl><div v-if="project.industry"><dt>行业</dt><dd>{{ project.industry }}</dd></div><div v-if="project.owner"><dt>创建人</dt><dd>{{ project.owner }}</dd></div><div><dt>{{ project.updated_at || project.modified_at ? '更新于' : '创建于' }}</dt><dd>{{ projectCardDate(project.updated_at || project.modified_at || project.created_at, true) }}</dd></div></dl><div v-if="project.tags?.length" class="ckb-project-preview-tags"><span v-for="tag in project.tags" :key="tag">{{ tag }}</span></div></div>
                <footer class="ckb-project-preview-footer"><button type="button" @click="dismissProjectPreview(); openDirectory(project)">打开项目<i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></footer>
              </section>
            </el-popover>
            <div v-if="!visibleProjectDirectories.length" class="ckb-space-empty ckb-project-empty-small"><h3>{{ loading ? '正在加载项目…' : directorySearchActive ? '没有匹配的项目' : '暂无项目' }}</h3><div class="ckb-space-empty-actions"><button v-if="directorySearchActive" class="ckb-button ckb-button-outline" @click="resetFilters">清除筛选</button><button class="ckb-button ckb-button-primary" :disabled="!canAsk || loading" @click="startProjectEditor()"><i class="fa-solid fa-plus" aria-hidden="true"></i>创建项目</button></div></div><p v-if="projectError" class="ckb-service-error" role="alert">{{ projectError }}<button @click="loadProjectDirectories">重新加载</button></p>
          </div>
          <div v-else-if="mode === 'library' && libraryLayout === 'grid'" ref="documentTable" class="ckb-file-gallery ckb-table-scroll ckb-directory-stage" :key="'library:' + activeProjectId + ':' + activeFolderId" tabindex="0" aria-label="资料卡片，可滚动"><article v-for="folder in visibleFolders" :key="folder.id" class="ckb-subfolder-card" :class="{ opening: openingDirectoryId === folder.id }"><button @click="openDirectory(activeProject, folder.id)"><knowledge-folder-artwork/><strong><svg class="ckb-project-folder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M3.5 8.5V6.2c0-.9.7-1.7 1.7-1.7h4.1l2.1 2.1h7.4c.9 0 1.7.7 1.7 1.7v.2"/><path d="M4.2 8.5h15.6c1.1 0 1.9 1 1.6 2l-1.4 7.3c-.2.9-.9 1.5-1.8 1.5H5.8c-.9 0-1.6-.6-1.8-1.5l-1.4-7.3c-.3-1 .5-2 1.6-2Z"/></svg>{{ folder.name }}</strong><small>{{ projectFolders.filter(item => item.parent_id === folder.id).length }} 个子目录 · {{ documents.filter(doc => doc.folder_id === folder.id).length }} 份资料</small><i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></button><button v-if="activeProject.can_manage" class="ckb-folder-edit" :aria-label="'编辑目录：' + folder.name" @click="startFolderEditor(folder)"><i class="fa-solid fa-ellipsis" aria-hidden="true"></i></button></article>
            <article v-for="doc in pagedDocuments" :key="doc.id" :class="['ckb-file-card', 'kind-' + fileAppearance(doc), { selected: selectedIds.includes(doc.id), locked: !doc.can_read }]">
              <div class="ckb-file-art">
                <label class="ckb-file-select"><input type="checkbox" :checked="selectedIds.includes(doc.id)" :disabled="busy || !doc.can_read || doc.state !== 'ready'" :aria-label="'选择资料：' + doc.title" @change="toggleSelection(doc)"></label>
                <knowledge-thumbnail :key="doc.id + doc.modified_at" :doc="doc" :fetch-image="apiFetch"/><span class="ckb-file-format">{{ doc.format }}</span>
                <knowledge-file-artwork :format="doc.format" :kind="fileAppearance(doc)" :media-kind="doc.media_kind"/>
                <span class="ckb-file-art-caption">{{ doc.category }}</span>
                <span v-if="!doc.can_read" class="ckb-file-locked"><i aria-hidden="true" class="fa-solid fa-lock"></i> 受限</span>
                <button v-else class="ckb-file-favorite" :aria-label="favorites.includes(doc.id) ? '取消收藏：' + doc.title : '收藏资料：' + doc.title" :aria-pressed="favorites.includes(doc.id)" @click="toggleFavorite(doc.id)"><i aria-hidden="true" :class="favorites.includes(doc.id) ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark'"></i></button>
              </div>
              <div class="ckb-file-body"><button class="ckb-file-title" :title="doc.title" @click="openDocument(doc)"><i :class="['ckb-file-type-icon', 'filetype-' + fileTypeKind(doc), fileTypeIcon(doc)]" aria-hidden="true"></i>{{ doc.title }}</button>
                <div class="ckb-file-project"><i aria-hidden="true" class="fa-regular fa-folder-open"></i><span>{{ doc.project || '未归档项目' }}</span><small>{{ doc.industry || '未标记行业' }}</small></div>
                <p v-if="doc.can_read && doc.description" class="ckb-file-description">{{ doc.description }}</p>
                <div v-if="doc.can_read && doc.tags?.length" class="ckb-doc-tags"><button v-for="tag in doc.tags.slice(0, 3)" :key="tag" @click="tagFilter = tag"># {{ tag }}</button><span v-if="doc.tags.length > 3">+{{ doc.tags.length - 3 }}</span></div>
                <div class="ckb-file-details"><span>{{ sizeLabel(doc.size || 0) }} · V{{ doc.version }}</span><b :class="['ckb-confidentiality', 'level-' + doc.confidentiality]">{{ doc.confidentiality_label || '内部' }}</b><span :class="['ckb-state', 'ckb-state-' + (doc.can_read ? doc.state : 'locked')]" :title="doc.status_message">{{ knowledgeState(doc) }}</span></div>
              </div>
              <footer class="ckb-file-footer"><span :title="'更新：' + doc.date + ' · ' + (doc.owner || '云端导入')">{{ doc.date }}<small :class="{ 'ckb-review-pending': doc.review === '待复核' }">{{ doc.review }}</small></span><div><button v-if="doc.can_manage" aria-label="管理资料" @click="editDocument(doc)">管理</button><button v-if="doc.can_manage && doc.state === 'failed' && doc.has_original" @click="retryDocument(doc)">重试</button><button v-if="doc.can_read" class="ckb-file-open" @click="openDocument(doc)">{{ doc.media_kind ? '播放' : '阅读' }}<i aria-hidden="true" class="fa-solid fa-arrow-up-right-from-square"></i></button><button v-else :disabled="doc.request_status === 'pending' || operationPending('access:' + doc.id)" @click="requestAccess(doc)">{{ doc.request_status === 'pending' ? '审批中' : doc.request_status === 'rejected' ? '重新申请' : '申请权限' }}</button></div></footer>
            </article>
            <div v-if="!filteredDocuments.length && !visibleFolders.length" class="ckb-gallery-empty"><i aria-hidden="true" class="fa-regular fa-folder-open"></i><h3>{{ loading ? '正在连接资料空间…' : directorySearchActive ? '没有匹配的文件' : '打开的目录，等待第一份资料。' }}</h3><p>{{ directorySearchActive ? '试试调整关键词、标签或日期范围。' : '可以创建子目录，或上传文档、录音和视频。' }}</p><button v-if="directorySearchActive" class="ckb-button ckb-button-outline" @click="resetFilters">清除筛选</button><button v-else-if="activeProject?.can_manage" class="ckb-button ckb-button-primary" :disabled="loading || !canAsk" @click="startUpload">上传第一份资料</button></div>
          </div>
          <div v-else-if="mode === 'library'" ref="documentTable" class="ckb-table-scroll" tabindex="0" aria-label="资料列表，可滚动"><div v-if="visibleFolders.length" class="ckb-folder-rail"><article v-for="folder in visibleFolders" :key="folder.id" class="ckb-subfolder-card" :class="{ opening: openingDirectoryId === folder.id }"><button @click="openDirectory(activeProject, folder.id)"><knowledge-folder-artwork/><strong>{{ folder.name }}</strong><small>{{ projectFolders.filter(item => item.parent_id === folder.id).length }} 个子目录 · {{ documents.filter(doc => doc.folder_id === folder.id).length }} 份资料</small><i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></button><button v-if="activeProject.can_manage" class="ckb-folder-edit" :aria-label="'编辑目录：' + folder.name" @click="startFolderEditor(folder)"><i class="fa-solid fa-ellipsis" aria-hidden="true"></i></button></article></div><table class="ckb-document-table"><thead><tr><th class="ckb-check-column"></th><th>资料名称</th><th>项目 / 行业</th><th>复核与索引</th><th>更新 / 版本</th><th>操作</th></tr></thead><tbody>
            <tr v-for="doc in pagedDocuments" :key="doc.id" :class="{ selected: selectedIds.includes(doc.id), locked: !doc.can_read }">
              <td><input type="checkbox" :checked="selectedIds.includes(doc.id)" :disabled="busy || !doc.can_read || doc.state !== 'ready'" :aria-label="'选择资料：' + doc.title" @change="toggleSelection(doc)"></td>
              <td class="ckb-name-cell"><button @click="openDocument(doc)"><i :class="['ckb-file-type-icon', 'filetype-' + fileTypeKind(doc), fileTypeIcon(doc)]" aria-hidden="true"></i><i v-if="!doc.can_read" class="fa-solid fa-lock ckb-file-lock" aria-label="无访问权限"></i><strong>{{ doc.title }}</strong></button><div>{{ doc.format }} · {{ sizeLabel(doc.size || 0) }} <span> · {{ doc.category }} · <b :class="['ckb-confidentiality', 'level-' + doc.confidentiality]">{{ doc.confidentiality_label || '内部' }}</b></span></div><div v-if="doc.tags?.length" class="ckb-doc-tags"><button v-for="tag in doc.tags" :key="tag" @click="tagFilter = tag"># {{ tag }}</button></div></td>
              <td><span>{{ doc.project || '未归档项目' }}</span><small>{{ doc.industry || '未标记行业' }}</small></td>
              <td><span :class="['ckb-state', 'ckb-state-' + (doc.can_read ? doc.state : 'locked')]" :title="doc.status_message">{{ knowledgeState(doc) }}</span><small :class="{ 'ckb-review-pending': doc.review === '待复核' }">{{ doc.review }}</small></td>
              <td><span>{{ doc.date }}</span><small>V{{ doc.version }} · {{ doc.owner || '云端导入' }}</small></td>
              <td class="ckb-table-actions"><template v-if="doc.can_read"><button :aria-label="favorites.includes(doc.id) ? '取消收藏' : '收藏资料'" @click="toggleFavorite(doc.id)"><i aria-hidden="true" :class="favorites.includes(doc.id) ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark'"></i> {{ favorites.includes(doc.id) ? '已收藏' : '收藏' }}</button><button @click="openDocument(doc)">{{ doc.media_kind ? '播放' : '阅读' }}</button></template><button v-else-if="doc.request_status === 'pending'" disabled>审批中</button><button v-else class="ckb-access-request" :disabled="operationPending('access:' + doc.id)" @click="requestAccess(doc)">{{ doc.request_status === 'rejected' ? '重新申请' : '申请权限' }}</button><button v-if="doc.can_manage" @click="editDocument(doc)">管理</button><button v-if="doc.can_manage && doc.state === 'failed' && doc.has_original" @click="retryDocument(doc)">重试</button></td>
            </tr>
            <tr v-if="!filteredDocuments.length"><td colspan="6" class="ckb-table-empty">{{ loading ? '正在加载资料…' : '当前筛选下没有资料，可调整筛选或上传文件。' }}</td></tr>
          </tbody></table></div>
          <div v-else ref="documentTable" class="ckb-case-grid ckb-table-scroll ckb-directory-stage" :key="'cases:' + activeProjectId + ':' + activeFolderId" aria-label="经验列表"><article v-for="folder in visibleFolders" :key="folder.id" class="ckb-subfolder-card" :class="{ opening: openingDirectoryId === folder.id }"><button @click="openDirectory(activeProject, folder.id)"><knowledge-folder-artwork/><strong>{{ folder.name }}</strong><small>{{ projectFolders.filter(item => item.parent_id === folder.id).length }} 个子目录 · {{ documents.filter(doc => doc.folder_id === folder.id).length }} 份资料</small><i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></button><button v-if="activeProject.can_manage" class="ckb-folder-edit" :aria-label="'编辑目录：' + folder.name" @click="startFolderEditor(folder)"><i class="fa-solid fa-ellipsis" aria-hidden="true"></i></button></article>
            <article v-for="doc in pagedDocuments" :key="doc.id" class="ckb-case-card" :class="['kind-' + fileAppearance(doc), { locked: !doc.can_read, selected: selectedIds.includes(doc.id) }]">
              <div :class="['ckb-case-cover', doc.media_kind || 'document']" aria-hidden="true"><knowledge-thumbnail :key="doc.id + doc.modified_at" :doc="doc" :fetch-image="apiFetch"/><div class="ckb-cover-grid"></div><div v-if="doc.media_kind === 'audio'" class="ckb-cover-wave"><b v-for="n in 19" :key="n" :style="{height: (14 + (n * 17 % 43)) + 'px', animationDelay: (n * .08) + 's'}"></b></div><div v-else-if="doc.media_kind === 'video'" class="ckb-cover-play"><i class="fa-solid fa-play"></i></div><knowledge-file-artwork v-else :format="doc.format" :kind="fileAppearance(doc)" :media-kind="doc.media_kind"/><span class="ckb-cover-label">{{ doc.media_kind === 'audio' ? 'LISTEN / 录音' : doc.media_kind === 'video' ? 'WATCH / 视频' : ['PNG','JPG','JPEG'].includes(doc.format) ? 'LOOK / 照片与手稿' : 'READ / 文档' }}</span><small>{{ doc.format }}</small></div>
              <div class="ckb-case-card-top"><span :class="['ckb-case-icon', doc.media_kind]"><i aria-hidden="true" :class="doc.media_kind === 'audio' ? 'fa-solid fa-wave-square' : doc.media_kind === 'video' ? 'fa-solid fa-play' : 'fa-regular fa-file-lines'"></i></span><span>{{ doc.category }}</span><input type="checkbox" :checked="selectedIds.includes(doc.id)" :disabled="busy || !doc.can_read || doc.state !== 'ready'" :aria-label="'选择资料：' + doc.title" @change="toggleSelection(doc)"></div>
              <button class="ckb-case-title" @click="openDocument(doc)"><i :class="['ckb-file-type-icon', 'filetype-' + fileTypeKind(doc), fileTypeIcon(doc)]" aria-hidden="true"></i>{{ doc.title }}</button><p>{{ doc.can_read ? doc.description || doc.project || '暂无说明，可在管理中补充背景与经验。' : '受限资料，申请授权后查看。' }}</p>
              <div class="ckb-doc-tags"><button v-for="tag in (doc.tags || []).slice(0, 4)" :key="tag" @click="tagFilter = tag"># {{ tag }}</button></div>
              <div class="ckb-case-card-meta"><span>{{ doc.format }} · {{ doc.confidentiality_label }} · {{ doc.date }}</span><span :class="['ckb-state', 'ckb-state-' + (doc.can_read ? doc.state : 'locked')]">{{ knowledgeState(doc) }}</span></div>
              <footer><button @click="openDocument(doc)">{{ !doc.can_read ? '申请权限' : doc.media_kind ? '播放与详情' : '查看原件' }} <i aria-hidden="true" class="fa-solid fa-arrow-right"></i></button><button v-if="doc.can_manage" @click="editDocument(doc)">{{doc.note_id?'编辑笔记':'编辑信息'}}</button></footer>
            </article><div v-if="!filteredDocuments.length && !visibleFolders.length" class="ckb-case-empty"><div class="ckb-vault-visual" aria-hidden="true"><div class="ckb-vault-ring"></div><div class="ckb-vault-cube"><i class="fa-solid fa-cubes"></i></div><span class="ckb-vault-satellite one"><i class="fa-regular fa-file-lines"></i></span><span class="ckb-vault-satellite two"><i class="fa-solid fa-wave-square"></i></span><span class="ckb-vault-satellite three"><i class="fa-solid fa-play"></i></span></div><span class="ckb-empty-eyebrow">EVERY EXPERIENCE COUNTS</span><h3>{{ loading ? '正在连接经验档案…' : caseCount ? '暂未找到匹配的经验' : '让第一份经验，成为新的起点。' }}</h3><p>{{ caseCount ? '换个关键词、标签或时间范围，继续寻找。' : '一份项目复盘、一段分享录音、一次方法实践，都值得留下。' }}</p><div class="ckb-empty-actions"><button class="ckb-button ckb-button-primary" :disabled="!canAsk" @click="startUpload"><i aria-hidden="true" class="fa-solid fa-plus"></i>沉淀第一份经验</button><button v-if="caseCount" class="ckb-button ckb-button-outline" @click="resetFilters">清除筛选</button><button v-else class="ckb-button ckb-button-outline" @click="browseLibrary">浏览公司资料</button></div><small>支持照片、手稿、文档、录音与视频 · 仅检索经验沉淀</small></div>
          </div>
          <nav v-if="!showingProjects &amp;&amp; searchMode !== 'content'" class="ckb-pagination" aria-label="资料分页"><span class="ckb-page-range">共 {{ libraryPageRange.total }} 份 · 第 {{ libraryPageRange.start }}–{{ libraryPageRange.end }} 份</span><div><select v-model.number="libraryPageSize" aria-label="每页资料数量"><option :value="10">10 条 / 页</option><option :value="20">20 条 / 页</option><option :value="50">50 条 / 页</option></select><button aria-label="上一页资料" :disabled="currentLibraryPage <= 1" @click="changeLibraryPage(currentLibraryPage - 1)"><i aria-hidden="true" class="fa-solid fa-angle-left"></i></button><button v-for="page in libraryPageNumbers" :key="page" :aria-label="'第 ' + page + ' 页资料'" :aria-current="page === currentLibraryPage ? 'page' : undefined" :class="{ active: page === currentLibraryPage }" @click="changeLibraryPage(page)">{{ page }}</button><button aria-label="下一页资料" :disabled="currentLibraryPage >= libraryPageCount" @click="changeLibraryPage(currentLibraryPage + 1)"><i aria-hidden="true" class="fa-solid fa-angle-right"></i></button><span class="ckb-page-total">{{ currentLibraryPage }} / {{ libraryPageCount }} 页</span></div></nav>

        </div>
      </section>
      <section v-if="mode === 'chat'" id="ckb-chat-panel" class="ckb-chat-layout ckb-view-panel" :class="{'is-generating': busy}" role="tabpanel" aria-labelledby="ckb-chat-tab">
        <aside class="ckb-chat-aside"><div class="ckb-chat-space"><span><i class="fa-solid fa-fingerprint" aria-hidden="true"></i></span><div>你的研究空间<small>PRIVATE RESEARCH SPACE</small></div></div>
          <button class="ckb-button ckb-button-outline ckb-new-conversation" :disabled="busy || chatHistoryBusy" @click="startConversation"><i class="fa-solid fa-plus" aria-hidden="true"></i><span>开始新对话</span><i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></button>
          <section class="ckb-session-panel" aria-label="研究历史面板"><label class="ckb-aside-label" for="ckb-chat-history">研究历史</label>
          <select id="ckb-chat-history" aria-label="研究历史" v-model="chatSessionId" :disabled="busy || chatHistoryBusy" @change="loadChatHistory(chatSessionId)"><option value="">新研究对话</option><option v-for="session in chatSessions" :key="session.id" :value="session.id">{{ session.title }}</option></select>
          <div v-if="chatSessions.length" class="ckb-session-list"><button v-for="session in chatSessions.slice(0,6)" :key="session.id" :class="{active: chatSessionId === session.id}" :disabled="busy || chatHistoryBusy" :title="session.title" @click="loadChatHistory(session.id)"><i class="fa-regular fa-message" aria-hidden="true"></i><span>{{ session.title }}</span><i class="fa-solid fa-angle-right" aria-hidden="true"></i></button></div><div v-else class="ckb-session-empty"><i class="fa-regular fa-message" aria-hidden="true"></i><span>从一个问题开始，<br>研究历史会保存在这里。</span></div><div class="ckb-history-actions"><button :disabled="busy || chatHistoryBusy" @click="loadChatHistory(chatSessionId)">刷新对话</button><button :disabled="busy || chatHistoryBusy || !chatSessionId" @click="deleteConversation">删除当前对话</button></div>
          </section><section class="ckb-evidence-panel" aria-label="检索资料面板"><div class="ckb-aside-label"><i class="fa-solid fa-layer-group" aria-hidden="true"></i>检索范围</div><strong>{{ scopeLabel }}</strong>
          <p class="ckb-scope-note">{{ selectedIds.length ? '回答仅依据选中文件的检索片段。' : chatScope === 'my-projects' ? '按当前账号 ID 统计上传项目，只检索本人上传且已完成索引的资料。' : (chatCollection === 'experience' ? '仅检索经验沉淀，不调用资料库内容。' : '仅检索资料库，不调用经验沉淀内容。') }}</p>
          <button class="ckb-button ckb-button-outline" :disabled="busy" @click="chatCollection === 'experience' ? browseCases() : browseLibrary(); showAllFiles()">选择资料</button>
          <button v-if="selectedIds.length || ['my-projects','my-experience'].includes(chatScope)" class="ckb-button ckb-button-outline" :disabled="busy" @click="changeScope([])">{{ chatCollection === 'experience' ? '改为全部经验' : '改为全部资料' }}</button>
          <button v-for="doc in selectedDocuments" :key="doc.id" :class="['ckb-reading-link', 'kind-' + fileAppearance(doc)]" @click="openDocument(doc)"><span class="ckb-scope-file-art" aria-hidden="true"><knowledge-file-artwork :format="doc.format" :kind="fileAppearance(doc)" :media-kind="doc.media_kind"/></span><span>{{ doc.title }}</span></button>
          </section><div class="ckb-chat-aside-foot">关键结论请核对引用；待复核稿需保留复核说明。</div>
        </aside>
        <div class="ckb-chat-main"><div class="ckb-chat-ambience" aria-hidden="true"><span></span><span></span><span></span></div>
          <header class="ckb-chat-header"><span><i aria-hidden="true" class="fa-solid fa-wand-magic-sparkles"></i><span>{{ chatCollection === 'experience' ? '经验助手' : '知识助手' }}<small>{{ chatCollection === 'experience' ? 'EXPERIENCE COPILOT' : 'RESEARCH COPILOT' }}</small></span></span><div class="ckb-chat-trust"><span class="ckb-live-presence"><b></b>{{ busy ? '正在研究' : '就绪' }}</span><span><i aria-hidden="true" class="fa-solid fa-shield-halved"></i>权限内检索</span><span><i aria-hidden="true" class="fa-solid fa-link"></i>引用可核查</span></div></header>
          <div v-if="memoryStatus || chatError" class="ckb-memory-status" :class="{'ckb-memory-error': chatError}" role="status">{{ chatError || memoryStatus }}</div>
          <div ref="chatFeed" class="ckb-chat-feed" @scroll.passive="onChatScroll" aria-live="polite" aria-relevant="additions">
            <button v-if="chatHasMore" class="ckb-button ckb-button-outline" :disabled="busy || chatHistoryBusy" @click="loadChatHistory(chatSessionId, true)">加载更早消息</button>
            <div v-if="!messages.length" class="ckb-chat-welcome">
              <div class="ckb-intelligence-visual" aria-hidden="true"><div class="ckb-neural-ring"></div><div class="ckb-neural-ring second"></div><div class="ckb-neural-card back"></div><div class="ckb-neural-card front"><i class="fa-solid fa-wand-magic-sparkles"></i><span></span><span></span></div><b class="ckb-neural-dot one"></b><b class="ckb-neural-dot two"></b></div><span class="ckb-welcome-eyebrow">THINK WITH YOUR KNOWLEDGE</span>
              <h3>{{ chatCollection === 'experience' ? '从经历中，找到可复用的方法。' : '从资料里，找到下一步。' }}</h3><p>把问题交给知识，让每个判断都有迹可循。</p><div class="ckb-welcome-scope"><i class="fa-solid fa-layer-group" aria-hidden="true"></i>{{ scopeLabel }}</div>
              <div class="ckb-suggestions"><button v-for="(question, index) in chatSuggestions" :key="question" @click="sendQuestion(question)"><span>0{{ index + 1 }}</span>{{ question }}<i aria-hidden="true" class="fa-solid fa-arrow-right"></i></button></div>
            </div>
            <div v-for="(message, index) in messages" :key="index" :class="['ckb-message', 'ckb-message-' + message.role, { 'is-streaming': message.role === 'assistant' &amp;&amp; !message.complete &amp;&amp; !message.error &amp;&amp; busy }]">
              <template v-if="message.role === 'user'"><span class="ckb-user-question">{{ message.text }}</span><small>范围：{{ message.scope }}</small></template>
              <template v-else>
                <div class="ckb-answer-heading"><span><i aria-hidden="true" class="fa-solid fa-wand-magic-sparkles"></i> 知识助手</span><small>{{ message.complete ? '回答完成' : message.error ? '生成未完成' : answerStatus }}</small></div>
                <details v-if="message.progress.length" class="ckb-progress" :open="!message.complete">
                  <summary><span :class="['ckb-progress-indicator', { active: !message.complete && !message.error }]"></span><strong>{{ message.complete ? '处理完成' : message.error ? '处理已停止' : '正在处理' }}</strong><span class="ckb-progress-current">{{ !message.complete && !message.error ? message.progress[message.progress.length - 1].label : '查看处理过程' }}</span><small>{{ message.elapsedSeconds }} 秒</small></summary>
                  <ol class="ckb-progress-steps"><li v-for="(step, n) in message.progress" :key="n" :class="step.state"><span class="ckb-step-mark"><i aria-hidden="true" :class="step.state === 'done' ? 'fa-solid fa-check' : step.state === 'error' ? 'fa-solid fa-exclamation' : 'fa-solid fa-circle'"></i></span><div><strong>{{ step.label }}</strong><p>{{ step.detail }}</p></div></li></ol>
                  <p v-if="!message.complete && !message.error" class="ckb-wait-note">{{ message.text ? '回答正在实时更新。' : '等待云端下一步进度，回答生成后会逐步显示。' }}</p>
                </details>
                <div v-if="!message.text &amp;&amp; !message.complete &amp;&amp; !message.error &amp;&amp; busy" class="ckb-thinking-ribbon" role="status"><span aria-hidden="true"><b></b><b></b><b></b><b></b><b></b></span>正在连接资料与问题…</div><div class="ckb-live-answer"><template v-for="(block, blockIndex) in answerBlocks(message.text)" :key="blockIndex"><div v-if="block.type === 'table'" class="ckb-answer-table"><table><thead><tr><th v-for="(header, n) in block.headers" :key="n">{{ header }}</th></tr></thead><tbody><tr v-for="(row, n) in block.rows" :key="n"><td v-for="(cell, m) in row" :key="m">{{ cell }}</td></tr></tbody></table></div><span v-else>{{ block.text }}</span></template></div><p v-if="message.error" class="ckb-service-error" role="alert">{{ message.error }}</p>
                <div v-if="message.references.length" class="ckb-citation-heading">参考文件 <span>{{ referenceGroups(message.references).length }} 份文件 · {{ message.references.length }} 个片段</span></div>
                <button v-for="(group, n) in referenceGroups(message.references)" :key="group.key" :class="['ckb-citation', 'kind-' + fileAppearance(citationDocument(group))]" @click="openCitation(group)"><span>{{ n + 1 }}</span><span class="ckb-citation-file" aria-hidden="true"><knowledge-file-artwork :format="citationDocument(group).format" :kind="fileAppearance(citationDocument(group))" :media-kind="citationDocument(group).media_kind"/></span><div><strong>{{ group.title }}</strong><small>{{ group.references.length }} 个片段 · 引用 {{ referenceIds(group) }} · 点击展开</small></div><i aria-hidden="true" class="fa-solid fa-angle-right"></i></button>
                <div v-if="message.complete &amp;&amp; message.text &amp;&amp; !message.redacted" class="ckb-answer-actions"><button @click="copyAnswer(message)" aria-label="复制回答"><i class="fa-regular fa-copy" aria-hidden="true"></i>复制回答</button><span><i class="fa-solid fa-check" aria-hidden="true"></i>回答完成<span v-if="message.references.length"> · {{ referenceGroups(message.references).length }} 份参考文件</span></span></div>
              </template>
            </div>
          </div>
          <button v-if="messages.length &amp;&amp; !chatAtBottom" class="ckb-jump-latest" @click="scrollChat(true)"><i class="fa-solid fa-arrow-down" aria-hidden="true"></i>回到最新回答</button>
          <div class="ckb-composer-area"><div class="ckb-composer" :class="{'has-draft': draft.trim()}"><textarea ref="composer" v-model="draft" maxlength="1500" :disabled="!canAsk" aria-label="知识问答问题" placeholder="提问、梳理研究思路，或从一份资料开始…" rows="2" @keydown="onComposerKey"></textarea><div><span class="ckb-composer-scope"><i aria-hidden="true" class="fa-regular fa-folder-open"></i> {{ scopeLabel }}</span><span class="ckb-composer-signal" aria-hidden="true"><b><i></i><i></i><i></i><i></i></b><small>{{ busy ? '正在研究' : !canAsk ? '等待连接' : draft.trim() ? '可以发送' : '随时提问' }}</small></span><button v-if="busy" aria-label="停止生成" @click="controller?.abort()"><i aria-hidden="true" class="fa-solid fa-stop"></i></button><button v-else :disabled="!draft.trim() || !canAsk" aria-label="发送问题" @click="sendQuestion"><i aria-hidden="true" class="fa-solid fa-arrow-up"></i></button></div></div><p>Enter 发送 · Shift + Enter 换行 <span>{{ busy ? answerStatus : "请核对引用依据" }}</span></p></div>
        </div>
      </section>


      <knowledge-note-editor v-if="noteEditorId" :key="noteEditorId" :note-id="noteEditorId" :fetch-api="apiFetch" :username="service.username" @close="noteEditorId=''; loadNotes()" @changed="noteChanged"/>
      <el-dialog modal-class="ckb-glass-overlay" v-model="projectEditorOpen" :title="editingProject ? '项目设置' : '创建项目'" width="880px" class="ckb-dialog ckb-project-dialog ckb-reveal-dialog" append-to-body :close-on-click-modal="!projectSaving"><knowledge-glass-surface/><div class="ckb-project-editor"><aside><knowledge-folder-artwork/><span>{{ projectEditorIsCase ? 'EXPERIENCE ARCHIVE' : 'PROJECT ARCHIVE' }}</span><h3>{{ projectForm.name || '每个项目，都有自己的空间。' }}</h3><p>{{ projectEditorIsCase ? '留存项目经验、案例复盘与方法，让下一次研究少走弯路。' : '先记录背景，再让文件、录音与视频各得其所。' }}</p><div><span>01 / 创建空目录</span><span>02 / 组织子目录</span><span>03 / 归档与研究</span></div></aside><form class="ckb-form-grid" @submit.prevent="saveProjectDirectory"><div class="ckb-attribution ckb-form-wide"><span><i aria-hidden="true" class="fa-solid fa-user-shield"></i>{{ editingProject ? '创建人：' + (editingProject.created_by || '历史未采集') : '创建人将自动记录为当前登录账号' }}</span><small>{{ editingProject ? '最后修改：' + (editingProject.modified_by || '历史未采集') : '项目修改会保存操作人和前后内容' }}</small><button v-if="editingProject" type="button" @click="openAudit({project_id: editingProject.id})">项目操作记录 <i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></div><p v-if="projectError" class="ckb-service-error ckb-form-wide" role="alert">{{ projectError }}</p><label class="ckb-form-wide">项目名称<input v-model="projectForm.name" aria-label="项目名称" maxlength="200" placeholder="例如：AI Agent 行业研究" autofocus></label><label>行业<input v-model="projectForm.industry" aria-label="项目行业" maxlength="100" placeholder="例如：人工智能"></label><label>项目分类<select v-model="projectForm.category" aria-label="项目分类"><option v-for="category in projectCategoryOptions" :key="category">{{ category }}</option></select><small>{{ projectEditorIsCase ? '案例库分类 · 沉淀可复用经验' : '资料库分类 · 归集研究原始资料与成果' }}</small></label><label>复核状态<select v-model="projectForm.review" aria-label="项目复核状态"><option>待复核</option><option>已复核</option><option>参考资料</option></select></label><label>保密等级<select v-model="projectForm.confidentiality" aria-label="项目保密等级" @change="projectForm.confidentiality !== 'internal' && (projectForm.visibility = 'restricted')"><option value="internal">内部</option><option v-if="service.is_admin" value="secret">机密</option></select></label><label v-if="projectForm.confidentiality === 'internal'" class="ckb-project-restrict ckb-form-wide"><input type="checkbox" :checked="projectForm.visibility === 'restricted'" @change="projectForm.visibility = $event.target.checked ? 'restricted' : 'members'">项目单独授权</label><label v-if="projectForm.visibility === 'restricted' && projectForm.confidentiality === 'internal'" class="ckb-form-wide">指定成员<input v-model="projectForm.readersText" aria-label="项目指定成员" placeholder="多个登录账号用逗号分隔"></label><label class="ckb-form-wide">项目标签<input v-model="projectForm.tagsText" aria-label="项目标签" maxlength="1000" placeholder="行业背景，市场进入，访谈方法"><small>文件自动继承，上传时无需重复填写。</small></label><label class="ckb-form-wide">项目说明<textarea v-model="projectForm.description" aria-label="项目说明" maxlength="10000" rows="3" placeholder="记录项目目标、背景与适用范围。"></textarea></label><button type="submit" hidden></button></form></div><template #footer><button v-if="editingProject?.can_manage" class="ckb-button ckb-project-delete" :disabled="projectSaving" @click="deleteProjectDirectory"><i class="fa-solid fa-trash-can" aria-hidden="true"></i>删除项目</button><button class="ckb-button ckb-button-outline" :disabled="projectSaving" @click="projectEditorOpen = false">取消</button><button class="ckb-button ckb-button-primary" :disabled="projectSaving || !projectForm.name?.trim()" @click="saveProjectDirectory">{{ projectSaving ? '保存中…' : editingProject ? '保存项目设置' : '创建空项目' }}</button></template></el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="folderEditorOpen" :title="editingFolder ? '编辑目录' : '新建目录'" width="480px" class="ckb-dialog ckb-folder-dialog ckb-reveal-dialog" append-to-body><knowledge-glass-surface/><div class="ckb-folder-editor-art"><knowledge-folder-artwork/></div><p class="ckb-dialog-intro">{{ activeProject?.name }} / {{ directoryBreadcrumbs.map(folder => folder.name).join(' / ') || '根目录' }}</p><p v-if="folderError" class="ckb-service-error" role="alert">{{ folderError }}</p><form class="ckb-form-grid" @submit.prevent="saveFolder"><label class="ckb-form-wide">目录名称<input v-model="folderName" aria-label="目录名称" maxlength="200" placeholder="例如：录音、笔录、报告" autofocus></label></form><template #footer><button v-if="editingFolder" class="ckb-button ckb-button-outline ckb-delete-button" :disabled="folderSaving" @click="deleteEmptyFolder">删除空目录</button><button class="ckb-button ckb-button-outline" :disabled="folderSaving" @click="folderEditorOpen = false">取消</button><button class="ckb-button ckb-button-primary" :disabled="folderSaving || !folderName.trim()" @click="saveFolder">{{ folderSaving ? '保存中…' : editingFolder ? '保存目录' : '创建目录' }}</button></template></el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="readerOpen" width="94vw" class="ckb-dialog ckb-reader-dialog ckb-workbench-reader" :class="{'ckb-reader-focused':readerFocus}" append-to-body :title="selectedDoc?.title || '资料阅读'" @closed="releaseReader"><knowledge-glass-surface/>
        <template v-if="selectedDoc"><div class="ckb-reader-toolbar"><span>{{ selectedDoc.format || '引用资料' }} · {{ selectedDoc.review || '请核对来源' }} · V{{ selectedDoc.version || 1 }}</span><div><button v-if="selectedDoc.note_id && selectedDoc.can_manage" class="ckb-button ckb-button-outline" @click="editRichNote(selectedDoc.note_id)">编辑笔记</button><button v-if="selectedDoc.has_original" class="ckb-button ckb-button-outline" :disabled="operationPending('download:' + selectedDoc.id)" @click="downloadOriginal(selectedDoc)">{{operationPending('download:' + selectedDoc.id) ? downloadPhase(selectedDoc) : '下载水印副本'}}</button><button class="ckb-button ckb-button-primary" :disabled="busy || !canAsk || selectedDoc.state !== 'ready'" @click="askDocument">单独向这份资料提问</button></div></div>
        <div v-if="downloadProgress[selectedDoc.id]" class="ckb-download-progress"><span role="status"><i class="fa-solid fa-circle-notch fa-spin" aria-hidden="true"></i>{{ downloadPhase(selectedDoc) }}</span><time>已等待 {{ downloadProgress[selectedDoc.id].elapsed }} 秒</time><progress v-if="downloadProgress[selectedDoc.id].total_pages" :max="downloadProgress[selectedDoc.id].total_pages" :value="downloadProgress[selectedDoc.id].page" aria-label="水印处理进度"></progress><small>正在生成保留原格式的带水印副本，完成后会自动交给浏览器下载。</small></div><div class="ckb-reader-view-tabs" role="group" aria-label="阅读方式"><div class="ckb-reader-locate-tools"><label><i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i><input v-model="readerFind" maxlength="500" aria-label="在原文中查找" placeholder="在原文中查找…" @keydown.enter="findInReader"><button :disabled="locating || !readerFind.trim()" @click="findInReader">{{ locating ? '定位中…' : '查找' }}</button></label><span v-if="readerLocation" role="status">{{ readerLocation.matched ? '已匹配原文' + (readerLocation.page ? ' · 第 ' + readerLocation.page + ' 页' : '') : readerLocation.message }}</span><button :aria-pressed="readerFocus" @click="readerFocus = !readerFocus"><i class="fa-solid fa-expand" aria-hidden="true"></i>{{ readerFocus ? '退出专注' : '专注阅读' }}</button></div><button v-if="!selectedDoc.media_kind" :aria-pressed="readerMode === 'original'" :disabled="!selectedDoc.has_original" @click="readerMode = 'original'"><i class="fa-regular fa-file" aria-hidden="true"></i>完整原件</button><button v-if="!selectedDoc.media_kind" :aria-pressed="readerMode === 'excerpts'" @click="readerMode = 'excerpts'">检索片段<span>{{ readerTotal || selectedDoc.references?.length || 0 }}</span></button><details v-if="selectedDoc.has_original" class="ckb-reader-policy"><summary><i class="fa-solid fa-shield-halved" aria-hidden="true"></i>下载与预览带账号、时间和追踪标记<span>格式说明</span></summary><p class="ckb-export-note"><i class="fa-solid fa-shield-halved" aria-hidden="true"></i> 下载与预览带账号、时间和追踪标记。Office 与文字保留原格式；Excel 添加背景及打印页脚标记。图片为 PNG，录音为带身份提示的 MP3，视频为带可见水印的 MP4。</p></details><small v-if="!selectedDoc.has_original">这份历史资料未归档原件，当前提供检索片段</small></div><div class="ckb-reader-columns"><div class="ckb-original-pane">
          <div v-if="selectedDoc.media_kind" class="ckb-media-reader"><span class="ckb-media-eyebrow">{{ selectedDoc.media_kind === 'audio' ? 'AUDIO / 录音资料' : 'VIDEO / 视频资料' }}</span><video v-if="readerUrl && selectedDoc.media_kind === 'video'" :key="readerUrl" :src="readerUrl" controls preload="metadata" @error="readerError = '浏览器无法解码此视频，请下载后用本地播放器打开。'"></video><div v-if="selectedDoc.media_kind === 'audio'" class="ckb-audio-art" aria-hidden="true"><i aria-hidden="true" class="fa-solid fa-wave-square"></i></div><audio v-if="readerUrl && selectedDoc.media_kind === 'audio'" :key="readerUrl" :src="readerUrl" controls preload="metadata" @error="readerError = '浏览器无法解码此音频，请下载后用本地播放器打开。'"></audio><p v-if="readerLoading">正在加载音视频…</p><p v-if="readerError" role="alert">{{ readerError }}</p><h3>文字说明</h3><pre>{{ selectedDoc.description }}</pre><p>问答仅依据这段说明，未自动转写音视频内容。</p></div>
          <knowledge-document-viewer ref="nativeReader" @located="readerLocation = $event" :find-text="readerFind" v-else-if="readerMode === 'original' &amp;&amp; readerBlob" :key="selectedDoc.id + readerTrace" :blob="readerBlob" :format="selectedDoc.format" :identity="service.username + ' · ' + new Date().toLocaleString('zh-CN')" :trace="readerTrace"/><knowledge-pdf-viewer :format="selectedDoc.format" :location="readerLocation" v-else-if="readerMode === 'original' &amp;&amp; readerUrl &amp;&amp; ['PDF','DOC','XLS','XLSX','PPT','PPTX'].includes(selectedDoc.format)" :key="selectedDoc.id + readerTrace" :document-id="selectedDoc.id" :first-page="readerUrl" :pages="readerPDFPages" :fetch-page="apiFetch"/>
          <img v-else-if="readerMode === 'original' &amp;&amp; readerUrl" :src="readerUrl" alt="扫描资料原件">
          <div v-else-if="readerMode === 'original'" class="ckb-original-unavailable"><i :class="readerOriginalLoading ? 'fa-solid fa-circle-notch fa-spin' : 'fa-regular fa-file-lines'" aria-hidden="true"></i><h3>{{ readerOriginalLoading ? '正在展开原件…' : '使用原格式文件继续阅读' }}</h3><p v-if="readerError" role="alert">{{ readerError }}</p><p v-else-if="!readerOriginalLoading">{{ ['DOCX','DOC','XLS','XLSX','PPT','PPTX','TXT','MD','CSV','PDF','PNG','JPG','JPEG','WEBP','GIF','BMP'].includes(selectedDoc.format) ? '暂时未能打开原件，请重试。' : selectedDoc.format + ' 暂不支持在线原版式预览，可下载保留格式的水印副本查看。' }}</p><button v-if="!readerOriginalLoading &amp;&amp; selectedDoc.has_original" class="ckb-button ckb-button-primary" :disabled="operationPending('download:' + selectedDoc.id)" @click="downloadOriginal(selectedDoc)">下载水印副本</button><button v-if="readerError &amp;&amp; !readerOriginalLoading" class="ckb-button ckb-button-outline" @click="openDocument(selectedDoc)">重试预览</button></div><div v-else class="ckb-source-reader"><p v-if="readerLoading">正在加载解析文字…</p><p v-if="readerError" role="status">{{ readerError }}</p><p v-if="!readerLoading && !selectedDoc.references?.length">暂无可展示的解析片段。</p><section v-for="reference in selectedDoc.references" :key="reference.id"><div class="ckb-citation-heading">片段 {{ reference.id }}</div><pre>{{ reference.text }}</pre><p v-if="!selectedDoc.has_original" class="ckb-export-note">历史资料未归档受控原件，暂不能生成带水印副本。</p></section><button v-if="readerTotal > (selectedDoc.references?.length || 0)" class="ckb-button ckb-button-outline" :disabled="readerLoading" @click="morePreview">加载后续解析片段</button></div>
        </div><aside class="ckb-reader-question"><h3>阅读与核对</h3><p>{{ selectedDoc.status_message || '点击引用可核对依据。' }}</p><div v-if="selectedDoc.tags?.length" class="ckb-doc-tags"><span v-for="tag in selectedDoc.tags" :key="tag"># {{ tag }}</span></div><p v-if="!selectedDoc.media_kind">{{ readerMode === 'original' ? '正在查看归档原件。在线版式供阅读，正式引用请核对下载文件。' : '当前是检索依据片段，可切回完整原件阅读上下文。' }}</p>
          <div v-if="selectedDoc.references?.length && readerUrl" class="ckb-reader-evidence"><strong>解析片段</strong><details v-for="reference in selectedDoc.references" :key="reference.id"><summary>片段 {{ reference.id }}<span v-if="reference.pages?.length"> · 第 {{ reference.pages.join('、') }} 页</span></summary><button @click="locateReference(reference)">定位这段原文</button><pre>{{ reference.text }}</pre></details><button v-if="readerTotal > selectedDoc.references.length" :disabled="readerLoading" @click="morePreview">加载更多片段</button></div>
          <div v-if="messages.length" class="ckb-reader-last-answer"><strong>最近的回答</strong><template v-for="(message, index) in messages.slice(-2)" :key="index"><p v-if="message.role === 'user'">{{ message.text }}</p><pre v-else>{{ message.text || answerStatus }}<span v-if="message.error">{{ message.error }}</span></pre></template></div>
          <div class="ckb-reader-ask"><textarea v-model="draft" maxlength="1500" :disabled="busy || selectedDoc.state !== 'ready'" placeholder="就这份原件提问，例如：哪些结论仍需复核？"></textarea><button class="ckb-button ckb-button-primary" :disabled="busy || !draft.trim() || selectedDoc.state !== 'ready'" @click="askWhileReading">{{ busy ? answerStatus || '正在回答…' : '依据这份资料回答' }}</button></div>
        </aside></div></template>
      </el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="auditOpen" title="操作记录" width="850px" class="ckb-dialog ckb-audit-dialog" append-to-body><knowledge-glass-surface/><p class="ckb-export-note">操作人和时间由后端自动记录。项目/文件管理者可查看对应记录，管理员可查看全部。</p><p v-if="auditError" class="ckb-service-error" role="alert">{{ auditError }}</p><div class="ckb-audit-list" :aria-busy="auditLoading"><article v-for="event in auditEvents" :key="event.id"><header><span><i class="fa-solid fa-fingerprint" aria-hidden="true"></i><strong>{{ auditAction(event.action) }}</strong></span><time>{{ new Date(event.created_at).toLocaleString('zh-CN') }}</time></header><p>{{ event.target_name }}<b>{{ event.actor_username }}</b></p><details v-if="Object.keys(event.changes || {}).length"><summary>查看前后内容 · {{ Object.keys(event.changes).length }} 项</summary><dl v-for="(change, field) in event.changes" :key="field"><dt>{{ auditField(field) }}</dt><dd><small>修改前</small><pre>{{ auditValue(change.before) }}</pre></dd><dd><small>修改后</small><pre>{{ auditValue(change.after) }}</pre></dd></dl></details><p v-if="event.details?.trace_id" class="ckb-audit-trace">追踪编号 {{ event.details.trace_id }}</p><p v-if="event.details?.reason">{{ event.details.reason }}</p></article><p v-if="!auditEvents.length">{{ auditLoading ? '正在加载记录…' : '暂无记录，历史操作不会补造。' }}</p></div><template #footer><span class="ckb-audit-count">共 {{ auditTotal }} 条 · 第 {{ auditPage }} 页</span><button class="ckb-button ckb-button-outline" :disabled="auditLoading || auditPage <= 1" @click="auditPage--; loadAudit()">上一页</button><button class="ckb-button ckb-button-outline" :disabled="auditLoading || auditPage * 30 >= auditTotal" @click="auditPage++; loadAudit()">下一页</button><button class="ckb-button ckb-button-primary" @click="auditOpen = false">关闭</button></template></el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="uploadOpen" :title="quickCapture ? '随手记录一份经验' : '上传到当前目录'" width="680px" class="ckb-dialog" append-to-body :close-on-click-modal="!uploadBusy" :show-close="!uploadBusy" :close-on-press-escape="!uploadBusy"><knowledge-glass-surface/>
        <p v-if="uploadError" class="ckb-service-error" role="alert">{{ uploadError }}</p>
        <p v-if="!uploadResults.length" class="ckb-dialog-intro">文档与图片自动解析并建立检索索引。录音和视频可直接归档、播放、下载；填写说明后仅检索说明。</p><p v-if="uploadResults.length && !uploadBusy" class="ckb-upload-summary" role="status">上传结果：{{ uploadSummary }}</p>
        <fieldset v-if="!uploadResults.length || uploadBusy" :disabled="uploadBusy" class="ckb-upload-fields"><div v-if="!quickCapture" class="ckb-upload-inheritance"><knowledge-folder-artwork/><div><strong>{{ activeProject?.name }}</strong><p>{{ directoryBreadcrumbs.map(folder => folder.name).join(' / ') || '项目根目录' }}</p><span>继承项目的行业、标签、分类与权限</span><div class="ckb-doc-tags"><span v-for="tag in activeProject?.tags || []" :key="tag"># {{ tag }}</span></div></div></div><div v-if="quickCapture" class="ckb-capture-context"><p>先留下现场，稍后整理。保存到你自己的「随手记录 · 待整理」，仅参与经验沉淀检索。文字会生成可检索笔记，附件保留原件，也可以只写文字。</p><label>经验名称<input v-model="captureTitle" maxlength="160" placeholder="例如：客户访谈中的三个追问方法"></label><label>适用场景<input v-model="captureScene" maxlength="300" placeholder="这份记录适用于什么情况？"></label><label>可复用做法<textarea v-model="captureMethod" maxlength="3000" rows="3" placeholder="记录做法、收获或需要留意的地方。"></textarea></label></div><label class="ckb-file-drop ckb-file-drop-large" @dragover.prevent @drop.prevent="droppedFiles"><i class="fa-solid fa-cloud-arrow-up" aria-hidden="true"></i><strong>选择或拖入文档、照片、手稿、录音与视频</strong><input type="file" multiple accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac,.mp4,.webm" aria-label="选择上传资料" @change="chooseFiles"><small>文档与图片 ≤ 32 MB · 音视频 ≤ 128 MB<br>同目录同名不同内容保留新版本</small></label><div class="ckb-form-grid"><label class="ckb-form-wide">文件说明（可选）<textarea aria-label="文字说明" v-model="uploadForm.description" maxlength="10000" rows="3" placeholder="补充这批文件的背景或内容。音视频填写后可检索此说明，不自动转写。"></textarea></label></div></fieldset>
        <ul class="ckb-upload-list"><li v-for="(file, index) in stagedFiles" :key="index">{{ file.name }} <small>{{ sizeLabel(file.size) }}</small></li></ul><ul class="ckb-upload-results" aria-live="polite"><li v-for="(item, index) in uploadDisplayResults" :key="index"><strong>{{ item.name }}</strong><span :data-state="item.phase">{{ item.state }}<template v-if="item.detail"> · {{ item.detail }}</template></span><button v-if="item.can_retry" class="ckb-button ckb-button-outline" @click="retryDocument(item)">重试处理</button></li></ul>
        <template #footer><template v-if="uploadResults.length && !uploadBusy"><button v-if="stagedFiles.length" class="ckb-button ckb-button-outline" @click="uploadFiles">重试上传失败文件</button> <button class="ckb-button ckb-button-outline" @click="startUpload">继续上传</button> <button class="ckb-button ckb-button-primary" @click="viewUploaded">{{ uploadResults.some(item => item.id) ? '完成，查看资料' : '返回资料库' }}</button></template><template v-else><button class="ckb-button ckb-button-outline" :disabled="uploadBusy" @click="uploadOpen = false">取消</button> <button class="ckb-button ckb-button-primary" :disabled="uploadBusy || (quickCapture ? !captureTitle.trim() : !stagedFiles.length)" @click="uploadFiles">{{ uploadBusy ? '正在上传，请稍候…' : '上传并归档' }}</button></template></template>
      </el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="metadataOpen" title="文件设置" width="680px" class="ckb-dialog ckb-reveal-dialog" append-to-body><knowledge-glass-surface/><div class="ckb-file-editor-hero" :class="'kind-' + fileAppearance(editingDoc || {})"><knowledge-file-artwork :format="editingDoc?.format" :kind="fileAppearance(editingDoc || {})" :media-kind="editingDoc?.media_kind"/><div><strong>{{ editingDoc?.title }}</strong><small>{{ editingDoc?.project }} · {{ editingDoc?.format }} · {{ sizeLabel(editingDoc?.size || 0) }}</small></div></div><div class="ckb-attribution"><span>实际上传人：{{ editingDoc?.uploaded_by || '历史未采集' }}</span><small>最后修改：{{ editingDoc?.modified_by || '历史未采集' }}</small><button v-if="editingDoc?.id" @click="openAudit({document_id: editingDoc.id})">文件操作记录 <i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></div><div class="ckb-form-grid"><label class="ckb-form-wide">文件名称<input v-model="uploadForm.title" aria-label="文件名称" maxlength="255"></label><label v-if="editingDoc?.knowledge_project_id" class="ckb-form-wide">归档目录<select v-model="uploadForm.folder_id" aria-label="归档目录"><option value="">项目根目录</option><option v-for="folder in projectFolders.filter(item => item.project_id === editingDoc.knowledge_project_id)" :key="folder.id" :value="folder.id">{{ folderLabel(folder) }}</option></select></label><template v-if="!editingDoc?.inherits_project">
<label>所属项目<input aria-label="所属项目" v-model="uploadForm.project" :disabled="!!editingDoc?.knowledge_project_id" maxlength="200" placeholder="例如：新能源汽车尽调"></label>
<label>行业<input aria-label="行业" v-model="uploadForm.industry" maxlength="100" placeholder="例如：汽车与出行"></label>
<label>资料分类<select aria-label="资料分类" v-model="uploadForm.category"><option v-for="item in metadataCategoryOptions" :key="item">{{ item }}</option></select></label>
<label>复核状态<select aria-label="复核状态" v-model="uploadForm.review"><option>待复核</option><option>已复核</option><option>参考资料</option></select></label>
<label>保密等级<select aria-label="保密等级" v-model="uploadForm.confidentiality" @change="syncConfidentiality"><option value="internal">内部</option><option v-if="service.is_admin" value="secret">机密</option></select><small>普通账号默认可用，仅可读取内部资料；机密仅管理员可用。</small></label>
<div class="ckb-acl-summary"><i aria-hidden="true" class="fa-solid fa-shield-halved"></i><span>{{ uploadForm.confidentiality === 'internal' && uploadForm.visibility === 'members' ? '正常账号默认可读' : uploadForm.confidentiality !== 'internal' ? '仅管理员可读，普通账号不能申请访问' : '仅创建人、管理员及指定成员可读；其他成员可申请授权' }}</span><label v-if="uploadForm.confidentiality === 'internal'" class="ckb-restrict-toggle"><input type="checkbox" :checked="uploadForm.visibility === 'restricted'" @change="uploadForm.visibility = $event.target.checked ? 'restricted' : 'members'">内部资料也单独授权</label></div>
<label v-if="uploadForm.visibility === 'restricted' && uploadForm.confidentiality === 'internal'" class="ckb-form-wide">指定成员账号<input aria-label="指定成员账号" v-model="uploadForm.readersText" maxlength="10000" placeholder="系统登录账号，多个账号用逗号分隔；留空则仅自己和管理员可见"><small>指定成员须为正常账号；此授权仅适用于内部资料。</small></label>
<label class="ckb-form-wide">自定义标签<input aria-label="自定义标签" v-model="uploadForm.tagsText" maxlength="1000" placeholder="逗号分隔，最多 20 个标签"><span class="ckb-doc-tags"><span v-for="tag in formTags" :key="tag"># {{ tag }}</span></span></label></template><div v-else class="ckb-upload-inheritance ckb-form-wide"><i class="fa-solid fa-link" aria-hidden="true"></i><span>行业、标签、分类与权限跟随项目设置。</span></div><label class="ckb-form-wide">文字说明<textarea aria-label="文字说明" v-model="uploadForm.description" maxlength="10000" rows="3"></textarea><small v-if="editingDoc?.media_kind">更新说明、项目、行业或标签后，会重新索引说明；原件保持不变。</small></label>
</div><p>文件名、归档目录和说明可随时调整。项目属性请在项目设置中修改。旧版本保留，可分别管理。</p>
        <template #footer><button class="ckb-button ckb-button-outline ckb-delete-button" :disabled="operationPending('delete:' + editingDoc?.id)" @click="deleteDocument(editingDoc)">{{operationPending('delete:' + editingDoc?.id) ? '删除中…' : '删除资料'}}</button><button class="ckb-button ckb-button-primary" :disabled="operationPending('save:' + editingDoc?.id)" @click="saveMetadata">{{operationPending('save:' + editingDoc?.id) ? '保存中…' : '保存修改'}}</button></template>
      </el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="requestCenterOpen" :title="service.is_admin ? '权限审批' : '我的权限申请'" width="760px" class="ckb-dialog ckb-request-dialog" append-to-body><knowledge-glass-surface/>
        <p class="ckb-dialog-intro">{{ service.is_admin ? '所有管理员共享审批列表；任一管理员处理后，结果会同步。批准后阅读、下载和 AI 问答权限同时生效。' : '可在这里查看受限资料的申请进度。' }}</p>
        <div class="ckb-request-list"><article v-for="request in accessRequests" :key="request.id"><div><strong>{{ request.document_title }}</strong><span>{{ request.confidentiality_label || '内部' }} · {{ request.requester_username }}</span><p>{{ request.reason }}</p><small>{{ request.created_at ? new Date(request.created_at).toLocaleString('zh-CN') : '' }}<template v-if="request.decision_note"> · 处理说明：{{ request.decision_note }}</template></small></div><aside><b :data-status="request.status">{{ requestStatusLabel(request.status) }}</b><template v-if="service.is_admin && request.status === 'pending'"><button class="ckb-button ckb-button-primary" :disabled="operationPending('decision:' + request.id)" @click="decideAccess(request, 'approved')">批准</button><button class="ckb-button ckb-button-outline" :disabled="operationPending('decision:' + request.id)" @click="decideAccess(request, 'rejected')">拒绝</button></template></aside></article><p v-if="!accessRequests.length" class="ckb-home-empty">{{ accessLoading ? '正在加载…' : '暂无权限申请。' }}</p></div>
        <template #footer><button class="ckb-button ckb-button-primary" @click="requestCenterOpen = false">关闭</button></template>
      </el-dialog>
    </div>`
};
