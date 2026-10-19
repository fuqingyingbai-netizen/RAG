/* Company knowledge uses the authenticated backend; cloud credentials stay on the server. */
const CompanyKnowledge = {
  props: { projects: { type: Array, default: () => [] } },
  data() {
    return {
      viewRestored: false, restoringView: false, libraryPage: 1, libraryPageSize: 10, homeQuestion: '', sortOrder: 'updated', readingHistory: [], recentUploadIds: [], mode: 'home', projectFilter: '', industryFilter: '', statusFilter: '', reviewFilter: '', selectedIds: [], pollClock: null, readerUrl: '', readerLoading: false, readerError: '', readerTotal: 0, previewPage: 1, readerPDFPage: 1, readerPDFPages: 0, uploadBusy: false, uploadError: '', uploadResults: [], editingDoc: null, metadataOpen: false, uploadForm: { project: '', industry: '', category: '项目原件', review: '待复核', confidentiality: 'internal', visibility: 'members', readersText: '' }, query: '', category: '全部资料', space: 'all', favoritesOnly: false, mineOnly: false,
      favorites: [], readerOpen: false, selectedDoc: null, readerPage: 0,
      uploadOpen: false, stagedFiles: [], draft: '', scope: 'all', chatScope: 'accessible', messages: [],
      cloudDocuments: [], totalDocuments: 0, documentPage: 0, loading: false,
      service: { configured: false, access_allowed: false, is_admin: false }, serviceError: '',
      myProjects: { project_count: 0, document_count: 0, projects: [] }, accessRequests: [], requestCenterOpen: false, accessLoading: false,
      busy: false, answerStatus: '', controller: null, activityClock: null,
      categories: ['全部资料', '项目原件', '研究成果', '方法与模板'],
      suggestions: ['查找与新能源汽车竞争格局有关的历史研究，并标注来源', '根据资料梳理访谈提纲，区分已有依据和待确认问题', '比较资料中的主要结论，指出差异与待复核事项'],
    };
  },
  computed: {
    libraryView() { return { libraryPage: this.libraryPage, libraryPageSize: this.libraryPageSize, sortOrder: this.sortOrder, mode: this.mode, category: this.category, query: this.query, projectFilter: this.projectFilter, industryFilter: this.industryFilter, statusFilter: this.statusFilter, reviewFilter: this.reviewFilter, favoritesOnly: this.favoritesOnly, mineOnly: this.mineOnly }; },
    activeFilterLabel() { return [this.mineOnly && '我的项目', this.query && '搜索：' + this.query, this.projectFilter, this.industryFilter, this.statusFilter && '状态：' + ({ready:'可检索',queued:'等待处理',uploading:'上传中',parsing:'解析中',indexing:'索引中',failed:'处理失败'}[this.statusFilter] || this.statusFilter), this.reviewFilter, this.favoritesOnly && '仅收藏', this.recentUploadIds.length && '本次上传'].filter(Boolean).join(' · '); },
    uploadSummary() { const rows = this.uploadDisplayResults; const ready = rows.filter(row => row.phase === 'ready').length; const failed = rows.filter(row => !row.id || row.phase === 'failed').length; const pending = rows.length - ready - failed; return [ready && ready + ' 份资料已可检索', pending && pending + ' 份后台处理中', failed && failed + ' 份失败，请查看下方详情'].filter(Boolean).join('；'); },
    documents() { return this.cloudDocuments.map(doc => ({ ...doc, summary: [doc.industry, doc.review, doc.status_message].filter(Boolean).join(' · '), date: doc.modified_at ? new Date(doc.modified_at).toLocaleDateString('zh-CN') : '' })); },
    filteredDocuments() {
      const keyword = this.query.trim().toLowerCase();
      return this.documents.filter(doc =>
        (!this.recentUploadIds.length || this.recentUploadIds.includes(doc.id)) &&
        (this.category === '全部资料' || doc.category === this.category) &&
        (!this.projectFilter || (doc.project || '未归类项目') === this.projectFilter) &&
        (!this.industryFilter || doc.industry === this.industryFilter) &&
        (!this.statusFilter || doc.state === this.statusFilter) &&
        (!this.reviewFilter || doc.review === this.reviewFilter) &&
        (!this.mineOnly || doc.is_owner) &&
        (!this.favoritesOnly || this.favorites.includes(doc.id)) &&
        (!keyword || [doc.title, doc.summary, doc.project, doc.format].join(' ').toLowerCase().includes(keyword)));
    },
    sortedDocuments() { return [...this.filteredDocuments].sort((a, b) => this.sortOrder === 'title' ? a.title.localeCompare(b.title, 'zh-CN') : (Date.parse(b.modified_at) || 0) - (Date.parse(a.modified_at) || 0)); },
    libraryFilterKey() { return JSON.stringify([this.category, this.query, this.projectFilter, this.industryFilter, this.statusFilter, this.reviewFilter, this.favoritesOnly, this.mineOnly, this.recentUploadIds, this.sortOrder, this.libraryPageSize]); },
    libraryPageCount() { return Math.max(1, Math.ceil(this.sortedDocuments.length / this.libraryPageSize)); },
    currentLibraryPage() { return Math.min(Math.max(1, this.libraryPage), this.libraryPageCount); },
    pagedDocuments() { const start = (this.currentLibraryPage - 1) * this.libraryPageSize; return this.sortedDocuments.slice(start, start + this.libraryPageSize); },
    libraryPageRange() { const total = this.sortedDocuments.length; const start = total ? (this.currentLibraryPage - 1) * this.libraryPageSize + 1 : 0; return { start, end: Math.min(this.currentLibraryPage * this.libraryPageSize, total), total }; },
    libraryPageNumbers() { const start = Math.max(1, Math.min(this.currentLibraryPage - 2, this.libraryPageCount - 4)); return Array.from({ length: Math.min(5, this.libraryPageCount) }, (_, index) => start + index); },
    readableDocuments() { return this.documents.filter(doc => doc.can_read); },
    recentDocuments() { return [...this.readableDocuments].sort((a, b) => (Date.parse(b.modified_at) || 0) - (Date.parse(a.modified_at) || 0)).slice(0, 4); },
    recentlyRead() { return this.readingHistory.map(id => this.documents.find(doc => doc.id === id && doc.can_read)).filter(Boolean).slice(0, 4); },
    projectCollections() { return this.projectOptions.map(name => ({ name, count: this.readableDocuments.filter(doc => doc.project === name).length, industry: [...new Set(this.readableDocuments.filter(doc => doc.project === name).map(doc => doc.industry).filter(Boolean))].join(' / ') })).sort((a, b) => b.count - a.count).slice(0, 4); },
    libraryScopeFiltered() { return this.category !== '全部资料' || Boolean(this.activeFilterLabel); },
    readyCount() { return this.readableDocuments.filter(doc => doc.state === 'ready').length; },
    reviewedCount() { return this.readableDocuments.filter(doc => doc.review === '已复核').length; },
    projectOptions() { return [...new Set(this.readableDocuments.map(doc => doc.project).filter(Boolean))]; },
    industryOptions() { return [...new Set(this.documents.map(doc => doc.industry).filter(Boolean))]; },
    pendingCount() { return this.documents.filter(doc => ['queued', 'uploading', 'parsing', 'indexing'].includes(doc.state)).length; },
    failedCount() { return this.documents.filter(doc => doc.state === 'failed').length; },
    scopeLabel() { return this.selectedIds.length ? '选中 ' + this.selectedIds.length + ' 份资料' : this.chatScope === 'my-projects' ? '我的项目资料' : '全部可访问资料'; },
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
    libraryView: { deep: true, handler() { this.saveLibraryView(); } },
    libraryFilterKey() { if (!this.restoringView) { this.libraryPage = 1; this.scrollLibraryTop(); } },
    libraryPageCount(count) { if (!this.loading && this.libraryPage > count) this.libraryPage = count; },
  },
  mounted() { this.loadService(); this.pollClock = setInterval(() => { if (this.canAsk && !document.hidden) { this.loadDocuments(false, false); this.loadAccessRequests(); this.loadMyProjects(); } }, 6000); },
  beforeUnmount() { this.controller?.abort(); clearInterval(this.activityClock); clearInterval(this.pollClock); this.releaseReader(); },
  methods: {
    async apiFetch(url, options = {}) {
      const token = localStorage.getItem('accessToken');
      const response = await fetch(url, { ...options, headers: { ...options.headers, Authorization: 'Bearer ' + (token || '') } });
      if (response.status === 401) throw new Error('登录已过期，请重新登录。');
      return response;
    },
    async loadService() {
      try {
        const response = await this.apiFetch('/company-knowledge/status');
        if (!response.ok) throw new Error('无法读取知识库状态。');
        this.service = await response.json();
        if (!this.service.access_allowed) throw new Error('该账号尚未获得公司知识库访问权限，请联系管理员。');
        if (!this.service.configured) throw new Error('公司知识库尚未配置，请联系管理员。');
        try { this.favorites = JSON.parse(localStorage.getItem('companyKnowledgeFavorites:' + this.service.username) || '[]'); } catch { this.favorites = []; }
        if (!this.viewRestored) this.restoreLibraryView();
        await Promise.all([this.loadDocuments(), this.loadMyProjects(), this.loadAccessRequests()]);
      } catch (error) { this.serviceError = error.message; }
    },
    async loadDocuments(more = false, refresh = false) {
      if (this.loading) return;
      this.loading = true; this.serviceError = '';
      try {
        let lastPage = more ? this.documentPage + 1 : Math.max(1, this.documentPage);
        const incoming = []; let result;
        for (let page = more ? lastPage : 1; page <= lastPage; page++) {
          const response = await this.apiFetch('/company-knowledge/documents?page_number=' + page + '&page_size=100&refresh=' + (refresh && page === 1));
          result = await response.json();
          if (!response.ok) throw new Error(result.detail || '资料加载失败。');
          incoming.push(...result.documents);
          lastPage = Math.max(lastPage, Math.ceil(result.total_count / 100));
          if (!result.documents.length) break;
        }
        this.cloudDocuments = [...new Map((more ? [...this.cloudDocuments, ...incoming] : incoming).map(doc => [doc.id, doc])).values()];
        this.totalDocuments = result.total_count; this.documentPage = lastPage;
        this.categories = ['全部资料', ...new Set([...['项目原件', '研究成果', '方法与模板', '访谈纪要', '行业资料'], ...this.cloudDocuments.map(doc => doc.category)])]; this.serviceError = result.warning || ''; this.selectedIds = this.selectedIds.filter(id => this.cloudDocuments.some(doc => doc.id === id && doc.can_read !== false));
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
    restoreLibraryView() { this.restoringView = true; try { const saved = JSON.parse(localStorage.getItem('companyKnowledgeView:' + this.service.username) || '{}'); for (const key of ['category','query','projectFilter','industryFilter','statusFilter','reviewFilter']) if (typeof saved[key] === 'string') this[key] = saved[key]; if (['home','library','chat'].includes(saved.mode)) this.mode = saved.mode; if ([10,20,50].includes(saved.libraryPageSize)) this.libraryPageSize = saved.libraryPageSize; if (Number.isInteger(saved.libraryPage) && saved.libraryPage > 0) this.libraryPage = saved.libraryPage; if (['updated','title'].includes(saved.sortOrder)) this.sortOrder = saved.sortOrder; if (typeof saved.favoritesOnly === 'boolean') this.favoritesOnly = saved.favoritesOnly; if (typeof saved.mineOnly === 'boolean') this.mineOnly = saved.mineOnly; } catch {} try { const history = JSON.parse(localStorage.getItem('companyKnowledgeReading:' + this.service.username) || '[]'); this.readingHistory = Array.isArray(history) ? history.filter(id => typeof id === 'string').slice(0, 12) : []; } catch {} this.viewRestored = true; if (this.$nextTick) this.$nextTick(() => { this.restoringView = false; }); else this.restoringView = false; },
    scrollLibraryTop() { this.$nextTick?.(() => { if (this.$refs?.documentTable) this.$refs.documentTable.scrollTop = 0; }); },
    changeLibraryPage(page) { this.libraryPage = Math.max(1, Math.min(page, this.libraryPageCount)); this.scrollLibraryTop(); },
    askLibrary() {
      if (this.busy) return;
      if (!this.selectedIds.length && this.libraryScopeFiltered) {
        const ids = this.filteredDocuments.filter(doc => doc.can_read && doc.state === 'ready').map(doc => doc.id);
        if (!ids.length) { ElementPlus.ElMessage.info('当前范围没有可检索资料。'); return; }
        if (ids.length > 20) { ElementPlus.ElMessage.info('当前范围超过 20 份资料，请先勾选需要研究的文件。'); return; }
        this.changeScope(ids);
      }
      this.askSelection();
    },
    browseProject(name) { this.selectCategory('全部资料'); this.projectFilter = name; this.mode = 'library'; },
    browseMyProject(name = '') { this.selectCategory('全部资料'); this.mineOnly = true; this.projectFilter = name; this.mode = 'library'; },
    summarizeMyProjects() { if (this.busy) return; this.newConversation(); this.selectedIds = []; this.chatScope = 'my-projects'; this.mode = 'chat'; this.sendQuestion('请根据我上传的项目资料，总结我参与过的项目、主要研究内容和可复用经验；先给出简短总结，再用 Markdown 表格列出项目、行业、资料数量和主要成果，并标注引用依据。'); },
    browseLibrary() { this.selectCategory('全部资料'); this.mode = 'library'; },
    beginResearch(question) { if (this.busy) return; const text = typeof question === 'string' ? question.trim() : this.homeQuestion.trim(); if (!text) return; this.changeScope([]); this.mode = 'chat'; this.homeQuestion = ''; this.sendQuestion(text); },
    prepareResearch(kind) { if (this.busy) return; if (kind === 'templates') { this.selectCategory('方法与模板'); this.mode = 'library'; return; } if (kind === 'compare' && this.selectedIds.length < 2) { this.browseLibrary(); ElementPlus.ElMessage.info('请先勾选至少两份可检索资料，再点击“向选中资料提问”。'); return; } this.draft = kind === 'compare' ? '比较所选资料的结论差异，逐项列出依据与待复核事项。' : '查找相关历史项目，说明项目背景、研究方法及可复用经验，并标注来源。'; this.askSelection(); },
    selectCategory(category) { this.resetFilters(); this.category = category; },
    selectFavorites() { const active = this.favoritesOnly; this.selectCategory('全部资料'); this.favoritesOnly = !active; },
    selectFailed() { const active = this.statusFilter === 'failed'; this.selectCategory('全部资料'); this.statusFilter = active ? '' : 'failed'; },
    viewUploaded() { this.selectCategory('全部资料'); this.recentUploadIds = this.uploadResults.filter(row => row.id).map(row => row.id); this.mode = 'library'; this.uploadOpen = false; },
    showMode(mode) { this.mode = mode; },
    selectSpace(id) { this.space = this.space === id ? 'all' : id; },
    resetFilters() { this.recentUploadIds = []; this.query = ''; this.space = 'all'; this.favoritesOnly = false; this.mineOnly = false; this.projectFilter = ''; this.industryFilter = ''; this.statusFilter = ''; this.reviewFilter = ''; },
    toggleFavorite(id) { this.favorites = this.favorites.includes(id) ? this.favorites.filter(x => x !== id) : [...this.favorites, id]; try { localStorage.setItem('companyKnowledgeFavorites:' + this.service.username, JSON.stringify(this.favorites)); } catch {} },
    async openDocument(doc) {
      if (!doc.can_read) { await this.requestAccess(doc); return; }
      this.readingHistory = [doc.id, ...this.readingHistory.filter(id => id !== doc.id)].slice(0, 12);
      try { localStorage.setItem('companyKnowledgeReading:' + this.service.username, JSON.stringify(this.readingHistory)); } catch {}
      this.releaseReader(); this.selectedDoc = { ...doc, references: this.allReferences.filter(ref => ref.document_id === doc.cloud_id) };
      this.readerOpen = true; this.readerPDFPage = 1; this.readerPDFPages = 0; this.previewPage = 1; this.readerTotal = 0; this.readerError = '';
      const id = doc.id; this.readerLoading = true;
      try {
        const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + '/preview');
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || '文字预览加载失败。');
        if (this.selectedDoc?.id !== id) return;
        this.selectedDoc.references = result.references; this.readerTotal = result.total; this.readerError = result.message || '';
        if (doc.has_original && ['PDF', 'PNG', 'JPG', 'JPEG'].includes(doc.format)) {
          const original = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + (doc.format === 'PDF' ? '/page?page=1' : '/original'));
          if (doc.format === 'PDF') this.readerPDFPages = Number(original.headers.get('X-Document-Pages') || 1);
          if (!original.ok) throw new Error('原件预览暂不可用，可尝试下载。');
          const blob = await original.blob();
          if (this.selectedDoc?.id === id && this.readerOpen) this.readerUrl = URL.createObjectURL(blob);
        }
      } catch (error) { if (this.selectedDoc?.id === id) this.readerError = error.message; }
      finally { if (this.selectedDoc?.id === id) this.readerLoading = false; }
    },
    async changePDFPage(page) {
      if (this.readerLoading || page < 1 || page > this.readerPDFPages) return;
      this.readerLoading = true; const id = this.selectedDoc.id;
      try {
        const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + '/page?page=' + page);
        if (!response.ok) throw new Error('PDF 页面加载失败，请下载原件核对。');
        const blob = await response.blob();
        if (this.selectedDoc?.id === id && this.readerOpen) { this.releaseReader(); this.readerUrl = URL.createObjectURL(blob); this.readerPDFPage = page; }
      } catch (error) { this.readerError = error.message; } finally { this.readerLoading = false; }
    },
    releaseReader() { if (this.readerUrl) URL.revokeObjectURL(this.readerUrl); this.readerUrl = ''; },
    async morePreview() {
      if (this.readerLoading || !this.selectedDoc?.id) return;
      this.readerLoading = true; const id = this.selectedDoc.id;
      try {
        const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + '/preview?page=' + (this.previewPage + 1));
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '片段加载失败。');
        if (this.selectedDoc?.id === id) { this.selectedDoc.references.push(...result.references); this.previewPage++; }
      } catch (error) { this.readerError = error.message; } finally { this.readerLoading = false; }
    },
    async downloadOriginal(doc) {
      try {
        const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(doc.id) + '/original?download=true');
        if (!response.ok) { const result = await response.json(); throw new Error(result.detail || '下载失败。'); }
        const url = URL.createObjectURL(await response.blob()); const a = document.createElement('a'); a.href = url; a.download = doc.title; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    changeScope(ids) { if (this.busy) return; if (ids.length > 20) { ElementPlus.ElMessage.warning('一次最多选择 20 份资料。'); return; } this.selectedIds = ids; this.chatScope = 'accessible'; this.newConversation(); },
    toggleSelection(doc) { if (!doc.can_read || doc.state !== 'ready') return; this.changeScope(this.selectedIds.includes(doc.id) ? this.selectedIds.filter(id => id !== doc.id) : [...this.selectedIds, doc.id]); },
    askWhileReading() { if (!this.selectedDoc?.id || this.busy) return; const question = this.draft; if (this.selectedIds.length !== 1 || this.selectedIds[0] !== this.selectedDoc.id) this.changeScope([this.selectedDoc.id]); this.sendQuestion(question); },
    askSelection() { this.mode = 'chat'; this.readerOpen = false; this.$nextTick(() => this.$refs.composer?.focus()); },
    chooseFiles(event) { this.stagedFiles = Array.from(event.target.files || []); this.uploadResults = []; this.uploadError = ''; },
    async uploadFiles() {
      if (this.uploadBusy || !this.stagedFiles.length) return;
      this.uploadBusy = true; this.uploadError = ''; this.uploadResults = this.uploadResults.filter(row => row.id);
      const failed = [];
      for (const file of this.stagedFiles) {
        const row = { name: file.name, state: '上传中' }; this.uploadResults.push(row); const shown = this.uploadResults[this.uploadResults.length - 1];
        try {
          if (file.size > 32 * 1024 * 1024) throw new Error('超过 32 MB 限制');
          const form = new FormData(); form.append('file', file);
          for (const key of ['project', 'industry', 'category', 'review', 'confidentiality', 'visibility']) form.append(key, this.uploadForm[key]);
          form.append('readers', JSON.stringify(this.uploadForm.readersText.split(/[,，\n]/).map(name => name.trim()).filter(Boolean)));
          const response = await this.apiFetch('/company-knowledge/uploads', { method: 'POST', body: form });
          const result = await response.json(); if (!response.ok) throw new Error(result.detail || '上传失败');
          shown.id = result.id; shown.phase = result.state; shown.state = result.label || '等待处理'; shown.detail = '原件已保存，处理状态会自动更新。';
        } catch (error) { shown.state = error.message; failed.push(file); }
      }
      this.stagedFiles = failed; this.uploadBusy = false; await Promise.all([this.loadDocuments(), this.loadMyProjects()]);
    },
    async retryDocument(doc) { try { const response = await this.apiFetch('/company-knowledge/documents/' + doc.id + '/retry', { method: 'POST' }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '重试失败'); await this.loadDocuments(); } catch (error) { ElementPlus.ElMessage.error(error.message); } },
    editDocument(doc) { this.editingDoc = doc; this.uploadForm = { project: doc.project || '', industry: doc.industry || '', category: doc.category, review: doc.review, confidentiality: doc.confidentiality || 'internal', visibility: doc.visibility, readersText: (doc.readers || []).join(', ') }; this.metadataOpen = true; },
    async saveMetadata() {
      try {
        const response = await this.apiFetch('/company-knowledge/documents/' + this.editingDoc.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...this.uploadForm, readers: this.uploadForm.readersText.split(/[,，\n]/).map(name => name.trim()).filter(Boolean) }) });
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '保存失败');
        this.metadataOpen = false; this.newConversation(); await Promise.all([this.loadDocuments(), this.loadMyProjects()]);
      } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    startUpload() { this.uploadForm = { project: this.projectFilter, industry: this.industryFilter, category: '项目原件', review: '待复核', confidentiality: 'internal', visibility: 'members', readersText: '' }; this.stagedFiles = []; this.uploadResults = []; this.uploadError = ''; this.uploadOpen = true; },
    syncConfidentiality() { if (this.uploadForm.confidentiality !== 'internal') this.uploadForm.visibility = 'restricted'; },
    requestStatusLabel(status) { return ({ pending: '审批中', approved: '已批准', rejected: '已拒绝' })[status] || '未申请'; },
    async requestAccess(doc) {
      if (!doc.can_request && doc.request_status === 'pending') { ElementPlus.ElMessage.info('该资料的权限申请正在审批中。'); return; }
      try {
        const prompt = await ElementPlus.ElMessageBox.prompt('请说明需要阅读《' + doc.title + '》的原因，管理员将根据项目和保密等级审批。', '申请访问权限', { confirmButtonText: '提交申请', cancelButtonText: '取消', inputPlaceholder: '例如：新员工培训，需要学习项目方法', inputValidator: value => Boolean(value && value.trim()) || '请填写申请原因' });
        const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(doc.id) + '/access-requests', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: prompt.value.trim() }) });
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '申请提交失败。');
        ElementPlus.ElMessage.success('权限申请已提交。'); await Promise.all([this.loadDocuments(), this.loadAccessRequests()]);
      } catch (error) { if (error !== 'cancel' && error !== 'close') ElementPlus.ElMessage.error(error.message || '申请提交失败。'); }
    },
    async decideAccess(request, decision) {
      try {
        let note = '';
        if (decision === 'rejected') { const prompt = await ElementPlus.ElMessageBox.prompt('请填写拒绝原因。', '拒绝访问申请', { confirmButtonText: '确认拒绝', cancelButtonText: '取消', inputValidator: value => Boolean(value && value.trim()) || '请填写拒绝原因' }); note = prompt.value.trim(); }
        const response = await this.apiFetch('/company-knowledge/access-requests/' + request.id + '/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, note }) });
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '审批失败。');
        ElementPlus.ElMessage.success(decision === 'approved' ? '已批准访问。' : '已拒绝申请。'); await Promise.all([this.loadAccessRequests(), this.loadDocuments()]);
      } catch (error) { if (error !== 'cancel' && error !== 'close') ElementPlus.ElMessage.error(error.message || '审批失败。'); }
    },
    async deleteDocument(doc) {
      try { await ElementPlus.ElMessageBox.confirm('从资料库和问答索引移除《' + doc.title + '》？', '删除资料', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }); } catch { return; }
      try { const response = await this.apiFetch('/company-knowledge/documents/' + doc.id, { method: 'DELETE' }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '删除失败'); this.readerOpen = false; this.newConversation(); await Promise.all([this.loadDocuments(), this.loadMyProjects()]); } catch (error) { ElementPlus.ElMessage.error(error.message); }
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
    openCitation(group) { const doc = this.documents.find(doc => doc.cloud_id === group.document_id); if (doc) this.openDocument(doc); else { this.releaseReader(); this.selectedDoc = { title: group.title, references: group.references }; this.readerOpen = true; } },
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
    newConversation() { this.controller?.abort(); this.messages = []; this.draft = ''; },
    scrollChat() { this.$nextTick(() => { const feed = this.$refs.chatFeed; if (feed) feed.scrollTop = feed.scrollHeight; }); },
    async sendQuestion(question) {
      const content = (typeof question === 'string' ? question : this.draft).trim();
      if (!content || this.busy || !this.canAsk) return;
      if (content.length > 1500) { ElementPlus.ElMessage.warning('问题请控制在 1500 字以内。'); return; }
      if (!this.selectedIds.length && /(我的项目|我(?:曾经)?(?:做过|参与过|负责过|上传过|上传的).{0,12}(?:项目|资料|文件)|我.{0,6}(?:做了|做过|参与|负责|上传).{0,10}(?:哪些|什么).{0,6}(?:项目|资料|文件))/.test(content)) this.chatScope = 'my-projects';
      const history = this.messages.filter(message => message.text && !message.error && (message.role === 'user' || message.complete)).slice(-20).map(message => ({ role: message.role, content: message.text.slice(0, 20000) }));
      while (history.reduce((total, message) => total + message.content.length, 0) > 60000) history.shift();
      this.messages.push({ role: 'user', text: content, scope: this.scopeLabel });
      this.messages.push({ role: 'assistant', text: '', references: [], progress: [], elapsedSeconds: 0, scope: this.scopeLabel, complete: false });
      const answer = this.messages[this.messages.length - 1];
      this.busy = true; this.answerStatus = '正在连接云端知识库…'; this.draft = '';
      this.controller = new AbortController(); this.scrollChat();
      const started = Date.now();
      this.updateProgress(answer, { stage: 'connecting', label: '正在连接知识库', detail: '问题已提交，正在等待云端响应。' });
      this.activityClock = setInterval(() => { answer.elapsedSeconds = Math.max(answer.elapsedSeconds, Math.floor((Date.now() - started) / 1000)); }, 1000);
      let reader;
      try {
        const response = await this.apiFetch('/company-knowledge/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: this.controller.signal, body: JSON.stringify({ message: content, history, document_ids: this.selectedIds, scope: this.chatScope }) });
        if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || '知识库请求失败。'); }
        if (!response.body) throw new Error('浏览器未收到流式回答。');
        reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
        const consume = block => {
          const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
          if (!data) return;
          const event = JSON.parse(data);
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
      } catch (error) { answer.error = error.name === 'AbortError' ? '已停止生成。' : error.message; this.finishProgress(answer, true); }
      finally { clearInterval(this.activityClock); this.activityClock = null; if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); } this.busy = false; this.controller = null; this.answerStatus = ''; this.scrollChat(); }
      return;
    },
    onComposerKey(event) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); this.sendQuestion(); } }
  },
  template: `
    <div class="ckb-workspace ckb-workbench" :class="{ 'ckb-chat-workspace': mode === 'chat' }">
      <nav class="ckb-navigation" aria-label="知识库导航"><div class="ckb-tabs" role="tablist" aria-label="知识库视图">
        <button id="ckb-home-tab" role="tab" :aria-selected="mode === 'home'" :class="{ active: mode === 'home' }" @click="mode = 'home'">研究首页</button>
        <button id="ckb-library-tab" role="tab" :aria-selected="mode === 'library'" :class="{ active: mode === 'library' }" @click="mode = 'library'">资料库 <span>{{ totalDocuments }}</span></button>
        <button id="ckb-chat-tab" role="tab" :aria-selected="mode === 'chat'" :class="{ active: mode === 'chat' }" @click="mode = 'chat'">研究问答</button>
      </div><div class="ckb-nav-actions"><button class="ckb-request-center-button" @click="requestCenterOpen = true; loadAccessRequests()"><i class="fa-regular fa-bell"></i>{{ service.is_admin ? '权限审批' : '我的申请' }}<span v-if="pendingAccessCount">{{ pendingAccessCount }}</span></button><span class="ckb-connection"><span :class="{ online: canAsk }"></span>{{ canAsk ? '企业知识已连接' : '正在连接知识库' }}</span></div></nav>
      <div v-if="serviceError" class="ckb-service-error" role="alert">{{ serviceError }} <button @click="loadService">重试</button></div>
      <section v-if="mode === 'home'" class="ckb-research-home" role="tabpanel" aria-labelledby="ckb-home-tab">
        <div class="ckb-home-top">
          <div class="ckb-research-entry"><div class="ckb-entry-label">研究 · 检索 · 核对</div><h2>今天要研究什么？</h2><p>从历史项目、研究成果与原始资料中查找依据。</p>
            <form class="ckb-home-composer" @submit.prevent="beginResearch()"><label for="ckb-home-question">研究问题</label><textarea id="ckb-home-question" v-model="homeQuestion" maxlength="1500" rows="2" placeholder="例如：过去的汽车行业项目中，有哪些可复用的访谈方法？" :disabled="!canAsk || busy" @keydown.enter.exact.prevent="beginResearch()"></textarea><div><span><i class="fa-regular fa-folder-open"></i> 全部有权访问的资料</span><button type="submit" :disabled="!homeQuestion.trim() || !canAsk || busy">开始研究 <i class="fa-solid fa-arrow-right"></i></button></div></form>
            <div class="ckb-home-shortcuts"><button @click="prepareResearch('cases')"><i class="fa-regular fa-compass"></i> 查找历史案例</button><button @click="prepareResearch('compare')"><i class="fa-solid fa-code-compare"></i> 比较资料结论</button><button @click="prepareResearch('templates')"><i class="fa-regular fa-copy"></i> 查找方法与模板</button></div>
          </div>
          <aside class="ckb-knowledge-brief"><div class="ckb-section-eyebrow">知识概览</div><div class="ckb-brief-total"><strong>{{ readableDocuments.length }}</strong><span>份可访问资料</span></div><dl><div><dt>已可检索</dt><dd>{{ readyCount }}</dd></div><div><dt>已复核</dt><dd>{{ reviewedCount }}</dd></div><div><dt>已归档项目</dt><dd>{{ projectOptions.length }}</dd></div></dl><button v-if="pendingCount || failedCount" class="ckb-processing-link" @click="browseLibrary(); statusFilter = failedCount ? 'failed' : ''">{{ pendingCount }} 份处理中 · {{ failedCount }} 份失败 <i class="fa-solid fa-arrow-right"></i></button><p><template v-if="documents.length < totalDocuments">概览基于已加载的 {{ documents.length }} 份资料。<br></template>回答附引用来源，关键结论请核对原文。</p></aside>
        </div>
        <section class="ckb-home-section ckb-my-projects"><header><div><h3>我的项目</h3><p>按当前账号归集上传过的项目和资料</p></div><div><button @click="browseMyProject()">查看全部</button><button class="ckb-button ckb-button-primary" :disabled="!myProjects.document_count || busy" @click="summarizeMyProjects"><i class="fa-solid fa-wand-magic-sparkles"></i> AI 总结我的项目</button></div></header><div class="ckb-my-project-summary"><div><strong>{{ myProjects.project_count }}</strong><span>个项目</span></div><div><strong>{{ myProjects.document_count }}</strong><span>份资料</span></div><div class="ckb-project-bars"><button v-for="project in myProjects.projects" :key="project.name" @click="browseMyProject(project.name)"><span><strong>{{ project.name }}</strong><small>{{ project.industries?.join(' / ') || '未标记行业' }}</small></span><i><b :style="{ width: Math.max(8, project.document_count / myProjectMaxCount * 100) + '%' }"></b></i><em>{{ project.document_count }} 份</em></button><p v-if="!myProjects.projects.length">尚未找到当前账号上传的项目资料。</p></div></div></section>
        <section class="ckb-home-section"><header><div><h3>项目资料</h3><p>按项目浏览原件、访谈与研究成果</p></div><button @click="browseLibrary">查看全部资料 <i class="fa-solid fa-arrow-right"></i></button></header><div v-if="projectCollections.length" class="ckb-project-grid"><button v-for="project in projectCollections" :key="project.name" @click="browseProject(project.name)"><span class="ckb-project-monogram">{{ project.name.slice(0, 1) }}</span><strong>{{ project.name }}</strong><small>{{ project.industry || '未标记行业' }}</small><span class="ckb-project-bottom">{{ project.count }} 份资料 <i class="fa-solid fa-arrow-up-right-from-square"></i></span></button></div><div v-else class="ckb-home-empty">{{ loading ? '正在加载项目资料…' : '暂无归档项目。上传资料时填写所属项目，即可在此归集。' }}</div></section>
        <div class="ckb-home-bottom"><section class="ckb-home-section"><header><div><h3>最新资料</h3><p>按资料更新时间排列</p></div><button aria-label="上传资料" :disabled="!canAsk" @click="startUpload"><i class="fa-solid fa-plus"></i> 上传资料</button></header><div class="ckb-recent-list"><div v-for="doc in recentDocuments" :key="doc.id" class="ckb-recent-row"><span class="ckb-file-type">{{ doc.format }}</span><button @click="openDocument(doc)"><strong>{{ doc.title }}</strong><small>{{ doc.project || doc.category }} · {{ doc.date }}</small></button><span class="ckb-review-pill" :class="{ verified: doc.review === '已复核' }">{{ doc.review || '待复核' }}</span></div><p v-if="!recentDocuments.length" class="ckb-home-empty">{{ loading ? '正在加载资料…' : '暂无可访问资料' }}</p></div></section>
        <section class="ckb-home-section"><header><div><h3>继续阅读</h3><p>最近打开的资料</p></div><button @click="mode = 'library'; selectFavorites()">我的收藏</button></header><div class="ckb-recent-list"><div v-for="doc in recentlyRead" :key="doc.id" class="ckb-recent-row"><span class="ckb-file-type">{{ doc.format }}</span><button @click="openDocument(doc)"><strong>{{ doc.title }}</strong><small>{{ doc.project || doc.category }}</small></button><i class="fa-solid fa-angle-right"></i></div><div v-if="!recentlyRead.length" class="ckb-reading-empty"><i class="fa-regular fa-bookmark"></i><strong>从一份资料开始</strong><p>阅读过的文件会保留在这里，方便下次继续。</p><button @click="browseLibrary">浏览资料库 <i class="fa-solid fa-arrow-right"></i></button></div></div></section></div>
      </section>
      <section v-if="mode === 'library'" class="ckb-library-layout" role="tabpanel" aria-labelledby="ckb-library-tab">
        <aside class="ckb-library-sidebar"><span class="ckb-aside-label">知识分类</span>
          <button v-for="item in categories" :key="item" :class="{ active: category === item && !mineOnly && !favoritesOnly }" @click="selectCategory(item)">{{ item }}<small>{{ item === '全部资料' ? documents.length : documents.filter(doc => doc.category === item).length }}</small></button>
          <div class="ckb-sidebar-divider"></div><span class="ckb-aside-label">我的工作</span>
          <button :class="{ active: mineOnly }" @click="browseMyProject()">我的项目<small>{{ myProjects.project_count }}</small></button>
          <button :class="{ active: favoritesOnly }" @click="selectFavorites">我的收藏<small>{{ favorites.length }}</small></button>
          <button :class="{ active: statusFilter === 'failed' }" @click="selectFailed">处理失败<small>{{ failedCount }}</small></button>
          <p>资料按账号权限展示。项目和行业用于归类筛选。</p>
        </aside>
        <div class="ckb-library-content"><header class="ckb-library-heading"><div><span class="ckb-section-eyebrow">{{ projectFilter || (mineOnly ? '当前账号' : '公司资料') }}</span><h2>{{ mineOnly ? '我的项目' : favoritesOnly ? '我的收藏' : category }}</h2></div><span>{{ filteredDocuments.length }} 份资料</span></header>
          <div v-if="mineOnly" class="ckb-inline-project-summary"><span>共 {{ myProjects.project_count }} 个项目、{{ myProjects.document_count }} 份资料，只统计当前账号上传的内容。</span><button class="ckb-button ckb-button-primary" :disabled="!myProjects.document_count || busy" @click="summarizeMyProjects">AI 总结项目</button></div>
          <div class="ckb-library-tools"><label class="ckb-search"><i class="fa-solid fa-magnifying-glass"></i><input v-model="query" aria-label="搜索知识库资料" placeholder="搜索文件名、项目、行业或资料说明"><button v-if="query" aria-label="清空搜索" @click="query = ''">×</button></label><button class="ckb-button ckb-button-outline" :disabled="loading || !canAsk" @click="loadDocuments(false, true)">{{ loading ? '加载中…' : '刷新资料' }}</button><button class="ckb-button ckb-button-primary" aria-label="上传资料" :disabled="!canAsk" @click="startUpload"><i class="fa-solid fa-plus"></i> 上传资料</button></div>
          <div class="ckb-select-filters">
            <select v-model="projectFilter" aria-label="筛选项目"><option value="">全部项目</option><option v-for="item in projectOptions" :key="item">{{ item }}</option></select>
            <select v-model="industryFilter" aria-label="筛选行业"><option value="">全部行业</option><option v-for="item in industryOptions" :key="item">{{ item }}</option></select>
            <select v-model="statusFilter" aria-label="筛选处理状态"><option value="">全部处理状态</option><option value="ready">可检索</option><option value="queued">等待处理</option><option value="uploading">上传中</option><option value="parsing">解析中</option><option value="indexing">索引中</option><option value="failed">处理失败</option></select>
            <select v-model="reviewFilter" aria-label="筛选复核状态"><option value="">全部复核状态</option><option>待复核</option><option>已复核</option><option>参考资料</option></select>
            <button @click="resetFilters">清除筛选</button>
          </div>
          <p v-if="activeFilterLabel" class="ckb-active-filters">当前筛选：{{ activeFilterLabel }}</p>
          <div class="ckb-selection-bar"><span>勾选资料以限定问答范围 <span v-if="selectedIds.length"> · 已选 {{ selectedIds.length }} 份</span></span><div><select v-model="sortOrder" aria-label="资料排序"><option value="updated">最近更新</option><option value="title">名称排序</option></select><button v-if="selectedIds.length" :disabled="busy" @click="changeScope([])">取消选择</button><button class="ckb-button ckb-button-primary" :disabled="!canAsk || busy" @click="askLibrary">{{ selectedIds.length ? '向选中资料提问' : libraryScopeFiltered ? '向当前资料提问' : '检索全部资料' }} <i class="fa-solid fa-arrow-right"></i></button></div></div>
          <div ref="documentTable" class="ckb-table-scroll" tabindex="0" aria-label="资料列表，可滚动"><table class="ckb-document-table"><thead><tr><th class="ckb-check-column"></th><th>资料名称</th><th>项目 / 行业</th><th>复核与索引</th><th>更新 / 版本</th><th>操作</th></tr></thead><tbody>
            <tr v-for="doc in pagedDocuments" :key="doc.id" :class="{ selected: selectedIds.includes(doc.id), locked: !doc.can_read }">
              <td><input type="checkbox" :checked="selectedIds.includes(doc.id)" :disabled="busy || !doc.can_read || doc.state !== 'ready'" :aria-label="'选择资料：' + doc.title" @change="toggleSelection(doc)"></td>
              <td class="ckb-name-cell"><button @click="openDocument(doc)"><i :class="['fa-regular', !doc.can_read ? 'fa-lock' : doc.format === 'PDF' ? 'fa-file-pdf' : 'fa-file-lines']"></i><strong>{{ doc.title }}</strong></button><div>{{ doc.format }} · {{ sizeLabel(doc.size || 0) }} <span> · {{ doc.category }} · <b :class="['ckb-confidentiality', 'level-' + doc.confidentiality]">{{ doc.confidentiality_label || '内部' }}</b></span></div></td>
              <td><span>{{ doc.project || '未归档项目' }}</span><small>{{ doc.industry || '未标记行业' }}</small></td>
              <td><span :class="['ckb-state', 'ckb-state-' + (doc.can_read ? doc.state : 'locked')]" :title="doc.status_message">{{ doc.label }}</span><small :class="{ 'ckb-review-pending': doc.review === '待复核' }">{{ doc.review }}</small></td>
              <td><span>{{ doc.date }}</span><small>V{{ doc.version }} · {{ doc.owner || '云端导入' }}</small></td>
              <td class="ckb-table-actions"><template v-if="doc.can_read"><button :aria-label="favorites.includes(doc.id) ? '取消收藏' : '收藏资料'" @click="toggleFavorite(doc.id)"><i :class="favorites.includes(doc.id) ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark'"></i> {{ favorites.includes(doc.id) ? '已收藏' : '收藏' }}</button><button @click="openDocument(doc)">阅读</button></template><button v-else-if="doc.request_status === 'pending'" disabled>审批中</button><button v-else class="ckb-access-request" @click="requestAccess(doc)">{{ doc.request_status === 'rejected' ? '重新申请' : '申请权限' }}</button><button v-if="doc.can_manage" @click="editDocument(doc)">管理</button><button v-if="doc.can_manage && doc.state === 'failed' && doc.has_original" @click="retryDocument(doc)">重试</button></td>
            </tr>
            <tr v-if="!filteredDocuments.length"><td colspan="6" class="ckb-table-empty">{{ loading ? '正在加载资料…' : '当前筛选下没有资料，可调整筛选或上传文件。' }}</td></tr>
          </tbody></table></div>
          <nav class="ckb-pagination" aria-label="资料分页"><span class="ckb-page-range">共 {{ libraryPageRange.total }} 份 · 第 {{ libraryPageRange.start }}–{{ libraryPageRange.end }} 份</span><div><select v-model.number="libraryPageSize" aria-label="每页资料数量"><option :value="10">10 条 / 页</option><option :value="20">20 条 / 页</option><option :value="50">50 条 / 页</option></select><button aria-label="上一页资料" :disabled="currentLibraryPage <= 1" @click="changeLibraryPage(currentLibraryPage - 1)"><i class="fa-solid fa-angle-left"></i></button><button v-for="page in libraryPageNumbers" :key="page" :aria-label="'第 ' + page + ' 页资料'" :aria-current="page === currentLibraryPage ? 'page' : undefined" :class="{ active: page === currentLibraryPage }" @click="changeLibraryPage(page)">{{ page }}</button><button aria-label="下一页资料" :disabled="currentLibraryPage >= libraryPageCount" @click="changeLibraryPage(currentLibraryPage + 1)"><i class="fa-solid fa-angle-right"></i></button><span class="ckb-page-total">{{ currentLibraryPage }} / {{ libraryPageCount }} 页</span></div></nav>

        </div>
      </section>
      <section v-if="mode === 'chat'" id="ckb-chat-panel" class="ckb-chat-layout" role="tabpanel" aria-labelledby="ckb-chat-tab">
        <aside class="ckb-chat-aside">
          <button class="ckb-button ckb-button-outline" :disabled="busy" @click="newConversation">开始新对话</button>
          <div class="ckb-aside-label">检索范围</div><strong>{{ scopeLabel }}</strong>
          <p class="ckb-scope-note">{{ selectedIds.length ? '回答仅依据选中文件的检索片段。' : chatScope === 'my-projects' ? '按当前账号 ID 统计上传项目，只检索本人上传且已完成索引的资料。' : '检索当前账号可访问且已完成索引的资料。' }}</p>
          <button class="ckb-button ckb-button-outline" :disabled="busy" @click="mode = 'library'">选择资料</button>
          <button v-if="selectedIds.length || chatScope === 'my-projects'" class="ckb-button ckb-button-outline" :disabled="busy" @click="changeScope([])">改为全部资料</button>
          <button v-for="doc in selectedDocuments" :key="doc.id" class="ckb-reading-link" @click="openDocument(doc)"><i class="fa-regular fa-file-lines"></i><span>{{ doc.title }}</span></button>
          <div class="ckb-chat-aside-foot">关键结论请核对引用；待复核稿需保留复核说明。</div>
        </aside>
        <div class="ckb-chat-main">
          <header class="ckb-chat-header"><span><i class="fa-solid fa-wand-magic-sparkles"></i> 知识助手</span><small>基于公司资料 · 引用可核查</small></header>
          <div ref="chatFeed" class="ckb-chat-feed" aria-live="polite" aria-relevant="additions">
            <div v-if="!messages.length" class="ckb-chat-welcome">
              <div class="ckb-knowledge-mark"><i class="fa-regular fa-compass"></i></div>
              <h3>从问题到有依据的判断</h3><p>查找项目经验、比较资料结论，或就选中文件深入提问。</p>
              <div class="ckb-suggestions"><button v-for="(question, index) in suggestions" :key="question" @click="sendQuestion(question)"><span>0{{ index + 1 }}</span>{{ question }}<i class="fa-solid fa-arrow-right"></i></button></div>
            </div>
            <div v-for="(message, index) in messages" :key="index" :class="['ckb-message', 'ckb-message-' + message.role]">
              <template v-if="message.role === 'user'"><span class="ckb-user-question">{{ message.text }}</span><small>范围：{{ message.scope }}</small></template>
              <template v-else>
                <div class="ckb-answer-heading"><span><i class="fa-solid fa-wand-magic-sparkles"></i> 知识助手</span><small>{{ message.complete ? '回答完成' : message.error ? '生成未完成' : answerStatus }}</small></div>
                <details v-if="message.progress.length" class="ckb-progress" :open="!message.complete">
                  <summary><span :class="['ckb-progress-indicator', { active: !message.complete && !message.error }]"></span><strong>{{ message.complete ? '处理完成' : message.error ? '处理已停止' : '正在处理' }}</strong><span class="ckb-progress-current">{{ !message.complete && !message.error ? message.progress[message.progress.length - 1].label : '查看处理过程' }}</span><small>{{ message.elapsedSeconds }} 秒</small></summary>
                  <ol class="ckb-progress-steps"><li v-for="(step, n) in message.progress" :key="n" :class="step.state"><span class="ckb-step-mark"><i :class="step.state === 'done' ? 'fa-solid fa-check' : step.state === 'error' ? 'fa-solid fa-exclamation' : 'fa-solid fa-circle'"></i></span><div><strong>{{ step.label }}</strong><p>{{ step.detail }}</p></div></li></ol>
                  <p v-if="!message.complete && !message.error" class="ckb-wait-note">{{ message.text ? '回答正在实时更新。' : '等待云端下一步进度，回答生成后会逐步显示。' }}</p>
                </details>
                <div class="ckb-live-answer"><template v-for="(block, blockIndex) in answerBlocks(message.text)" :key="blockIndex"><div v-if="block.type === 'table'" class="ckb-answer-table"><table><thead><tr><th v-for="(header, n) in block.headers" :key="n">{{ header }}</th></tr></thead><tbody><tr v-for="(row, n) in block.rows" :key="n"><td v-for="(cell, m) in row" :key="m">{{ cell }}</td></tr></tbody></table></div><span v-else>{{ block.text }}</span></template></div><p v-if="message.error" class="ckb-service-error" role="alert">{{ message.error }}</p>
                <div v-if="message.references.length" class="ckb-citation-heading">参考文件 <span>{{ referenceGroups(message.references).length }} 份文件 · {{ message.references.length }} 个片段</span></div>
                <button v-for="(group, n) in referenceGroups(message.references)" :key="group.key" class="ckb-citation" @click="openCitation(group)"><span>{{ n + 1 }}</span><i class="fa-regular fa-file-lines"></i><div><strong>{{ group.title }}</strong><small>{{ group.references.length }} 个片段 · 引用 {{ referenceIds(group) }} · 点击展开</small></div><i class="fa-solid fa-angle-right"></i></button>
              </template>
            </div>
          </div>
          <div class="ckb-composer-area"><div class="ckb-composer"><textarea ref="composer" v-model="draft" maxlength="1500" :disabled="!canAsk" aria-label="知识问答问题" placeholder="提问、梳理研究思路，或从一份资料开始…" rows="2" @keydown="onComposerKey"></textarea><div><span><i class="fa-regular fa-folder-open"></i> {{ scopeLabel }}</span><button v-if="busy" aria-label="停止生成" @click="controller?.abort()"><i class="fa-solid fa-stop"></i></button><button v-else :disabled="!draft.trim() || !canAsk" aria-label="发送问题" @click="sendQuestion"><i class="fa-solid fa-arrow-up"></i></button></div></div><p>Enter 发送 · Shift + Enter 换行 <span>{{ busy ? answerStatus : "请核对引用依据" }}</span></p></div>
        </div>
      </section>


      <el-dialog v-model="readerOpen" width="94vw" class="ckb-dialog ckb-reader-dialog ckb-workbench-reader" append-to-body :title="selectedDoc?.title || '资料阅读'" @closed="releaseReader">
        <template v-if="selectedDoc"><div class="ckb-reader-toolbar"><span>{{ selectedDoc.format || '引用资料' }} · {{ selectedDoc.review || '请核对来源' }} · V{{ selectedDoc.version || 1 }}</span><div><button v-if="selectedDoc.has_original" class="ckb-button ckb-button-outline" @click="downloadOriginal(selectedDoc)">下载原件</button><button class="ckb-button ckb-button-primary" :disabled="busy || !canAsk || selectedDoc.state !== 'ready'" @click="askDocument">单独向这份资料提问</button></div></div>
        <div class="ckb-reader-columns"><div class="ckb-original-pane">
          <div v-if="readerUrl && selectedDoc.format === 'PDF'" class="ckb-pdf-pages"><div class="ckb-pdf-controls"><button :disabled="readerLoading || readerPDFPage <= 1" @click="changePDFPage(readerPDFPage - 1)">上一页</button><span>{{ readerPDFPage }} / {{ readerPDFPages }}</span><button :disabled="readerLoading || readerPDFPage >= readerPDFPages" @click="changePDFPage(readerPDFPage + 1)">下一页</button></div><img :src="readerUrl" alt="PDF 原件页面预览"></div>
          <img v-else-if="readerUrl" :src="readerUrl" alt="扫描资料原件">
          <div v-else class="ckb-source-reader"><p v-if="readerLoading">正在加载解析文字…</p><p v-if="readerError" role="status">{{ readerError }}</p><p v-if="!readerLoading && !selectedDoc.references?.length">暂无可展示的解析片段。</p><section v-for="reference in selectedDoc.references" :key="reference.id"><div class="ckb-citation-heading">片段 {{ reference.id }}</div><pre>{{ reference.text }}</pre><a v-if="!selectedDoc.has_original && originalUrl(reference.url)" class="ckb-button ckb-button-outline" :href="originalUrl(reference.url)" target="_blank" rel="noopener noreferrer">打开云端原件 / 下载</a></section><button v-if="readerTotal > (selectedDoc.references?.length || 0)" class="ckb-button ckb-button-outline" :disabled="readerLoading" @click="morePreview">加载后续解析片段</button></div>
        </div><aside class="ckb-reader-question"><h3>阅读与核对</h3><p>{{ selectedDoc.status_message || '点击引用可核对依据。' }}</p><p v-if="selectedDoc.format !== 'PDF' && !readerUrl">当前展示解析文字，版式请下载原件核对。</p>
          <div v-if="selectedDoc.references?.length && readerUrl" class="ckb-reader-evidence"><strong>解析片段</strong><details v-for="reference in selectedDoc.references" :key="reference.id"><summary>片段 {{ reference.id }}</summary><pre>{{ reference.text }}</pre></details><button v-if="readerTotal > selectedDoc.references.length" :disabled="readerLoading" @click="morePreview">加载更多片段</button></div>
          <div v-if="messages.length" class="ckb-reader-last-answer"><strong>最近的回答</strong><template v-for="(message, index) in messages.slice(-2)" :key="index"><p v-if="message.role === 'user'">{{ message.text }}</p><pre v-else>{{ message.text || answerStatus }}<span v-if="message.error">{{ message.error }}</span></pre></template></div>
          <div class="ckb-reader-ask"><textarea v-model="draft" maxlength="1500" :disabled="busy || selectedDoc.state !== 'ready'" placeholder="就这份原件提问，例如：哪些结论仍需复核？"></textarea><button class="ckb-button ckb-button-primary" :disabled="busy || !draft.trim() || selectedDoc.state !== 'ready'" @click="askWhileReading">{{ busy ? answerStatus || '正在回答…' : '依据这份资料回答' }}</button></div>
        </aside></div></template>
      </el-dialog>
      <el-dialog v-model="uploadOpen" title="上传公司资料" width="680px" class="ckb-dialog" append-to-body :close-on-click-modal="!uploadBusy" :show-close="!uploadBusy" :close-on-press-escape="!uploadBusy">
        <p v-if="!uploadResults.length" class="ckb-dialog-intro">上传后自动解析并建立检索索引。Word、PDF、扫描图片、Excel、PPT 和文本，单份不超过 32 MB。</p>
        <p v-if="uploadResults.length && !uploadBusy" class="ckb-upload-summary" role="status">上传结果：{{ uploadSummary }}</p>
        <fieldset v-if="!uploadResults.length || uploadBusy" :disabled="uploadBusy" class="ckb-upload-fields"><div class="ckb-form-grid">
<label>所属项目<input aria-label="所属项目" v-model="uploadForm.project" maxlength="200" placeholder="例如：新能源汽车尽调"></label>
<label>行业<input aria-label="行业" v-model="uploadForm.industry" maxlength="100" placeholder="例如：汽车与出行"></label>
<label>资料分类<select aria-label="资料分类" v-model="uploadForm.category"><option v-for="item in ['项目原件','研究成果','方法与模板','访谈纪要','行业资料']" :key="item">{{ item }}</option></select></label>
<label>复核状态<select aria-label="复核状态" v-model="uploadForm.review"><option>待复核</option><option>已复核</option><option>参考资料</option></select></label>
<label>保密等级<select aria-label="保密等级" v-model="uploadForm.confidentiality" @change="syncConfidentiality"><option value="internal">内部</option><option value="confidential">敏感</option><option value="secret">机密</option></select><small>敏感和机密资料需要单独授权。</small></label>
<label>可见范围<select aria-label="可见范围" v-model="uploadForm.visibility" :disabled="uploadForm.confidentiality !== 'internal'"><option value="members">全部知识库授权成员</option><option value="restricted">仅上传者、管理员及指定成员</option></select></label>
<label v-if="uploadForm.visibility === 'restricted'" class="ckb-form-wide">指定成员账号<input aria-label="指定成员账号" v-model="uploadForm.readersText" maxlength="10000" placeholder="系统登录账号，多个账号用逗号分隔；留空则仅自己和管理员可见"><small>指定成员仍需先获得知识库访问权限。</small></label>
</div><label class="ckb-file-drop">选择文件（可多选）<input type="file" multiple accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.jpg,.jpeg,.png" aria-label="选择上传资料" @change="chooseFiles"><small>同名不同内容保留为新版本；相同内容会提示已上传。</small></label></fieldset>
        <ul class="ckb-upload-list"><li v-for="(file, index) in stagedFiles" :key="index">{{ file.name }} <small>{{ sizeLabel(file.size) }}</small></li></ul><ul class="ckb-upload-results" aria-live="polite"><li v-for="(item, index) in uploadDisplayResults" :key="index"><strong>{{ item.name }}</strong><span :data-state="item.phase">{{ item.state }}<template v-if="item.detail"> · {{ item.detail }}</template></span><button v-if="item.can_retry" class="ckb-button ckb-button-outline" @click="retryDocument(item)">重试处理</button></li></ul>
        <template #footer><template v-if="uploadResults.length && !uploadBusy"><button v-if="stagedFiles.length" class="ckb-button ckb-button-outline" @click="uploadFiles">重试上传失败文件</button> <button class="ckb-button ckb-button-outline" @click="startUpload">继续上传</button> <button class="ckb-button ckb-button-primary" @click="viewUploaded">{{ uploadResults.some(item => item.id) ? '完成，查看资料' : '返回资料库' }}</button></template><template v-else><button class="ckb-button ckb-button-outline" :disabled="uploadBusy" @click="uploadOpen = false">取消</button> <button class="ckb-button ckb-button-primary" :disabled="uploadBusy || !stagedFiles.length" @click="uploadFiles">{{ uploadBusy ? '正在上传，请稍候…' : '上传并建立索引' }}</button></template></template>
      </el-dialog>
      <el-dialog v-model="metadataOpen" title="管理资料" width="680px" class="ckb-dialog" append-to-body><p>{{ editingDoc?.title }}</p><div class="ckb-form-grid">
<label>所属项目<input aria-label="所属项目" v-model="uploadForm.project" maxlength="200" placeholder="例如：新能源汽车尽调"></label>
<label>行业<input aria-label="行业" v-model="uploadForm.industry" maxlength="100" placeholder="例如：汽车与出行"></label>
<label>资料分类<select aria-label="资料分类" v-model="uploadForm.category"><option v-for="item in ['项目原件','研究成果','方法与模板','访谈纪要','行业资料']" :key="item">{{ item }}</option></select></label>
<label>复核状态<select aria-label="复核状态" v-model="uploadForm.review"><option>待复核</option><option>已复核</option><option>参考资料</option></select></label>
<label>保密等级<select aria-label="保密等级" v-model="uploadForm.confidentiality" @change="syncConfidentiality"><option value="internal">内部</option><option value="confidential">敏感</option><option value="secret">机密</option></select><small>敏感和机密资料需要单独授权。</small></label>
<label>可见范围<select aria-label="可见范围" v-model="uploadForm.visibility" :disabled="uploadForm.confidentiality !== 'internal'"><option value="members">全部知识库授权成员</option><option value="restricted">仅上传者、管理员及指定成员</option></select></label>
<label v-if="uploadForm.visibility === 'restricted'" class="ckb-form-wide">指定成员账号<input aria-label="指定成员账号" v-model="uploadForm.readersText" maxlength="10000" placeholder="系统登录账号，多个账号用逗号分隔；留空则仅自己和管理员可见"><small>指定成员仍需先获得知识库访问权限。</small></label>
</div><p>更新可见范围后，后续检索与原件访问使用新权限。旧版本保留，可分别管理。</p>
        <template #footer><button class="ckb-button ckb-button-outline ckb-delete-button" @click="deleteDocument(editingDoc); metadataOpen = false">删除资料</button><button class="ckb-button ckb-button-primary" @click="saveMetadata">保存修改</button></template>
      </el-dialog>
      <el-dialog v-model="requestCenterOpen" :title="service.is_admin ? '权限审批' : '我的权限申请'" width="760px" class="ckb-dialog ckb-request-dialog" append-to-body>
        <p class="ckb-dialog-intro">{{ service.is_admin ? '审批后，阅读、下载和 AI 问答权限会同时生效。' : '可在这里查看受限资料的申请进度。' }}</p>
        <div class="ckb-request-list"><article v-for="request in accessRequests" :key="request.id"><div><strong>{{ request.document_title }}</strong><span>{{ request.confidentiality_label || '内部' }} · {{ request.requester_username }}</span><p>{{ request.reason }}</p><small>{{ request.created_at ? new Date(request.created_at).toLocaleString('zh-CN') : '' }}<template v-if="request.decision_note"> · 处理说明：{{ request.decision_note }}</template></small></div><aside><b :data-status="request.status">{{ requestStatusLabel(request.status) }}</b><template v-if="service.is_admin && request.status === 'pending'"><button class="ckb-button ckb-button-primary" @click="decideAccess(request, 'approved')">批准</button><button class="ckb-button ckb-button-outline" @click="decideAccess(request, 'rejected')">拒绝</button></template></aside></article><p v-if="!accessRequests.length" class="ckb-home-empty">{{ accessLoading ? '正在加载…' : '暂无权限申请。' }}</p></div>
        <template #footer><button class="ckb-button ckb-button-primary" @click="requestCenterOpen = false">关闭</button></template>
      </el-dialog>
    </div>`
};
