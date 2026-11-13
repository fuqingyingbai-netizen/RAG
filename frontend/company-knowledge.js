/* Company knowledge uses the authenticated backend; cloud credentials stay on the server. */
const KnowledgeFileArtwork = {
  props: { format: String, kind: String, mediaKind: String },
  template: `<div class="ckb-file-object" aria-hidden="true"><span class="ckb-file-fold"></span><b>{{ format }}</b><div class="ckb-file-lines"><i></i><i></i><i></i></div><div v-if="kind === 'sheet'" class="ckb-file-cells"></div><div v-if="mediaKind" class="ckb-file-media"><i :class="mediaKind === 'audio' ? 'fa-solid fa-wave-square' : 'fa-solid fa-play'"></i></div></div>`,
};
const KnowledgeFolderArtwork = { template: `<div class="ckb-folder-object" aria-hidden="true"><span class="ckb-folder-back"></span><span class="ckb-folder-sheet one"></span><span class="ckb-folder-sheet two"></span><span class="ckb-folder-lid"><i class="fa-solid fa-layer-group"></i></span><span class="ckb-folder-tab"></span></div>` };
const KnowledgeUploadProgressRow = {
  props: { item: Object }, emits: ['open'],
  template: `<button type="button" class="ckb-upload-pending-row" :data-upload-id="item.client_id" :data-state="item.phase" :aria-label="'查看上传任务：'+item.name" @click="$emit('open')"><span v-if="['waiting','transferring','saving'].includes(item.phase)" class="ckb-loading-spinner" aria-hidden="true"></span><i v-else class="fa-solid fa-circle-exclamation" aria-hidden="true"></i><span class="ckb-upload-pending-name"><strong>{{item.name}}</strong><small>{{item.phase==='saving'?'传输完成，正在保存':item.phase==='transferring'?'正在上传':item.state}}<template v-if="item.phase==='transferring' && item.percent!==null"> · {{item.percent}}%</template></small></span><progress v-if="item.phase==='transferring' || item.phase==='saving'" :value="item.saving || item.percent===null?undefined:item.percent" max="100" aria-label="上传进度"></progress><span class="ckb-upload-pending-action">{{item.phase==='upload_failed' || item.phase==='stopped'?'查看详情':'查看进度'}}<i class="fa-solid fa-chevron-right" aria-hidden="true"></i></span></button>`,
};
const knowledgePreviewLanes = [Promise.resolve(), Promise.resolve()]; let knowledgePreviewLane = 0;
const knowledgeAnswerMarkup = new WeakMap();
const KnowledgeThumbnail = {
  props: { doc: Object, fetchImage: Function },
  data() { return { url: '', failed: false }; },
  mounted() { if (!this.doc.can_read || !this.doc.has_original || !['PDF','PNG','JPG','JPEG','MP4','WEBM'].includes(this.doc.format)) return; const start = () => { this.observer?.disconnect(); this.load(); }; if (typeof IntersectionObserver === 'undefined') start(); else { this.observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) start(); }); this.observer.observe(this.$el); } },
  beforeUnmount() { this.disposed = true; this.observer?.disconnect(); this.controller?.abort(); if (this.url) URL.revokeObjectURL(this.url); },
  methods: { async load() { const lane=knowledgePreviewLane++ % knowledgePreviewLanes.length; const task=knowledgePreviewLanes[lane].then(()=>this.loadImage());knowledgePreviewLanes[lane]=task.catch(()=>{});await task; }, async loadImage() { if(this.disposed)return; this.controller = new AbortController(); try { const response = await this.fetchImage('/company-knowledge/documents/' + encodeURIComponent(this.doc.id) + '/thumbnail', {signal:this.controller.signal}); if (!response.ok) throw Error(); const blob = await response.blob(); if (!this.disposed) this.url = URL.createObjectURL(blob); } catch { this.failed = true; } } },
  template: `<span class="ckb-content-thumbnail" :class="{'has-image':!!url}" aria-hidden="true"><img v-if="url" :src="url" alt=""></span>`,
};
const KnowledgeFailureActions = {
  props: {doc:Object,retryBusy:Boolean}, emits:['retry','reupload','remove','edit-note','details'],
  template:`<div v-if="doc?.state === 'failed'" class="ckb-failed-actions" :data-failure-id="doc.id"><button v-if="doc.can_read" class="ckb-failure-details" @click.stop="$emit('details',doc)">失败详情</button><template v-if="doc.can_manage && doc.can_read"><button v-if="doc.has_original" :disabled="retryBusy" @click.stop="$emit('retry',doc)">{{retryBusy?'提交中…':'重试处理'}}</button><button v-if="!doc.note_id" @click.stop="$emit('reupload',doc)">{{doc.has_original?'重新上传':'补传原件'}}</button><button v-else @click.stop="$emit('edit-note',doc.note_id)">编辑并重试发布</button><button class="ckb-delete-button" :aria-label="'删除失败资料：'+doc.title" @click.stop="$emit('remove',doc)">删除</button></template><small v-else>需{{doc.owner ? '归属人 '+doc.owner+' 或' : ''}}管理员处理</small></div>`,
};
// Element Plus owns menu focus, arrow-key navigation and click-outside.
// Also close on Escape while focus remains on the native trigger button.
// Keep document permissions and mutations in the existing parent methods.
const KnowledgeFileMenu = {
  props: { doc: Object, canMove: Boolean, canCopy: Boolean },
  emits: ['move', 'manage', 'remove', 'copy', 'cut', 'history'],
  template: `<el-dropdown ref="actions" v-if="doc?.can_manage && doc.state !== 'failed'" trigger="click" placement="bottom-end" popper-class="ckb-file-action-menu">
    <button type="button" class="ckb-file-more" :aria-label="'更多操作：' + doc.title" @keydown.esc.stop.prevent="$refs.actions.handleClose()" @click.stop @dblclick.stop>更多<i class="fa-solid fa-chevron-down" aria-hidden="true"></i></button>
    <template #dropdown><el-dropdown-menu>
      <el-dropdown-item :disabled="!canCopy" @click="$emit('copy', doc)">复制</el-dropdown-item>
      <el-dropdown-item :disabled="!canCopy" @click="$emit('cut', doc)">剪切</el-dropdown-item>
      <el-dropdown-item v-if="doc.can_history" @click="$emit('history', doc)">历史版本</el-dropdown-item>
      <el-dropdown-item v-if="canMove" :aria-label="'移动资料：' + doc.title" @click="$emit('move', doc)"><i class="fa-solid fa-folder-open" aria-hidden="true"></i>移动到…</el-dropdown-item>
      <el-dropdown-item :aria-label="'管理资料：' + doc.title" @click="$emit('manage', doc)"><i class="fa-solid fa-sliders" aria-hidden="true"></i>文件设置</el-dropdown-item>
      <el-dropdown-item divided class="ckb-file-menu-danger" :aria-label="'删除资料：' + doc.title" @click="$emit('remove', doc)"><i class="fa-regular fa-trash-can" aria-hidden="true"></i>删除文件</el-dropdown-item>
    </el-dropdown-menu></template>
  </el-dropdown>`,
};
const CompanyKnowledge = {
  components: { KnowledgeUploadProgressRow, KnowledgeFileMenu, KnowledgeFailureActions, KnowledgeSheetViewer: typeof window !== 'undefined' ? window.KnowledgeSheetViewer : {}, KnowledgeNoteEditor: typeof window !== 'undefined' ? window.KnowledgeNoteEditor : {}, KnowledgeThumbnail, KnowledgeFileArtwork, KnowledgeFolderArtwork, KnowledgeGlassSurface: typeof window !== 'undefined' ? window.KnowledgeGlassSurface : {}, KnowledgeDocumentViewer: typeof window !== 'undefined' ? window.KnowledgeDocumentViewer : {}, KnowledgePdfViewer: typeof window !== 'undefined' ? window.KnowledgePdfViewer : {} },
  emits: ['department-change'],
  props: { departmentEntry: {type:Object, default:null}, projects: { type: Array, default: () => [] },
    feedback: {type:Function, default:null}, operationState:{type:Object, default:() => ({})} },
  data() {
    return {
      fileClipboard:null,pasteRequest:null,clipboardBusy:false,fileContext:null,fileContextAnchor:null,fileContextCloser:null,
      versionOpen:false,versionLoading:false,versionTitle:'',versionRows:[],versionError:'',versionSequence:0,uploadRequestIds:new Map(),
      uploadBatchDestination:null,uploadXHR:null,uploadCurrent:null,uploadStopped:false,uploadLeaveGuard:null,readerMediaTimer:null,readerMediaWake:null,readerMediaMessage:'',readerImageZoom:100,
      departmentEntryApplied:false, fixedDepartmentContext:false, departmentFilter: '', departmentOptions: [{id:'market',label:'市场部'},{id:'project',label:'项目部'},{id:'policy',label:'制度文件'},{id:'expert',label:'专家资料'}],
      retryTrackingIds: [], retryReceiptsExpanded: false, projectCreationDepartment: '',
      uploadTargetProjectId: '', uploadTargetFolderId: '', reuploadContext:null, moveOpen: false, moveDoc: null, moveProjectId: '', moveFolderId: '', moveBusy: false, moveError: '',
      catalogueMutation:0,catalogueRefreshQueued:false,noteDeleting:false,noteEditorId: '', noteDrafts: [], noteError: '', noteCreating: false,
      searchMode: 'metadata', contentMatches: [], contentTotal: 0, contentPage: 1, contentBusy: false, contentError: '', contentSearched: false, searchSequence: 0, readerLocation: null, readerFind: '', readerFocus: false, locating: false, quickCapture: false, captureTitle: '', captureScene: '', captureMethod: '',
      projectDirectories: [], projectFolders: [], projectLoading: false, projectError: '', projectDisplay: 'projects', activeProjectId: '', activeFolderId: '', openingDirectoryId: '', directoryTimer: null, projectEditorOpen: false, editingProject: null, projectSaving: false, projectForm: {}, folderEditorOpen: false, editingFolder: null, folderName: '', folderSaving: false, folderError: '',
      theme: 'light', motionPaused: true, libraryLayout: 'list', tabIndicatorStyle: { opacity: 0 },
      selectedProjectIds: [], selectedFolderIds: [], selectionBusy: false, selectionSequence: 0, returnLocation: null, scopeFilesExpanded:false,
      downloadProgress: {}, readerSheet:null,readerOriginalCode:'',restoringOriginal:false, readerBlob: null, readerSearchQuery:'',readerSearchStatus:'',readerSearchIndex:0,readerHasMore:false,readerOriginalFind:'',readerExcerptError:'',readerOriginalError:'', readerMode: 'original', readerTrace: '', readerOriginalLoading: false, chatAtBottom: true,
      auditOpen: false, auditLoading: false, auditEvents: [], auditTotal: 0, auditPage: 1, auditScope: {}, auditError: '', auditSequence: 0,
      tagFilter: '', dateFrom: '', dateTo: '', dateField: 'created_at', libraryIntent: '',
      caseCategories: ['项目经验', '案例复盘', '方法与模板', '培训分享', '现场照片', '手稿笔记', '影音随记'],
      allCategories: ['项目原件', '研究成果', '访谈纪要', '行业资料', '项目经验', '案例复盘', '方法与模板', '培训分享', '现场照片', '手稿笔记', '影音随记'],
      viewRestored: false, restoringView: false, libraryPage: 1, libraryPageSize: 10, projectPreview: {id:'', pendingId:'', pinned:false, blockedUntil:0, rearmOnMove:false, x:null, y:null, cursorX:null, cursorY:null, reference:null, openTimer:null, closeTimer:null}, advancedFiltersOpen: false, homeActivityTab: 'updated', homeSearch: '', recycleOpen: false, recycleLoading: false, recycleError: '', recycleItems: [], recyclePage: 1, recycleTotal: 0, recycleBusy: '', homeQuestion: '', sortOrder: 'updated', readingHistory: [], recentUploadIds: [], mode: 'home', projectFilter: '', industryFilter: '', statusFilter: '', reviewFilter: '', selectedIds: [], pollClock: null, readerUrl: '', readerLoading: false, readerError: '', readerTotal: 0, previewPage: 1, readerPDFPages: 0, uploadBusy: false, uploadError: '', uploadResults: [], editingDoc: null, metadataOpen: false, uploadForm: { project: '', industry: '', category: '项目原件', review: '待复核', confidentiality: 'internal', visibility: 'members', readersText: '', tagsText: '', description: '' }, query: '', category: '全部资料', space: 'all', favoritesOnly: false, mineOnly: false,
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
    canPasteFiles() { return !!this.fileClipboard && !this.clipboardBusy && this.canAsk &&
      (!this.activeProjectId || !!this.activeProject?.can_manage) && !this.directorySearchActive; },
    visibleUploadTasks() {
      return this.uploadResults.filter(item => {
        if(item.id || !item.destination)return false;
        const dest=item.destination;
        return this.caseCategories.includes(dest.category)===(this.currentCollection==='experience') &&
          (!this.departmentActive || dest.department===this.departmentFilter || this.departmentFilter==='unassigned'&&!dest.department) &&
          (this.activeProjectId ? dest.project_id===this.activeProjectId && dest.folder_id===this.activeFolderId : !this.showingProjects || !dest.project_id);
      });
    },
    uploadDescriptionRequired() {
      const projectId=this.reuploadContext?.project_id??this.uploadTargetProjectId;
      return !this.quickCapture&&!projectId&&this.stagedFiles.some(file=>/\.(mp3|wav|m4a|ogg|flac|mp4|webm)$/i.test(file.name));
    },
    readerExcerptCountLabel() {
      const loaded=this.selectedDoc?.references?.length||0;
      return this.readerTotal>0&&this.readerTotal>=loaded
        ? `已加载 ${loaded} / ${this.readerTotal} 个解析片段`
        : `当前显示 ${loaded} 个检索依据片段`;
    },
    libraryEmptyMessage() {
      if (this.loading) return '正在加载资料…';
      if (this.query.trim()) return '未找到匹配的资料，请更换关键词或清空搜索。';
      return this.activeProject ? '当前目录暂无资料。' : '暂无符合条件的资料，可以尝试清空筛选。';
    },
    readerContextHint() {
      if (this.readerMode === 'excerpts') return this.selectedDoc?.has_original
        ? '当前是检索依据片段，可切回完整原件阅读上下文。'
        : '当前仅有解析文字，尚未归档完整原件。片段不能代替原件全文。';
      if (this.readerOriginalLoading) return '正在准备原件预览，请稍候。';
      if (this.readerOriginalError) return '原件预览未打开，请根据提示处理；已有解析片段仍可单独核对。';
      return '正在查看归档原件。在线版式供阅读，正式引用请核对下载文件。';
    },
    retryTrackedDocuments() { const docs=new Map(this.collectionDocuments.filter(doc=>doc.can_read).map(doc=>[doc.id,doc]));return this.retryTrackingIds.map(id=>docs.get(id)).filter(Boolean); },
    retryReceiptSummary() {
      const counts={processing:0,ready:0,failed:0};
      for(const doc of this.retryTrackedDocuments){if(doc.state==='ready')counts.ready++;else if(doc.state==='failed')counts.failed++;else counts.processing++;}
      return [[counts.processing,'处理中'],[counts.ready,'成功'],[counts.failed,'失败']].filter(([count])=>count).map(([count,label])=>count+' '+label).join(' · ');
    },
    uploadDestinationLabel() {
      if(this.quickCapture)return '经验沉淀 / 随手记录 · 待整理 / 项目根目录';
      const saved=this.uploadDisplayResults.find(item=>item.document)?.document;
      if(saved)return this.documentLocationLabel(saved);
      return this.documentLocationLabel({category:this.uploadForm.category,knowledge_project_id:this.reuploadContext?.project_id??this.uploadTargetProjectId,folder_id:this.reuploadContext?.folder_id??this.uploadTargetFolderId,project:this.uploadForm.project});
    },
    departmentActive() { return this.currentCollection==='library' && !!this.departmentFilter; },
    departmentPage() { return this.departmentActive && this.departmentFilter!=='unassigned'; },
    departmentName() { return this.departmentFilter==='unassigned'?'待归类':this.departmentOptions.find(item=>item.id===this.departmentFilter)?.label || ''; },
    chatDepartmentName() { const departments=[...new Set(this.selectedDocuments.map(doc=>this.itemDepartment(doc)))];return this.chatCollection==='library'&&departments.length===1&&departments[0]?this.departmentLabel(departments[0]):''; },

    selectionCount() { return this.selectedIds.length + this.selectedProjectIds.length + this.selectedFolderIds.length; },
    selectionSummary() { return [this.selectedProjectIds.length && this.selectedProjectIds.length + ' 个项目', this.selectedFolderIds.length && this.selectedFolderIds.length + ' 个目录', this.selectedIds.length && this.selectedIds.length + ' 份文件'].filter(Boolean).join('、'); },
    returnLocationLabel() { return this.returnLocation?.label || '资料位置'; },
    uploadTargetProject() { return this.projectDirectories.find(p => p.id === this.uploadTargetProjectId) || null; },
    uploadTargetProjects() { return this.collectionProjects.filter(p => p.can_manage); },
    moveTargetProjects() { return this.projectDirectories.filter(p => p.can_manage && this.caseCategories.includes(p.category) === this.caseCategories.includes(this.moveDoc?.category)); },
    chatSuggestions() { return this.chatCollection === 'experience' ? ['查找类似场景的实践经验，说明适用条件和注意事项', '把这些复盘整理成可以复用的步骤，并标明依据', '根据照片、手稿的识别文字和音视频说明，总结已记录的经验与待确认事项'] : this.suggestions; },
    readerMatches() { const q=this.normalizeReaderText(this.readerSearchQuery);return q?(this.selectedDoc?.references||[]).filter(ref=>this.normalizeReaderText(ref.text).includes(q)):[]; },
    searchDocumentIds() { return this.filteredDocuments.filter(doc => doc.can_read && doc.state === 'ready' && doc.is_current !== 0).map(doc => doc.id); },
    chatCollection() { return ['experience','my-experience'].includes(this.chatScope) ? 'experience' : 'library'; },
    currentCollection() { return this.mode === 'cases' ? 'experience' : this.mode === 'chat' ? this.chatCollection : 'library'; },
    collectionDocuments() { return this.documents.filter(doc => this.caseCategories.includes(doc.category) === (this.currentCollection === 'experience') && (!this.departmentActive || this.inDepartment(doc))); },
    collectionProjects() { return this.projectDirectories.filter(project => this.caseCategories.includes(project.category) === (this.currentCollection === 'experience') && (!this.departmentActive || this.inDepartment(project))); },
    libraryCount() { return this.documents.filter(doc => !this.caseCategories.includes(doc.category)).length; },
    collectionMineCount() { return this.collectionProjects.filter(project => project.owner === this.service.username).length; },
    collectionMineDocumentCount() { return this.collectionDocuments.filter(doc => doc.is_owner).length; },
    collectionFavoritesCount() { return this.collectionDocuments.filter(doc => this.favorites.includes(doc.id)).length; },
    myExperienceNotes() { return this.noteDrafts.filter(note=>this.projectDirectories.some(p=>p.id===note.project_id&&p.owner===this.service.username&&this.caseCategories.includes(p.category))); },
    myExperienceCount() { const ids=new Set(this.myExperienceNotes.map(note=>note.id));return this.myExperienceNotes.length+this.collectionDocuments.filter(doc=>doc.is_owner&&(!doc.note_id||!ids.has(doc.note_id))).length; },
    publishedNoteDocuments() { return Object.fromEntries(this.collectionDocuments.filter(doc=>doc.note_id&&doc.can_read&&doc.is_current!==0).map(doc=>[doc.note_id,doc])); },
    visibleNoteDrafts() {
      if(this.currentCollection!=='experience'||this.favoritesOnly)return [];
      const keyword=this.query.trim().toLowerCase();return (this.mineOnly?this.myExperienceNotes:this.noteDrafts).filter(note=>(this.category==='全部资料'||this.projectDirectories.some(p=>p.id===note.project_id&&p.category===this.category))&&(!this.activeProjectId||note.project_id===this.activeProjectId&&(this.directorySearchActive?this.directoryFolderScope.has(note.folder_id||''):(note.folder_id||'')===this.activeFolderId))&&(!this.statusFilter||this.statusFilter==='failed'&&note.index_state==='failed')&&(!keyword||note.title.toLowerCase().includes(keyword)));
    },
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
    directoryFolderScope() {
      const children=new Map();for(const folder of this.projectFolders)if(folder.project_id===this.activeProjectId){if(!children.has(folder.parent_id))children.set(folder.parent_id,[]);children.get(folder.parent_id).push(folder.id);}
      const ids=new Set(),pending=[this.activeFolderId||''];while(pending.length){const id=pending.pop();if(ids.has(id))continue;ids.add(id);pending.push(...(children.get(id)||[]));}return ids;
    },
    visibleFolders() {
      if(!this.activeProjectId||this.tagFilter||this.dateFrom||this.dateTo||this.statusFilter||this.reviewFilter||this.favoritesOnly)return [];
      const keyword=this.query.trim().toLowerCase();return this.projectFolders.filter(folder=>folder.project_id===this.activeProjectId&&(keyword?folder.id!==this.activeFolderId&&this.directoryFolderScope.has(folder.id)&&folder.name.toLowerCase().includes(keyword):folder.parent_id===this.activeFolderId));
    },
    visibleProjectDirectories() {
      const query = this.query.trim().toLowerCase();
      return this.projectDirectories.filter(project =>
        (!this.departmentActive || this.inDepartment(project)) &&
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
    libraryView() { return { fixedDepartmentContext: this.fixedDepartmentContext, departmentFilter: this.departmentFilter, chatCollection: this.chatCollection, projectDisplay: this.projectDisplay, activeProjectId: this.activeProjectId, activeFolderId: this.activeFolderId, libraryLayout: this.libraryLayout, tagFilter: this.tagFilter, dateFrom: this.dateFrom, dateTo: this.dateTo, dateField: this.dateField, libraryPage: this.libraryPage, libraryPageSize: this.libraryPageSize, sortOrder: this.sortOrder, mode: this.mode, category: this.category, query: this.query, projectFilter: this.projectFilter, industryFilter: this.industryFilter, statusFilter: this.statusFilter, reviewFilter: this.reviewFilter, favoritesOnly: this.favoritesOnly, mineOnly: this.mineOnly }; },
    activeFilterLabel() { return [this.tagFilter && '标签：' + this.tagFilter, (this.dateFrom || this.dateTo) && (this.dateField === 'created_at' ? '上传' : '更新') + '：' + (this.dateFrom || '不限') + ' 至 ' + (this.dateTo || '不限'), this.mineOnly && (this.currentCollection==='experience'?'我的笔记':'我的项目'), this.query && '搜索：' + this.query, this.projectFilter, this.industryFilter, this.statusFilter && '状态：' + ({ready:'可检索',queued:'等待处理',uploading:'上传中',parsing:'解析中',indexing:'索引中',failed:'处理失败'}[this.statusFilter] || this.statusFilter), this.reviewFilter, this.favoritesOnly && '仅收藏'].filter(Boolean).join(' · '); },
    uploadSummary() { const rows = this.uploadDisplayResults; const ready = rows.filter(row => row.phase === 'ready').length; const archived = rows.filter(row => row.phase === 'archived').length; const failed = rows.filter(row => !row.id || row.phase === 'failed').length; const pending = rows.length - ready - archived - failed; return [ready && ready + ' 份资料已可检索', archived && archived + ' 份音视频已归档，可播放与下载', pending && pending + ' 份后台处理中', failed && failed + ' 份失败，请查看下方详情'].filter(Boolean).join('；'); },
    visibleCategories() { return this.mode === 'cases' ? ['全部资料', ...this.caseCategories] : this.categories.filter(item => !this.caseCategories.includes(item)); },
    caseCount() { return this.documents.filter(doc => this.caseCategories.includes(doc.category)).length; },
    tagOptions() { return [...new Set([...this.collectionDocuments.filter(doc => doc.can_read).flatMap(doc => doc.tags || []), ...this.collectionProjects.flatMap(project => project.tags || [])])].sort((a,b) => a.localeCompare(b, 'zh-CN')); },
    formTags() { return this.parseTags(this.uploadForm.tagsText); },
    documents() { return this.cloudDocuments.map(doc => ({ ...doc, summary: [doc.industry, doc.review, doc.status_message].filter(Boolean).join(' · '), date: doc.modified_at ? new Date(doc.modified_at).toLocaleDateString('zh-CN') : '' })); },
    filteredDocuments() {
      const keyword = this.query.trim().toLowerCase();
      return this.documents.filter(doc =>
        (!this.departmentActive || this.inDepartment(doc)) &&
        (!this.showingProjects || (doc.is_root && !doc.knowledge_project_id)) &&
        (!this.activeProjectId || doc.knowledge_project_id === this.activeProjectId) &&
        (!this.activeProjectId || (this.directorySearchActive ? this.directoryFolderScope.has(doc.folder_id || '') : (doc.folder_id || '') === this.activeFolderId)) &&
        (this.caseCategories.includes(doc.category) === (this.currentCollection === 'experience')) &&
        (!this.tagFilter || (doc.tags || []).includes(this.tagFilter)) &&
        (!this.dateFrom && !this.dateTo || this.documentInDateRange(doc)) &&
        (this.category === '全部资料' || doc.category === this.category) &&
        (!this.projectFilter || (doc.project || '未归类项目') === this.projectFilter) &&
        (!this.industryFilter || doc.industry === this.industryFilter) &&
        (!this.statusFilter || doc.state === this.statusFilter) &&
        (!this.reviewFilter || doc.review === this.reviewFilter) &&
        (!this.mineOnly || doc.is_owner) &&
        (!(this.mineOnly&&this.currentCollection==='experience'&&doc.note_id&&this.myExperienceNotes.some(note=>note.id===doc.note_id))) &&
        (!this.favoritesOnly || this.favorites.includes(doc.id)) &&
        (!keyword || this.searchMode === 'content' || [doc.title, doc.summary, doc.project, doc.format, doc.description, ...(doc.tags || [])].join(' ').toLowerCase().includes(keyword)));
    },
    sortedDocuments() { return [...this.filteredDocuments].sort((a, b) => this.sortOrder === 'title' ? a.title.localeCompare(b.title, 'zh-CN') : (Date.parse(b.modified_at) || 0) - (Date.parse(a.modified_at) || 0)); },
    libraryRows() {
      const notes=this.showingProjects?[]:this.visibleNoteDrafts;
      const ids=new Set(notes.map(note=>note.id));
      const rows=notes.map(note=>({kind:'note',id:note.id,title:note.title,modified_at:note.updated_at,note,document:this.publishedNoteDocuments[note.id],project:this.projectDirectories.find(project=>project.id===note.project_id)}));
      rows.push(...this.filteredDocuments.filter(doc=>!doc.note_id||!ids.has(doc.note_id)).map(doc=>({kind:'file',id:doc.id,title:doc.title,modified_at:doc.modified_at,document:doc})));
      rows.sort((a,b)=>this.sortOrder==='title'?a.title.localeCompare(b.title,'zh-CN'):(Date.parse(b.modified_at)||0)-(Date.parse(a.modified_at)||0));
      return this.showingProjects ? [...this.visibleProjectDirectories.map(project=>({kind:'project',id:project.id,project})),...rows] : rows;
    },
    libraryFilterKey() { return JSON.stringify([this.departmentFilter, this.activeProjectId, this.activeFolderId, this.mode === 'cases', this.searchMode, this.tagFilter, this.dateFrom, this.dateTo, this.dateField, this.category, this.query, this.projectFilter, this.industryFilter, this.statusFilter, this.reviewFilter, this.favoritesOnly, this.mineOnly, this.recentUploadIds, this.sortOrder, this.libraryPageSize]); },
    libraryPageCount() { return Math.max(1, Math.ceil(this.libraryRows.length / this.libraryPageSize)); },
    currentLibraryPage() { return Math.min(Math.max(1, this.libraryPage), this.libraryPageCount); },
    pagedProjectDirectories() { return this.pagedLibraryRows.filter(row=>row.kind==='project').map(row=>row.project); },
    pagedDocuments() { if(this.showingProjects)return this.pagedLibraryRows.filter(row=>row.kind==='file').map(row=>row.document);const start = (this.currentLibraryPage - 1) * this.libraryPageSize; return this.sortedDocuments.slice(start, start + this.libraryPageSize); },
    pagedLibraryRows() { const start=(this.currentLibraryPage-1)*this.libraryPageSize;return this.libraryRows.slice(start,start+this.libraryPageSize); },
    libraryPageRange() { const total = this.libraryRows.length; const start = total ? (this.currentLibraryPage - 1) * this.libraryPageSize + 1 : 0; return { start, end: Math.min(this.currentLibraryPage * this.libraryPageSize, total), total }; },
    libraryPageNumbers() { const start = Math.max(1, Math.min(this.currentLibraryPage - 2, this.libraryPageCount - 4)); return Array.from({ length: Math.min(5, this.libraryPageCount) }, (_, index) => start + index); },
    readableDocuments() { return this.collectionDocuments.filter(doc => doc.can_read); },
    advancedFilterCount() { return [this.dateFrom || this.dateTo].filter(Boolean).length; },
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
    failedCount() { const docs=this.collectionDocuments.filter(doc=>doc.state==='failed');const ids=new Set(docs.map(doc=>doc.note_id).filter(Boolean));return docs.length+(this.currentCollection==='experience'?this.noteDrafts.filter(note=>note.index_state==='failed'&&!ids.has(note.id)).length:0); },
    scopeLabel() { const label = this.chatCollection === 'experience' ? '经验沉淀' : '总资料库' + (this.chatDepartmentName ? ' · '+this.chatDepartmentName : ''); return this.selectedIds.length ? label + ' · 选中 ' + this.selectedIds.length + ' 份资料' : ['my-projects','my-experience'].includes(this.chatScope) ? label + (this.chatScope==='my-experience'?' · 我的笔记':' · 我的项目') : label + ' · 全部可访问资料'; },
    selectedDocuments() { return this.documents.filter(doc => doc.can_read && this.selectedIds.includes(doc.id)); },
    myProjectMaxCount() { return Math.max(1, ...this.myProjects.projects.map(project => project.document_count || 0)); },
    pendingAccessCount() { return this.accessRequests.filter(request => request.status === 'pending').length; },
    uploadDisplayResults() {
      const documents = new Map(this.cloudDocuments.map(doc => [doc.id, doc]));
      return this.uploadResults.map(item => {
        const doc = documents.get(item.id);
        return doc ? { ...item, document:doc, state: doc.label, phase: doc.state, detail: doc.status_message,
          can_retry: doc.can_manage && doc.state === 'failed' && doc.has_original } : item;
      });
    },
    canAsk() { return this.service.configured && this.service.access_allowed; },
    allReferences() { const references = new Map(); for (const message of this.messages) for (const reference of message.references || []) references.set((reference.document_id || reference.url) + ':' + reference.id, reference); return [...references.values()]; },
  },
  watch: {
    'service.username'() { this.clearFileClipboard(); this.uploadRequestIds.clear(); },
    departmentEntry(value) { if(value)this.openDepartment(value.department); },
    departmentFilter() { this.emitDepartment(); },
    departmentPage() { this.$nextTick(() => this.syncTabIndicator()); },

    activeProjectId(value) { if (value) { for (const key of ['projectFilter','industryFilter','statusFilter','reviewFilter','tagFilter','dateFrom','dateTo']) this[key] = ''; this.advancedFiltersOpen = false; } },
    visibleProjectDirectories(rows) { if ((this.projectPreview.id && !rows.some(row => row.id === this.projectPreview.id)) || (this.projectPreview.pendingId && !rows.some(row => row.id === this.projectPreview.pendingId))) this.dismissProjectPreview(); },
    mode(value) { this.emitDepartment(); this.dismissProjectPreview?.(); this.$nextTick(() => this.syncTabIndicator()); if (value === 'chat') this.scrollChat(); },
    libraryView: { deep: true, handler() { this.saveLibraryView(); } },
    libraryFilterKey() { this.closeFileContext(); this.dismissProjectPreview?.(); this.invalidateContentSearch(); if (!this.restoringView) { this.libraryPage = 1; this.scrollLibraryTop(); } },
    libraryPageCount(count) { if (!this.loading && !this.restoringView && this.libraryPage > count) this.libraryPage = count; },
    readerOpen(open) { if (open) this.dismissProjectPreview?.(); if (!open) { this.readerSequence++; this.readerLoading = false; this.readerOriginalLoading = false; this.releaseReader(); } },
  },
  mounted() { this.installClipboardListeners(); this.installProjectPreviewListeners(); this.restoreTheme(); this.initialWorkspaceLoad=this.loadService(); this.$nextTick(() => { this.syncTabIndicator(); if (typeof ResizeObserver !== 'undefined') { this.tabObserver = new ResizeObserver(() => this.syncTabIndicator()); this.tabObserver.observe(this.$el.querySelector('.ckb-tabs')); } }); this.pollClock = setInterval(() => { if (this.canAsk && !document.hidden && (this.pendingCount || !this.lastCataloguePoll || Date.now() - this.lastCataloguePoll > 29000)) { this.lastCataloguePoll = Date.now(); this.loadDocuments(false, false); this.loadAccessRequests(); this.loadMyProjects(); } }, 6000); },
  beforeUnmount() { this.uploadStopped=true;if(this.uploadCurrent&&!this.uploadCurrent.saving)this.uploadXHR?.abort();if(typeof window!=='undefined')window.removeEventListener('beforeunload',this.uploadLeaveGuard);this.uninstallProjectPreviewListeners(); document.removeEventListener?.('pointerdown',this.fileContextCloser); if(typeof window!=='undefined')window.removeEventListener?.('resize',this.fileContextCloser); this.clearFileClipboard?.(); this.contentController?.abort(); this.searchSequence++; this.tabObserver?.disconnect(); clearTimeout(this.directoryTimer); if (typeof document !== 'undefined' && document.documentElement) delete document.documentElement.dataset.knowledgeTheme; this.chatDisposed = true; this.chatGeneration++; this.requestsActive = false; this.cancelPendingReads(); this.controller?.abort(); clearInterval(this.activityClock); clearInterval(this.pollClock); this.releaseReader(); },
  methods: {
    displayDocumentTitle(doc) { return doc?.display_title || doc?.title || ''; },
    canClipboardDocument(doc) { return !!doc?.can_manage && !!doc.can_read && !!doc.has_original && !doc.note_id && !doc.research_project_id && !['queued','uploading','parsing','indexing','deleting','deleted'].includes(doc.state); },
    fileRequestId() { return typeof crypto!=='undefined' && crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36)+'-'+Math.random().toString(36).slice(2); },
    putFileClipboard(doc, action) {
      if(!this.canClipboardDocument(doc))return;
      this.fileClipboard={id:doc.id,title:this.displayDocumentTitle(doc),action,modified_at:doc.modified_at,username:this.service.username};this.pasteRequest=null;
      this.closeFileContext();ElementPlus.ElMessage.info((action==='cut'?'已剪切标记':'已复制')+'，请进入目标目录后粘贴。');
    },
    clearFileClipboard() { this.fileClipboard=null;this.pasteRequest=null;this.closeFileContext(); },
    openFileContext(doc,event) {
      if(event.target?.closest?.('input,textarea,select,[contenteditable="true"]'))return;
      event.preventDefault();event.stopPropagation();this.fileContextAnchor=event.currentTarget;
      const box=event.currentTarget?.getBoundingClientRect?.();
      const x=event.clientX || box?.left || 12,y=event.clientY || box?.bottom || 12;
      this.fileContext={doc:doc||null,x:Math.max(8,Math.min(x,window.innerWidth-204)),y:Math.max(8,Math.min(y,window.innerHeight-244))};
      this.$nextTick(()=>this.$refs.fileContextMenu?.querySelector('button:not([disabled])')?.focus());
    },
    closeFileContext(restore=false) { this.fileContext=null;if(restore)this.fileContextAnchor?.focus?.({preventScroll:true}); },
    fileContextKey(event) {
      if(event.key==='Escape'){event.preventDefault();this.closeFileContext(true);return;}
      if(event.key==='Tab'){this.closeFileContext();return;}
      if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
      event.preventDefault();const buttons=[...this.$refs.fileContextMenu.querySelectorAll('button:not([disabled])')];if(!buttons.length)return;
      const index=buttons.indexOf(document.activeElement);buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();
    },
    fileRowKey(doc,event) {
      if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){this.openFileContext(doc,event);return;}
      if(event.target?.closest?.('input,textarea,select,[contenteditable="true"]')||window.getSelection()?.toString())return;
      if((event.ctrlKey||event.metaKey)&&['c','x'].includes(event.key.toLowerCase())&&this.canClipboardDocument(doc)){
        event.preventDefault();event.stopPropagation();this.putFileClipboard(doc,event.key.toLowerCase()==='x'?'cut':'copy');
      }
    },
    directoryFileKey(event) {
      if(event.target?.closest?.('input,textarea,select,[contenteditable="true"]'))return;
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='v'&&this.canPasteFiles){event.preventDefault();this.pasteFile();}
    },
    directoryFileContext(event) { if(!event.defaultPrevented && !event.target?.closest?.('button,a,input,textarea,select,[data-project-id],[data-folder-id],.ckb-directory-card'))this.openFileContext(null,event); },
    installClipboardListeners() {
      this.fileContextCloser=event=>{if(!event.target?.closest?.('.ckb-file-context-menu'))this.closeFileContext();};
      document.addEventListener('pointerdown',this.fileContextCloser);window.addEventListener('resize',this.fileContextCloser);
    },
    async pasteFile() {
      if(!this.canPasteFiles)return;
      const clipboard={...this.fileClipboard};
      if(clipboard.username!==this.service.username){this.clearFileClipboard();return;}
      const target={project_id:this.activeProjectId||'',folder_id:this.activeProjectId?(this.activeFolderId||''):''};
      const destination=JSON.stringify([clipboard.id,clipboard.action,target]);
      if(this.pasteRequest?.destination!==destination)this.pasteRequest={destination,id:this.fileRequestId()};
      const action=clipboard.action==='cut'?'move':'copy',path='/company-knowledge/documents/'+encodeURIComponent(clipboard.id);
      const payload={...target,request_id:this.pasteRequest.id,expected_modified_at:clipboard.modified_at};
      this.clipboardBusy=true;this.closeFileContext();
      try {
        const previewResponse=await this.apiFetch(path+'/'+action+'-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const preview=await previewResponse.json();if(!previewResponse.ok)throw Error(preview.detail||'无法检查目标目录');
        if(!preview.completed && preview.no_change){ElementPlus.ElMessage.info('文件已在当前目录。');return;}
        if(!preview.completed && preview.access_changes){
          try{await ElementPlus.ElMessageBox.confirm('当前权限：'+preview.before_access+'\n目标权限：'+preview.after_access+'\n'+preview.permission_note,'确认文件权限变化',{confirmButtonText:'确认粘贴',cancelButtonText:'取消',type:'warning',closeOnClickModal:false});}catch{return;}
        }
        let result=preview.result;
        if(!preview.completed){const response=await this.apiFetch(path+'/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,confirmation:preview.confirmation})});result=await response.json();if(!response.ok)throw Error(result.detail||'粘贴失败');}
        this.catalogueMutation++;this.pasteRequest=null;if(clipboard.action==='cut'){this.fileClipboard=null;this.selectedIds=[];}
        await Promise.all([this.loadDocuments(),this.loadMyProjects()]);
        ElementPlus.ElMessage.success(clipboard.action==='cut'?'文件及历史版本已移动。':'已复制为“'+this.displayDocumentTitle(result.document)+'”。'+(result.document.state==='queued'?'正在建立检索索引。':''));
      }catch(error){ElementPlus.ElMessage.error(error.message);}finally{this.clipboardBusy=false;}
    },
    async showFileVersions(doc) {
      this.closeFileContext();this.versionOpen=true;this.versionLoading=true;this.versionRows=[];this.versionError='';this.versionTitle=doc.title;
      const sequence=++this.versionSequence;
      try{
        const response=await this.apiFetch('/company-knowledge/documents/'+encodeURIComponent(doc.id)+'/versions');const result=await response.json();if(!response.ok)throw Error(result.detail||'版本加载失败');
        if(sequence===this.versionSequence)this.versionRows=result.versions;
      }catch(error){if(sequence===this.versionSequence)this.versionError=error.message;}finally{if(sequence===this.versionSequence)this.versionLoading=false;}
    },
    departmentLabel(value) { return this.departmentOptions.find(item=>item.id===value)?.label || '待归类'; },
    itemDepartment(item) { return item.department || this.projectDirectories.find(project=>project.id===item.knowledge_project_id)?.department || ''; },
    inDepartment(item) { return this.itemDepartment(item)===(this.departmentFilter==='unassigned'?'':this.departmentFilter); },
    emitDepartment() { this.$emit?.('department-change', ['library','chat'].includes(this.mode)&&this.currentCollection==='library'?this.departmentFilter:''); },
    setDepartmentFilter(value) {
      if(this.busy){ElementPlus.ElMessage.info('请先停止当前回答，再切换部门资料。');return;}
      if(value && value!=='unassigned'&&!this.departmentOptions.some(item=>item.id===value))return;
      this.selectionSequence++;this.selectionBusy=false;this.showProjectRoot();this.departmentFilter=value;this.clearSelection();this.newConversation();this.emitDepartment();
    },
    openDepartment(value) {
      if(this.busy){ElementPlus.ElMessage.info('请先停止当前回答，再切换部门资料。');return;}
      this.departmentEntryApplied=true;this.browseLibrary();this.fixedDepartmentContext=true;this.setDepartmentFilter(value);
    },
    openChat() { if(this.mode==='chat')return;if(this.currentCollection==='library'&&this.departmentFilter){this.askLibrary();return;}this.mode='chat'; },
    async openRecycle(page=1) {
      this.recycleOpen=true; this.recycleLoading=true; this.recycleError=''; this.recyclePage=page;
      try { const response=await this.apiFetch('/company-knowledge/recycle-bin?page='+page); const data=await response.json(); if(!response.ok)throw Error(data.detail||'回收站加载失败'); this.recycleItems=data.items; this.recycleTotal=data.total; }
      catch(error){this.recycleError=error.message;} finally {this.recycleLoading=false;}
    },
    async restoreRecycle(item) {
      if(this.recycleBusy)return;
      try {await ElementPlus.ElMessageBox.confirm('恢复《'+item.title+'》及本次一同删除的资料？文件恢复后会重新建立检索索引。','恢复资料',{confirmButtonText:'恢复',cancelButtonText:'取消',type:'info'});}catch{return;}
      this.recycleBusy=item.id; this.recycleError='';
      try {const response=await this.apiFetch('/company-knowledge/recycle-bin/'+encodeURIComponent(item.id)+'/restore',{method:'POST'});const data=await response.json();if(!response.ok)throw Error(data.detail||'恢复失败');this.catalogueMutation++;await Promise.all([this.openRecycle(this.recyclePage),this.loadProjectDirectories(),this.loadDocuments(),this.loadMyProjects(),this.loadNotes()]);ElementPlus.ElMessage.success('已恢复，检索索引将在后台更新。');for(const notice of data.notices||[])ElementPlus.ElMessage.warning(notice);}
      catch(error){this.recycleError=error.message;}finally{this.recycleBusy='';}
    },

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
    openFromDoubleClick(project,event,folderId='') { if(!event.target.closest('button,input,a,textarea,select')){this.dismissProjectPreview();this.openDirectory(project,folderId);} },
    openFileFromDoubleClick(doc,event) { if(!event.target.closest('button,input,a,textarea,select,.el-dropdown'))this.openDocument(doc); },
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
      const choosingUpload = this.uploadOpen && !this.quickCapture;
      return {mode:this.mode, project_id:(choosingUpload ? this.uploadTargetProjectId : this.activeProjectId) || '', folder_id:(choosingUpload ? this.uploadTargetFolderId : this.activeFolderId) || '',
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
      const id = this.selectedDoc.id, sequence = this.readerSequence; this.locating = true; this.readerMode = 'original'; this.readerOriginalFind = reference.text || '';
      if(reference.text && !(this.selectedDoc.references || []).some(ref=>ref.text===reference.text))this.selectedDoc.references=[reference,...(this.selectedDoc.references || [])];
      if(!this.selectedDoc.has_original){this.locating=false;this.readerMode='excerpts';this.readerLocation={message:'历史资料未归档原件，请核对引用片段。'};return;}
      if(this.selectedDoc.media_kind){this.locating=false;this.readerLocation={message:'这条引用来自人工文字说明，音视频未自动转写。'};return;}
      if(this.readerSheet){this.locating=false;this.readerMode='excerpts';this.readerLocation={message:'表格按工作表和行号阅读，来源页码不能直接换算成行号，请核对解析片段。'};return;}
      if(['TXT','MD','CSV'].includes(this.selectedDoc.format)){this.locating=false;this.readerLocation={message:'正在原文中匹配引用文字…'};this.$nextTick(()=>this.$refs.nativeReader?.findSource());return;}
      try { const response=await this.apiFetch('/company-knowledge/documents/'+encodeURIComponent(id)+'/locate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:(reference.text || '').slice(0,10000),pages:(reference.pages || []).map(Number).filter(n=>Number.isInteger(n)&&n>0)})}); const result=await response.json(); if(!response.ok)throw Error(result.detail || '来源定位失败'); if(this.readerOpen&&this.selectedDoc?.id===id&&this.readerSequence===sequence) this.readerLocation=result; }
      catch(error) { if(this.readerOpen&&this.selectedDoc?.id===id&&this.readerSequence===sequence)this.readerLocation={message:error.message}; }
      finally { if(this.readerSequence===sequence)this.locating=false; }
    },
    normalizeReaderText(text) { return String(text||'').normalize('NFKC').replace(/\s/g,'').toLocaleLowerCase(); },
    readerParts(text) {
      const value=String(text||''),needle=this.normalizeReaderText(this.readerSearchQuery);if(!needle)return [{text:value,match:false}];
      let compact='',offset=0;const positions=[];
      for(const char of value){const normalized=this.normalizeReaderText(char);for(const c of normalized){compact+=c;positions.push([offset,offset+char.length]);}offset+=char.length;}
      const parts=[];let cursor=0,index=0,count=0;
      while(count++<200&&(index=compact.indexOf(needle,index))>=0){const start=positions[index]?.[0],end=positions[index+needle.length-1]?.[1];if(start===undefined||end===undefined)break;parts.push({text:value.slice(cursor,start),match:false},{text:value.slice(start,end),match:true});cursor=end;index+=needle.length;}
      parts.push({text:value.slice(cursor),match:false});return parts;
    },
    referenceMatches(reference) { return !!this.readerSearchQuery&&this.normalizeReaderText(reference.text).includes(this.normalizeReaderText(this.readerSearchQuery)); },
    moveReaderMatch(delta=0) { const count=this.readerMatches.length;if(!count)return;this.readerSearchIndex=(this.readerSearchIndex+delta+count)%count;this.$nextTick?.(()=>(this.$refs.excerptReader?.querySelectorAll('.ckb-reader-hit')[this.readerSearchIndex]||this.$refs.mediaDescription?.querySelector('mark'))?.scrollIntoView({block:'center'})); },
    showReference(reference,query='') {
      if(reference.text&&!(this.selectedDoc.references||[]).some(ref=>ref.text===reference.text))this.selectedDoc.references=[{...reference,id:'引用 '+reference.id},...(this.selectedDoc.references||[])];
      this.readerLocation=null;this.readerMode='excerpts';this.readerSearchQuery=query||reference.text||'';this.readerSearchIndex=0;this.moveReaderMatch();
    },
    async findInReader() {
      const query=this.readerFind.trim();if(!query||!this.selectedDoc||this.locating||this.readerLoading)return;
      const id=this.selectedDoc.id,sequence=this.readerSequence;const current=()=>this.readerOpen&&this.selectedDoc?.id===id&&this.readerSequence===sequence&&this.readerFind.trim()===query;
      this.locating=true;this.readerLocation=null;this.readerMode='excerpts';this.readerSearchQuery=query;this.readerSearchIndex=0;this.readerExcerptError='';this.readerSearchStatus='正在搜索解析文字…';
      try {
        let pages=0;
        while(current()&&(this.readerHasMore||this.readerTotal>(this.selectedDoc.references||[]).length)&&pages++<100){const before=this.previewPage;await this.morePreview();if(before===this.previewPage)break;}
        if(!current())return;
        const incomplete=this.readerHasMore||this.readerTotal>(this.selectedDoc.references||[]).length;
        this.readerSearchStatus=(this.readerMatches.length?'命中 '+this.readerMatches.length+' 个片段':'当前解析文字未找到匹配')+(incomplete?'；尚未加载全部，可继续查找。':'；已检查全部可用解析片段。');this.moveReaderMatch();
      }finally{if(this.readerSequence===sequence)this.locating=false;}
    },
    openQuickCapture() { if(this.uploadBusy){this.uploadOpen=true;return;} this.reuploadContext=null;this.quickCapture=true; this.captureTitle=''; this.captureScene=''; this.captureMethod=''; this.uploadForm={project:'',industry:'',category:'项目经验',review:'待复核',confidentiality:'internal',visibility:'members',readersText:'',tagsText:'',description:''}; this.stagedFiles=[];this.uploadResults=[];this.uploadError='';this.uploadOpen=true; },
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
    async deleteRichNote(id) {
      if(this.noteDeleting)return;this.noteDeleting=true;
      try {
        const response=await this.apiFetch('/company-knowledge/notes/'+encodeURIComponent(id)+'/deletion-preview');const preview=await response.json();if(!response.ok)throw Error(preview.detail||'笔记删除范围加载失败');
        try{await ElementPlus.ElMessageBox.confirm('确定删除图文笔记“'+preview.title+'”？将同时移除草稿、'+preview.publication_count+' 个发布版本及 '+preview.image_count+' 张配图。删除后可在回收站恢复，10 天后自动清理本地原件。','删除图文笔记',{type:'warning',confirmButtonText:'确认删除笔记',cancelButtonText:'取消',closeOnClickModal:false});}catch{return;}
        const deleted=await this.apiFetch('/company-knowledge/notes/'+encodeURIComponent(id),{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:preview.confirmation})});const result=await deleted.json();if(!deleted.ok)throw Error(result.detail||'笔记删除失败');
        if(this.noteEditorId===id)this.noteEditorId='';if(this.selectedDoc?.note_id===id)this.readerOpen=false;
        try{localStorage.removeItem('knowledgeNoteRecovery:'+this.service.username+':'+id);}catch{}
        this.catalogueMutation++;await Promise.all([this.loadDocuments(),this.loadNotes(),this.loadMyProjects()]);ElementPlus.ElMessage.success('图文笔记及其发布版本已删除。');
      }catch(error){ElementPlus.ElMessage.error(error.message);}finally{this.noteDeleting=false;}
    },
    editRichNote(id) { this.readerOpen=false;this.noteEditorId=id; },
    noteChanged() {this.loadNotes();this.loadDocuments();},
    async captureProject() {
      const name='随手记录 · 待整理'; let project=this.projectDirectories.find(p=>p.name===name&&p.owner===this.service.username&&this.caseCategories.includes(p.category));
      if(project)return project.id;
      const response=await this.apiFetch('/company-knowledge/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,category:'项目经验',industry:'',tags:['待整理'],description:'照片、手稿、录音与实践记录的临时归档空间。',review:'待复核',confidentiality:'internal',visibility:'members',readers:[]})});
      const result=await response.json(); if(!response.ok) { if(response.status===409){await this.loadProjectDirectories();project=this.projectDirectories.find(p=>p.name===name&&p.owner===this.service.username&&this.caseCategories.includes(p.category));if(project)return project.id;} throw Error(result.detail || '待整理空间创建失败'); } return result.id;
    },
    activateChatCollection(collection) { if (this.busy || this.chatCollection === collection) return; this.newConversation(); this.selectedIds = []; this.selectedProjectIds=[];this.selectedFolderIds=[]; this.chatSessions = []; this.chatScope = collection === 'experience' ? 'experience' : 'accessible'; this.loadChatHistory(); },
    openHome() {
      if(this.busy){ElementPlus.ElMessage.info('请先停止当前回答，再切换知识库页面。');return;}
      this.departmentEntryApplied=true;this.fixedDepartmentContext=false;this.newConversation();this.showProjectRoot();this.departmentFilter='';
      this.selectedIds=[];this.selectedProjectIds=[];this.selectedFolderIds=[];this.chatScope='accessible';this.mode='home';this.emitDepartment();this.refreshChatSessions();
    },
    syncTabIndicator() { const tabs = this.$el?.querySelector('.ckb-tabs'), active = tabs?.querySelector('[aria-selected="true"]'); if (!active) return; const parent = tabs.getBoundingClientRect(), rect = active.getBoundingClientRect(); this.tabIndicatorStyle = { width: rect.width + 'px', transform: 'translateX(' + (rect.left - parent.left + tabs.scrollLeft) + 'px)', opacity: 1 }; },
    navigateTabs(event) { if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; const tabs = [...event.currentTarget.querySelectorAll('[role="tab"]')], index = tabs.indexOf(document.activeElement); if (index < 0) return; event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length; tabs[next].focus(); tabs[next].click(); },
    async openAudit(scope = {}) { this.auditScope = scope; this.auditPage = 1; this.auditEvents = []; this.auditOpen = true; await this.loadAudit(); },
    async loadAudit() {
      const sequence = ++this.auditSequence; this.auditLoading = true; this.auditError = '';
      try { const query = new URLSearchParams({ ...this.auditScope, page: String(this.auditPage) }); const response = await this.apiFetch('/company-knowledge/audit-events?' + query); const data = await response.json(); if (!response.ok) throw new Error(data.detail || '操作记录加载失败'); if (sequence !== this.auditSequence) return; this.auditEvents = data.events || []; this.auditTotal = data.total || 0; }
      catch (error) { if (sequence === this.auditSequence) this.auditError = error.message; }
      finally { if (sequence === this.auditSequence) this.auditLoading = false; }
    },
    auditAction(action) { return ({'project.create':'创建项目','project.update':'修改项目','project.delete':'删除项目','folder.create':'创建目录','folder.update':'修改目录','folder.delete':'删除目录','document.move':'移动文件','document.upload':'上传文件','document.update':'修改文件信息','document.inherit':'同步项目属性','document.retry':'重试处理','document.access_decision':'权限审批','document.delete':'删除文件','document.download':'下载文件','document.preview':'预览文件','document.export_failed':'水印导出失败'})[action] || action; },
    auditField(field) { return ({name:'项目/目录名称',title:'文件名称',industry:'行业',category:'分类',review:'复核状态',confidentiality:'保密等级',visibility:'授权范围',readers:'指定成员',tags:'标签',description:'说明',knowledge_project_id:'所属项目 ID',is_root:'根目录文件',inherits_project:'继承项目属性',owner:'归属账号',folder_id:'归档目录 ID',parent_id:'上级目录 ID',state:'处理状态',version:'版本'})[field] || field; },
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
        try {await ElementPlus.ElMessageBox.confirm('确定删除项目“'+preview.name+'”？将同时移除 '+preview.document_count+' 份资料（含历史版本）、'+preview.note_count+' 篇图文笔记和 '+preview.folder_count+' 个子目录。删除后可在回收站中恢复，10 天后自动清理本地原件。','删除整个项目',{type:'warning',confirmButtonText:'确认删除整个项目',cancelButtonText:'取消',closeOnClickModal:false});}
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
    documentLocationLabel(doc) { const collection=this.caseCategories.includes(doc.category)?'经验沉淀':'资料库';if(!doc.knowledge_project_id)return collection+' / 根目录（独立文件）';const project=this.projectDirectories.find(p=>p.id===doc.knowledge_project_id);const folder=doc.folder_id&&this.projectFolders.find(f=>f.id===doc.folder_id&&f.project_id===doc.knowledge_project_id);return collection+' / '+(project?.name||doc.project||'项目信息暂未加载')+' / '+(doc.folder_id?(folder?this.folderLabel(folder):'目录信息暂未加载'):'项目根目录'); },
    async openUploadedDocument(item) { const doc=this.cloudDocuments.find(row=>row.id===item.id);if(!doc){ElementPlus.ElMessage.warning('资料状态尚未同步，请刷新后再查看。');return;}this.uploadOpen=false;await this.openDocument(doc); },
    canOpenDocumentDirectory(doc) { return !doc.knowledge_project_id||this.projectDirectories.some(project=>project.id===doc.knowledge_project_id); },
    documentDirectoryReason(doc) { return this.canOpenDocumentDirectory(doc)?'':doc.can_read===false?'你尚无此文件和所在项目的访问权限。':'你拥有此文件阅读权，但没有所在项目的目录权限。'; },
    openDocumentDirectory(doc) { const project=doc.knowledge_project_id&&this.projectDirectories.find(p=>p.id===doc.knowledge_project_id);if(doc.knowledge_project_id&&!project){ElementPlus.ElMessage.warning(this.documentDirectoryReason(doc));return;}this.mode=this.caseCategories.includes(doc.category)?'cases':'library';this.uploadOpen=false;if(project)this.openDirectory(project,doc.folder_id||'');else this.showProjectRoot(); },
    showProjectRoot() { clearTimeout(this.directoryTimer); this.searchMode='metadata'; this.activeProjectId = ''; this.activeFolderId = ''; this.projectDisplay = 'projects'; this.resetFilters(); this.libraryIntent = ''; this.scrollLibraryTop(); },
    showAllFiles() { clearTimeout(this.directoryTimer); this.searchMode='metadata'; this.activeProjectId = ''; this.activeFolderId = ''; this.projectDisplay = 'files'; this.scrollLibraryTop(); },
    openDirectory(project, folderId = '') {
      if (!project || (folderId && !this.projectFolders.some(folder => folder.id === folderId && folder.project_id === project.id))) return;
      clearTimeout(this.directoryTimer); this.dismissProjectPreview?.(); this.searchMode='metadata';
      this.mode=this.caseCategories.includes(project.category)?'cases':'library';if(this.departmentActive && !this.inDepartment(project))this.departmentFilter=project.department||'unassigned'; this.activeProjectId = project.id; this.activeFolderId = folderId;
      this.projectDisplay = 'contents'; this.openingDirectoryId = ''; this.resetFilters(); this.advancedFiltersOpen=false; this.category='全部资料'; this.libraryIntent=''; this.scrollLibraryTop();
    },
    goUpDirectory() { if (!this.activeProject) return this.showProjectRoot(); const folder=this.projectFolders.find(f=>f.id===this.activeFolderId&&f.project_id===this.activeProjectId); if(folder)this.openDirectory(this.activeProject,folder.parent_id||'');else this.showProjectRoot(); },
    startProjectEditor(project = null) {
      this.editingProject = project; this.projectError = '';
      this.projectCreationDepartment=!project&&this.mode!=='cases'&&this.departmentPage?this.departmentFilter:'';
      this.projectForm = { department: project ? project.department || '' : this.departmentFilter==='unassigned'?'':this.departmentFilter, name: project?.name || '', industry: project?.industry || '', category: project?.category || (this.visibleCategories.includes(this.category) && this.category !== '全部资料' ? this.category : this.mode === 'cases' ? '项目经验' : '项目原件'), review: project?.review || '待复核', confidentiality: project?.confidentiality === 'confidential' ? 'secret' : project?.confidentiality || 'internal', visibility: project?.visibility || 'members', readersText: (project?.readers || []).join(', '), tagsText: (project?.tags || []).join('，'), description: project?.description || '' };
      this.projectEditorOpen = true;
    },
    async saveProjectDirectory() {
      if (this.projectSaving) return;
      if(!this.editingProject&&this.projectCreationDepartment)this.projectForm.department=this.projectCreationDepartment;
      if(!this.editingProject&&!this.projectEditorIsCase&&!this.projectForm.department){this.projectError='请选择所属部门／栏目。';return;}
      this.projectSaving = true; this.projectError = '';
      try { const values = { ...this.projectForm, name: this.projectForm.name.trim(), tags: this.parseTags(this.projectForm.tagsText), readers: this.projectForm.readersText.split(/[,，\n]/).map(x => x.trim()).filter(Boolean) }; if (values.confidentiality !== 'internal') values.visibility = 'restricted'; const response = await this.apiFetch('/company-knowledge/projects' + (this.editingProject ? '/' + this.editingProject.id : ''), { method: this.editingProject ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '项目保存失败'); this.projectEditorOpen = false; await this.loadDocuments(); this.departmentFilter=this.mode==='cases'?'':result.department||''; this.activeProjectId = result.id; this.activeFolderId = ''; this.projectDisplay = 'contents'; this.resetFilters(); }
      catch (error) { this.projectError = error.message; }
      finally { this.projectSaving = false; }
    },
    startFolderEditor(folder = null) { if (!this.activeProject?.can_manage) { ElementPlus.ElMessage.info('此项目为只读，仅创建者或管理员可新建目录。'); return; } this.editingFolder = folder; this.folderName = folder?.name || ''; this.folderError = ''; this.folderEditorOpen = true; },
    async saveFolder() {
      if (!this.activeProject?.can_manage || this.folderSaving) return;
      this.folderSaving = true; this.folderError = '';
      try { const response = await this.apiFetch('/company-knowledge/projects/' + this.activeProject.id + '/folders' + (this.editingFolder ? '/' + this.editingFolder.id : ''), { method: this.editingFolder ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: this.folderName, parent_id: this.activeFolderId }) }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '目录保存失败'); this.folderEditorOpen = false; await this.loadProjectDirectories(); }
      catch (error) { this.folderError = error.message; }
      finally { this.folderSaving = false; }
    },
    async deleteEmptyFolder() {
      if(!this.editingFolder||this.folderSaving)return;
      this.folderSaving=true;this.folderError='';
      const url='/company-knowledge/projects/'+encodeURIComponent(this.activeProject.id)+'/folders/'+encodeURIComponent(this.editingFolder.id);
      try {
        const previewResponse=await this.apiFetch(url+'/deletion-preview');
        const preview=await previewResponse.json();if(!previewResponse.ok)throw Error(preview.detail||'无法核对删除范围');
        const message=preview.recyclable
          ? '确认删除目录《'+preview.name+'》及其中的 '+preview.folder_count+' 个子目录、'+preview.document_count+' 份文件（含历史版本）、'+preview.note_count+' 篇笔记或草稿？本次删除的整个目录将进入回收站，保留 10 天，可整体恢复目录结构。'
          : '确认删除空目录《'+preview.name+'》？删除后无法恢复，不会进入回收站。';
        await ElementPlus.ElMessageBox.confirm(message,preview.recyclable?'删除目录及内容':'删除空目录',{confirmButtonText:preview.recyclable?'移入回收站':'删除目录',cancelButtonText:'取消',type:'warning'});
        const response=await this.apiFetch(url,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:preview.confirmation})});
        const result=await response.json();if(!response.ok)throw Error(result.detail||'删除目录失败');
        this.folderEditorOpen=false;this.catalogueMutation++;
        await Promise.all([this.loadProjectDirectories(),this.loadDocuments(),this.loadNotes(),this.loadMyProjects()]);
        this.selectedFolderIds=this.selectedFolderIds.filter(id=>this.projectFolders.some(folder=>folder.id===id));
        this.selectedIds=this.selectedIds.filter(id=>this.documents.some(doc=>doc.id===id&&doc.state!=='deleted'));
      } catch(error) {if(error!=='cancel'&&error!=='close')this.folderError=error.message;} finally {this.folderSaving=false;}
    },
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
    browseCases(category = '全部资料') { this.fixedDepartmentContext=false;this.departmentFilter='';this.showProjectRoot(); this.resetFilters(); this.category = category; this.mode = 'cases'; this.libraryIntent = ''; this.activateChatCollection('experience'); },
    withFeedback(key, label, work, options = {}) { return this.feedback ? this.feedback('knowledge:' + key, label, work, options) : work(() => {}); },
    operationPending(key) { return !!this.operationState?.['knowledge:' + key]; },
    cancelPendingReads() { for (const cancel of this.pendingReads || []) cancel(); },
    async apiFetch(url, options = {}) {
      const token = localStorage.getItem('accessToken');
      const readOnly = ['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase());
      const backgroundDownload = readOnly && (/\/original\?download=true(?:&|$)/.test(url) || /\/download(?:\?|$)/.test(url));
      const convertedPreview = readOnly && /\/documents\/[^/]+\/(?:page|thumbnail)(?:\?|$)/.test(url);
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
        const stop = message => { const error = new Error(message); cleanup(); reject(error); controller.abort(error); };
        cancel = () => stop('读取已停止，请重新打开资料。');
        if (!backgroundDownload) this.pendingReads?.add(cancel);
        // Office previews may need the server's 180-second conversion window.
        timer = setTimeout(() => stop(convertedPreview ? '原件转换等待超时，请重试预览或下载水印副本。' : '读取超时，请重试；未重复提交任何操作。'), backgroundDownload || url.includes('/original') || /\/notes\/[^/]+\/export/.test(url) ? 600000 : convertedPreview ? 210000 : 30000);
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
        this.restoreRetryTracking();
        try { this.favorites = JSON.parse(localStorage.getItem('companyKnowledgeFavorites:' + this.service.username) || '[]'); } catch { this.favorites = []; }
        if (!this.viewRestored) {
          if(this.departmentEntryApplied)this.viewRestored=true;
          else { this.restoreLibraryView();if(this.departmentEntry)this.openDepartment(this.departmentEntry.department); }
        }
        try { const saved=JSON.parse(sessionStorage.getItem('companyKnowledgeReturn:'+this.service.username)||'null');if(saved?.view&&['library','cases'].includes(saved.view.mode))this.returnLocation=saved; }catch{}
        if (sessionStorage.getItem('companyKnowledgeOpenMyProjects') === '1') {
          sessionStorage.removeItem('companyKnowledgeOpenMyProjects');
          this.browseLibrary(); this.mineOnly = true;
        }
        this.initialCatalogueLoad = this.loadDocuments();
        await Promise.all([this.initialCatalogueLoad, this.loadMyProjects(), this.loadAccessRequests()]);
        await this.loadRecentRetryTracking();
        if (this.mode === 'cases') this.chatScope = 'experience';
        if(this.departmentEntryApplied)await this.refreshChatSessions();else await this.loadChatHistory();
      } catch (error) { this.serviceError = error.message; }
    },
    async loadDocuments(more = false, refresh = false) {
      if (this.loading) { this.catalogueRefreshQueued=true;return; }
      const mutation=this.catalogueMutation||0;
      const previousAccess = JSON.stringify(this.cloudDocuments.map(doc => [doc.id, doc.can_read, doc.version, doc.modified_at, doc.state]));
      this.loading = true; this.serviceError = '';
      const directories = this.loadProjectDirectories?.();
      try {
        let lastPage = more ? this.documentPage + 1 : Math.max(1, this.documentPage);
        const incoming = []; let result;
        const readPage = async page => {
          const response = await this.apiFetch('/company-knowledge/documents?page_number=' + page + '&page_size=100&local_only=true&refresh=' + (refresh && page === 1));
          const value = await response.json();
          if (response.status === 403) { this.newConversation(); this.chatSessions = []; this.service.access_allowed = false; }
          if (!response.ok) throw new Error(value.detail || '资料加载失败。');
          return value;
        };
        const firstPage = more ? lastPage : 1;
        result = await readPage(firstPage); incoming.push(...result.documents);
        lastPage = Math.max(lastPage, Math.ceil(result.total_count / 100));
        for (let page = firstPage + 1; result.documents.length && page <= lastPage; page += 3) {
          const pages = Array.from({length:Math.min(3,lastPage-page+1)},(_,i)=>page+i);
          const batch = await Promise.all(pages.map(readPage));
          for (const value of batch) incoming.push(...value.documents);
        }
        if(mutation!==(this.catalogueMutation||0)){this.catalogueRefreshQueued=true;return;}
        this.cloudDocuments = [...new Map((more ? [...this.cloudDocuments, ...incoming] : incoming).map(doc => [doc.id, doc])).values()];
        this.loadNotes?.(); this.totalDocuments = result.total_count; this.documentPage = lastPage;
        this.categories = ['全部资料', ...new Set([...['项目原件', '研究成果', '方法与模板', '访谈纪要', '行业资料'], ...this.cloudDocuments.map(doc => doc.category)])]; this.serviceError = result.warning || '';
        if (this.selectedIds.some(id => !this.cloudDocuments.some(doc => doc.id === id && doc.can_read !== false))) {
          this.chatScopeUnavailable = true; this.chatError = '所选资料已删除或权限已变化，请重新选择资料。';
        }
        const currentAccess = JSON.stringify(this.cloudDocuments.map(doc => [doc.id, doc.can_read, doc.version, doc.modified_at, doc.state]));
        if (previousAccess !== currentAccess) this.invalidateContentSearch?.();
        if (previousAccess !== currentAccess && this.chatSessionId && !this.busy && !this.chatHistoryBusy) await this.loadChatHistory(this.chatSessionId);
      } catch (error) { this.serviceError = error.message; }
      finally { await directories; this.loading = false; if (!this.restoringView && this.libraryPageCount) this.libraryPage = Math.min(this.libraryPage, this.libraryPageCount);if(this.catalogueRefreshQueued&&this.requestsActive!==false){this.catalogueRefreshQueued=false;await this.loadDocuments();} }
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
    restoreLibraryView() { this.restoringView = true; try { const saved = JSON.parse(localStorage.getItem('companyKnowledgeView:' + this.service.username) || '{}'); for (const key of ['departmentFilter','category','query','projectFilter','industryFilter','statusFilter','reviewFilter','tagFilter','dateFrom','dateTo']) if (typeof saved[key] === 'string') this[key] = saved[key]; if (['projects','files','contents'].includes(saved.projectDisplay)) this.projectDisplay = saved.projectDisplay; if (typeof saved.activeProjectId === 'string') this.activeProjectId = saved.activeProjectId; if (typeof saved.activeFolderId === 'string') this.activeFolderId = saved.activeFolderId; this.libraryLayout = 'list'; if (['home','library','chat','cases'].includes(saved.mode)) this.mode = saved.mode; if (saved.mode === 'chat' && saved.chatCollection === 'experience') this.chatScope = 'experience'; if ([10,20,50].includes(saved.libraryPageSize)) this.libraryPageSize = saved.libraryPageSize; if (Number.isInteger(saved.libraryPage) && saved.libraryPage > 0) this.libraryPage = saved.libraryPage; if (['created_at','modified_at'].includes(saved.dateField)) this.dateField = saved.dateField; if (['updated','title'].includes(saved.sortOrder)) this.sortOrder = saved.sortOrder; if (typeof saved.fixedDepartmentContext === 'boolean') this.fixedDepartmentContext = saved.fixedDepartmentContext; if (typeof saved.favoritesOnly === 'boolean') this.favoritesOnly = saved.favoritesOnly; if (typeof saved.mineOnly === 'boolean') this.mineOnly = saved.mineOnly; } catch {} try { const history = JSON.parse(localStorage.getItem('companyKnowledgeReading:' + this.service.username) || '[]'); this.readingHistory = Array.isArray(history) ? history.filter(id => typeof id === 'string').slice(0, 12) : []; } catch {} if(this.departmentFilter!=='unassigned'&&!this.departmentOptions.some(item=>item.id===this.departmentFilter))this.departmentFilter='';this.viewRestored = true; if (this.$nextTick) this.$nextTick(() => { this.restoringView = false; }); else this.restoringView = false; },
    scrollLibraryTop() { this.$nextTick?.(() => { if (this.$refs?.documentTable) this.$refs.documentTable.scrollTop = 0; }); },
    changeLibraryPage(page) { this.libraryPage = Math.max(1, Math.min(page, this.libraryPageCount)); this.scrollLibraryTop(); },
    async askLibrary() {
      if (this.busy) return;
      if (this.selectionBusy) return;
      if(this.mode==='cases'&&this.mineOnly&&!this.selectionCount){if(!this.collectionDocuments.some(doc=>doc.is_owner&&doc.can_read&&doc.state==='ready'&&doc.is_current!==0)){ElementPlus.ElMessage.info('我的笔记中暂无可检索资料，请先发布笔记或等待文件处理完成。');return;}const origin=this.captureBrowseLocation();this.newConversation();this.selectedIds=[];this.chatScope='my-experience';this.askSelection(origin);return;}
      const origin = this.captureBrowseLocation();
      if (this.selectedProjectIds.length || this.selectedFolderIds.length || (!this.selectedIds.length && (this.activeProjectId || this.departmentActive))) {
        const sequence = ++this.selectionSequence, locationKey = this.libraryFilterKey;
        this.selectionBusy = true;
        try {
          const response = await this.apiFetch('/company-knowledge/selection', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
            scope:this.currentCollection==='experience'?'experience':'accessible',
            ...(this.departmentActive?{department:this.departmentFilter==='unassigned'?'':this.departmentFilter}:{}),
            project_ids:this.selectedProjectIds.length||this.selectedFolderIds.length||this.selectedIds.length?this.selectedProjectIds:[...(this.activeFolderId||!this.activeProjectId?[]:[this.activeProjectId])],
            folder_ids:this.selectedProjectIds.length||this.selectedFolderIds.length||this.selectedIds.length?this.selectedFolderIds:[...(this.activeFolderId?[this.activeFolderId]:[])],document_ids:this.selectedIds})});
          const result = await response.json(); if(!response.ok)throw Error(result.detail||'提问范围加载失败。');
          if(sequence!==this.selectionSequence||locationKey!==this.libraryFilterKey)return;
          this.changeScope(result.document_ids); this.selectedProjectIds=[]; this.selectedFolderIds=[];
          if(result.skipped_count)ElementPlus.ElMessage.info('已选择 '+result.document_count+' 份可检索资料，另有 '+result.skipped_count+' 份尚未完成索引或仅归档。');
          this.askSelection(origin); return;
        } catch(error) { if(sequence===this.selectionSequence)ElementPlus.ElMessage.error(error.message); }
        finally { if(sequence===this.selectionSequence)this.selectionBusy=false; }
        return;
      }
      if (this.selectedDocuments.some(doc => this.caseCategories.includes(doc.category) !== (this.currentCollection === 'experience'))) this.changeScope([]);
      if (this.libraryIntent === 'compare') {
        if (this.selectedIds.length < 2) { ElementPlus.ElMessage.info('请先勾选至少两份可检索资料。'); return; }
        this.draft = '比较所选资料的结论差异，逐项列出依据与待复核事项。';
        this.libraryIntent = ''; this.askSelection(); return;
      }
      if (!this.selectedIds.length && this.libraryScopeFiltered) {
        const ids = this.filteredDocuments.filter(doc => doc.can_read && doc.state === 'ready' && doc.is_current !== 0).map(doc => doc.id);
        if (!ids.length) { ElementPlus.ElMessage.info('当前范围没有可检索资料。'); return; }
        if (ids.length > 1000) { ElementPlus.ElMessage.info('当前范围超过 1000 份资料，请缩小范围。'); return; }
        this.changeScope(ids);
      }
      if (!this.selectedIds.length) this.changeScope([]);
      this.askSelection(origin);
    },
    browseProject(name) { const directory = this.projectDirectories.find(p => p.name === name); if (directory) { this.mode = 'library'; this.openDirectory(directory); return; } this.showAllFiles(); this.selectCategory('全部资料'); this.projectFilter = name; this.mode = 'library'; },
    browseMyProject(name = '') { const mode = this.currentCollection === 'experience' ? 'cases' : 'library'; this.showProjectRoot(); const directory = this.collectionProjects.find(p => p.name === name && p.owner === this.service.username); if (directory) { this.mode = mode; this.openDirectory(directory); return; } this.selectCategory('全部资料'); this.mineOnly = true; this.projectFilter = name; this.mode = mode; },
    browseMyNotes() { this.showProjectRoot();this.selectCategory('全部资料');this.mode='cases';this.activateChatCollection('experience');this.projectDisplay='files';this.mineOnly=true; },
    summarizeMyProjects() { if (this.busy) return; const experience = this.currentCollection === 'experience'; this.newConversation(); this.selectedIds = []; this.chatScope = experience ? 'my-experience' : 'my-projects'; this.mode = 'chat'; this.sendQuestion(experience ? '请仅根据我在经验沉淀中的项目资料，总结我沉淀的实践经验，用 Markdown 表格列出主题、可复用方法和引用依据。' : '请根据我上传的项目资料，总结我参与过的项目、主要研究内容和可复用经验；先给出简短总结，再用 Markdown 表格列出项目、行业、资料数量和主要成果，并标注引用依据。'); },
    browseLibrary() { this.fixedDepartmentContext=false;this.departmentFilter='';this.showProjectRoot(); this.selectCategory('全部资料'); this.mode = 'library'; this.libraryIntent = ''; this.activateChatCollection('library'); },
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
    selectCategory(category, keepDirectory=false) { clearTimeout(this.directoryTimer); this.searchMode='metadata'; this.invalidateContentSearch?.(); if(!keepDirectory){this.activeProjectId='';this.activeFolderId='';this.projectDisplay='projects';this.libraryIntent='';} this.resetFilters(); this.category = category; },
    selectFavorites() { const active = this.favoritesOnly; this.selectCategory('全部资料'); this.showAllFiles(); this.favoritesOnly = !active; },
    selectFailed() { const active = this.statusFilter === 'failed'; this.selectCategory('全部资料'); this.showAllFiles(); this.statusFilter = active ? '' : 'failed'; },
    viewUploaded() { this.searchMode='metadata'; const experience = this.quickCapture || (this.uploadTargetProject ? this.caseCategories.includes(this.uploadTargetProject.category) : this.caseCategories.includes(this.uploadForm.category)); this.activeProjectId=this.quickCapture ? this.projectDirectories.find(p=>p.name==='随手记录 · 待整理'&&p.owner===this.service.username&&this.caseCategories.includes(p.category))?.id || '' : this.uploadTargetProjectId;this.activeFolderId=this.quickCapture?'':this.uploadTargetFolderId;this.projectDisplay=this.activeProjectId?'contents':'projects';this.libraryIntent=''; this.resetFilters(); this.selectCategory('全部资料',true); this.mode = experience ? 'cases' : 'library';this.departmentFilter=experience?'':this.uploadForm.department||''; this.uploadOpen = false; },
    showMode(mode) { this.mode = mode; },
    selectSpace(id) { this.space = this.space === id ? 'all' : id; },
    resetFilters() { this.searchMode='metadata'; this.tagFilter = ''; this.dateFrom = ''; this.dateTo = ''; this.recentUploadIds = []; this.query = ''; this.space = 'all'; this.favoritesOnly = false; this.mineOnly = false; this.projectFilter = ''; this.industryFilter = ''; this.statusFilter = ''; this.reviewFilter = ''; },
    toggleFavorite(id) { this.favorites = this.favorites.includes(id) ? this.favorites.filter(x => x !== id) : [...this.favorites, id]; try { localStorage.setItem('companyKnowledgeFavorites:' + this.service.username, JSON.stringify(this.favorites)); } catch {} },
    async openDocument(doc) {
      if (!doc.can_read) { await this.requestAccess(doc); return; }
      this.readingHistory = [doc.id, ...this.readingHistory.filter(id => id !== doc.id)].slice(0, 12);
      try { localStorage.setItem('companyKnowledgeReading:' + this.service.username, JSON.stringify(this.readingHistory)); } catch {}
      this.readerImageZoom=100;this.readerSheet=null;this.readerOriginalCode='';this.readerLocation = null; this.readerFind = '';this.readerOriginalFind='';this.readerSearchQuery='';this.readerSearchStatus='';this.readerSearchIndex=0;this.readerHasMore=false;this.readerExcerptError='';this.readerOriginalError=''; this.readerFocus = false; this.locating = false; this.releaseReader(); this.selectedDoc = { ...doc, references: this.allReferences.filter(ref => ref.document_id === doc.cloud_id) };
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
          if(doc.media_kind){await this.loadMediaPlayback(doc,current);return;}
          if(doc.format==='XLSX') { const probe=await this.apiFetch('/company-knowledge/documents/'+encodeURIComponent(id)+'/sheet');const table=await probe.json();if(!probe.ok){if(current())this.readerOriginalCode=probe.headers?.get('X-Preview-Error')||'';throw Error(table.detail||'表格无法读取');}if(['table','workbook'].includes(table.mode)){if(current()){this.readerSheet=table;this.readerTrace=probe.headers?.get('X-Watermark-Trace')||'';}return;} }
          const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + (['PDF','DOC','DOCX','XLS','XLSX','PPT','PPTX'].includes(doc.format) ? '/page?page=1' : '/original'));
          if (!response.ok) { const data = await response.json().catch(() => ({})); if(current())this.readerOriginalCode=response.headers?.get('X-Preview-Error')||'';throw new Error(data.detail || '原件预览暂不可用，请重试或下载文件。'); }
          const blob = await response.blob();
          if (!current()) return;
          this.readerTrace = response.headers?.get('X-Watermark-Trace') || '';
          if (['TXT','MD','CSV'].includes(doc.format)) this.readerBlob = typeof Vue !== 'undefined' ? Vue.markRaw(blob) : blob;
          else { this.readerUrl = URL.createObjectURL(blob); if (['PDF','DOC','DOCX','XLS','XLSX','PPT','PPTX'].includes(doc.format)) this.readerPDFPages = Number(response.headers.get('X-Document-Pages') || 1); }
        } catch (error) { if (current()) { this.readerOriginalError = error.message;if(this.readerOriginalCode==='original_missing')this.selectedDoc.has_original=false; } }
        finally { if (current()) this.readerOriginalLoading = false; }
      };
      const excerpts = async () => {
        if (doc.media_kind) { this.selectedDoc.references = doc.description?[{id:'说明',text:doc.description,pages:[]}]:[];this.readerTotal=this.selectedDoc.references.length;return; }
        try {
          const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + '/preview');
          const result = await response.json();
          if (!response.ok) throw new Error(result.detail || '检索片段加载失败。');
          if (current()) { this.selectedDoc.references = result.references; this.readerTotal = Number(result.total)||result.references?.length||0;this.readerHasMore=Boolean(result.has_more)||this.readerTotal>(result.references?.length||0); if (result.message && !doc.has_original) this.readerError = result.message; }
        } catch (error) { if (current()) this.readerExcerptError = error.message; }
      };
      try { await Promise.all([original(), excerpts()]); }
      finally { if (current()) this.readerLoading = false; }
    },
    async loadMediaPlayback(doc,current,retry=false) {
      this.readerMediaMessage='正在准备播放…';
      for(let attempt=0;attempt<180&&current();attempt++){
        const response=await this.apiFetch('/company-knowledge/documents/'+encodeURIComponent(doc.id)+'/playback'+(retry&&attempt===0?'?retry=true':''));
        const result=await response.json();if(!current())return;
        if(response.status===202||response.status===429){
          this.readerMediaMessage=result.message||result.detail||'正在排队准备播放…';
          await new Promise(resolve=>{this.readerMediaWake=resolve;this.readerMediaTimer=setTimeout(resolve,2000);});
          this.readerMediaWake=null;continue;
        }
        if(!response.ok)throw Error(result.detail||'播放准备失败，请重试或下载原文件。');
        this.readerUrl=result.url;this.readerMediaMessage='正在加载播放信息…';return;
      }
      if(current())throw Error('播放准备耗时较长，可稍后重试或先下载原文件。');
    },
    async retryMediaPlayback() {
      const doc=this.selectedDoc;if(!doc||this.readerOriginalLoading)return;
      this.releaseReader();this.readerError='';this.readerOriginalError='';this.readerOriginalLoading=true;
      const sequence=++this.readerSequence,current=()=>this.readerOpen&&this.selectedDoc?.id===doc.id&&this.readerSequence===sequence;
      try{await this.loadMediaPlayback(doc,current,true);}catch(error){if(current())this.readerOriginalError=error.message;}
      finally{if(current())this.readerOriginalLoading=false;}
    },
    mediaPlaybackError(event) {
      if(event.target?.getAttribute && event.target.getAttribute('src')!==this.readerUrl)return;
      const code=event.target?.error?.code;
      this.readerMediaMessage='';this.readerOriginalError=code===3||code===4?'浏览器无法解码播放版本，请重试或下载原文件。':'播放加载失败，可能是网络中断或播放授权过期，请重试。';
    },
    imagePreviewError(event) {
      if(this.selectedDoc?.media_kind||event.target?.src!==this.readerUrl)return;
      this.releaseReader();this.readerOriginalError='图片解码失败，请重试预览或下载原图。';
    },
    releaseReader() { clearTimeout(this.readerMediaTimer);this.readerMediaWake?.();this.readerMediaWake=null;this.readerMediaMessage='';this.readerSheet=null;if (this.readerUrl?.startsWith('blob:')) URL.revokeObjectURL(this.readerUrl); this.readerUrl = ''; this.readerBlob = null; },
    async restoreOriginal(event) {
      const file=event.target.files?.[0],doc=this.selectedDoc;if(!file||!doc||this.restoringOriginal)return;
      event.target.value='';this.restoringOriginal=true;const sequence=this.readerSequence;
      try {
        try{await ElementPlus.ElMessageBox.confirm('为“'+doc.title+'”补传原件？请核对文件对应关系。系统将保留当前归档位置和权限，并按补传内容重新建立索引。','补传缺失原件',{confirmButtonText:'确认补传并重新索引',cancelButtonText:'取消'});}catch{return;}
        const form=new FormData();form.append('file',file);form.append('confirmation',doc.id);
        const response=await this.apiFetch('/company-knowledge/documents/'+encodeURIComponent(doc.id)+'/original',{method:'POST',body:form});const result=await response.json();if(!response.ok)throw Error(result.detail||'补传失败');
        this.catalogueMutation++;this.cloudDocuments=[result,...this.cloudDocuments.filter(d=>d.id!==result.id)];this.newConversation();
        if(this.readerOpen&&this.selectedDoc?.id===doc.id&&this.readerSequence===sequence)await this.openDocument(result);
        await this.loadDocuments();ElementPlus.ElMessage.success('原件已补齐，正在重新建立索引。');
      }catch(error){ElementPlus.ElMessage.error(error.message);}finally{this.restoringOriginal=false;}
    },
    async morePreview() {
      if (this.readerLoading || !this.selectedDoc?.id) return;
      this.readerLoading = true; const id = this.selectedDoc.id, sequence = this.readerSequence;
      const current = () => this.selectedDoc?.id === id && this.readerOpen && this.readerSequence === sequence;
      try {
        const response = await this.apiFetch('/company-knowledge/documents/' + encodeURIComponent(id) + '/preview?page=' + (this.previewPage + 1));
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '片段加载失败。');
        if (current()) { this.selectedDoc.references.push(...(result.references||[]));this.readerTotal=Math.max(Number(result.total)||0,this.selectedDoc.references.length);this.readerHasMore=Boolean(result.has_more)||this.readerTotal>this.selectedDoc.references.length;this.previewPage++;if(!result.references?.length)this.readerHasMore=false; }
      } catch (error) { if (current()) this.readerExcerptError = error.message; } finally { if (current()) this.readerLoading = false; }
    },
    downloadPhase(doc) {
      if(this.plainOriginal(doc))return ({preparing:'准备下载…',ready:'接收文件中…',receiving:'接收文件中…',handoff:'交给浏览器下载…'})[this.downloadProgress[doc.id]?.stage]||'正在下载…';
      const state = this.downloadProgress[doc.id];
      if (!state) return '转换并加水印中…';
      return ({preparing:'准备安全副本…',converting:'处理兼容格式中…',media:'处理音视频标记中…',
        stamping:state.total_pages ? '水印 ' + state.page + '/' + state.total_pages + (['PDF','PPT','PPTX'].includes(doc.format) ? ' 页' : ' 项') : '添加水印中…',
        packaging:'整理下载文件…',ready:'接收文件中…',receiving:'接收文件中…',handoff:'交给浏览器下载…',failed:'处理失败'})[state.stage] || '生成水印副本中…';
    },
    async downloadOriginal(doc) {
      try { await this.withFeedback('download:' + doc.id, this.plainOriginal(doc)?'正在下载原文件':'正在生成带水印下载副本', async phase => {
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
          if (!response.ok) { const result = await response.json();if(response.headers?.get('X-Preview-Error')==='original_missing'&&this.selectedDoc?.id===doc.id){this.readerOriginalCode='original_missing';this.selectedDoc.has_original=false;}throw new Error(result.detail || '下载失败。'); }
          this.downloadProgress[doc.id].stage = 'receiving'; report();
          const blob = await response.blob();
          this.downloadProgress[doc.id].stage = 'handoff'; report();
          const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = decodeURIComponent(response.headers?.get('X-Download-Filename') || encodeURIComponent(this.displayDocumentTitle(doc))); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
          ElementPlus.ElMessage.success(this.plainOriginal(doc)?'原文件已交给浏览器下载，请查看下载列表':'带水印副本已交给浏览器下载，请查看下载列表');
        } finally { finished = true; clearInterval(clock); delete this.downloadProgress[doc.id]; }
      }, {readOnly:true}); } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    changeScope(ids) { if (this.busy) return; if (ids.length > 1000) { ElementPlus.ElMessage.warning('一次最多选择 1000 份资料。'); return; } const rows = ids.map(id => this.documents.find(doc => doc.id === id)).filter(Boolean); const experience = rows.length ? this.caseCategories.includes(rows[0].category) : this.currentCollection === 'experience'; if (rows.some(doc => this.caseCategories.includes(doc.category) !== experience)) { ElementPlus.ElMessage.warning('资料库与经验沉淀请分别提问，不能跨库选择资料。'); return; } this.selectedIds = [...new Set(ids)]; this.chatScope = experience ? 'experience' : 'accessible'; this.scopeFilesExpanded=false; this.newConversation(); },
    useAllChatSources() { if(this.busy)return;this.departmentFilter='';this.changeScope([]); },
    clearSelection() { if(this.busy||this.selectionBusy)return;this.selectedProjectIds=[];this.selectedFolderIds=[];this.changeScope([]); },
    toggleDirectorySelection(kind, id) { if(this.busy||this.selectionBusy)return; const key=kind==='project'?'selectedProjectIds':'selectedFolderIds';this[key]=this[key].includes(id)?this[key].filter(value=>value!==id):[...this[key],id];this.newConversation(); },
    captureBrowseLocation() {
      if(!['library','cases'].includes(this.mode))return null;
      return {view:{...this.libraryView},selectedIds:[...this.selectedIds],projectIds:[...this.selectedProjectIds],folderIds:[...this.selectedFolderIds],
        label:[this.mode==='cases'?'经验沉淀':'总资料库',this.mode==='cases'?'':this.departmentName,this.activeProject?.name,...this.directoryBreadcrumbs.map(f=>f.name)].filter(Boolean).join(' / '),
        scrollTop:this.$refs?.documentTable?.scrollTop||0,readerId:this.readerOpen?this.selectedDoc?.id||'':''};
    },
    saveReturnLocation() { try { if(this.service.username)sessionStorage.setItem('companyKnowledgeReturn:'+this.service.username,JSON.stringify(this.returnLocation)); } catch {} },
    async returnToBrowse() {
      const origin=this.returnLocation;if(!origin||this.restoringView)return;
      this.restoringView=true;this.readerOpen=false;this.dismissProjectPreview?.();
      try {
      // Initial lists may still be empty after a refresh; they do not prove deletion.
      await (this.initialWorkspaceLoad || this.initialCatalogueLoad);
      if(this.requestsActive===false||this.returnLocation!==origin)return;
      if(this.projectError || this.serviceError && !this.cloudDocuments.length){ElementPlus.ElMessage.warning('资料位置尚未加载完成，请刷新资料后重试。');return;}
      const keys=['fixedDepartmentContext','departmentFilter','mode','projectDisplay','activeProjectId','activeFolderId','libraryLayout','tagFilter','dateFrom','dateTo','dateField','libraryPage','libraryPageSize','sortOrder','category','query','projectFilter','industryFilter','statusFilter','reviewFilter','favoritesOnly','mineOnly'];
      for(const key of keys)if(Object.prototype.hasOwnProperty.call(origin.view,key))this[key]=origin.view[key];
      this.searchMode='metadata';this.libraryIntent='';this.libraryLayout='list';
      const project=this.projectDirectories.find(p=>p.id===this.activeProjectId);
      if(this.activeProjectId&&!project){this.activeProjectId='';this.activeFolderId='';this.projectDisplay='projects';}
      if(this.activeFolderId&&!this.projectFolders.some(f=>f.id===this.activeFolderId&&f.project_id===this.activeProjectId))this.activeFolderId='';
      this.selectedProjectIds=origin.projectIds.filter(id=>this.projectDirectories.some(p=>p.id===id));
      this.selectedFolderIds=origin.folderIds.filter(id=>this.projectFolders.some(f=>f.id===id));
      if(!this.busy)this.selectedIds=origin.selectedIds.filter(id=>this.documents.some(d=>d.id===id&&d.can_read));
      await this.$nextTick();this.libraryPage=Math.min(this.libraryPage,this.libraryPageCount);await this.$nextTick();
      if(this.$refs?.documentTable)this.$refs.documentTable.scrollTop=origin.scrollTop;
      const doc=origin.readerId&&this.documents.find(d=>d.id===origin.readerId&&d.can_read);if(doc)await this.openDocument(doc);
      } finally { this.restoringView=false; }
    },
    toggleSelection(doc) { if (this.selectionBusy || !doc.can_read || doc.state !== 'ready') return; const ids = this.selectedDocuments.filter(row => this.caseCategories.includes(row.category) === this.caseCategories.includes(doc.category)).map(row => row.id); this.changeScope(ids.includes(doc.id) ? ids.filter(id => id !== doc.id) : [...ids, doc.id]); },
    askWhileReading() { if (!this.selectedDoc?.id || this.busy) return; const question = this.draft; if (this.selectedIds.length !== 1 || this.selectedIds[0] !== this.selectedDoc.id) this.changeScope([this.selectedDoc.id]); this.sendQuestion(question); },
    askSelection(origin=null) { if(this.mode!=='chat'){this.returnLocation=origin?.view?origin:this.captureBrowseLocation();this.saveReturnLocation();} this.mode = 'chat'; this.readerOpen = false; this.$nextTick(() => this.$refs.composer?.focus()); },
    chooseFiles(event) { if(this.uploadBusy)return; this.stagedFiles = Array.from(event.target.files || []); this.uploadResults = []; this.uploadError = ''; },
    plainOriginal(doc) { return !!doc?.media_kind || ['PNG','JPG','JPEG','WEBP','GIF','BMP'].includes(doc?.format); },
    uploadSize(bytes) { return ((Number(bytes)||0)/1024/1024).toFixed(1)+' MB'; },
    uploadProgressText(row) {
      if(row.saving)return '文件已传输，服务器正在保存，请勿重复上传。本次已用时 '+row.elapsed+' 秒。';
      const speed=row.speed>=1024*1024?this.uploadSize(row.speed)+'/s':Math.max(1,Math.round(row.speed/1024))+' KB/s';
      if(row.phase==='transferring')return this.uploadSize(row.sent)+' / '+this.uploadSize(row.total)+(row.speed>0?' · '+speed:' · 等待网络传输')+' · '+row.elapsed+' 秒';
      return row.detail||'';
    },
    cancelUpload() {
      this.uploadStopped=true;
      if(this.uploadCurrent&&!this.uploadCurrent.saving)this.uploadXHR?.abort();
    },
    minimizeUpload() {
      this.uploadOpen=false;
      const dest=this.uploadBatchDestination;if(!dest)return;
      this.showProjectRoot();this.category='全部资料';this.mode=this.caseCategories.includes(dest.category)?'cases':'library';
      this.departmentFilter=this.mode==='cases'?'':dest.department||'';
      const project=this.projectDirectories.find(item=>item.id===dest.project_id);
      if(project)this.openDirectory(project,dest.folder_id);
      else if(dest.project_id)this.showAllFiles();
    },
    mediaPlaybackStatus(event) {
      if(!this.selectedDoc?.media_kind || event.target?.getAttribute('src')!==this.readerUrl)return;
      if(['canplay','playing','ended'].includes(event.type) || ['loadeddata','seeked'].includes(event.type)&&event.target.readyState>=3)this.readerMediaMessage='';
      else if(['loadstart','waiting','seeking'].includes(event.type) || event.type==='stalled'&&event.target.readyState<3)this.readerMediaMessage=event.type==='loadstart'?'正在加载音视频…':'正在缓冲…';
    },
    transferUpload(url, form, row) {
      const token=localStorage.getItem('accessToken'),started=Date.now();
      return new Promise((resolve,reject)=>{
        const xhr=new XMLHttpRequest();this.uploadXHR=xhr;this.uploadCurrent=row;
        Object.assign(row,{phase:'transferring',sent:0,total:row.file.size,percent:0,speed:0,elapsed:0,saving:false});
        let lastTime=started,lastBytes=0;
        const clock=setInterval(()=>{row.elapsed=Math.floor((Date.now()-started)/1000);if(Date.now()-lastTime>10000)row.speed=0;},1000);
        const finish=()=>{clearInterval(clock);if(this.uploadXHR===xhr){this.uploadXHR=null;this.uploadCurrent=null;}};
        xhr.open('POST',url);xhr.setRequestHeader('Authorization','Bearer '+(token||''));
        xhr.upload.onprogress=event=>{
          const now=Date.now();row.sent=event.loaded;row.total=event.lengthComputable?event.total:row.file.size;
          row.percent=event.lengthComputable?Math.min(100,Math.floor(event.loaded/event.total*100)):null;
          row.speed=(event.loaded-lastBytes)/Math.max(.001,(now-lastTime)/1000);lastTime=now;lastBytes=event.loaded;
        };
        xhr.upload.onload=()=>{row.saving=true;row.phase='saving';row.state='服务器保存中';row.percent=100;};
        xhr.onload=()=>{
          finish();
          if(token!==localStorage.getItem('accessToken')||this.requestsActive===false){this.uploadStopped=true;reject(Error('登录或页面已变化，请在资料列表核对上传结果。'));return;}
          let result;try{result=JSON.parse(xhr.responseText);}catch{reject(Error('服务器返回异常，保存结果待核对，请先刷新资料列表。'));return;}
          resolve({ok:xhr.status>=200&&xhr.status<300,status:xhr.status,json:async()=>result});
        };
        xhr.onerror=()=>{finish();reject(Error('网络连接中断，保存结果待核对，请先刷新资料列表再重试。'));};
        xhr.onabort=()=>{finish();reject(Error('已停止传输；如文件已到达服务器，请在资料列表核对是否已保存。'));};
        try{xhr.send(form);}catch(error){finish();reject(error);}
      });
    },
    async uploadFiles() {
      if(this.uploadDescriptionRequired&&!this.uploadForm.description.trim()){this.uploadError='根目录音视频需要填写文字说明，问答仅检索此说明，不自动转写。';return;}
      if(!this.uploadBusy)this.prepareCaptureNote?.();
      if (this.uploadBusy || !this.stagedFiles.length) return;
      const formSnapshot={...this.uploadForm},contextSnapshot=this.reuploadContext?{...this.reuploadContext}:null,targetProjectSnapshot=this.uploadTargetProjectId,targetFolderSnapshot=this.uploadTargetFolderId;
      if(contextSnapshot && this.stagedFiles.length!==1){this.uploadError='重新上传一次只选择一份文件。';return;}
      if(!this.quickCapture&&!contextSnapshot&&!targetProjectSnapshot&&this.currentCollection!=='experience'&&Object.prototype.hasOwnProperty.call(formSnapshot,'department')&&!formSnapshot.department){this.uploadError='请选择所属部门／栏目。';return;}
      const tags = this.parseTags(formSnapshot.tagsText);
      if (tags.length > 20 || tags.some(tag => tag.length > 40)) { this.uploadError = '最多添加 20 个标签，每个不超过 40 字，请修改后重试。'; return; }
      if (!this.quickCapture && !targetProjectSnapshot && this.stagedFiles.some(file => /\.(mp3|wav|m4a|ogg|flac|mp4|webm)$/i.test(file.name)) && !formSnapshot.description.trim()) {
        this.uploadError = '请先填写音视频的文字说明，原件无需转写即可归档。'; return;
      }
      if (this.quickCapture && !this.captureTitle.trim()) { this.uploadError='请为这次经验起一个名字。'; return; }
      let captureProjectId='',captureDescription='';
      this.uploadBusy = true; this.uploadStopped=false; this.uploadError = ''; this.uploadResults = this.uploadResults.filter(row => row.id);
      this.uploadLeaveGuard=event=>{if(this.uploadBusy){event.preventDefault();event.returnValue='';}};
      if(typeof window!=='undefined')window.addEventListener('beforeunload',this.uploadLeaveGuard);
      const failed = [];
      this.uploadBatchDestination={project_id:contextSnapshot?.project_id??targetProjectSnapshot,folder_id:contextSnapshot?.folder_id??targetFolderSnapshot,category:formSnapshot.category,department:formSnapshot.department||''};
      if(this.quickCapture) { try { captureProjectId=await this.captureProject(); captureDescription=[this.captureTitle.trim(),this.captureScene.trim()&&'适用场景：'+this.captureScene.trim(),this.captureMethod.trim()&&'可复用做法：'+this.captureMethod.trim(),formSnapshot.description.trim()].filter(Boolean).join('\n\n'); } catch(error){this.uploadError=error.message;this.uploadBusy=false;if(typeof window!=='undefined')window.removeEventListener('beforeunload',this.uploadLeaveGuard);return;} }
      if(captureProjectId)this.uploadBatchDestination={...this.uploadBatchDestination,project_id:captureProjectId,folder_id:''};
      const queued=this.stagedFiles.map(file=>({file,name:contextSnapshot?.title||file.name,state:'等待上传',phase:'waiting',destination:{...this.uploadBatchDestination},client_id:Date.now().toString(36)+Math.random().toString(36).slice(2)}));
      this.uploadResults.push(...queued);
      for (const row of queued) {
        const file=row.file,shown=this.uploadResults.find(item=>item.client_id===row.client_id);
        if(this.uploadStopped){shown.phase='stopped';shown.state='已停止，尚未上传';failed.push(file);continue;}
        shown.state='上传中';
        try {
          const media = /\.(mp3|wav|m4a|ogg|flac|mp4|webm)$/i.test(file.name);
          if (file.size > (media ? 128 : 32) * 1024 * 1024) throw new Error(media ? '音视频超过 128 MB 限制' : '超过 32 MB 限制');
          if (media && !captureProjectId && !targetProjectSnapshot && !formSnapshot.description.trim()) throw new Error('请填写音视频的文字说明');
          if(contextSnapshot&&file.name.split('.').pop().toLowerCase()!==contextSnapshot.title.split('.').pop().toLowerCase())throw new Error('请选择与原资料相同格式的文件；其他格式请另行上传。');
          const form = new FormData(); if(contextSnapshot)form.append('file',file,contextSnapshot.title);else form.append('file', file);
          for (const key of ['project', 'industry', 'category', 'review', 'confidentiality', 'visibility']) form.append(key, formSnapshot[key]);
          form.append('department',formSnapshot.department||'');
          form.append('tags', JSON.stringify(this.parseTags(formSnapshot.tagsText)));
          form.append('description', this.quickCapture ? captureDescription : formSnapshot.description);
          const targetProject=contextSnapshot?.project_id??targetProjectSnapshot,targetFolder=contextSnapshot?.folder_id??targetFolderSnapshot;
          if (captureProjectId || targetProject) { form.append('project_id', captureProjectId || targetProject); form.append('folder_id', captureProjectId ? '' : targetFolder); } else form.append('root', 'true');
          form.append('readers', JSON.stringify(formSnapshot.readersText.split(/[,，\n]/).map(name => name.trim()).filter(Boolean)));
          if(contextSnapshot?.restore_original)form.append('confirmation',contextSnapshot.id);
          else {const fingerprint=JSON.stringify([...form.entries()].filter(([key])=>key!=='file'));let requests=this.uploadRequestIds.get(file);if(!requests){requests=new Map();this.uploadRequestIds.set(file,requests);}if(!requests.has(fingerprint))requests.set(fingerprint,this.fileRequestId());form.append('request_id',requests.get(fingerprint));}
          const response = await this.transferUpload(contextSnapshot?.restore_original?'/company-knowledge/documents/'+encodeURIComponent(contextSnapshot.id)+'/original':'/company-knowledge/uploads', form, shown);
          const result = await response.json(); if (!response.ok) throw new Error(contextSnapshot&&response.status===409&&String(result.detail).includes('相同内容')?'文件内容未变化，请关闭此窗口并对原记录点击“重试处理”。':result.detail || '上传失败');
          this.cloudDocuments=[result,...this.cloudDocuments.filter(doc=>doc.id!==result.id)];this.catalogueMutation=(this.catalogueMutation||0)+1;
          shown.id = result.id; shown.name=this.displayDocumentTitle(result); shown.notice=result.upload_notice||''; shown.phase = result.state; shown.state = result.label || '等待处理'; shown.detail = '原件已保存，处理状态会自动更新。'; this.uploadRequestIds.delete(file);
        } catch (error) { shown.state = error.message;shown.phase='upload_failed'; failed.push(file); }
      }
      this.stagedFiles = failed; this.uploadBusy = false; this.uploadCurrent=null;
      if(typeof window!=='undefined')window.removeEventListener('beforeunload',this.uploadLeaveGuard);
      if(this.requestsActive!==false)await Promise.all([this.loadDocuments(), this.loadMyProjects()]);
    },
    retryTrackingKey() { return 'companyKnowledgeRetryIds:'+(this.service.account_id??this.service.username); },
    restoreRetryTracking() { this.retryTrackingIds=[];this.retryReceiptsExpanded=false;try{const ids=JSON.parse(localStorage.getItem(this.retryTrackingKey())||'[]');if(Array.isArray(ids))this.retryTrackingIds=[...new Set(ids.filter(id=>typeof id==='string'&&id.length>0&&id.length<=64))].slice(0,3);this.retryReceiptsExpanded=localStorage.getItem(this.retryTrackingKey()+':expanded')==='true';}catch{} },
    setRetryReceiptsExpanded(expanded) { this.retryReceiptsExpanded=!!expanded;try{localStorage.setItem(this.retryTrackingKey()+':expanded',String(this.retryReceiptsExpanded));}catch{} },
    rememberRetry(id) { this.retryTrackingIds=[id,...this.retryTrackingIds.filter(value=>value!==id)].slice(0,3);try{localStorage.setItem(this.retryTrackingKey(),JSON.stringify(this.retryTrackingIds));}catch{} },
    async loadRecentRetryTracking() { if(!this.service.is_admin)return;try{const response=await this.apiFetch('/company-knowledge/audit-events?page=1&page_size=100');if(!response.ok)return;const result=await response.json();const visible=new Set(this.cloudDocuments.filter(doc=>doc.can_read).map(doc=>doc.id));const ids=(result.events||[]).filter(event=>event.action==='document.retry'&&event.actor_username===this.service.username&&visible.has(event.target_id)).map(event=>event.target_id);for(const id of [...new Set(ids)].slice(0,3).reverse())this.rememberRetry(id);}catch{} },
    retryResultLabel(doc) { return doc.state==='ready'?'重试成功，已可检索':doc.state==='failed'?'重试未成功，请查看失败详情':['queued','uploading','parsing','indexing'].includes(doc.state)?'已提交重试，正在处理':doc.label||'请查看资料状态'; },
    async retryDocument(doc) { try { await this.withFeedback('retry:' + doc.id, '正在重试知识库资料处理', async () => { const response = await this.apiFetch('/company-knowledge/documents/' + doc.id + '/retry', { method: 'POST' }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '重试失败');this.rememberRetry(doc.id);this.setRetryReceiptsExpanded(true);this.catalogueMutation++;this.cloudDocuments=this.cloudDocuments.map(row=>row.id===doc.id?{...row,state:'queued',label:'等待处理',status_message:'已提交重试，原归档位置不变'}:row);ElementPlus.ElMessage.success('重试已提交，完整路径和后续结果会保留在“最近重试的资料”。'); await this.loadDocuments(); }); } catch (error) { ElementPlus.ElMessage.error(error.message); } },
    editDocument(doc) { if(doc.note_id){this.editRichNote(doc.note_id);return;} this.editingDoc = doc; this.uploadForm = { department:this.itemDepartment(doc), title: doc.title, folder_id: doc.folder_id || '', project: doc.project || '', industry: doc.industry || '', category: doc.category, review: doc.review, confidentiality: doc.confidentiality === 'confidential' ? 'secret' : doc.confidentiality || 'internal', tagsText: (doc.tags || []).join('，'), description: doc.description || '', visibility: doc.visibility, readersText: (doc.readers || []).join(', ') }; this.metadataOpen = true; },
    async saveMetadata() {
      try { await this.withFeedback('save:' + this.editingDoc.id, '正在保存资料信息', async () => {
        const response = await this.apiFetch('/company-knowledge/documents/' + this.editingDoc.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...this.uploadForm, tags: this.parseTags(this.uploadForm.tagsText), readers: this.uploadForm.readersText.split(/[,，\n]/).map(name => name.trim()).filter(Boolean) }) });
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '保存失败');
        this.metadataOpen = false;this.catalogueMutation++; this.newConversation(); await Promise.all([this.loadDocuments(), this.loadMyProjects()]);
      }); } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    startUpload() { if(this.uploadBusy){this.uploadOpen=true;return;} if (this.activeProject && !this.activeProject.can_manage) { ElementPlus.ElMessage.info('此项目为只读，仅创建者或管理员可上传文件。'); return; } this.reuploadContext=null;this.quickCapture=false; this.uploadTargetProjectId=this.activeProject?.can_manage?this.activeProjectId:'';this.uploadTargetFolderId=this.uploadTargetProjectId?this.activeFolderId:'';this.uploadForm={description:'',department:this.departmentFilter==='unassigned'?'':this.departmentFilter};this.setUploadTarget(false);this.stagedFiles = []; this.uploadResults = []; this.uploadError = ''; this.uploadOpen = true; },
    startReupload(doc) { if(this.uploadBusy){this.uploadOpen=true;return;}
      if(!doc.can_manage||doc.note_id||doc.state!=='failed')return;
      const project=doc.knowledge_project_id&&this.projectDirectories.find(p=>p.id===doc.knowledge_project_id&&p.can_manage);
      if(doc.knowledge_project_id&&!project||doc.folder_id&&!this.projectFolders.some(f=>f.id===doc.folder_id&&f.project_id===doc.knowledge_project_id)){ElementPlus.ElMessage.warning('原归档位置已失效或没有管理权限，请刷新后联系项目管理员。');return;}
      this.quickCapture=false;this.reuploadContext={id:doc.id,title:doc.title,restore_original:!doc.has_original,project_id:doc.knowledge_project_id||'',folder_id:doc.folder_id||''};this.uploadTargetProjectId=doc.knowledge_project_id||'';this.uploadTargetFolderId=doc.folder_id||'';
      this.uploadForm={department:this.itemDepartment(doc),description:doc.description||''};this.setUploadTarget(false);if(!project)Object.assign(this.uploadForm,{project:doc.project||'',industry:doc.industry||'',category:doc.category,review:doc.review||'待复核',confidentiality:doc.confidentiality||'internal',visibility:doc.visibility||'members',readersText:(doc.readers||[]).join(', '),tagsText:(doc.tags||[]).join('，')});
      this.stagedFiles=[];this.uploadResults=[];this.uploadError='';this.uploadOpen=true;
    },
    showFailureDetails(doc) { const reason=doc.status_message||'服务未返回具体原因，请由管理者检查原件或重试处理。';const instructions=doc.can_manage?(doc.note_id?'可以重试处理、编辑并重试发布，或删除笔记。':doc.has_original?'原件仍已保存。可以先重试处理；原件有误时重新上传修正文件；不再需要时删除。':'原件缺失，请补传原件后重新建立索引，或删除记录。'):'当前账号只有阅读权限，请联系归属人 '+(doc.owner||'或管理员')+' 处理；申请阅读权限不会获得删除或重新上传权限。';return ElementPlus.ElMessageBox.alert('《'+doc.title+'》\n失败原因：'+reason+'\n\n'+instructions+(doc.format==='PDF'?'\n如果原件需要打开密码，请重新上传已解密的 PDF，重复原件不能解决加密问题。':''),'文件处理失败',{confirmButtonText:'知道了',customClass:'ckb-failure-dialog'}).catch(()=>{}); },
    discardUploadResult(item) { if(this.uploadBusy||item.id)return;this.uploadResults=this.uploadResults.filter(row=>row.client_id!==item.client_id);this.stagedFiles=this.stagedFiles.filter(file=>file!==item.file);if(!this.stagedFiles.length)this.uploadError=''; },
    setUploadTarget(resetFolder = true) { if(resetFolder)this.uploadTargetFolderId='';const p=this.uploadTargetProject;Object.assign(this.uploadForm,{department:p?p.department||'':this.uploadForm.department||'',project:p?.name||'',industry:p?.industry||'',category:p?.category||(this.currentCollection==='experience'?'项目经验':'项目原件'),review:p?.review||'待复核',confidentiality:p?.confidentiality||'internal',visibility:p?.visibility||'members',readersText:(p?.readers||[]).join(', '),tagsText:(p?.tags||[]).join('，')}); },
    canMoveDocument(doc) { return doc.can_manage && !doc.note_id && !doc.research_project_id; },
    async startMove(doc) { this.moveDoc=doc;this.moveProjectId=doc.knowledge_project_id||'';this.moveFolderId=doc.folder_id||'';this.moveError='';this.moveOpen=true;await this.loadProjectDirectories(); },
    async moveDocument() {
      if(this.moveBusy||!this.moveDoc)return;this.moveBusy=true;this.moveError='';
      const path='/company-knowledge/documents/'+encodeURIComponent(this.moveDoc.id),target={project_id:this.moveProjectId,folder_id:this.moveFolderId};
      try {
        const response=await this.apiFetch(path+'/move-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(target)});const preview=await response.json();if(!response.ok)throw Error(preview.detail||'无法读取移动范围');
        if(!preview.completed && preview.no_change){this.moveError='请选择不同的归档位置。';return;}
        const message='将《'+preview.title+'》的 '+preview.version_count+' 个版本从“'+preview.source+'”移到“'+preview.destination+'”。\n所属部门：'+preview.before_department+' → '+preview.after_department+'\n当前权限：'+preview.before_access+'\n移动后权限：'+preview.after_access+'\n'+preview.permission_note+(preview.reindex_required?'\n音视频说明会重新建立索引。':'');
        try { await ElementPlus.ElMessageBox.confirm(message,'确认移动与权限变化',{confirmButtonText:'确认移动',cancelButtonText:'取消',type:preview.access_changes?'warning':'info',closeOnClickModal:false,customClass:'ckb-move-confirm'}); } catch { return; }
        const moved=await this.apiFetch(path+'/move',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...target,confirmation:preview.confirmation})});const result=await moved.json();if(!moved.ok)throw Error(result.detail||'移动失败');
        this.catalogueMutation++;this.selectedIds=[];this.newConversation();this.metadataOpen=false;this.readerOpen=false;this.moveOpen=false;
        await Promise.all([this.loadDocuments(),this.loadMyProjects()]);ElementPlus.ElMessage.success('文件及 '+result.moved_version_count+' 个版本已移动。');
      } catch(error) { this.moveError=error.message; } finally { this.moveBusy=false; }
    },
    syncConfidentiality() { if (this.uploadForm.confidentiality !== 'internal') this.uploadForm.visibility = 'restricted'; },
    requestStatusLabel(status) { return ({ pending: '审批中', approved: '已批准', rejected: '已拒绝' })[status] || '未申请'; },
    async requestAccess(doc) {
      if (!doc.can_request && doc.request_status === 'pending') { ElementPlus.ElMessage.info('该资料的权限申请正在审批中。'); return; }
      try {
        const prompt = await ElementPlus.ElMessageBox.prompt('请说明需要阅读《' + doc.title + '》的原因，管理员将根据项目和保密等级审批。', '申请访问权限', { customClass:'ckb-input-prompt', confirmButtonText: '提交申请', cancelButtonText: '取消', inputPlaceholder: '例如：新员工培训，需要学习项目方法', inputValidator: value => Boolean(value && value.trim()) || '请填写申请原因' });
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
        if (decision === 'rejected') { const prompt = await ElementPlus.ElMessageBox.prompt('请填写拒绝原因。', '拒绝访问申请', { customClass:'ckb-input-prompt', confirmButtonText: '确认拒绝', cancelButtonText: '取消', inputValidator: value => Boolean(value && value.trim()) || '请填写拒绝原因' }); note = prompt.value.trim(); }
        await this.withFeedback('decision:' + request.id, '正在保存权限审批结果', async () => {
        const response = await this.apiFetch('/company-knowledge/access-requests/' + request.id + '/decision', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, note }) });
        const result = await response.json(); if (!response.ok) throw new Error(result.detail || '审批失败。');
        ElementPlus.ElMessage.success(decision === 'approved' ? '已批准访问。' : '已拒绝申请。'); await Promise.all([this.loadAccessRequests(), this.loadDocuments()]);
        });
      } catch (error) { if (error !== 'cancel' && error !== 'close') ElementPlus.ElMessage.error(error.message || '审批失败。'); }
    },
    async deleteDocument(doc) {
      if(doc.note_id){await this.deleteRichNote(doc.note_id);return;}
      try { await ElementPlus.ElMessageBox.confirm('将《' + doc.title + '》移入回收站？10 天内可恢复，到期后自动清理本地原件。', '删除资料', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }); } catch { return; }
      try { await this.withFeedback('delete:' + doc.id, '正在删除知识库资料', async () => { const response = await this.apiFetch('/company-knowledge/documents/' + doc.id, { method: 'DELETE' }); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '删除失败'); this.readerOpen = false; this.metadataOpen = false;this.uploadResults=this.uploadResults.filter(item=>item.id!==doc.id);this.catalogueMutation++; this.newConversation(); await Promise.all([this.loadDocuments(), this.loadMyProjects()]); }); } catch (error) { ElementPlus.ElMessage.error(error.message); }
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
    async openCitation(group) { const doc = this.documents.find(doc => doc.cloud_id === group.document_id); if (doc) { await this.openDocument(doc); if(this.readerOpen&&this.selectedDoc?.id===doc.id)this.showReference(group.references[0]||{},this.searchMode==='content'?this.query.trim():''); } else { this.releaseReader(); this.selectedDoc = { title: group.title, references: group.references }; this.readerOpen = true; } },
    referenceIds(group) { return group.references.map(reference => reference.id).join('、'); },
    renderAnswer(message) {
      const text = message.text || '', references = message.references || [];
      const signature = JSON.stringify(references.map(ref => [ref.id, ref.document_id, ref.title]));
      const cached = knowledgeAnswerMarkup.get(message);
      if (cached?.text === text && cached.signature === signature) return cached.html;
      let html = typeof window !== 'undefined' && window.SafeMarkdown
        ? window.SafeMarkdown.render(text)
        : text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
      if (typeof document !== 'undefined') {
        const template = document.createElement('template'); template.innerHTML = html;
        // The answer is text and citations; document-supplied images must not make network requests.
        template.content.querySelectorAll('img').forEach(img => img.replaceWith(document.createTextNode(img.alt || '')));
        const known = new Map(references.map(ref => [String(ref.id), ref]));
        const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT), nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        for (const node of nodes) {
          if (node.parentElement?.closest('a, pre, code')) continue;
          const matches = [...node.textContent.matchAll(/\[id_([^\]\s]+)\]/g)];
          if (!matches.length) continue;
          const fragment = document.createDocumentFragment(); let offset = 0;
          for (const match of matches) {
            fragment.append(document.createTextNode(node.textContent.slice(offset, match.index)));
            const ref = known.get(match[1]);
            if (ref) {
              const button = document.createElement('button'); button.type = 'button';
              button.className = 'ckb-inline-citation'; button.dataset.citationId = match[1];
              button.textContent = match[1]; button.title = '查看来源 ' + match[1] + '：' + (ref.title || '资料片段');
              button.setAttribute('aria-label', button.title); fragment.append(button);
            } else fragment.append(document.createTextNode('[未核验引用 ' + match[1] + ']'));
            offset = match.index + match[0].length;
          }
          fragment.append(document.createTextNode(node.textContent.slice(offset))); node.replaceWith(fragment);
        }
        html = template.innerHTML;
      }
      knowledgeAnswerMarkup.set(message, { text, signature, html }); return html;
    },
    openAnswerCitation(event, message) {
      const button = event.target.closest('button[data-citation-id]');
      if (!button || !event.currentTarget.contains(button)) return;
      const reference = message.references.find(ref => String(ref.id) === button.dataset.citationId);
      if (reference) this.openCitation({ document_id: reference.document_id, title: reference.title, references: [reference] });
    },
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
      if(data.session_id && Array.isArray(data.document_ids)){const departments=[...new Set(data.document_ids.map(id=>this.documents.find(doc=>doc.id===id)).filter(Boolean).map(doc=>this.itemDepartment(doc)))];this.departmentFilter=departments.length===1?departments[0]||'unassigned':'';}else if(data.session_id)this.departmentFilter='';
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
    async exportAnswer(message, format, tableIndex = 0, valueColumn = null) {
      if (!message.id || message.exportBusy || message.redacted || !message.complete || this.busy) return;
      const sessionId = this.chatSessionId, generation = this.chatGeneration;
      const sentToken = localStorage.getItem('accessToken'); message.exportBusy = true;
      try {
        const response = await this.apiFetch('/company-knowledge/conversations/' + encodeURIComponent(sessionId) + '/messages/' + message.id + '/export', {
          method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({format,table_index:tableIndex,value_column:valueColumn})
        });
        if (!response.ok) { const data = await response.json(); throw new Error(data.detail || '文件生成失败，请重试。'); }
        const blob = await response.blob();
        if (this.chatDisposed || generation !== this.chatGeneration || sessionId !== this.chatSessionId || sentToken !== localStorage.getItem('accessToken')) return;
        const url = URL.createObjectURL(blob), link = document.createElement('a');
        link.href = url; link.download = '知识库回答-' + message.id + (format === 'xlsx' ? '-表格' + (tableIndex+1) : '') + '.' + format;
        document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (error) { if (!this.chatDisposed && generation === this.chatGeneration) ElementPlus.ElMessage.error(error.message); }
      finally { message.exportBusy = false; }
    },
    answerTables(message) { return this.answerBlocks(message.text).filter(block => block.type === 'table'); },
    chartColumns(table) {
      return table.headers.map((name,index) => ({name,index})).filter(({name,index}) => index > 0 && !/年份|年度|日期|编号|序号|代码|引用|来源/.test(name) && table.rows.some(row => /^[+-]?[\d,]+(?:\.\d+)?\s*[^\d\s]{0,8}$/.test((row[index] || '').replace(/\[id_[^\]]+\]/g,'').replace(/\*\*/g,'').trim())));
    },
    async sendQuestion(question) {
      const content = (typeof question === 'string' ? question : this.draft).trim();
      if (!content || this.busy || this.chatHistoryBusy || !this.canAsk) return;
      if(this.chatCollection==='library'&&this.departmentFilter&&!this.selectedIds.length){this.chatError='部门资料范围尚未确认，请返回资料位置重新选择后提问。';return;}
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
          if (event.type === 'saved') answer.id = event.message_id;
          if (event.type === 'evidence_scope') answer.evidenceScope = event.message;
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
      <nav class="ckb-navigation" aria-label="知识库导航"><div v-if="departmentPage" class="ckb-directory-path" role="navigation" aria-label="当前部门位置"><button type="button" aria-label="返回公司知识库" :disabled="busy" @click="openHome">公司知识库</button><i class="fa-solid fa-angle-right" aria-hidden="true"></i><span aria-current="page">{{ departmentName }}</span></div><div v-show="!departmentPage" class="ckb-tabs" role="tablist" aria-label="知识库视图" @keydown="navigateTabs"><span class="ckb-tab-indicator" aria-hidden="true" :style="tabIndicatorStyle"></span>
        <button id="ckb-home-tab" role="tab" aria-label="知识库首页" :aria-selected="mode === 'home'" :tabindex="mode === 'home' ? 0 : -1" :class="{ active: mode === 'home' }" @click="openHome"><i class="fa-solid fa-compass" aria-hidden="true"></i><span class="ckb-tab-copy"><strong>知识库首页</strong></span></button>
        <button id="ckb-library-tab" role="tab" aria-label="总资料库" :aria-selected="mode === 'library'" :tabindex="mode === 'library' ? 0 : -1" :class="{ active: mode === 'library' }" @click="browseLibrary"><i class="fa-solid fa-layer-group" aria-hidden="true"></i><span class="ckb-tab-copy"><strong>总资料库</strong></span><em>{{ libraryCount }}</em></button>
        <button id="ckb-chat-tab" role="tab" aria-label="智能问答" :aria-selected="mode === 'chat'" :tabindex="mode === 'chat' ? 0 : -1" :class="{ active: mode === 'chat' }" @click="openChat"><i class="fa-solid fa-wand-magic-sparkles" aria-hidden="true"></i><span class="ckb-tab-copy"><strong>智能问答</strong></span></button>
        <button id="ckb-cases-tab" role="tab" aria-label="经验沉淀" :aria-selected="mode === 'cases'" :tabindex="mode === 'cases' ? 0 : -1" :class="{ active: mode === 'cases' }" @click="browseCases()"><i class="fa-solid fa-cubes" aria-hidden="true"></i><span class="ckb-tab-copy"><strong><span class="ckb-experience-dot" aria-hidden="true"></span>经验沉淀</strong></span><em>{{ caseCount }}</em></button>
      </div><div class="ckb-nav-actions"><button class="ckb-request-center-button" @click="openRecycle()" aria-label="回收站"><i class="fa-solid fa-trash-can" aria-hidden="true"></i>回收站</button><button class="ckb-theme-toggle" aria-label="切换知识库主题" :aria-pressed="theme === 'dark'" :title="theme === 'light' ? '切换为深色主题' : '切换为浅色主题'" @click="setTheme(theme === 'light' ? 'dark' : 'light')"><i :class="theme === 'light' ? 'fa-regular fa-moon' : 'fa-regular fa-sun'" aria-hidden="true"></i></button><button v-if="service.is_admin" class="ckb-request-center-button" aria-label="操作记录" @click="openAudit()"><i aria-hidden="true" class="fa-solid fa-clock-rotate-left"></i>操作记录</button><button class="ckb-request-center-button" @click="requestCenterOpen = true; loadAccessRequests()"><i aria-hidden="true" class="fa-regular fa-bell"></i>{{ service.is_admin ? '权限审批' : '我的申请' }}<span v-if="pendingAccessCount">{{ pendingAccessCount }}</span></button><span class="ckb-connection" role="status" :title="canAsk ? '知识库已连接' : serviceError ? '连接未就绪' : '正在连接知识库'" :aria-label="canAsk ? '知识库已连接' : serviceError ? '连接未就绪' : '正在连接知识库'"><span :class="{ online: canAsk }"></span><span v-if="!canAsk">{{ serviceError ? '连接未就绪' : '正在连接知识库' }}</span></span></div></nav>
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
            <li v-for="doc in homeActivityDocuments" :key="doc.id"><span class="ckb-simple-format" role="img" :aria-label="doc.format || '文件'" :title="doc.format || '文件'"><i :class="['ckb-file-type-icon', 'filetype-' + fileTypeKind(doc), fileTypeIcon(doc)]" aria-hidden="true"></i></span><button class="ckb-simple-file-name" :title="displayDocumentTitle(doc)" @click="openDocument(doc)"><strong>{{ displayDocumentTitle(doc) }}</strong><span>{{ doc.project || doc.category || '未归类' }}</span></button><div class="ckb-simple-file-meta"><span class="ckb-simple-review">{{ doc.review || '待复核' }}</span><time>{{ doc.date }}</time></div></li>
          </ul>
          <div v-else class="ckb-simple-empty"><strong>{{ loading ? '正在加载资料…' : homeActivityTab === 'viewed' ? '暂无浏览记录' : '暂无可访问资料' }}</strong><button class="ckb-simple-button" @click="openHomeLibrary">打开资料库</button></div>
        </section>
        <section class="ckb-home-projects" aria-label="常用项目"><header><h3>常用项目</h3><button class="ckb-simple-link" @click="browseLibrary">全部项目 <i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></header><p v-if="projectLoading && !collectionProjects.length" role="status">正在加载项目…</p><p v-else-if="!collectionProjects.length">暂无可访问项目</p><button v-for="project in collectionProjects.slice(0,6)" :key="project.id" class="ckb-home-project-link" @click="openDirectory(project)"><i class="fa-regular fa-folder-open" aria-hidden="true"></i><span>{{ project.name }}</span><small>{{ project.document_count }} 份资料</small><i class="fa-solid fa-angle-right" aria-hidden="true"></i></button></section>
        </div>
      </section>
      <section v-if="mode === 'library' || mode === 'cases'" :key="mode" class="ckb-library-layout ckb-view-panel" :class="{ 'ckb-cases-layout': mode === 'cases' }" :role="departmentPage ? 'region' : 'tabpanel'" :aria-label="departmentPage ? departmentName + '资料' : undefined" :aria-labelledby="departmentPage ? undefined : mode === 'cases' ? 'ckb-cases-tab' : 'ckb-library-tab'">
        <aside class="ckb-library-sidebar"><div class="ckb-rail-brand"><span><i aria-hidden="true" :class="mode === 'cases' ? 'fa-solid fa-cubes' : 'fa-solid fa-layer-group'"></i></span><div>{{ mode === 'cases' ? '经验档案' : '资料空间' }}</div></div><span class="ckb-aside-label">知识分类</span>
          <button v-for="item in visibleCategories" :key="item" :class="{ active: category === item && !mineOnly && !favoritesOnly }" @click="selectCategory(item)">{{ item === '全部资料' && mode === 'cases' ? '全部经验' : item }}<small>{{ item === '全部资料' ? (mode === 'cases' ? caseCount : collectionDocuments.length) : collectionDocuments.filter(doc => doc.category === item).length }}</small></button>
          <div class="ckb-sidebar-divider"></div><span class="ckb-aside-label">我的工作</span>
          <button v-if="mode==='cases'" :class="{active:mineOnly}" @click="browseMyNotes">我的笔记<small>{{myExperienceCount}}</small></button><button v-else :class="{ active: mineOnly }" @click="browseMyProject()">我的项目<small>{{ collectionMineCount }}</small></button>
          <button :class="{ active: favoritesOnly }" @click="selectFavorites">我的收藏<small>{{ collectionFavoritesCount }}</small></button>
          <button :class="{ active: statusFilter === 'failed' }" @click="selectFailed">处理失败<small>{{ failedCount }}</small></button>
          <p>资料按账号权限展示。项目和行业用于归类筛选。</p>
        </aside>
        <div class="ckb-library-content" tabindex="0" @contextmenu="directoryFileContext($event)" @keydown="directoryFileKey" :class="{'ckb-sparse-space': showingProjects ? visibleProjectDirectories.length &lt; 3 : filteredDocuments.length &lt; 3}"><div class="ckb-archive-scene" aria-hidden="true"><svg viewBox="0 0 600 500" fill="none"><g stroke="currentColor" stroke-width="1"><circle cx="310" cy="248" r="186" stroke-dasharray="3 12"/><circle cx="310" cy="248" r="150"/><path d="M85 248H535M310 23V473" stroke-dasharray="2 9"/><path d="M202 190V165Q202 153 214 153H273L296 174H409Q421 174 421 186V333Q421 345 409 345H214Q202 345 202 333Z"/><path d="M233 220V147Q233 139 241 139H341L374 171V220M341 139V174H374M255 181H312M255 195H344"/><path d="M190 220H432L416 337Q415 345 405 345H218Q208 345 207 336Z"/><path d="M280 273L310 257L340 273L310 289ZM280 285L310 301L340 285M280 297L310 313L340 297"/><path d="M116 178H164L190 220M432 272H473L500 302M292 345V389H358"/><circle cx="116" cy="178" r="4"/><circle cx="500" cy="302" r="4"/><circle cx="358" cy="389" r="4"/></g></svg></div><nav v-if="!showingProjects" class="ckb-directory-path" aria-label="项目目录路径"><button class="ckb-directory-up" aria-label="返回上一级" @click="goUpDirectory"><i class="fa-solid fa-arrow-left" aria-hidden="true"></i>返回上一级</button><span class="ckb-breadcrumb-divider" aria-hidden="true">|</span><button :title="mode==='cases'?'返回经验空间':'返回项目空间'" @click="showProjectRoot">{{mode==='cases'?'经验空间':departmentPage?departmentName:'项目空间'}}</button><template v-if="activeProject"><i class="fa-solid fa-angle-right" aria-hidden="true"></i><button v-if="activeFolderId" :title="'返回项目：'+activeProject.name" @click="openDirectory(activeProject)">{{ activeProject.name }}</button><span v-else aria-current="page">{{ activeProject.name }}</span><template v-for="(folder,index) in directoryBreadcrumbs" :key="folder.id"><i class="fa-solid fa-angle-right" aria-hidden="true"></i><button v-if="index<directoryBreadcrumbs.length-1" :title="'返回目录：'+folder.name" @click="openDirectory(activeProject,folder.id)">{{ folder.name }}</button><span v-else aria-current="page">{{ folder.name }}</span></template></template><span v-else aria-current="page">{{mode==='cases'&&mineOnly?'我的笔记':favoritesOnly?'我的收藏':statusFilter==='failed'?'处理失败':mode==='cases'?'经验资料':departmentPage?'本部门全部文件':'全部文件'}}</span></nav><header class="ckb-library-heading"><div><h2>{{ searchMode === 'content' ? '正文搜索' : activeProject ? (directoryBreadcrumbs.at(-1)?.name || activeProject.name) : mode==='cases'&&mineOnly ? '我的笔记' : showingProjects ? (mineOnly ? '我的项目' : mode === 'cases' ? '经验空间' : departmentName || '项目空间') : favoritesOnly ? '我的收藏' : statusFilter==='failed' ? '处理失败' : mode==='cases' ? '经验资料' : departmentPage ? '本部门全部文件' : '全部文件' }}</h2><span class="ckb-heading-count">{{ searchMode === 'content' ? (contentSearched ? contentTotal + ' 个片段' : '当前库') : mode==='cases'&&mineOnly ? libraryRows.length+' 条笔记与经验' : showingProjects ? visibleProjectDirectories.length + ' 个项目 · ' + filteredDocuments.length + ' 份独立文件' : visibleFolders.length + ' 个目录 · ' + libraryRows.length + ' 条资料' }}</span></div><div class="ckb-library-tools"><button v-if="fileClipboard" class="ckb-button ckb-button-outline" :disabled="!canPasteFiles" @click="pasteFile"><i class="fa-regular fa-paste" aria-hidden="true"></i>{{clipboardBusy?'粘贴中…':'粘贴'}}</button><label class="ckb-search"><i aria-hidden="true" class="fa-solid fa-magnifying-glass"></i><input v-model="query" aria-label="搜索知识库资料" :placeholder="searchMode === 'content' ? '搜索正文内容，按 Enter 查看相关片段' : activeProject ? '搜索当前目录及下级的文件或目录' : mode==='cases' ? '搜索经验、笔记或项目' : departmentPage ? '搜索本部门的项目或文件' : '搜索项目或文件'" @keydown.enter="searchMode === 'content' &amp;&amp; searchContent()"><button v-if="query" aria-label="清空搜索" @click="query = ''">×</button></label><button class="ckb-button ckb-button-outline ckb-refresh-action" aria-label="刷新" :title="loading ? '正在刷新资料' : '刷新资料'" :disabled="loading || !canAsk" @click="loadDocuments(false, true)"><i class="fa-solid fa-rotate-right" :class="{'fa-spin':loading}" aria-hidden="true"></i><span>{{ loading ? '加载中…' : '刷新' }}</span></button><template v-if="activeProject"><button class="ckb-button ckb-button-outline" :disabled="!activeProject.can_manage || !canAsk" :aria-describedby="!activeProject.can_manage ? 'ckb-directory-write-policy' : undefined" :title="activeProject.can_manage ? '在当前目录下新建目录' : '仅项目创建者或管理员可新建目录'" @click="startFolderEditor()"><i class="fa-solid fa-folder-plus" aria-hidden="true"></i>{{ activeFolderId ? '新建子目录' : '新建目录' }}</button><button v-if="activeProject.can_manage" class="ckb-directory-settings" aria-label="编辑项目" title="项目设置" @click="startProjectEditor(activeProject)"><i class="fa-solid fa-sliders" aria-hidden="true"></i></button><button class="ckb-button ckb-button-primary" aria-label="上传文件" :disabled="!activeProject.can_manage || !canAsk" :aria-describedby="!activeProject.can_manage ? 'ckb-directory-write-policy' : undefined" :title="activeProject.can_manage ? '上传到当前目录' : '仅项目创建者或管理员可上传文件'" @click="startUpload"><i class="fa-solid fa-plus" aria-hidden="true"></i>上传文件</button></template><template v-else><button class="ckb-button ckb-button-outline" :disabled="!canAsk" @click="startUpload"><i class="fa-solid fa-arrow-up-from-bracket" aria-hidden="true"></i>上传文件</button><button class="ckb-button ckb-button-primary" :disabled="!canAsk" @click="startProjectEditor()"><i class="fa-solid fa-plus" aria-hidden="true"></i>创建项目</button></template></div></header><p v-if="activeProject &amp;&amp; !activeProject.can_manage" id="ckb-directory-write-policy" class="ckb-directory-write-policy" role="status"><i class="fa-solid fa-lock" aria-hidden="true"></i>只读项目：仅项目创建者或管理员可新建目录、上传文件。</p><p v-if="projectError && !projectEditorOpen" class="ckb-service-error" role="alert">{{ projectError }} <button @click="loadProjectDirectories">重试加载项目</button></p>
          <div v-if="fileClipboard" class="ckb-file-clipboard" role="status"><span>{{fileClipboard.action==='cut'?'待移动':'待复制'}}：<strong>{{fileClipboard.title}}</strong></span><small>进入目标目录后粘贴 · {{fileClipboard.action==='cut'?'Ctrl+X':'Ctrl+C'}} / Ctrl+V</small><button :disabled="clipboardBusy" aria-label="取消待粘贴文件" @click="clearFileClipboard">取消</button></div>
          <div v-if="mode === 'cases'" class="ckb-case-intro"><div class="ckb-note-tools"><button class="ckb-button ckb-button-outline" :disabled="noteCreating || !!openingDirectoryId || !canAsk || (activeProject && !activeProject.can_manage)" @click="createRichNote"><i class="fa-solid fa-pen-to-square" aria-hidden="true"></i>{{noteCreating?'正在创建…':'新建图文笔记'}}</button><button class="ckb-button ckb-button-outline" :disabled="!canAsk" title="记录到自己的经验空间" @click="openQuickCapture"><i class="fa-solid fa-pen-nib" aria-hidden="true"></i>随手记录</button></div></div><p v-if="mode==='cases' && noteError" class="ckb-service-error" role="alert">{{noteError}}<button @click="loadNotes">重试</button></p>
          <div v-if="libraryIntent === 'compare'" class="ckb-compare-intent" role="status"><div><strong>先选择资料，再比较结论</strong><span>勾选至少 2 份可检索资料，下一步进入问答确认比较问题。</span></div><button @click="libraryIntent = ''">退出比较</button></div>

          <section v-if="statusFilter === 'failed' &amp;&amp; !activeProjectId &amp;&amp; retryTrackedDocuments.length" class="ckb-retry-receipts" aria-label="最近重试的资料"><header><button type="button" class="ckb-retry-toggle" :aria-expanded="retryReceiptsExpanded" aria-controls="ckb-retry-receipt-details" @click="setRetryReceiptsExpanded(!retryReceiptsExpanded)"><strong>最近重试</strong><span class="ckb-retry-summary">{{retryReceiptSummary}}</span><small class="ckb-retry-latest" :title="retryTrackedDocuments[0].title">最新：{{retryTrackedDocuments[0].title}}</small><span class="ckb-retry-toggle-label">{{retryReceiptsExpanded?'收起':'展开'}}<i class="fa-solid" :class="retryReceiptsExpanded?'fa-chevron-up':'fa-chevron-down'" aria-hidden="true"></i></span></button></header><div v-show="retryReceiptsExpanded" id="ckb-retry-receipt-details"><p class="ckb-retry-explanation">重试沿用原位置。处理完成后会退出失败列表，结果仍可在这里查看。</p><article v-for="doc in retryTrackedDocuments" :key="doc.id" :data-retry-document-id="doc.id"><div><strong>{{doc.title}}</strong><small>{{documentLocationLabel(doc)}}</small><span :class="'ckb-retry-result-'+doc.state">{{retryResultLabel(doc)}}</span></div><nav :aria-label="'重试结果操作：'+doc.title"><button v-if="canOpenDocumentDirectory(doc)" @click="openDocumentDirectory(doc)">打开所在目录</button><span v-else :title="documentDirectoryReason(doc)">仅文件阅读权，未开放项目目录</span><button @click="openDocument(doc)">查看文件</button><button v-if="doc.state==='failed'" @click="showFailureDetails(doc)">失败详情</button></nav></article></div></section>
          <section v-if="!activeProjectId &amp;&amp; !(mode==='cases' &amp;&amp; (mineOnly || statusFilter==='failed'))" class="ckb-catalog-controls" aria-label="搜索与筛选">
            <div class="ckb-catalog-toolbar"><output v-if="departmentPage &amp;&amp; fixedDepartmentContext" aria-label="当前所属部门／栏目">{{ departmentName }}</output><select v-else-if="mode!=='cases'" :value="departmentFilter" :disabled="busy" @change="setDepartmentFilter($event.target.value)" aria-label="筛选所属部门／栏目"><option value="">全部部门／栏目</option><option v-for="item in departmentOptions" :key="item.id" :value="item.id">{{item.label}}</option><option value="unassigned">待归类</option></select><select v-model="industryFilter" aria-label="筛选行业"><option value="">全部行业</option><option v-for="item in industryOptions" :key="item">{{ item }}</option></select><select v-model="reviewFilter" aria-label="筛选复核状态"><option value="">全部复核状态</option><option>待复核</option><option>已复核</option><option>参考资料</option></select><button type="button" class="ckb-more-filters" :aria-expanded="advancedFiltersOpen" aria-controls="ckb-catalog-advanced" @click="advancedFiltersOpen = !advancedFiltersOpen">更多筛选<span v-if="advancedFilterCount" class="ckb-filter-count">{{ advancedFilterCount }}</span><i class="fa-solid" :class="advancedFiltersOpen ? 'fa-chevron-up' : 'fa-chevron-down'" aria-hidden="true"></i></button><button type="button" class="ckb-clear-filters" aria-label="清空筛选" title="清空筛选" @click="resetFilters">清空</button><button v-if="showingProjects" type="button" class="ckb-catalog-files" @click="showAllFiles">{{departmentPage?'本部门全部文件':'全部文件'}}<i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></div>
            <div v-show="advancedFiltersOpen" id="ckb-catalog-advanced" class="ckb-catalog-advanced"><div class="ckb-catalog-date"><span>时间范围</span><div class="ckb-date-filter"><select v-model="dateField" aria-label="时间类型"><option value="created_at">上传时间</option><option value="modified_at">更新时间</option></select><input type="date" v-model="dateFrom" aria-label="开始日期" :max="dateTo || undefined"><span>至</span><input type="date" v-model="dateTo" aria-label="结束日期" :min="dateFrom || undefined"></div></div></div>
          </section>

          <div class="ckb-selection-bar" :class="{'has-selection':selectionCount}"><span v-if="!selectionCount" class="ckb-selection-hint"><i class="fa-regular fa-square-check" aria-hidden="true"></i>勾选项目或文件，限定问答范围</span><span v-if="selectionCount" class="ckb-scope-counter"><i aria-hidden="true" class="fa-solid fa-crosshairs"></i>{{ selectionCount ? '已选 '+selectionSummary+((selectedProjectIds.length||selectedFolderIds.length)?'（含下级目录）':'') : '' }}</span><div><select v-model="sortOrder" aria-label="资料排序"><option value="updated">最近更新</option><option value="title">名称排序</option></select><button v-if="selectionCount" :disabled="busy || selectionBusy" @click="clearSelection">取消选择</button><button class="ckb-button ckb-button-primary" :disabled="!canAsk || busy || selectionBusy || (libraryIntent === 'compare' && selectedIds.length < 2)" @click="askLibrary">{{ selectionBusy?'正在准备资料…':selectionCount?'向所选范围提问':activeProject?'向当前目录提问':mode==='cases'&&mineOnly?'向我的笔记提问':(mode==='cases'?'检索全部经验':departmentPage?'检索本部门资料':'检索全部资料') }} <i aria-hidden="true" class="fa-solid fa-arrow-right"></i></button></div></div>
          <div v-if="showingProjects" ref="documentTable" class="ckb-directory-grid ckb-table-scroll ckb-directory-stage" aria-label="项目目录" role="list">
            <div v-if="pagedProjectDirectories.length" class="ckb-project-list-head" aria-hidden="true"><span>项目名称</span><span>类别</span><span>时间</span><span>操作</span></div>
            <el-popover v-for="project in pagedProjectDirectories" :key="project.id" placement="right-start" strategy="fixed" transition="none" :reference-el="projectPreview.reference || undefined" :fallback-placements="['left-start','right-end','left-end','bottom-start','top-start']" :width="400" :visible="projectPreview.id === project.id" :trigger="[]" :show-after="0" :hide-after="0" :persistent="false" :show-arrow="false" :offset="14" :enterable="true" popper-class="ckb-project-detail-popover">
              <template #reference><article class="ckb-project-directory ckb-project-card-small ckb-project-row" @dblclick="openFromDoubleClick(project,$event)" role="listitem" :class="{ opening: openingDirectoryId === project.id }" :data-project-preview-row="project.id" tabindex="0" :aria-label="'项目详情：' + project.name" @pointerenter="queueProjectPreview(project, $event)" @pointermove="queueProjectPreview(project, $event)" @pointerleave="leaveProjectPreview(project, $event)" @focusin="focusProjectPreview(project, $event)" @focusout="leaveProjectPreview(project, $event)">
                <input class="ckb-directory-check" type="checkbox" :aria-label="'选择项目：'+project.name" title="包含全部下级目录中可访问且已完成索引的资料" :checked="selectedProjectIds.includes(project.id)" :disabled="busy||selectionBusy" @click.stop @dblclick.stop @change="toggleDirectorySelection('project',project.id)"><button type="button" class="ckb-project-door" :aria-label="'进入项目：' + project.name" @click.stop="dismissProjectPreview(); openDirectory(project)" @keydown.enter.stop @keydown.space.stop><h3 :title="project.name"><svg class="ckb-project-folder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M3.5 8.5V6.2c0-.9.7-1.7 1.7-1.7h4.1l2.1 2.1h7.4c.9 0 1.7.7 1.7 1.7v.2"/><path d="M4.2 8.5h15.6c1.1 0 1.9 1 1.6 2l-1.4 7.3c-.2.9-.9 1.5-1.8 1.5H5.8c-.9 0-1.6-.6-1.8-1.5l-1.4-7.3c-.3-1 .5-2 1.6-2Z"/></svg><span>{{ project.name }}</span></h3><div class="ckb-project-card-meta"><span>{{ project.category || '未分类' }}<template v-if="project.department &amp;&amp; !caseCategories.includes(project.category)"> · {{departmentLabel(project.department)}}</template></span><time :datetime="project.updated_at || project.modified_at || project.created_at" :title="project.updated_at || project.modified_at ? '更新时间' : '创建时间'">{{ projectCardDate(project.updated_at || project.modified_at || project.created_at) }}</time></div></button>
                <div class="ckb-project-card-actions"><button type="button" class="ckb-project-info" :data-project-preview-trigger="project.id" :aria-label="'查看详情：' + project.name" :aria-expanded="projectPreview.id === project.id" :aria-controls="'ckb-project-preview-' + project.id" @click.stop="toggleProjectPreview(project, $event)" @keydown.enter.stop @keydown.space.stop><i class="fa-solid fa-circle-info" aria-hidden="true"></i></button><button v-if="project.can_manage" type="button" class="ckb-project-edit" :aria-label="'编辑项目：' + project.name" @click.stop="dismissProjectPreview(); startProjectEditor(project)" @keydown.enter.stop @keydown.space.stop><span>设置</span><i class="fa-solid fa-chevron-down" aria-hidden="true"></i></button><span v-else class="ckb-read-only" title="你拥有阅读权限；仅创建者或管理员可修改和删除">只读</span></div>
              </article></template>
              <section :id="'ckb-project-preview-' + project.id" class="ckb-project-preview" :aria-label="'项目详情：' + project.name" @pointerenter="holdProjectPreview" @pointerleave="leaveProjectPreview(project, $event)" @focusin="holdProjectPreview" @focusout="leaveProjectPreview(project, $event)">
                <header class="ckb-project-preview-header"><span class="ckb-preview-folder" aria-hidden="true"><svg class="ckb-preview-folder-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M3.5 8.5V6.2c0-.9.7-1.7 1.7-1.7h4.1l2.1 2.1h7.4c.9 0 1.7.7 1.7 1.7v.2"/><path d="M4.2 8.5h15.6c1.1 0 1.9 1 1.6 2l-1.4 7.3c-.2.9-.9 1.5-1.8 1.5H5.8c-.9 0-1.6-.6-1.8-1.5l-1.4-7.3c-.3-1 .5-2 1.6-2Z"/></svg></span><div><strong>{{ project.name }}</strong><div class="ckb-project-preview-labels"><span>{{ project.category || '未分类' }}<template v-if="project.department &amp;&amp; !caseCategories.includes(project.category)"> · {{departmentLabel(project.department)}}</template></span><span v-if="project.confidentiality">{{ {internal:'内部',secret:'机密'}[project.confidentiality] || '机密' || project.confidentiality }}</span></div></div><button type="button" class="ckb-project-preview-close" aria-label="关闭项目简介" @click="dismissProjectPreview(true)"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button></header>
                <div class="ckb-project-preview-content"><p class="ckb-project-preview-description" :class="{'is-empty':!project.description}">{{ project.description || '暂无项目简介' }}</p><div class="ckb-project-preview-stats"><div><strong>{{ project.folder_count ?? '—' }}</strong><span>目录</span></div><div><strong>{{ project.document_count ?? '—' }}</strong><span>资料</span></div></div><dl><div v-if="project.industry"><dt>行业</dt><dd>{{ project.industry }}</dd></div><div v-if="project.owner"><dt>创建人</dt><dd>{{ project.owner }}</dd></div><div><dt>{{ project.updated_at || project.modified_at ? '更新于' : '创建于' }}</dt><dd>{{ projectCardDate(project.updated_at || project.modified_at || project.created_at, true) }}</dd></div></dl><div v-if="project.tags?.length" class="ckb-project-preview-tags"><span v-for="tag in project.tags" :key="tag">{{ tag }}</span></div></div>
                <p v-if="!project.can_manage" class="ckb-project-preview-access">你拥有阅读权限；仅项目创建者或管理员可修改和删除。</p>
                <footer class="ckb-project-preview-footer"><button type="button" @click="dismissProjectPreview(); openDirectory(project)">打开项目<i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></footer>
              </section>
            </el-popover>
            <knowledge-upload-progress-row v-for="item in visibleUploadTasks" :key="item.client_id" :item="item" @open="uploadOpen=true"/>
            <article v-for="doc in pagedDocuments" :key="doc.id" :data-document-id="doc.id" tabindex="0" @contextmenu="openFileContext(doc,$event)" @keydown="fileRowKey(doc,$event)" :class="{'ckb-file-cut':fileClipboard?.action==='cut' &amp;&amp; fileClipboard.id===doc.id}" class="ckb-root-file-row" role="listitem" @dblclick="openFileFromDoubleClick(doc,$event)"><input class="ckb-directory-check" type="checkbox" :aria-label="'选择资料：'+doc.title" :checked="selectedIds.includes(doc.id)" :disabled="busy||selectionBusy||!doc.can_read||doc.state!=='ready'" @click.stop @dblclick.stop @change="toggleSelection(doc)"><button class="ckb-root-file-door" @click="openDocument(doc)"><i :class="['ckb-file-type-icon', 'filetype-' + fileTypeKind(doc), fileTypeIcon(doc)]" aria-hidden="true"></i><span><strong>{{ displayDocumentTitle(doc) }}</strong><small>{{ doc.format }} · {{ sizeLabel(doc.size || 0) }} · V{{ doc.version }} · {{ doc.confidentiality_label || '内部' }}</small></span></button><span class="ckb-root-file-state" :title="doc.status_message"><span :class="['ckb-state','ckb-state-'+(doc.can_read?doc.state:'locked')]">{{ knowledgeState(doc) }}</span></span><time>{{ doc.date }}</time><div class="ckb-root-file-actions"><knowledge-failure-actions :doc="doc" :retry-busy="operationPending('retry:'+doc.id)" @retry="retryDocument" @reupload="startReupload" @remove="deleteDocument" @edit-note="editRichNote" @details="showFailureDetails"/><button v-if="doc.can_read" class="ckb-read-action" @click.stop="openDocument(doc)">{{ doc.media_kind ? '播放' : '阅读' }}</button><knowledge-file-menu :can-copy="canClipboardDocument(doc)" @copy="putFileClipboard($event,'copy')" @cut="putFileClipboard($event,'cut')" @history="showFileVersions" :doc="doc" :can-move="canMoveDocument(doc)" @move="startMove" @manage="editDocument" @remove="deleteDocument"/><button v-if="!doc.can_read" @click="requestAccess(doc)">{{ doc.request_status === 'pending' ? '审批中' : '申请权限' }}</button></div></article>
            <div v-if="!visibleProjectDirectories.length && !filteredDocuments.length && !visibleUploadTasks.length" class="ckb-space-empty ckb-project-empty-small"><h3>{{ loading ? '正在加载项目…' : directorySearchActive ? '没有匹配的项目' : '暂无项目' }}</h3><div class="ckb-space-empty-actions"><button v-if="directorySearchActive" class="ckb-button ckb-button-outline" @click="resetFilters">清除筛选</button><button class="ckb-button ckb-button-primary" :disabled="!canAsk || loading" @click="startProjectEditor()"><i class="fa-solid fa-plus" aria-hidden="true"></i>创建项目</button></div></div><p v-if="projectError" class="ckb-service-error" role="alert">{{ projectError }}<button @click="loadProjectDirectories">重新加载</button></p>
          </div>
          <div v-else ref="documentTable" class="ckb-table-scroll" tabindex="0" aria-label="资料列表，可滚动"><div v-if="visibleFolders.length" class="ckb-folder-rail"><article v-for="folder in visibleFolders" :key="folder.id" class="ckb-subfolder-card" @dblclick="openFromDoubleClick(activeProject, $event, folder.id)" :class="{ opening: openingDirectoryId === folder.id }"><input class="ckb-directory-check" type="checkbox" :aria-label="'选择目录：'+folder.name" title="包含下级目录中可访问且已完成索引的资料" :checked="selectedFolderIds.includes(folder.id)" :disabled="busy||selectionBusy" @click.stop @dblclick.stop @change="toggleDirectorySelection('folder',folder.id)"><button @click.stop="openDirectory(activeProject, folder.id)"><knowledge-folder-artwork/><strong>{{ folder.name }}</strong><small>{{ projectFolders.filter(item => item.parent_id === folder.id).length }} 个子目录 · {{ documents.filter(doc => doc.folder_id === folder.id).length }} 份资料</small><i class="fa-solid fa-angle-right" aria-hidden="true"></i></button><button v-if="activeProject.can_manage" class="ckb-folder-edit" :aria-label="'编辑目录：' + folder.name" @click="startFolderEditor(folder)"><i class="fa-solid fa-ellipsis" aria-hidden="true"></i></button></article></div><table v-if="visibleUploadTasks.length || libraryRows.length || !visibleFolders.length" class="ckb-document-table"><thead><tr><th class="ckb-check-column"></th><th>资料名称</th><th>项目 / 行业</th><th>复核与索引</th><th>更新 / 版本</th><th>操作</th></tr></thead><tbody>
            <tr v-for="item in visibleUploadTasks" :key="item.client_id" class="ckb-upload-pending-table-row"><td colspan="6"><knowledge-upload-progress-row :item="item" @open="uploadOpen=true"/></td></tr>
            <template v-for="row in pagedLibraryRows" :key="row.kind+':'+row.id">
            <tr v-if="row.kind==='note'" :class="{selected:row.document && selectedIds.includes(row.document.id)}">
              <td><input type="checkbox" :aria-label="'选择笔记：'+row.title" :checked="!!row.document && selectedIds.includes(row.document.id)" :disabled="busy || selectionBusy || !row.document || row.document.state!=='ready'" :title="row.document?.state==='ready'?'将已发布版本加入提问范围':'发布并完成索引后可加入提问范围'" @change="toggleSelection(row.document)"></td>
              <td class="ckb-name-cell"><button @click="editRichNote(row.id)"><i class="fa-solid fa-file-pen ckb-file-type-icon" aria-hidden="true"></i><strong>{{row.title}}</strong></button><div>图文笔记 <span v-if="!row.note.published_revision" title="草稿仅项目创建者与管理员可见">· 私有草稿</span><span v-else-if="row.note.has_unpublished_changes">· 有未发布修改</span></div></td>
              <td>{{row.project?.name || '未归档项目'}}<small>{{row.project?.industry || '未标记行业'}}</small></td>
              <td><span class="ckb-state" :class="'ckb-state-'+(row.note.index_state==='failed'?'failed':row.note.indexed_revision?'ready':'queued')">{{row.note.index_state==='failed'?'处理失败':!row.note.published_revision?'草稿':row.note.indexed_revision?'已发布':'发布处理中'}}</span><small v-if="row.note.index_state==='failed'" class="ckb-failure-reason">{{row.note.index_message || '发布处理失败，可编辑并重试发布，或删除笔记。'}}</small><small>{{row.document?.review || '尚未发布'}}</small></td>
              <td>{{new Date(row.modified_at).toLocaleDateString('zh-CN')}}<small>R{{row.note.revision}} · {{row.note.created_by}}</small></td>
              <td class="ckb-table-actions"><button @click="editRichNote(row.id)" :aria-label="'编辑笔记：'+row.title">{{row.note.index_state==='failed'?'编辑并重试发布':'编辑'}}</button><template v-if="row.document"><button :aria-label="(favorites.includes(row.document.id)?'取消收藏笔记：':'收藏笔记：')+row.title" @click="toggleFavorite(row.document.id)">{{favorites.includes(row.document.id)?'已收藏':'收藏'}}</button><button @click="openDocument(row.document)">阅读已发布版本</button></template><button class="ckb-delete-button" :disabled="noteDeleting" :aria-label="'删除笔记：'+row.title" @click="deleteRichNote(row.id)">删除</button></td>
            </tr><template v-else>
            <tr v-for="doc in [row.document]" :key="doc.id" :data-document-id="doc.id" tabindex="0" @contextmenu="openFileContext(doc,$event)" @keydown="fileRowKey(doc,$event)" @dblclick="openFileFromDoubleClick(doc,$event)" :class="{ selected: selectedIds.includes(doc.id), locked: !doc.can_read, 'ckb-file-cut':fileClipboard?.action==='cut' &amp;&amp; fileClipboard.id===doc.id }">
              <td><input type="checkbox" :checked="selectedIds.includes(doc.id)" :disabled="busy || !doc.can_read || doc.state !== 'ready'" :aria-label="'选择资料：' + doc.title" @change="toggleSelection(doc)"></td>
              <td class="ckb-name-cell"><button @click="openDocument(doc)"><i :class="['ckb-file-type-icon', 'filetype-' + fileTypeKind(doc), fileTypeIcon(doc)]" aria-hidden="true"></i><i v-if="!doc.can_read" class="fa-solid fa-lock ckb-file-lock" aria-label="无访问权限"></i><strong>{{ displayDocumentTitle(doc) }}</strong></button><div>{{mode==='cases'?'文件 · ':''}}{{ doc.format }} · {{ sizeLabel(doc.size || 0) }} <span> · {{ doc.category }} · <b :class="['ckb-confidentiality', 'level-' + doc.confidentiality]">{{ doc.confidentiality_label || '内部' }}</b></span></div><div v-if="doc.tags?.length || (doc.can_read &amp;&amp; itemDepartment(doc) &amp;&amp; !caseCategories.includes(doc.category))" class="ckb-doc-tags"><span v-if="doc.can_read &amp;&amp; itemDepartment(doc) &amp;&amp; !caseCategories.includes(doc.category)" class="ckb-static-tag">{{departmentLabel(itemDepartment(doc))}}</span><template v-for="tag in doc.tags" :key="tag"><span v-if="activeProjectId" class="ckb-static-tag"># {{ tag }}</span><button v-else @click="tagFilter = tag"># {{ tag }}</button></template></div></td>
              <td><button v-if="canOpenDocumentDirectory(doc)" class="ckb-location-link" :title="documentLocationLabel(doc)" :aria-label="'打开所在目录：'+doc.title" @click.stop="openDocumentDirectory(doc)">{{documentLocationLabel(doc)}}</button><template v-else><span :title="documentDirectoryReason(doc)">{{documentLocationLabel(doc)}}</span><small>{{documentDirectoryReason(doc)}}</small></template><small>{{ doc.industry || '未标记行业' }}</small></td>
              <td><span :class="['ckb-state', 'ckb-state-' + (doc.can_read ? doc.state : 'locked')]" :title="doc.status_message">{{ knowledgeState(doc) }}</span><small v-if="doc.state==='failed' && doc.can_read" class="ckb-failure-reason">{{doc.status_message || '未返回具体原因，请查看失败详情。'}}</small><small :class="{ 'ckb-review-pending': doc.review === '待复核' }">{{ doc.review }}</small></td>
              <td><span>{{ doc.date }}</span><small>V{{ doc.version }} · {{ doc.owner || '云端导入' }}</small></td>
              <td class="ckb-table-actions"><template v-if="doc.can_read"><button class="ckb-favorite-action" :class="{'is-saved':favorites.includes(doc.id)}" :aria-label="favorites.includes(doc.id) ? '取消收藏' : '收藏资料'" :aria-pressed="favorites.includes(doc.id)" :title="favorites.includes(doc.id) ? '取消收藏' : '收藏资料'" @click="toggleFavorite(doc.id)"><i aria-hidden="true" :class="favorites.includes(doc.id) ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark'"></i></button><button class="ckb-read-action" @click="openDocument(doc)">{{ doc.media_kind ? '播放' : '阅读' }}</button></template><button v-else-if="doc.request_status === 'pending'" disabled>审批中</button><button v-else class="ckb-access-request" :disabled="operationPending('access:' + doc.id)" @click="requestAccess(doc)">{{ doc.request_status === 'rejected' ? '重新申请' : '申请权限' }}</button><knowledge-failure-actions :doc="doc" :retry-busy="operationPending('retry:'+doc.id)" @retry="retryDocument" @reupload="startReupload" @remove="deleteDocument" @edit-note="editRichNote" @details="showFailureDetails"/><knowledge-file-menu :can-copy="canClipboardDocument(doc)" @copy="putFileClipboard($event,'copy')" @cut="putFileClipboard($event,'cut')" @history="showFileVersions" :doc="doc" :can-move="canMoveDocument(doc)" @move="startMove" @manage="editDocument" @remove="deleteDocument"/></td>
            </tr>
            </template></template>
            <tr v-if="!libraryRows.length && !visibleUploadTasks.length"><td colspan="6" class="ckb-table-empty">{{ libraryEmptyMessage }}</td></tr>
          </tbody></table></div>
          <nav v-if="libraryRows.length &amp;&amp; searchMode !== 'content'" class="ckb-pagination" aria-label="资料分页"><span class="ckb-page-range">共 {{ libraryPageRange.total }} 条 · 第 {{ libraryPageRange.start }}–{{ libraryPageRange.end }} 条</span><div><select v-model.number="libraryPageSize" aria-label="每页资料数量"><option :value="10">10 条 / 页</option><option :value="20">20 条 / 页</option><option :value="50">50 条 / 页</option></select><button aria-label="上一页资料" :disabled="currentLibraryPage <= 1" @click="changeLibraryPage(currentLibraryPage - 1)"><i aria-hidden="true" class="fa-solid fa-angle-left"></i></button><button v-for="page in libraryPageNumbers" :key="page" :aria-label="'第 ' + page + ' 页资料'" :aria-current="page === currentLibraryPage ? 'page' : undefined" :class="{ active: page === currentLibraryPage }" @click="changeLibraryPage(page)">{{ page }}</button><button aria-label="下一页资料" :disabled="currentLibraryPage >= libraryPageCount" @click="changeLibraryPage(currentLibraryPage + 1)"><i aria-hidden="true" class="fa-solid fa-angle-right"></i></button><span class="ckb-page-total">{{ currentLibraryPage }} / {{ libraryPageCount }} 页</span></div></nav>

        </div>
      </section>
      <section v-if="mode === 'chat'" id="ckb-chat-panel" class="ckb-chat-layout ckb-view-panel" :class="{'is-generating': busy}" :role="departmentPage ? 'region' : 'tabpanel'" :aria-label="departmentPage ? departmentName + '智能问答' : undefined" :aria-labelledby="departmentPage ? undefined : 'ckb-chat-tab'">
        <aside class="ckb-chat-aside"><button v-if="returnLocation" class="ckb-return-location" :title="returnLocationLabel" :disabled="restoringView" :aria-busy="restoringView" @click="returnToBrowse"><i class="fa-solid" :class="restoringView?'fa-circle-notch fa-spin':'fa-arrow-left'" aria-hidden="true"></i><span>{{restoringView?'正在返回资料位置…':'返回资料位置'}}<small>{{ returnLocationLabel }}</small></span></button><div class="ckb-chat-space"><span><i class="fa-solid fa-fingerprint" aria-hidden="true"></i></span><div>你的研究空间<small>PRIVATE RESEARCH SPACE</small></div></div>
          <button class="ckb-button ckb-button-outline ckb-new-conversation" :disabled="busy || chatHistoryBusy" @click="startConversation"><i class="fa-solid fa-plus" aria-hidden="true"></i><span>开始新对话</span><i class="fa-solid fa-arrow-up-right-from-square" aria-hidden="true"></i></button>
          <section class="ckb-session-panel" aria-label="研究历史面板"><label class="ckb-aside-label" for="ckb-chat-history">研究历史</label>
          <select id="ckb-chat-history" aria-label="研究历史" v-model="chatSessionId" :disabled="busy || chatHistoryBusy" @change="loadChatHistory(chatSessionId)"><option value="">新研究对话</option><option v-for="session in chatSessions" :key="session.id" :value="session.id">{{ session.title }}</option></select>
          <div v-if="chatSessions.length" class="ckb-session-list"><button v-for="session in chatSessions.slice(0,6)" :key="session.id" :class="{active: chatSessionId === session.id}" :disabled="busy || chatHistoryBusy" :title="session.title" @click="loadChatHistory(session.id)"><i class="fa-regular fa-message" aria-hidden="true"></i><span>{{ session.title }}</span><i class="fa-solid fa-angle-right" aria-hidden="true"></i></button></div><div v-else class="ckb-session-empty"><i class="fa-regular fa-message" aria-hidden="true"></i><span>从一个问题开始，<br>研究历史会保存在这里。</span></div><div class="ckb-history-actions"><button :disabled="busy || chatHistoryBusy" @click="loadChatHistory(chatSessionId)">刷新对话</button><button :disabled="busy || chatHistoryBusy || !chatSessionId" @click="deleteConversation">删除当前对话</button></div>
          </section><section class="ckb-evidence-panel" aria-label="检索资料面板"><div class="ckb-aside-label"><i class="fa-solid fa-layer-group" aria-hidden="true"></i>检索范围</div><strong>{{ scopeLabel }}</strong>
          <p class="ckb-scope-note">{{ selectedIds.length ? '回答仅依据选中文件的检索片段。' : chatScope === 'my-projects' ? '按当前账号 ID 统计上传项目，只检索本人上传且已完成索引的资料。' : (chatCollection === 'experience' ? '仅检索经验沉淀，不调用资料库内容。' : '仅检索资料库，不调用经验沉淀内容。') }}</p>
          <button class="ckb-button ckb-button-outline" :disabled="busy" @click="chatCollection === 'experience' ? browseCases() : browseLibrary(); showAllFiles()">选择资料</button>
          <button v-if="selectedIds.length || ['my-projects','my-experience'].includes(chatScope)" class="ckb-button ckb-button-outline" :disabled="busy" @click="useAllChatSources">{{ chatCollection === 'experience' ? '改为全部经验' : '改为全部资料' }}</button>
          <button v-for="doc in selectedDocuments.slice(0,scopeFilesExpanded?1000:5)" :key="doc.id" :class="['ckb-reading-link', 'kind-' + fileAppearance(doc)]" @click="openDocument(doc)"><span class="ckb-scope-file-art" aria-hidden="true"><knowledge-file-artwork :format="doc.format" :kind="fileAppearance(doc)" :media-kind="doc.media_kind"/></span><span>{{ displayDocumentTitle(doc) }}</span></button><button v-if="selectedDocuments.length>5" class="ckb-simple-link" @click="scopeFilesExpanded=!scopeFilesExpanded">{{ scopeFilesExpanded?'收起资料列表':'查看全部 '+selectedDocuments.length+' 份资料' }}</button>
          </section><div class="ckb-chat-aside-foot">关键结论请核对引用；待复核稿需保留复核说明。</div>
        </aside>
        <div class="ckb-chat-main"><div class="ckb-chat-ambience" aria-hidden="true"><span></span><span></span><span></span></div>
          <header class="ckb-chat-header"><span><i aria-hidden="true" class="fa-solid fa-wand-magic-sparkles"></i><span>{{ chatCollection === 'experience' ? '经验助手' : '知识助手' }}<small>{{ chatCollection === 'experience' ? 'EXPERIENCE COPILOT' : '' }}</small></span></span><div class="ckb-chat-trust"><span class="ckb-live-presence"><b></b>{{ busy ? '正在研究' : '就绪' }}</span><span><i aria-hidden="true" class="fa-solid fa-shield-halved"></i>权限内检索</span><span><i aria-hidden="true" class="fa-solid fa-link"></i>引用可核查</span></div></header>
          <div v-if="memoryStatus || chatError" class="ckb-memory-status" :class="{'ckb-memory-error': chatError}" role="status">{{ chatError || memoryStatus }}</div>
          <div ref="chatFeed" class="ckb-chat-feed" @scroll.passive="onChatScroll" aria-live="polite" aria-relevant="additions">
            <button v-if="chatHasMore" class="ckb-button ckb-button-outline" :disabled="busy || chatHistoryBusy" @click="loadChatHistory(chatSessionId, true)">加载更早消息</button>
            <div v-if="!messages.length" class="ckb-chat-welcome">
              <div class="ckb-intelligence-visual" aria-hidden="true"><div class="ckb-neural-ring"></div><div class="ckb-neural-ring second"></div><div class="ckb-neural-card back"></div><div class="ckb-neural-card front"><i class="fa-solid fa-wand-magic-sparkles"></i><span></span><span></span></div><b class="ckb-neural-dot one"></b><b class="ckb-neural-dot two"></b></div><span class="ckb-welcome-eyebrow"></span>
              <h3>{{selectedIds.length?'向所选资料提问':chatScope==='my-projects'?'向我的项目提问':chatScope==='my-experience'?'向我的笔记提问':chatCollection==='experience'?'向经验沉淀提问':'向资料库提问'}}</h3><p>输入问题，回答将附上引用来源。</p><div class="ckb-welcome-scope"><i class="fa-solid fa-layer-group" aria-hidden="true"></i>{{ scopeLabel }}</div>
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
                <div v-if="!message.text &amp;&amp; !message.complete &amp;&amp; !message.error &amp;&amp; busy" class="ckb-thinking-ribbon" role="status"><span aria-hidden="true"><b></b><b></b><b></b><b></b><b></b></span>正在连接资料与问题…</div><div class="ckb-live-answer ckb-answer-markdown" v-html="renderAnswer(message)" @click="openAnswerCitation($event,message)"></div><p v-if="message.error" class="ckb-service-error" role="alert">{{ message.error }}</p>
                <div v-if="message.references.length" class="ckb-citation-heading">参考文件 <span>{{ referenceGroups(message.references).length }} 份文件 · {{ message.references.length }} 个片段</span></div>
                <button v-for="(group, n) in referenceGroups(message.references)" :key="group.key" :class="['ckb-citation', 'kind-' + fileAppearance(citationDocument(group))]" @click="openCitation(group)"><span>{{ n + 1 }}</span><span class="ckb-citation-file" aria-hidden="true"><knowledge-file-artwork :format="citationDocument(group).format" :kind="fileAppearance(citationDocument(group))" :media-kind="citationDocument(group).media_kind"/></span><div><strong>{{ group.title }}</strong><small>{{ group.references.length }} 个片段 · 引用 {{ referenceIds(group) }} · 点击展开</small></div><i aria-hidden="true" class="fa-solid fa-angle-right"></i></button>
                <p v-if="message.complete &amp;&amp; message.references.length" class="ckb-evidence-scope">{{ message.evidenceScope || '回答依据本轮检索片段，未逐份通读全部资料。' }}</p>
                <div v-if="message.complete &amp;&amp; message.text &amp;&amp; !message.redacted" class="ckb-answer-actions"><button @click="copyAnswer(message)" aria-label="复制回答"><i class="fa-regular fa-copy" aria-hidden="true"></i>复制回答</button><button v-if="message.id &amp;&amp; message.references.length" :disabled="message.exportBusy || busy" @click="exportAnswer(message,'docx')">{{message.exportBusy?'正在生成文件…':'下载 Word'}}</button><button v-if="message.id &amp;&amp; message.references.length &amp;&amp; !answerTables(message).length" :disabled="busy" @click="sendQuestion('请根据当前资料把刚才问题的答案整理为表格，每行注明来源引用，缺失项明确标注，保留单位和期间。')">整理成表格</button><span><i class="fa-solid fa-check" aria-hidden="true"></i>回答完成<span v-if="message.references.length"> · {{ referenceGroups(message.references).length }} 份参考文件</span></span></div>
                <div v-if="message.complete &amp;&amp; message.id &amp;&amp; !message.redacted &amp;&amp; message.references.length" class="ckb-answer-exports"><div v-for="(table,tableIndex) in answerTables(message)" :key="tableIndex" class="ckb-answer-export-row"><span>表格 {{tableIndex+1}}</span><button :disabled="message.exportBusy || busy" @click="exportAnswer(message,'xlsx',tableIndex)">下载 Excel</button><template v-if="chartColumns(table).length"><label>图表指标 <select :value="message.chartColumn?.[tableIndex] ?? chartColumns(table)[0].index" @change="message.chartColumn = {...(message.chartColumn || {}),[tableIndex]:Number($event.target.value)}" :aria-label="'表格'+(tableIndex+1)+'图表指标'"><option v-for="column in chartColumns(table)" :key="column.index" :value="column.index">{{column.name}}</option></select></label><button :disabled="message.exportBusy || busy" @click="exportAnswer(message,'png',tableIndex,message.chartColumn?.[tableIndex] ?? chartColumns(table)[0].index)">下载图表 PNG</button></template></div><small v-if="answerTables(message).length">Excel 附原文依据。图表要求同单位数值和有效行引用，不能直接核对的计算值会提示补充依据。</small></div>
              </template>
            </div>
          </div>
          <button v-if="messages.length &amp;&amp; !chatAtBottom" class="ckb-jump-latest" @click="scrollChat(true)"><i class="fa-solid fa-arrow-down" aria-hidden="true"></i>回到最新回答</button>
          <div class="ckb-composer-area"><div class="ckb-composer" :class="{'has-draft': draft.trim()}"><textarea ref="composer" v-model="draft" maxlength="1500" :disabled="!canAsk" aria-label="知识问答问题" placeholder="提问、梳理研究思路，或从一份资料开始…" rows="2" @keydown="onComposerKey"></textarea><div><span class="ckb-composer-scope"><i aria-hidden="true" class="fa-regular fa-folder-open"></i> {{ scopeLabel }}</span><span class="ckb-composer-signal" aria-hidden="true"><b><i></i><i></i><i></i><i></i></b><small>{{ busy ? '正在研究' : !canAsk ? '等待连接' : draft.trim() ? '可以发送' : '随时提问' }}</small></span><button v-if="busy" aria-label="停止生成" @click="controller?.abort()"><i aria-hidden="true" class="fa-solid fa-stop"></i></button><button v-else :disabled="!draft.trim() || !canAsk" aria-label="发送问题" @click="sendQuestion"><i aria-hidden="true" class="fa-solid fa-arrow-up"></i></button></div></div><p>Enter 发送 · Shift + Enter 换行 <span>{{ busy ? answerStatus : "请核对引用依据" }}</span></p></div>
        </div>
      </section>


      <knowledge-note-editor v-if="noteEditorId" :key="noteEditorId" :note-id="noteEditorId" :fetch-api="apiFetch" :username="service.username" @close="noteEditorId=''; loadNotes()" @changed="noteChanged" @delete="deleteRichNote($event)"/>
      <el-dialog v-model="recycleOpen" title="回收站 · 保留 10 天" width="min(760px, 94vw)" class="ckb-dialog ckb-recycle-dialog" append-to-body>
        <p>删除的文件、笔记、非空目录和项目保留 10 天。恢复目录或项目会一同恢复该次删除的内容与目录结构；到期后自动清理本地原件。OSS 历史备份按恢复点策略另行到期。</p>
        <p v-if="recycleError" role="alert" class="ckb-service-error">{{recycleError}} <button @click="openRecycle(recyclePage)">重试</button></p>
        <p v-if="recycleLoading" role="status">正在加载回收站…</p>
        <div v-else><p v-if="!recycleItems.length">回收站为空。</p><div v-for="item in recycleItems" :key="item.id" class="ckb-recycle-row"><div><strong>{{item.title}}</strong><small>{{({document:'文件',project:'项目',note:'笔记',folder:'目录'})[item.kind]}} · 删除于 {{new Date(item.deleted_at).toLocaleString('zh-CN')}} · {{new Date(item.purge_after).toLocaleString('zh-CN')}} 到期</small></div><button class="ckb-button ckb-button-outline" :disabled="!!recycleBusy || !item.can_restore" @click="restoreRecycle(item)">{{recycleBusy===item.id?'恢复中…':item.can_restore?'恢复':'已到期，等待清理'}}</button></div></div>
        <template #footer><button class="ckb-button" :disabled="recycleLoading || recyclePage<=1" @click="openRecycle(recyclePage-1)">上一页</button><span>{{recyclePage}} / {{Math.max(1,Math.ceil(recycleTotal/50))}}</span><button class="ckb-button" :disabled="recycleLoading || recyclePage*50>=recycleTotal" @click="openRecycle(recyclePage+1)">下一页</button><button class="ckb-button ckb-button-primary" @click="recycleOpen=false">关闭</button></template>
      </el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="projectEditorOpen" :title="editingProject ? '项目设置' : '创建项目'" width="880px" class="ckb-dialog ckb-project-dialog ckb-reveal-dialog" append-to-body :close-on-click-modal="!projectSaving"><knowledge-glass-surface/><div class="ckb-project-editor"><aside><knowledge-folder-artwork/><span>{{ projectEditorIsCase ? 'EXPERIENCE ARCHIVE' : 'PROJECT ARCHIVE' }}</span><h3>{{ projectForm.name || '每个项目，都有自己的空间。' }}</h3><p>{{ projectEditorIsCase ? '留存项目经验、案例复盘与方法，让下一次研究少走弯路。' : '先记录背景，再让文件、录音与视频各得其所。' }}</p><div><span>01 / 创建空目录</span><span>02 / 组织子目录</span><span>03 / 归档与研究</span></div></aside><form class="ckb-form-grid" @submit.prevent="saveProjectDirectory"><div class="ckb-attribution ckb-form-wide"><span><i aria-hidden="true" class="fa-solid fa-user-shield"></i>{{ editingProject ? '创建人：' + (editingProject.created_by || '历史未采集') : '创建人将自动记录为当前登录账号' }}</span><small>{{ editingProject ? '最后修改：' + (editingProject.modified_by || '历史未采集') : '项目修改会保存操作人和前后内容' }}</small><button v-if="editingProject" type="button" @click="openAudit({project_id: editingProject.id})">项目操作记录 <i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></div><p v-if="projectError" class="ckb-service-error ckb-form-wide" role="alert">{{ projectError }}</p><label class="ckb-form-wide">项目名称<input v-model="projectForm.name" aria-label="项目名称" maxlength="200" placeholder="例如：AI Agent 行业研究" autofocus></label><label v-if="!projectEditorIsCase" class="ckb-form-wide">所属部门／栏目<output v-if="projectCreationDepartment" aria-label="项目所属部门／栏目">{{departmentLabel(projectCreationDepartment)}}</output><select v-else v-model="projectForm.department" aria-label="项目所属部门／栏目"><option value="">{{editingProject?'待归类':'请选择所属部门／栏目'}}</option><option v-for="item in departmentOptions" :key="item.id" :value="item.id">{{item.label}}</option></select><small>{{projectCreationDepartment ? '从'+departmentLabel(projectCreationDepartment)+'创建，所属部门固定。' : '目录和文件自动继承，阅读权限保持原设置。'}}</small></label><label>行业<input v-model="projectForm.industry" aria-label="项目行业" maxlength="100" placeholder="例如：人工智能"></label><label>项目分类<select v-model="projectForm.category" aria-label="项目分类"><option v-for="category in projectCategoryOptions" :key="category">{{ category }}</option></select><small>{{ projectEditorIsCase ? '案例库分类 · 沉淀可复用经验' : '资料库分类 · 归集研究原始资料与成果' }}</small></label><label>复核状态<select v-model="projectForm.review" aria-label="项目复核状态"><option>待复核</option><option>已复核</option><option>参考资料</option></select></label><label v-if="!projectEditorIsCase">保密等级<select v-model="projectForm.confidentiality" aria-label="项目保密等级" @change="projectForm.confidentiality !== 'internal' && (projectForm.visibility = 'restricted')"><option value="internal">内部</option><option v-if="service.is_admin" value="secret">机密</option></select></label><label v-if="!projectEditorIsCase && projectForm.confidentiality === 'internal'" class="ckb-project-restrict ckb-form-wide"><input type="checkbox" :checked="projectForm.visibility === 'restricted'" @change="projectForm.visibility = $event.target.checked ? 'restricted' : 'members'">项目单独授权</label><label v-if="!projectEditorIsCase && projectForm.visibility === 'restricted' && projectForm.confidentiality === 'internal'" class="ckb-form-wide">指定成员<input v-model="projectForm.readersText" aria-label="项目指定成员" placeholder="多个登录账号用逗号分隔"></label><label class="ckb-form-wide">项目标签<input v-model="projectForm.tagsText" aria-label="项目标签" maxlength="1000" placeholder="行业背景，市场进入，访谈方法"><small>文件自动继承，上传时无需重复填写。</small></label><label class="ckb-form-wide">项目说明<textarea v-model="projectForm.description" aria-label="项目说明" maxlength="10000" rows="3" placeholder="记录项目目标、背景与适用范围。"></textarea></label><button type="submit" hidden></button></form></div><template #footer><button v-if="editingProject?.can_manage" class="ckb-button ckb-project-delete" :disabled="projectSaving" @click="deleteProjectDirectory"><i class="fa-solid fa-trash-can" aria-hidden="true"></i>删除项目</button><button class="ckb-button ckb-button-outline" :disabled="projectSaving" @click="projectEditorOpen = false">取消</button><button class="ckb-button ckb-button-primary" :disabled="projectSaving || !projectForm.name?.trim()" @click="saveProjectDirectory">{{ projectSaving ? '保存中…' : editingProject ? '保存项目设置' : '创建空项目' }}</button></template></el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="folderEditorOpen" :close-on-click-modal="!folderSaving" :close-on-press-escape="!folderSaving" :show-close="!folderSaving" :title="editingFolder ? '编辑目录' : '新建目录'" width="480px" class="ckb-dialog ckb-folder-dialog ckb-reveal-dialog" append-to-body><knowledge-glass-surface/><div class="ckb-folder-editor-art"><knowledge-folder-artwork/></div><p class="ckb-dialog-intro">{{ activeProject?.name }} / {{ directoryBreadcrumbs.map(folder => folder.name).join(' / ') || '根目录' }}</p><p v-if="folderError" class="ckb-service-error" role="alert">{{ folderError }}</p><form class="ckb-form-grid" @submit.prevent="saveFolder"><label class="ckb-form-wide">目录名称<input v-model="folderName" aria-label="目录名称" maxlength="200" placeholder="例如：录音、笔录、报告" autofocus></label></form><template #footer><button v-if="editingFolder" class="ckb-button ckb-button-outline ckb-delete-button" :disabled="folderSaving" @click="deleteEmptyFolder">删除目录</button><button class="ckb-button ckb-button-outline" :disabled="folderSaving" @click="folderEditorOpen = false">取消</button><button class="ckb-button ckb-button-primary" :disabled="folderSaving || !folderName.trim()" @click="saveFolder">{{ folderSaving ? '保存中…' : editingFolder ? '保存目录' : '创建目录' }}</button></template></el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="readerOpen" width="94vw" class="ckb-dialog ckb-reader-dialog ckb-workbench-reader" :class="{'ckb-reader-focused':readerFocus,'ckb-reader-media':!!selectedDoc?.media_kind,'ckb-reader-compact':!selectedDoc?.references?.length}" append-to-body :title="displayDocumentTitle(selectedDoc) || '资料阅读'" @closed="!readerOpen && releaseReader()"><knowledge-glass-surface/>
        <template v-if="selectedDoc"><div class="ckb-reader-toolbar"><span>{{ selectedDoc.format || '引用资料' }} · {{ selectedDoc.review || '请核对来源' }} · V{{ selectedDoc.version || 1 }}</span><div><button v-if="selectedDoc.can_history" class="ckb-button ckb-button-outline" @click="showFileVersions(selectedDoc)">历史版本</button><button v-if="selectedDoc.note_id && selectedDoc.can_manage" class="ckb-button ckb-button-outline" @click="editRichNote(selectedDoc.note_id)">编辑笔记</button><button v-if="selectedDoc.has_original" class="ckb-button ckb-button-outline" :disabled="operationPending('download:' + selectedDoc.id) || readerOriginalCode==='pdf_encrypted'" @click="downloadOriginal(selectedDoc)">{{operationPending('download:' + selectedDoc.id) ? downloadPhase(selectedDoc) : (plainOriginal(selectedDoc)?'下载':'下载水印副本')}}</button><button v-if="!selectedDoc.media_kind || selectedDoc.description" class="ckb-button ckb-button-primary" :disabled="busy || !canAsk || selectedDoc.state !== 'ready'" @click="askDocument">{{selectedDoc.media_kind?'根据说明提问':'单独向这份资料提问'}}</button></div></div>
        <div v-if="downloadProgress[selectedDoc.id]" class="ckb-download-progress"><span role="status"><i class="fa-solid fa-circle-notch fa-spin" aria-hidden="true"></i>{{ downloadPhase(selectedDoc) }}</span><time>已等待 {{ downloadProgress[selectedDoc.id].elapsed }} 秒</time><progress v-if="downloadProgress[selectedDoc.id].total_pages" :max="downloadProgress[selectedDoc.id].total_pages" :value="downloadProgress[selectedDoc.id].page" aria-label="水印处理进度"></progress><small>{{plainOriginal(selectedDoc)?'正在接收原文件，完成后会交给浏览器下载。':'正在生成保留原格式的带水印副本，完成后会自动交给浏览器下载。'}}</small></div><div class="ckb-reader-view-tabs" role="group" aria-label="阅读方式"><div class="ckb-reader-locate-tools"><label v-if="!selectedDoc.media_kind || selectedDoc.description?.length > 300"><i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i><input v-model="readerFind" maxlength="500" :aria-label="selectedDoc.media_kind?'查找说明':'搜索解析文字'" :placeholder="selectedDoc.media_kind?'查找文字说明…':'搜索解析文字（含扫描件识别文字）…'" @keydown.enter="findInReader"><button :disabled="locating || readerLoading || !readerFind.trim()" @click="findInReader">{{ locating ? '定位中…' : '查找' }}</button></label><span v-if="readerLocation" role="status">{{ readerLocation.matched ? '已匹配原文' + (readerLocation.page ? ' · 第 ' + readerLocation.page + ' 页' : '') : readerLocation.message }}</span><button :aria-pressed="readerFocus" @click="readerFocus = !readerFocus"><i class="fa-solid fa-expand" aria-hidden="true"></i>{{ readerFocus ? '退出专注' : '专注阅读' }}</button></div><button v-if="!selectedDoc.media_kind" :aria-pressed="readerMode === 'original'" :disabled="!selectedDoc.has_original" @click="readerMode = 'original'"><i class="fa-regular fa-file" aria-hidden="true"></i>完整原件</button><button v-if="!selectedDoc.media_kind" :aria-pressed="readerMode === 'excerpts'" @click="readerMode = 'excerpts'">解析片段<span>{{ readerTotal || selectedDoc.references?.length || 0 }}</span></button><details v-if="selectedDoc.has_original && !plainOriginal(selectedDoc)" class="ckb-reader-policy"><summary><i class="fa-solid fa-shield-halved" aria-hidden="true"></i>下载与预览带账号、时间和追踪标记<span>格式说明</span></summary><p class="ckb-export-note"><i class="fa-solid fa-shield-halved" aria-hidden="true"></i> 下载与预览带账号、时间和追踪标记。Office 与文字保留原格式；Excel 添加背景及打印页脚标记。图片、音视频直接预览与下载原文件，不添加水印。</p></details><small v-if="!selectedDoc.has_original">原件缺失：这份历史资料只有解析片段，尚不能查看完整原件。{{selectedDoc.can_manage?'可补传原件恢复预览。':'请联系资料管理者补传原件。'}}</small><label v-if="!selectedDoc.has_original && selectedDoc.can_manage" class="ckb-restore-original"><span>{{restoringOriginal?'正在补传原件…':'补传原件'}}</span><input type="file" aria-label="补传缺失原件" :disabled="restoringOriginal" :accept="'.'+selectedDoc.format.toLowerCase()" @change="restoreOriginal($event)"></label></div><div class="ckb-reader-columns"><div class="ckb-original-pane">
          <div v-if="selectedDoc.media_kind" class="ckb-media-reader"><span class="ckb-media-eyebrow">{{ selectedDoc.media_kind === 'audio' ? 'AUDIO / 录音资料' : 'VIDEO / 视频资料' }}</span><video v-if="readerUrl && selectedDoc.media_kind === 'video'" :key="readerUrl" :src="readerUrl" controls preload="metadata" @error="mediaPlaybackError" @loadstart="mediaPlaybackStatus" @loadeddata="mediaPlaybackStatus" @canplay="mediaPlaybackStatus" @waiting="mediaPlaybackStatus" @stalled="mediaPlaybackStatus" @seeking="mediaPlaybackStatus" @seeked="mediaPlaybackStatus" @playing="mediaPlaybackStatus" @ended="mediaPlaybackStatus"></video><div v-if="selectedDoc.media_kind === 'audio'" class="ckb-audio-art" aria-hidden="true"><i aria-hidden="true" class="fa-solid fa-wave-square"></i></div><audio v-if="readerUrl && selectedDoc.media_kind === 'audio'" :key="readerUrl" :src="readerUrl" controls preload="metadata" @error="mediaPlaybackError" @loadstart="mediaPlaybackStatus" @loadeddata="mediaPlaybackStatus" @canplay="mediaPlaybackStatus" @waiting="mediaPlaybackStatus" @stalled="mediaPlaybackStatus" @seeking="mediaPlaybackStatus" @seeked="mediaPlaybackStatus" @playing="mediaPlaybackStatus" @ended="mediaPlaybackStatus"></audio><p v-if="readerMediaMessage && !readerOriginalError && !readerError" class="ckb-media-loading" role="status" aria-live="polite" aria-atomic="true"><span class="ckb-loading-spinner" aria-hidden="true"></span>{{readerMediaMessage}}</p><p v-if="readerError || readerOriginalError" role="alert">{{ readerError || readerOriginalError }}</p><div v-if="readerOriginalError" class="ckb-media-recovery"><button class="ckb-button ckb-button-primary" :disabled="readerOriginalLoading" @click="retryMediaPlayback">重试播放</button><button class="ckb-button ckb-button-outline" :disabled="operationPending('download:'+selectedDoc.id)" @click="downloadOriginal(selectedDoc)">下载原文件</button></div><h3 v-if="selectedDoc.description">文字说明</h3><pre v-if="selectedDoc.description" ref="mediaDescription"><template v-for="(part,n) in readerParts(selectedDoc.description)" :key="n"><mark v-if="part.match">{{part.text}}</mark><span v-else>{{part.text}}</span></template></pre><p v-if="readerSearchStatus" role="status">{{readerSearchStatus}}</p><p v-if="selectedDoc.description">问答仅依据这段说明，未自动转写音视频内容。</p></div>
          <knowledge-sheet-viewer v-else-if="readerMode==='original' && readerSheet" :key="selectedDoc.id" :document-id="selectedDoc.id" :initial="readerSheet" :fetch-page="apiFetch"/><knowledge-document-viewer ref="nativeReader" @located="readerLocation = $event" :find-text="readerOriginalFind" v-else-if="readerMode === 'original' &amp;&amp; readerBlob" :key="selectedDoc.id + readerTrace" :blob="readerBlob" :format="selectedDoc.format" :identity="service.username + ' · ' + new Date().toLocaleString('zh-CN')" :trace="readerTrace"/><knowledge-pdf-viewer :format="selectedDoc.format" :location="readerLocation" v-else-if="readerMode === 'original' &amp;&amp; readerUrl &amp;&amp; ['PDF','DOC','DOCX','XLS','XLSX','PPT','PPTX'].includes(selectedDoc.format)" :key="selectedDoc.id + readerTrace" :document-id="selectedDoc.id" :first-page="readerUrl" :pages="readerPDFPages" :fetch-page="apiFetch"/>
          <div v-else-if="readerMode === 'original' &amp;&amp; readerUrl" class="ckb-image-reader"><div class="ckb-image-controls"><button @click="readerImageZoom=Math.max(25,readerImageZoom-25)" :disabled="readerImageZoom<=25" aria-label="缩小图片">−</button><span>{{readerImageZoom}}%</span><button @click="readerImageZoom=Math.min(300,readerImageZoom+25)" :disabled="readerImageZoom>=300" aria-label="放大图片">＋</button><button @click="readerImageZoom=100">适应宽度</button></div><div class="ckb-image-canvas"><img :src="readerUrl" :style="{width:readerImageZoom+'%'}" alt="图片原件" @error="imagePreviewError"></div></div>
          <div v-else-if="readerMode === 'original'" class="ckb-original-unavailable"><i :class="readerOriginalLoading ? 'fa-solid fa-circle-notch fa-spin' : 'fa-regular fa-file-lines'" aria-hidden="true"></i><h3>{{ readerOriginalLoading ? '正在展开原件…' : readerOriginalCode==='pdf_encrypted' ? 'PDF 已加密，暂不能预览' : '原件暂时无法预览' }}</h3><p v-if="readerOriginalError" role="alert">{{ readerOriginalError }}</p><p v-else-if="!readerOriginalLoading">{{ ['DOCX','DOC','XLS','XLSX','PPT','PPTX','TXT','MD','CSV','PDF','PNG','JPG','JPEG','WEBP','GIF','BMP'].includes(selectedDoc.format) ? '暂时未能打开原件，请重试。' : selectedDoc.format + ' 暂不支持在线预览，可下载文件查看。' }}</p><button v-if="!readerOriginalLoading &amp;&amp; selectedDoc.has_original &amp;&amp; readerOriginalCode!=='pdf_encrypted'" class="ckb-button ckb-button-primary" :disabled="operationPending('download:' + selectedDoc.id)" @click="downloadOriginal(selectedDoc)">{{plainOriginal(selectedDoc)?'下载原文件':'下载水印副本'}}</button><button v-if="readerOriginalError &amp;&amp; !readerOriginalLoading &amp;&amp; readerOriginalCode!=='pdf_encrypted'" class="ckb-button ckb-button-outline" @click="openDocument(selectedDoc)">重试预览</button></div><div v-else ref="excerptReader" class="ckb-source-reader"><p class="ckb-excerpt-notice">解析片段是可检索文字，可能合并多页、存在重叠，或缺少图片和识别失败的内容，不能替代完整原件。</p><p v-if="readerLoading">正在加载解析文字…</p><p v-if="readerExcerptError" role="alert">{{ readerExcerptError }}</p><p v-if="readerSearchStatus" role="status">{{ readerSearchStatus }}</p><div v-if="readerMatches.length" class="ckb-excerpt-navigation"><button @click="moveReaderMatch(-1)">上一处</button><span>{{readerSearchIndex+1}} / {{readerMatches.length}} 个命中片段</span><button @click="moveReaderMatch(1)">下一处</button></div><p v-if="!readerLoading &amp;&amp; !selectedDoc.references?.length">暂无可展示的解析文字。{{ !selectedDoc.has_original ? '请联系资料管理者补传原件并重新索引。' : readerOriginalCode==='pdf_encrypted' ? '请提供已解除打开密码的 PDF 后重新索引。' : '可先查看完整原件，处理失败时请重试索引。' }}</p><section v-for="(reference,index) in selectedDoc.references" :key="index" :class="{'ckb-reader-hit':referenceMatches(reference)}"><div class="ckb-citation-heading">片段 {{ reference.id }}<span v-if="reference.pages?.length"> · 来源第 {{reference.pages.join('、')}} 页</span><button v-if="selectedDoc.has_original &amp;&amp; reference.pages?.length" @click="locateReference(reference)">查看对应原文页</button></div><pre><template v-for="(part,n) in readerParts(reference.text)" :key="n"><mark v-if="part.match">{{part.text}}</mark><span v-else>{{part.text}}</span></template></pre></section><p>{{readerExcerptCountLabel}}</p><button v-if="readerHasMore || readerTotal > (selectedDoc.references?.length || 0)" class="ckb-button ckb-button-outline" :disabled="readerLoading || locating" @click="morePreview">加载后续解析片段</button></div>
        </div><aside class="ckb-reader-question"><h3><i class="fa-solid fa-list-check" aria-hidden="true"></i>{{selectedDoc.media_kind?'资料信息':'阅读与核对'}}</h3><p v-if="selectedDoc.media_kind" class="ckb-media-info">{{sizeLabel(selectedDoc.size||0)}} · {{selectedDoc.uploaded_by||selectedDoc.owner}}<br>{{selectedDoc.created_at?new Date(selectedDoc.created_at).toLocaleString('zh-CN'):''}}</p><p class="ckb-reader-source-status">{{ selectedDoc.status_message || '点击引用可核对依据。' }}</p><div v-if="selectedDoc.tags?.length || (itemDepartment(selectedDoc) &amp;&amp; !caseCategories.includes(selectedDoc.category))" class="ckb-doc-tags"><span v-if="itemDepartment(selectedDoc) &amp;&amp; !caseCategories.includes(selectedDoc.category)">{{departmentLabel(itemDepartment(selectedDoc))}}</span><span v-for="tag in selectedDoc.tags" :key="tag"># {{ tag }}</span></div><p v-if="!selectedDoc.media_kind">{{readerContextHint}}</p>
          <div v-if="!selectedDoc.media_kind && selectedDoc.references?.length && readerUrl" class="ckb-reader-evidence"><strong>解析片段</strong><p class="ckb-excerpt-notice">片段数不等于原文页数；图片和版式请查看完整原件。</p><details v-for="reference in selectedDoc.references" :key="reference.id"><summary>片段 {{ reference.id }}<span v-if="reference.pages?.length"> · 第 {{ reference.pages.join('、') }} 页</span></summary><button @click="showReference(reference)">查看解析片段</button><button v-if="reference.pages?.length" @click="locateReference(reference)">查看对应原文页</button><pre>{{ reference.text }}</pre></details><button v-if="readerTotal > selectedDoc.references.length" :disabled="readerLoading" @click="morePreview">加载更多片段</button></div>
          <div v-if="!selectedDoc.media_kind && messages.length" class="ckb-reader-last-answer"><strong>最近的回答</strong><template v-for="(message, index) in messages.slice(-2)" :key="index"><p v-if="message.role === 'user'">{{ message.text }}</p><pre v-else>{{ message.text || answerStatus }}<span v-if="message.error">{{ message.error }}</span></pre></template></div>
          <div v-if="!selectedDoc.media_kind || selectedDoc.description" class="ckb-reader-ask"><label for="ckb-reader-question-input">{{selectedDoc.media_kind?'根据文字说明提问':'基于这份资料提问'}}</label><textarea id="ckb-reader-question-input" v-model="draft" maxlength="1500" :disabled="busy || selectedDoc.state !== 'ready'" :placeholder="selectedDoc.media_kind?'仅根据人工填写的说明回答，未自动转写音视频。':'就这份原件提问，例如：哪些结论仍需复核？'"></textarea><button class="ckb-button ckb-button-primary" :disabled="busy || !draft.trim() || selectedDoc.state !== 'ready'" @click="askWhileReading">{{ busy ? answerStatus || '正在回答…' : (selectedDoc.media_kind?'依据文字说明回答':'依据这份资料回答') }}</button></div>
          <div v-if="selectedDoc.media_kind && !selectedDoc.description" class="ckb-media-empty"><p>暂未填写文字说明。当前支持播放与下载，补充说明后可根据说明提问。</p><button v-if="selectedDoc.can_manage" class="ckb-button ckb-button-outline" :disabled="uploadBusy" @click="editDocument(selectedDoc)">补充说明</button></div>
        </aside></div></template>
      </el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="auditOpen" title="操作记录" width="850px" class="ckb-dialog ckb-audit-dialog" append-to-body><knowledge-glass-surface/><p class="ckb-export-note">操作人和时间由后端自动记录。项目/文件管理者可查看对应记录，管理员可查看全部。</p><p v-if="auditError" class="ckb-service-error" role="alert">{{ auditError }}</p><div class="ckb-audit-list" :aria-busy="auditLoading"><article v-for="event in auditEvents" :key="event.id"><header><span><i class="fa-solid fa-fingerprint" aria-hidden="true"></i><strong>{{ auditAction(event.action) }}</strong></span><time>{{ new Date(event.created_at).toLocaleString('zh-CN') }}</time></header><p>{{ event.target_name }}<b>{{ event.actor_username }}</b></p><details v-if="Object.keys(event.changes || {}).length"><summary>查看前后内容 · {{ Object.keys(event.changes).length }} 项</summary><dl v-for="(change, field) in event.changes" :key="field"><dt>{{ auditField(field) }}</dt><dd><small>修改前</small><pre>{{ auditValue(change.before) }}</pre></dd><dd><small>修改后</small><pre>{{ auditValue(change.after) }}</pre></dd></dl></details><p v-if="event.details?.trace_id" class="ckb-audit-trace">追踪编号 {{ event.details.trace_id }}</p><p v-if="event.details?.reason">{{ event.details.reason }}</p></article><p v-if="!auditEvents.length">{{ auditLoading ? '正在加载记录…' : '暂无记录，历史操作不会补造。' }}</p></div><template #footer><span class="ckb-audit-count">共 {{ auditTotal }} 条 · 第 {{ auditPage }} 页</span><button class="ckb-button ckb-button-outline" :disabled="auditLoading || auditPage <= 1" @click="auditPage--; loadAudit()">上一页</button><button class="ckb-button ckb-button-outline" :disabled="auditLoading || auditPage * 30 >= auditTotal" @click="auditPage++; loadAudit()">下一页</button><button class="ckb-button ckb-button-primary" @click="auditOpen = false">关闭</button></template></el-dialog>
      <button v-if="(uploadBusy || uploadResults.length) && !uploadOpen" class="ckb-upload-tray" @click="uploadOpen=true" :aria-label="uploadBusy?'查看正在上传的文件':'查看上传结果'"><i class="fa-solid fa-cloud-arrow-up" aria-hidden="true"></i>{{uploadBusy?(uploadCurrent?.state||'正在上传'):'上传已结束'}} · {{uploadBusy?'查看进度':'查看结果'}}</button>
      <el-dialog modal-class="ckb-glass-overlay" v-model="uploadOpen" :title="reuploadContext ? (reuploadContext.restore_original?'补传原件':'重新上传到原位置') : quickCapture ? '随手记录一份经验' : '上传文件'" width="680px" class="ckb-dialog" append-to-body :close-on-click-modal="!uploadBusy" :show-close="true" :close-on-press-escape="true"><knowledge-glass-surface/>
        <section class="ckb-upload-destination" aria-label="文件保存位置"><span>{{ uploadResults.some(item=>item.id) ? '已保存到' : '将保存到' }}</span><strong>{{ uploadDestinationLabel }}</strong><small v-if="reuploadContext">文件名：{{reuploadContext.title}} · 按原位置归档</small></section><p v-if="uploadError" class="ckb-service-error" role="alert">{{ uploadError }}</p>
        <p v-if="!uploadResults.length" class="ckb-dialog-intro">文档与图片自动解析并建立检索索引。根目录音视频需填写文字说明；项目内可先归档、播放和下载，填写说明后仅检索说明，不自动转写。</p><p v-if="uploadResults.length && !uploadBusy" class="ckb-upload-summary" role="status">上传结果：{{ uploadSummary }}</p>
        <p v-if="reuploadContext && reuploadContext.title.toLowerCase().endsWith('.pdf')" class="ckb-export-note">如果原文件加密，请选择已解密的 PDF；重新上传同一加密文件仍可能失败。</p><p v-if="reuploadContext" class="ckb-upload-inheritance">{{reuploadContext.restore_original?'补传后保留原记录与目录，并重新建立索引。':'新文件按原名称保存到原项目与目录，作为新版本；旧失败记录保留，可移入回收站。内容未改变时请直接重试处理。'}}</p><fieldset v-if="!uploadResults.length || uploadBusy" :disabled="uploadBusy" class="ckb-upload-fields"><div v-if="!quickCapture" class="ckb-form-grid ckb-upload-target"><label v-if="!reuploadContext">上传位置<select v-model="uploadTargetProjectId" @change="setUploadTarget()" aria-label="上传位置"><option value="">根目录（独立文件）</option><option v-for="project in uploadTargetProjects" :key="project.id" :value="project.id">{{ project.name }}</option></select></label><label v-if="currentCollection!=='experience'" :class="{'ckb-form-wide':!uploadTargetProjectId}">所属部门／栏目<output v-if="uploadTargetProjectId || reuploadContext" aria-label="上传所属部门／栏目">{{departmentLabel(uploadForm.department)}}</output><select v-else v-model="uploadForm.department" aria-label="上传所属部门／栏目"><option value="">{{uploadTargetProjectId||reuploadContext?'待归类':'请选择所属部门／栏目'}}</option><option v-for="item in departmentOptions" :key="item.id" :value="item.id">{{item.label}}</option></select><small v-if="uploadTargetProjectId">跟随所选项目，阅读权限保持原设置。</small></label><label v-if="uploadTargetProjectId && !reuploadContext">子目录<select v-model="uploadTargetFolderId" aria-label="上传子目录"><option value="">项目根目录</option><option v-for="folder in projectFolders.filter(f => f.project_id === uploadTargetProjectId)" :key="folder.id" :value="folder.id">{{ folderLabel(folder) }}</option></select></label><div class="ckb-upload-inheritance ckb-form-wide"><i class="fa-solid fa-shield-halved" aria-hidden="true"></i><span>{{ uploadTargetProject ? '继承项目的行业、标签、分类与权限：' + (uploadTargetProject.confidentiality !== 'internal' ? '机密，仅管理员可读' : uploadTargetProject.visibility === 'members' ? '内部，所有正常账号可读' : '内部，仅归属人、管理员与指定成员可读') : (currentCollection==='experience'?'经验沉淀对所有正常成员可读。':'根目录独立文件默认内部，所有正常账号可读；上传后可在文件设置中调整。') }}</span></div></div><div v-if="quickCapture" class="ckb-capture-context"><p>先留下现场，稍后整理。保存到你自己的「随手记录 · 待整理」，仅参与经验沉淀检索。文字会生成可检索笔记，附件保留原件，也可以只写文字。</p><label>经验名称<input v-model="captureTitle" maxlength="160" placeholder="例如：客户访谈中的三个追问方法"></label><label>适用场景<input v-model="captureScene" maxlength="300" placeholder="这份记录适用于什么情况？"></label><label>可复用做法<textarea v-model="captureMethod" maxlength="3000" rows="3" placeholder="记录做法、收获或需要留意的地方。"></textarea></label></div><label class="ckb-file-drop ckb-file-drop-large" @dragover.prevent @drop.prevent="droppedFiles"><i class="fa-solid fa-cloud-arrow-up" aria-hidden="true"></i><strong>选择或拖入文档、照片、手稿、录音与视频</strong><input type="file" :multiple="!reuploadContext" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.jpg,.jpeg,.png,.mp3,.wav,.m4a,.ogg,.flac,.mp4,.webm" aria-label="选择上传资料" @change="chooseFiles"><small>文档与图片 ≤ 32 MB · 音视频 ≤ 128 MB<br>同名同内容自动另存副本；同名不同内容保留 V1、V2 等历史版本</small></label><div class="ckb-form-grid"><label class="ckb-form-wide">{{uploadDescriptionRequired?'文件说明（必填）':'文件说明（可选）'}}<small v-if="uploadDescriptionRequired">根目录音视频需说明内容；问答只检索说明，不自动转写。</small><textarea :required="uploadDescriptionRequired" :aria-required="uploadDescriptionRequired" aria-label="文字说明" v-model="uploadForm.description" maxlength="10000" rows="3" placeholder="补充这批文件的背景或内容。音视频填写后可检索此说明，不自动转写。"></textarea></label></div></fieldset>
        <ul class="ckb-upload-list"><li v-for="(file, index) in stagedFiles" :key="index">{{ file.name }} <small>{{ sizeLabel(file.size) }}</small></li></ul><p v-if="uploadBusy" class="ckb-upload-hint">可收起窗口继续在本页操作；刷新或关闭网页会中断上传。传输完成后，仍需等待服务器确认保存。</p><ul class="ckb-upload-results" aria-live="polite"><li v-for="(item, index) in uploadDisplayResults" :key="index"><strong>{{ item.name }}</strong><p v-if="item.notice" class="ckb-upload-rename-notice" role="status">{{item.notice}}</p><small v-if="item.document" class="ckb-upload-result-path">{{documentLocationLabel(item.document)}} · V{{item.document.version}}</small><button v-if="item.document?.can_read" class="ckb-upload-result-open" :disabled="uploadBusy" @click="openUploadedDocument(item)">查看本次上传文件</button><span :data-state="item.phase">{{ item.state }}</span><div v-if="item.phase==='transferring' || item.phase==='saving'" class="ckb-upload-progress"><progress :value="item.percent===null?undefined:item.percent" max="100" :aria-label="item.saving?'文件传输已完成，等待服务器保存':'文件传输进度'"></progress><span>{{item.saving?'传输完成，保存中':item.percent===null?'传输中':item.percent+'%'}} · {{uploadProgressText(item)}}</span></div><small v-else-if="item.detail">{{item.detail}}</small><knowledge-failure-actions v-if="item.document" :doc="item.document" :retry-busy="operationPending('retry:'+item.id)" @retry="retryDocument" @reupload="startReupload" @remove="deleteDocument" @edit-note="editRichNote" @details="showFailureDetails"/><button v-if="!item.id && item.phase==='upload_failed'" class="ckb-delete-button" :disabled="uploadBusy" @click="discardUploadResult(item)">放弃上传</button></li></ul>
        <input ref="replacementUploadInput" type="file" hidden :multiple="!reuploadContext" aria-label="重新选择上传文件" @change="chooseFiles"><template #footer><template v-if="uploadResults.length && !uploadBusy"><button v-if="stagedFiles.length" class="ckb-button ckb-button-outline" @click="$refs.replacementUploadInput.click()">重新选择文件</button><button v-if="stagedFiles.length" class="ckb-button ckb-button-outline" @click="uploadFiles">重试上传失败文件</button> <button v-if="!reuploadContext" class="ckb-button ckb-button-outline" @click="startUpload">继续上传</button> <button class="ckb-button ckb-button-primary" @click="viewUploaded">{{ uploadResults.some(item => item.id) ? (reuploadContext ? '打开所在目录' : '完成，查看资料') : '返回资料库' }}</button></template><template v-else><template v-if="uploadBusy"><button class="ckb-button ckb-button-outline" @click="minimizeUpload">收起，继续操作</button><button class="ckb-button ckb-button-outline" :disabled="uploadStopped || (uploadCurrent?.saving && stagedFiles.length===1)" @click="cancelUpload">{{uploadStopped?'正在停止后续上传':uploadCurrent?.saving?'停止后续文件':'停止上传'}}</button></template><button v-else class="ckb-button ckb-button-outline" @click="uploadOpen = false">取消</button> <button class="ckb-button ckb-button-primary" :disabled="uploadBusy || (quickCapture ? !captureTitle.trim() : !stagedFiles.length) || (uploadDescriptionRequired && !uploadForm.description.trim())" @click="uploadFiles">{{ uploadBusy ? '正在上传，请稍候…' : '上传并归档' }}</button></template></template>
      </el-dialog>
      <teleport to="body"><div v-if="fileContext" ref="fileContextMenu" class="ckb-file-context-menu" role="menu" aria-label="文件操作" :style="{left:fileContext.x+'px',top:fileContext.y+'px'}" @keydown="fileContextKey" @contextmenu.prevent><template v-if="fileContext.doc"><button role="menuitem" :disabled="!canClipboardDocument(fileContext.doc)" @click="putFileClipboard(fileContext.doc,'copy')">复制<kbd>Ctrl+C</kbd></button><button role="menuitem" :disabled="!canClipboardDocument(fileContext.doc)" @click="putFileClipboard(fileContext.doc,'cut')">剪切<kbd>Ctrl+X</kbd></button><button v-if="fileContext.doc.can_history" role="menuitem" @click="showFileVersions(fileContext.doc)">历史版本</button></template><button role="menuitem" :disabled="!canPasteFiles" @click="pasteFile">{{clipboardBusy?'粘贴中…':'粘贴到当前目录'}}<kbd>Ctrl+V</kbd></button></div></teleport>
      <el-dialog modal-class="ckb-glass-overlay" v-model="versionOpen" title="历史版本" width="640px" class="ckb-dialog" append-to-body><knowledge-glass-surface/><p>{{versionTitle}} · 主列表显示最新版本，旧原件仍保留。</p><p v-if="versionLoading" role="status">正在加载版本…</p><p v-if="versionError" role="alert" class="ckb-service-error">{{versionError}}</p><div class="ckb-file-versions"><article v-for="doc in versionRows" :key="doc.id"><div><strong>{{displayDocumentTitle(doc)}}</strong><small>{{doc.is_latest?'最新版本 · ':''}}{{new Date(doc.created_at).toLocaleString('zh-CN')}} · {{doc.uploaded_by || doc.owner}}</small></div><button class="ckb-button ckb-button-outline" @click="versionOpen=false;openDocument(doc)">查看</button><button v-if="doc.has_original" class="ckb-button ckb-button-outline" :disabled="operationPending('download:'+doc.id)" @click="downloadOriginal(doc)">下载</button></article></div><template #footer><button class="ckb-button ckb-button-primary" @click="versionOpen=false">关闭</button></template></el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="moveOpen" title="移动文件" width="600px" class="ckb-dialog" append-to-body :close-on-click-modal="!moveBusy" :show-close="!moveBusy" :close-on-press-escape="!moveBusy"><knowledge-glass-surface/><p>《{{ moveDoc?.title }}》及同名历史版本将一起移动，原件和版本记录保留。</p><fieldset :disabled="moveBusy" class="ckb-upload-fields"><div class="ckb-form-grid"><label class="ckb-form-wide">目标位置<select v-model="moveProjectId" @change="moveFolderId = ''; moveError = ''" aria-label="移动目标位置"><option value="">根目录（独立文件）</option><option v-for="project in moveTargetProjects" :key="project.id" :value="project.id">{{ project.name }}</option></select></label><label v-if="moveProjectId" class="ckb-form-wide">子目录<select v-model="moveFolderId" aria-label="移动目标子目录"><option value="">项目根目录</option><option v-for="folder in projectFolders.filter(f => f.project_id === moveProjectId)" :key="folder.id" :value="folder.id">{{ folderLabel(folder) }}</option></select></label></div></fieldset><p class="ckb-export-note">{{ moveProjectId ? '下一步会显示目标项目权限；确认后继承项目属性和访问权限。' : '移回根目录保留现有保密等级和访问权限，不自动改成共享。' }}</p><p v-if="moveError" role="alert" class="ckb-service-error">{{ moveError }}</p><template #footer><button class="ckb-button ckb-button-outline" :disabled="moveBusy" @click="moveOpen = false">取消</button><button class="ckb-button ckb-button-primary" :disabled="moveBusy" @click="moveDocument">{{ moveBusy ? '正在处理…' : '查看移动与权限变化' }}</button></template></el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="metadataOpen" title="文件设置" width="680px" class="ckb-dialog ckb-reveal-dialog" append-to-body><knowledge-glass-surface/><div class="ckb-file-editor-hero" :class="'kind-' + fileAppearance(editingDoc || {})"><knowledge-file-artwork :format="editingDoc?.format" :kind="fileAppearance(editingDoc || {})" :media-kind="editingDoc?.media_kind"/><div><strong>{{ editingDoc?.title }}</strong><small>{{ editingDoc?.project }} · {{ editingDoc?.format }} · {{ sizeLabel(editingDoc?.size || 0) }}</small></div></div><div class="ckb-attribution"><span>实际上传人：{{ editingDoc?.uploaded_by || '历史未采集' }}</span><small>最后修改：{{ editingDoc?.modified_by || '历史未采集' }}</small><button v-if="editingDoc?.id" @click="openAudit({document_id: editingDoc.id})">文件操作记录 <i class="fa-solid fa-arrow-right" aria-hidden="true"></i></button></div><div class="ckb-form-grid"><label class="ckb-form-wide">文件名称<input v-model="uploadForm.title" aria-label="文件名称" maxlength="255"></label><label v-if="editingDoc?.knowledge_project_id" class="ckb-form-wide">归档目录<select v-model="uploadForm.folder_id" aria-label="归档目录"><option value="">项目根目录</option><option v-for="folder in projectFolders.filter(item => item.project_id === editingDoc.knowledge_project_id)" :key="folder.id" :value="folder.id">{{ folderLabel(folder) }}</option></select></label><template v-if="!editingDoc?.inherits_project">
<label v-if="!caseCategories.includes(editingDoc?.category)">所属部门／栏目<output v-if="editingDoc?.knowledge_project_id" aria-label="文件所属部门／栏目">{{departmentLabel(uploadForm.department)}}</output><select v-else v-model="uploadForm.department" aria-label="文件所属部门／栏目"><option value="">待归类</option><option v-for="item in departmentOptions" :key="item.id" :value="item.id">{{item.label}}</option></select></label><label>归档位置<input aria-label="所属项目" :value="editingDoc?.is_root ? '根目录 · 独立文件' : uploadForm.project" disabled maxlength="200" placeholder="例如：新能源汽车尽调"></label>
<label>行业<input aria-label="行业" v-model="uploadForm.industry" maxlength="100" placeholder="例如：汽车与出行"></label>
<label>资料分类<select aria-label="资料分类" v-model="uploadForm.category"><option v-for="item in metadataCategoryOptions" :key="item">{{ item }}</option></select></label>
<label>复核状态<select aria-label="复核状态" v-model="uploadForm.review"><option>待复核</option><option>已复核</option><option>参考资料</option></select></label>
<template v-if="!caseCategories.includes(editingDoc?.category)"><label>保密等级<select aria-label="保密等级" v-model="uploadForm.confidentiality" @change="syncConfidentiality"><option value="internal">内部</option><option v-if="service.is_admin" value="secret">机密</option></select><small>普通账号默认可用，仅可读取内部资料；机密仅管理员可用。</small></label>
<div class="ckb-acl-summary"><i aria-hidden="true" class="fa-solid fa-shield-halved"></i><span>{{ uploadForm.confidentiality === 'internal' && uploadForm.visibility === 'members' ? '正常账号默认可读' : uploadForm.confidentiality !== 'internal' ? '仅管理员可读，普通账号不能申请访问' : '仅创建人、管理员及指定成员可读；其他成员可申请授权' }}</span><label v-if="uploadForm.confidentiality === 'internal'" class="ckb-restrict-toggle"><input type="checkbox" :checked="uploadForm.visibility === 'restricted'" @change="uploadForm.visibility = $event.target.checked ? 'restricted' : 'members'">内部资料也单独授权</label></div>
<label v-if="uploadForm.visibility === 'restricted' && uploadForm.confidentiality === 'internal'" class="ckb-form-wide">指定成员账号<input aria-label="指定成员账号" v-model="uploadForm.readersText" maxlength="10000" placeholder="系统登录账号，多个账号用逗号分隔；留空则仅自己和管理员可见"><small>指定成员须为正常账号；此授权仅适用于内部资料。</small></label>
</template><p v-else class="ckb-form-wide">经验沉淀对所有正常企业成员可读，修改和删除仍由创建者或管理员操作。</p><label class="ckb-form-wide">自定义标签<input aria-label="自定义标签" v-model="uploadForm.tagsText" maxlength="1000" placeholder="逗号分隔，最多 20 个标签"><span class="ckb-doc-tags"><span v-for="tag in formTags" :key="tag"># {{ tag }}</span></span></label></template><div v-else class="ckb-upload-inheritance ckb-form-wide"><i class="fa-solid fa-link" aria-hidden="true"></i><span>部门／栏目、行业、标签、分类与权限跟随项目设置。</span></div><label class="ckb-form-wide">文字说明<textarea aria-label="文字说明" v-model="uploadForm.description" maxlength="10000" rows="3"></textarea><small v-if="editingDoc?.media_kind">更新说明、项目、行业或标签后，会重新索引说明；原件保持不变。</small></label>
</div><p>文件名、归档目录和说明可随时调整。项目属性请在项目设置中修改。旧版本保留，可分别管理。</p>
        <template #footer><button v-if="editingDoc && canMoveDocument(editingDoc)" class="ckb-button ckb-button-outline" @click="startMove(editingDoc)">移动文件</button><button class="ckb-button ckb-button-outline ckb-delete-button" :disabled="operationPending('delete:' + editingDoc?.id)" @click="deleteDocument(editingDoc)">{{operationPending('delete:' + editingDoc?.id) ? '删除中…' : '删除资料'}}</button><button class="ckb-button ckb-button-primary" :disabled="operationPending('save:' + editingDoc?.id)" @click="saveMetadata">{{operationPending('save:' + editingDoc?.id) ? '保存中…' : '保存修改'}}</button></template>
      </el-dialog>
      <el-dialog modal-class="ckb-glass-overlay" v-model="requestCenterOpen" :title="service.is_admin ? '权限审批' : '我的权限申请'" width="760px" class="ckb-dialog ckb-request-dialog" append-to-body><knowledge-glass-surface/>
        <p class="ckb-dialog-intro">{{ service.is_admin ? '所有管理员共享审批列表；任一管理员处理后，结果会同步。批准后阅读、下载和 AI 问答权限同时生效。' : '可在这里查看受限资料的申请进度。' }}</p>
        <div class="ckb-request-list"><article v-for="request in accessRequests" :key="request.id"><div><strong>{{ request.document_title }}</strong><span>{{ request.confidentiality_label || '内部' }} · {{ request.requester_username }}</span><p>{{ request.reason }}</p><small>{{ request.created_at ? new Date(request.created_at).toLocaleString('zh-CN') : '' }}<template v-if="request.decision_note"> · 处理说明：{{ request.decision_note }}</template></small></div><aside><b :data-status="request.status">{{ requestStatusLabel(request.status) }}</b><template v-if="service.is_admin && request.status === 'pending'"><button class="ckb-button ckb-button-primary" :disabled="operationPending('decision:' + request.id)" @click="decideAccess(request, 'approved')">批准</button><button class="ckb-button ckb-button-outline" :disabled="operationPending('decision:' + request.id)" @click="decideAccess(request, 'rejected')">拒绝</button></template></aside></article><p v-if="!accessRequests.length" class="ckb-home-empty">{{ accessLoading ? '正在加载…' : '暂无权限申请。' }}</p></div>
        <template #footer><button class="ckb-button ckb-button-primary" @click="requestCenterOpen = false">关闭</button></template>
      </el-dialog>
    </div>`
};
