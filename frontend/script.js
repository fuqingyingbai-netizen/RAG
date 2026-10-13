const { createApp } = Vue;

createApp({
  data() {
    return {
      token: localStorage.getItem('accessToken') || '', currentUser: null,
      authStep: 'role', authRole: 'user', authMode: 'login', authLoading: false,
      authForm: { username: '', password: '', admin_code: '' },
      activeView: localStorage.getItem('activeView') || 'submit', projects: [], projectMeta: {}, projectDetails: {}, artifactsByProject: {}, sourcesByProject: {}, traceByProject: {},
      taskSearch: '', selectedFiles: [], submitting: false, reindexing: false,
      taskPage: 1, taskPageSize: 12, sourcePage: 1, sourcePageSize: 50,
      nowTick: Date.now(), nowTimer: null, taskRefreshTimer: null, taskRefreshBusy: false, taskRefreshTicks: 0,
      reviewProjectId: '', reviewReportFiles: [], reviewProposalFiles: [], fieldSourceFiles: [], fieldSourceModule: '专家访谈/走访', secondStageRunning: false,
      knowledgeQuery: '', knowledgeResults: [],
      assistantOpen: false, assistantInput: '', assistantLoading: false,
      assistantPosition: JSON.parse(localStorage.getItem('assistantPosition') || '{"right":22,"bottom":22}'), assistantDrag: null, assistantWasDragged: false, assistantSuppressClick: false, assistantContextSummary: '',
      assistantMessages: [{ text: '你好，我可以帮你基于已入库资料、报告和知识库做问答。', isUser: false }],
      sessionId: 'source_assistant_' + Date.now(),
      modulesByTarget: { company: [
        { label: '公司背景', value: '公司背景' }, { label: '负面新闻', value: '负面新闻' },
        { label: '诉讼 / 制裁', value: '诉讼/制裁' }, { label: '股东高管', value: '股东高管' },
        { label: '融资情报', value: '融资情报' }, { label: '管理团队', value: '管理团队' },
        { label: '创始人背景', value: '创始人背景' }, { label: '竞品公司', value: '竞品公司' },
        { label: '上下游业务', value: '上下游业务' }, { label: '竞品情况', value: '竞品情况' },
        { label: '收入情况', value: '收入情况' }, { label: '行业政策', value: '行业政策' },
        { label: '舆情', value: '舆情' }
      ], person: ['创始人底色画像（家庭/教育/履历）', '人格特质与诚信评估', '商业操守与行业口碑', '经营胜任力（战略/执行/创新）', '识人用人与团队管控', '关联利益冲突（体外公司/代持/关联交易）', '司法负面与诉讼核查', '个人信用与财务风险', '投后治理与退出风险', '同业对标评估', '核心管理团队背景'].map(x => ({ label: x, value: x })), industry: ['行业定义', '供应商调研', '下游渠道', '终端客户调研', '政策环境分析', '市场规模与增长预测', '竞争格局', '投融资全景', '技术路线与壁垒', '核心公司尽调', '二级市场情绪', '投资机会研判'].map(x => ({ label: x, value: x })) },
      form: {
        projectName: '', startDate: '', endDate: '', companyName: '', identifier: '',
        industry: '', region: '', targetType: 'company', ddType: '商业尽调', targetContext: '',
        modules: ['公司背景', '诉讼/制裁', '负面新闻', '融资情报', '管理团队'], aiSearchEnabled: true,
        searchQueries: '', focusQuestions: '', keyQuestions: ''
      }
    };
  },
  computed: {
    isAuthenticated() { return !!this.token && !!this.currentUser; },
    authRoleLabel() { return this.authRole === 'admin' ? '管理员' : '普通用户'; },
    pageTitle() { return this.activeView === 'tasks' ? '任务管理' : this.activeView === 'sources' ? '溯源库' : this.activeView === 'review' ? '复核与一手资料' : '提交尽调任务'; },
    pageSubtitle() {
      if (this.activeView === 'tasks') return '查看任务成果、下载报告，并跟踪工作流 trace。';
      if (this.activeView === 'sources') return '检索项目资料、Markdown 报告和清洗事实，并使用 AI 小助手问答。';
      if (this.activeView === 'review') return '上传人工修订报告、专家访谈和走访资料，触发二阶段再生成。';
      return '填写核心输入，提交一个新的 AI 尽调任务。';
    },
    generatingCount() { return this.projects.filter(p => !['completed', 'failed', 'draft', 'paused'].includes(p.status)).length; },
    readyCount() { return this.projects.filter(p => p.status === 'completed').length; },
    sourceCount() { return this.knowledgeResults.length; },
    assistantFabStyle() { return { right: `${this.assistantPosition.right}px`, bottom: `${this.assistantPosition.bottom}px` }; },
    assistantPanelStyle() { return { right: `${this.assistantPosition.right}px`, bottom: `${this.assistantPosition.bottom + 68}px` }; },
    fileLabel() { return this.selectedFiles.length ? this.selectedFiles.map(f => f.name).join('、') : 'BP、公司介绍、工商截图、新闻、访谈纪要等'; },
    modules() { return this.modulesByTarget[this.form.targetType] || this.modulesByTarget.company; },
    ddTypes() { if (this.form.targetType === 'person') return ['人物背景尽调', '诚信与声誉核查', '投前人物综合评估']; if (this.form.targetType === 'industry') return ['行业全景研究', '赛道投资研究', '竞争与技术研究']; return ['商业尽调', '合规尽调', '负面新闻筛查', '综合桌面研究']; },
    targetPrimaryLabel() { return this.form.targetType === 'person' ? '目标人物姓名' : this.form.targetType === 'industry' ? '目标行业 / 赛道' : '目标公司名称'; },
    targetSecondaryLabel() { return this.form.targetType === 'person' ? '身份与关联机构（选填）' : this.form.targetType === 'industry' ? '重点公司 / 产品' : '官网 / 统一社会信用代码'; },
    targetSecondaryPlaceholder() { return this.form.targetType === 'person' ? '可留空；多个机构用 / 分隔，如：阿里巴巴 / 蚂蚁集团 / 云锋基金' : this.form.targetType === 'industry' ? '填写重点公司或产品' : ''; },
    filteredProjects() {
      const keyword = this.taskSearch.trim().toLowerCase();
      if (!keyword) return this.projects;
      return this.projects.filter(p => [p.title, p.target_name, p.industry, p.status].join(' ').toLowerCase().includes(keyword));
    },
    pagedProjects() { const start = (this.taskPage - 1) * this.taskPageSize; return this.filteredProjects.slice(start, start + this.taskPageSize); },
    pagedKnowledgeResults() { const start = (this.sourcePage - 1) * this.sourcePageSize; return this.knowledgeResults.slice(start, start + this.sourcePageSize); }
  },
  watch: {
    taskSearch() { this.taskPage = 1; },
    knowledgeQuery() { this.sourcePage = 1; },
    'form.targetType'(value) { const defaults = { company: ['公司背景', '诉讼/制裁', '负面新闻', '融资情报', '管理团队'], person: this.modulesByTarget.person.map(x => x.value), industry: this.modulesByTarget.industry.map(x => x.value) }; this.form.modules = defaults[value] || defaults.company; this.form.ddType = this.ddTypes[0]; this.form.targetContext = ''; if (value === 'person' || value === 'industry') { this.form.industry = ''; this.form.region = ''; } }
  },
    async mounted() {
      this.nowTimer = setInterval(() => { this.nowTick = Date.now(); }, 1000);
      this.taskRefreshTimer = setInterval(() => this.refreshVisibleTaskProgress(), 5000);
      if (this.token) { try { await this.fetchMe(); this.loadAssistantState(); await this.loadProjects(); } catch (_) { this.handleLogout(); } }
    },
  beforeUnmount() { if (this.nowTimer) clearInterval(this.nowTimer); if (this.taskRefreshTimer) clearInterval(this.taskRefreshTimer); },
  methods: {
    authHeaders(extra = {}) { return this.token ? { ...extra, Authorization: `Bearer ${this.token}` } : extra; },
    async authFetch(url, options = {}) {
      const opts = { ...options, headers: this.authHeaders(options.headers || {}) };
      const response = await fetch(url, opts);
      if (response.status === 401) { this.handleLogout(); throw new Error('登录已过期，请重新登录'); }
      return response;
    },
    async fetchMe() { const r = await this.authFetch('/auth/me'); if (!r.ok) throw new Error('认证失败'); this.currentUser = await r.json(); },
    selectAuthRole(role) {
      this.authRole = role === 'admin' ? 'admin' : 'user';
      this.authStep = 'form';
      this.authMode = 'login';
      this.authForm.admin_code = '';
    },
    backToRoleSelect() {
      this.authStep = 'role';
      this.authMode = 'login';
      this.authForm.admin_code = '';
    },
    switchAuthMode() {
      this.authMode = this.authMode === 'login' ? 'register' : 'login';
      this.authForm.admin_code = '';
    },
    async handleAuthSubmit() {
      const username = this.authForm.username.trim(), password = this.authForm.password.trim();
      if (!username || !password) return ElementPlus.ElMessage.warning('请填写账号和密码');
      if (this.authMode === 'register' && this.authRole === 'admin' && !this.authForm.admin_code.trim()) return ElementPlus.ElMessage.warning('请填写管理员邀请码');
      this.authLoading = true;
      try {
        const payload = { username, password };
        if (this.authMode === 'register') { payload.role = this.authRole; payload.admin_code = this.authForm.admin_code || null; }
        const r = await fetch(this.authMode === 'login' ? '/auth/login' : '/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        const data = await r.json().catch(() => ({})); if (!r.ok) throw new Error(data.detail || '认证失败');
        if (data.role !== this.authRole) throw new Error(`该账号是${data.role === 'admin' ? '管理员' : '普通用户'}，请从对应入口登录`);
        this.token = data.access_token; this.currentUser = { username: data.username, role: data.role };
        localStorage.setItem('accessToken', this.token); this.loadAssistantState(); await this.loadProjects();
      } catch (e) { ElementPlus.ElMessage.error(e.message); } finally { this.authLoading = false; }
    },
    handleLogout() { this.token = ''; this.currentUser = null; this.authStep = 'role'; this.authMode = 'login'; this.authForm.admin_code = ''; this.projects = []; this.knowledgeResults = []; localStorage.removeItem('accessToken'); },
    switchView(view) { this.activeView = view; localStorage.setItem('activeView', view); if (view === 'tasks' || view === 'review') { this.loadProjects(); this.refreshVisibleTaskProgress(); } if (view === 'sources') this.loadRepository(); },
    splitLines(text) { return (text || '').split('\n').map(x => x.trim()).filter(Boolean); },
    handleFileChange(file, fileList) { this.selectedFiles = fileList.map(item => item.raw || item).filter(Boolean); },
    handleFileRemove(file, fileList) { this.selectedFiles = fileList.map(item => item.raw || item).filter(Boolean); },
    async loadProjects() {
      const r = await this.authFetch('/research/projects'); const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || '加载任务失败'); this.projects = data.projects || [];
    },
    async submitTask() {
      if (!this.form.projectName.trim()) return ElementPlus.ElMessage.warning('请填写项目名称');
      this.submitting = true;
      try {
        const createPayload = {
          title: this.form.projectName.trim(),
          target_name: this.form.companyName.trim(),
          target_type: this.form.targetType,
          industry: this.form.industry.trim(),
          description: this.form.keyQuestions.trim(),
          metadata: {
            start_date: this.form.startDate,
            deadline: this.form.endDate,
            company_name: this.form.companyName,
            official_identifier: this.form.identifier,
            affiliation: this.form.targetType === 'person' ? this.form.targetContext : '',
            focus_entities: this.form.targetType === 'industry' ? this.form.targetContext : '',
            region: this.form.region,
            research_type: this.form.ddType,
            focus_modules: this.form.modules,
            ai_search_enabled: this.form.aiSearchEnabled,
            search_queries: this.splitLines(this.form.searchQueries),
            focus_questions: this.splitLines(this.form.focusQuestions || this.form.keyQuestions),
            special_requirements: this.form.keyQuestions
          }
        };
        const r = await this.authFetch('/research/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(createPayload) });
        const project = await r.json().catch(() => ({})); if (!r.ok) throw new Error(project.detail || '创建项目失败');
        this.projectMeta[project.id] = { startDate: this.form.startDate, endDate: this.form.endDate };
        this.projects.unshift(project); this.switchView('tasks'); ElementPlus.ElMessage.success('任务已提交，正在上传资料并启动工作流');
        for (const file of this.selectedFiles) await this.uploadProjectFile(project.id, file);
        await this.runWorkflow(project);
      } catch (e) { ElementPlus.ElMessage.error(e.message); } finally { this.submitting = false; }
    },
    async uploadProjectFile(projectId, file) {
      const formData = new FormData(); formData.append('file', file);
      const r = await this.authFetch(`/research/projects/${projectId}/upload`, { method: 'POST', body: formData });
      if (!r.ok) { const data = await r.json().catch(() => ({})); throw new Error(data.detail || `上传 ${file.name} 失败`); }
    },
    async runWorkflow(project) {
      this.traceByProject[project.id] = this.traceByProject[project.id] || [];
      const payload = {
        search_queries: this.splitLines(this.form.searchQueries), focus_questions: this.splitLines(this.form.focusQuestions || this.form.keyQuestions),
        target_type: this.form.targetType, client_name: '', deadline: this.form.endDate || '',
        company_name: this.form.companyName || project.target_name || '', official_identifier: this.form.targetType === 'company' ? (this.form.identifier || '') : '', region: this.form.region || '',
        affiliation: this.form.targetType === 'person' ? this.form.targetContext : '', focus_entities: this.form.targetType === 'industry' ? this.form.targetContext : '',
        research_type: this.form.ddType || '商业尽调', focus_modules: this.form.modules, ai_search_enabled: this.form.aiSearchEnabled,
        special_requirements: this.form.keyQuestions || '', generate_proposal: true
      };
      const r = await this.authFetch(`/research/projects/${project.id}/run/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!r.ok) { const data = await r.json().catch(() => ({})); throw new Error(data.detail || '工作流启动失败'); }
      const reader = r.body.getReader(), decoder = new TextDecoder(); let buffer = '';
      const pollInterval = setInterval(() => this.refreshProjectProgress(project), 5000);
      try {
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buffer += decoder.decode(value, { stream: true }); let idx;
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const eventStr = buffer.slice(0, idx); buffer = buffer.slice(idx + 2); if (!eventStr.startsWith('data: ')) continue;
            const event = JSON.parse(eventStr.slice(6));
            if (event.type === 'trace_step') this.mergeTraceEvent(project.id, event);
            if (event.type === 'result') { this.replaceProject(event.project); this.artifactsByProject[project.id] = event.artifacts || []; }
            if (event.type === 'paused') { project.status = 'paused'; ElementPlus.ElMessage.info(event.content || '任务已暂停'); }
            if (event.type === 'error') throw new Error(event.content || '工作流失败');
          }
        }
      } finally { clearInterval(pollInterval); }
      await this.loadProjects();
    },
    async rerunProject(project) {
      try {
        const r = await this.authFetch(`/research/projects/${project.id}/run-intake`);
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.detail || '加载重跑参数失败');
        await this.runExistingWorkflow(project, data.intake || {});
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      }
    },
    canPauseProject(project) {
      return !['draft', 'paused', 'completed', 'failed'].includes(project.status);
    },
    async pauseProject(project) {
      const r = await this.authFetch(`/research/projects/${project.id}/pause`, { method: 'POST' });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) return ElementPlus.ElMessage.error(data.detail || '暂停失败');
      project.status = data.status || 'pausing';
      ElementPlus.ElMessage.success(data.message || '已提交暂停请求');
      await this.loadProjects();
    },
    async runExistingWorkflow(project, savedIntake = null) {
      this.traceByProject[project.id] = this.traceByProject[project.id] || [];
      const intake = savedIntake || this.intakeFor(project);
      const payload = {
        search_queries: intake.search_queries || [],
        focus_questions: intake.focus_questions || [],
        target_type: project.target_type,
        client_name: intake.client_name || '',
        deadline: intake.deadline || '',
        company_name: intake.company_name || project.target_name || '',
        official_identifier: intake.official_identifier || '',
        affiliation: project.target_type === 'person' ? (intake.affiliation || '') : '',
        focus_entities: project.target_type === 'industry' ? (intake.focus_entities || '') : '',
        region: intake.region || '',
        research_type: intake.research_type || '商业尽调',
        focus_modules: intake.focus_modules || this.form.modules,
        ai_search_enabled: intake.ai_search_enabled !== false,
        special_requirements: intake.special_requirements || project.description || '',
        generate_proposal: true
      };
      const r = await this.authFetch(`/research/projects/${project.id}/run/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (!r.ok) { const data = await r.json().catch(() => ({})); throw new Error(data.detail || '工作流启动失败'); }
      const reader = r.body.getReader(), decoder = new TextDecoder(); let buffer = '';
      const pollInterval = setInterval(() => this.refreshProjectProgress(project), 5000);
      try {
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buffer += decoder.decode(value, { stream: true }); let idx;
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const eventStr = buffer.slice(0, idx); buffer = buffer.slice(idx + 2); if (!eventStr.startsWith('data: ')) continue;
            const event = JSON.parse(eventStr.slice(6));
            if (event.type === 'trace_step') this.mergeTraceEvent(project.id, event);
            if (event.type === 'result') { this.replaceProject(event.project); this.artifactsByProject[project.id] = event.artifacts || []; }
            if (event.type === 'paused') { project.status = 'paused'; ElementPlus.ElMessage.info(event.content || '任务已暂停'); }
            if (event.type === 'error') throw new Error(event.content || '工作流失败');
          }
        }
      } finally { clearInterval(pollInterval); }
      await this.loadProjects();
    },
    replaceProject(project) { const i = this.projects.findIndex(p => p.id === project.id); if (i >= 0) this.projects.splice(i, 1, project); else this.projects.unshift(project); },
    async onTaskExpand(row, expandedRows) { if (expandedRows.some(item => item.id === row.id)) await this.loadProjectDetail(row); },
    async viewProject(project) {
      await this.loadProjectDetail(project);
      this.$nextTick(() => this.$refs.taskTable?.toggleRowExpansion(project, true));
    },
    async loadProjectDetail(project) {
      const r = await this.authFetch(`/research/projects/${project.id}/detail`); const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || '加载项目详情失败');
      if (data.project) this.replaceProject(data.project);
      this.projectDetails[project.id] = data;
      this.artifactsByProject[project.id] = data.artifacts || [];
      this.sourcesByProject[project.id] = data.sources || [];
      if (data.trace?.length) this.mergeTraceList(project.id, data.trace);
      const intake = data.intake || {};
      this.projectMeta[project.id] = {
        startDate: intake.start_date || this.projectMeta[project.id]?.startDate || '',
        endDate: intake.deadline || this.projectMeta[project.id]?.endDate || ''
      };
    },
    async refreshProjectProgress(project) {
      const r = await this.authFetch(`/research/projects/${project.id}/progress`); const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || '加载任务进度失败');
      if (data.project) this.replaceProject(data.project);
      if (data.trace?.length) this.mergeTraceList(project.id, data.trace);
    },
    async refreshVisibleTaskProgress() {
      if (!this.token || !this.currentUser || !['tasks', 'review'].includes(this.activeView) || this.taskRefreshBusy) return;
      const activeProjects = this.projects.filter(project => !['completed', 'failed', 'draft', 'paused'].includes(project.status));
      if (!activeProjects.length) return;
      this.taskRefreshBusy = true;
      this.taskRefreshTicks += 1;
      try {
        await Promise.all(activeProjects.slice(0, 8).map(project => this.refreshProjectProgress(project).catch(() => null)));
        if (this.taskRefreshTicks % 4 === 0) {
          const r = await this.authFetch('/research/projects');
          const data = await r.json().catch(() => ({}));
          if (r.ok) this.projects = data.projects || this.projects;
        }
      } finally {
        this.taskRefreshBusy = false;
      }
    },
    mergeTraceEvent(projectId, event) {
      const list = this.traceByProject[projectId] || [];
      const key = [event.timestamp || '', event.stage || '', event.agent || '', event.label || '', event.detail || '', event.status || '', event.section || ''].join('|');
      if (!list.some(item => [item.timestamp || '', item.stage || '', item.agent || '', item.label || '', item.detail || '', item.status || '', item.section || ''].join('|') === key)) {
        list.push(event);
      }
      this.traceByProject[projectId] = list.slice(-500);
    },
    mergeTraceList(projectId, events) {
      (events || []).forEach(event => this.mergeTraceEvent(projectId, event));
    },
    async loadProjectArtifacts(project) {
      const r = await this.authFetch(`/research/projects/${project.id}/artifacts`); const data = await r.json().catch(() => []);
      if (r.ok) this.artifactsByProject[project.id] = data;
    },
    intakeFor(project) { return this.projectDetails[project.id]?.intake || {}; },
    projectPeriod(project) {
      const intake = this.intakeFor(project);
      const start = intake.start_date || this.projectMeta[project.id]?.startDate || '';
      const end = intake.deadline || this.projectMeta[project.id]?.endDate || '';
      if (start && end) return `${start} 至 ${end}`;
      return start || end || '-';
    },
    uploadFileSummary(project) {
      const sources = this.sourcesByProject[project.id] || [];
      const uploadCount = sources.filter(s => s.source_type === 'upload').length;
      const totalCount = this.projectDetails[project.id]?.source_count || sources.length;
      if (uploadCount > 0) return `${uploadCount} 个文件（共 ${totalCount} 个来源）`;
      if (totalCount > 0) return `无上传文件（共 ${totalCount} 个来源）`;
      return '暂无来源';
    },
    normalizeTraceEvent(event) {
      const item = { ...(event || {}) };
      const labels = {
        init: '工作流初始化',
        entity_resolution: '研究对象规范化',
        planning: '研究计划',
        web_search: '在线检索',
        structured_data: '专业平台采集',
        ocr: 'OCR 提取',
        quality: '来源质量评估',
        cleaning: '数据清洗',
        risk: '风险研判',
        report: '报告生成',
        proposal: '建议书生成',
        done: '工作流完成'
      };
      const statusText = {
        running: '进行中',
        done: '完成',
        skipped: '跳过',
        fallback: '降级继续',
        warning: '提醒',
        error: '失败',
        failed: '失败'
      };
      const label = String(item.label || '').trim();
      const looksBroken = !label || /^\?+$/.test(label) || /锛|鐮|涓|瀵|鏉|娓|椋|鑳|绫|璋|鍚|鍥/.test(label);
      if (looksBroken) {
        const base = labels[item.stage] || item.stage || '工作流';
        const suffix = statusText[item.status] || item.status || '';
        item.label = suffix ? `${base}：${suffix}` : base;
      }
      return item;
    },
    formatDuration(seconds) {
      const value = Math.max(0, Number(seconds || 0));
      const mins = Math.floor(value / 60), secs = Math.floor(value % 60);
      if (mins >= 60) return `${Math.floor(mins / 60)}小时${mins % 60}分`;
      return mins ? `${mins}分${secs}秒` : `${secs}秒`;
    },
    eventTimestampMs(event) {
      const raw = String(event?.timestamp || '').trim();
      if (!raw) return 0;
      const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(raw) ? raw : `${raw}Z`;
      const timestamp = new Date(normalized).getTime();
      return Number.isNaN(timestamp) ? 0 : timestamp;
    },
    eventAge(event) {
      const timestamp = this.eventTimestampMs(event);
      if (!timestamp) return '-';
      return `${this.formatDuration((this.nowTick - timestamp) / 1000)}前`;
    },
    heartbeatStale(event) {
      if (!event?.heartbeat) return false;
      const timestamp = this.eventTimestampMs(event);
      if (!timestamp) return false;
      return (this.nowTick - timestamp) > 60000;
    },
    traceDetail(event) {
      if (!event?.heartbeat) return event?.detail || event?.status || '';
      const parts = [];
      if (event.current_section) parts.push(`当前章节：${event.current_section}`);
      if (event.current_label) parts.push(`当前动作：${event.current_label}`);
      if (event.idle_seconds !== undefined) parts.push(`距上一条后端事件 ${this.formatDuration(event.idle_seconds)}`);
      return parts.join('；') || event.detail || '后端仍在执行，等待下一条进度';
    },
    traceFor(project) {
      const liveTrace = this.traceByProject[project.id] || [];
      const steps = [
        ['collecting', '检索与资料收集'], ['cleaning', '数据清洗'], ['risk_scoring', '风险研判'],
        ['report_generating', '报告生成'], ['proposal_generating', '建议书生成'], ['completed', '完成']
      ];
      const order = steps.map(item => item[0]);
      const current = order.indexOf(project.status);
      if (liveTrace.length) {
        const stageAliases = {
          collecting: ['init', 'planning', 'entity_resolution', 'web_search', 'structured_data', 'ocr', 'quality'],
          cleaning: ['cleaning'],
          risk_scoring: ['risk'],
          report_generating: ['report'],
          proposal_generating: ['proposal'],
          completed: ['done']
        };
        const currentLabel = (steps.find(item => item[0] === project.status) || [project.status, project.status])[1];
        const currentStages = stageAliases[project.status] || [project.status];
        const visible = (project.status === 'completed' ? liveTrace.slice(-200) : liveTrace.slice(-200)).map(this.normalizeTraceEvent);
        const hasCurrentRunning = visible.some(event => currentStages.includes(event.stage) && event.status === 'running');
        if (project.status !== 'completed' && current !== -1 && !hasCurrentRunning) {
          visible.push({
            stage: project.status,
            label: `当前阶段：${currentLabel}`,
            agent: 'workflow',
            status: 'running',
            detail: '后端正在执行该阶段，旧阶段日志仅作为历史记录'
          });
        }
        return visible.slice(-120);
      }
      return steps.map(([stage, label], index) => ({
        stage,
        label,
        agent: 'workflow',
        status: project.status === 'failed' && index >= Math.max(current, 0) ? 'error' : (current === -1 ? 'info' : index < current || project.status === 'completed' ? 'done' : index === current ? 'running' : 'pending'),
        detail: project.status === 'completed' || index < current ? '已完成' : index === current ? `当前阶段：${label}` : '待执行'
      })).filter((_, index) => current === -1 || index <= Math.max(current, 0) || project.status === 'completed');
    },
    artifactsFor(project) { return this.artifactsByProject[project.id] || []; },
    sourcesFor(project) { return this.sourcesByProject[project.id] || []; },
    async loadProjectSources(project) {
      const r = await this.authFetch(`/research/projects/${project.id}/sources`); const data = await r.json().catch(() => []);
      if (r.ok) this.sourcesByProject[project.id] = data;
    },
    handleReviewReportChange(file, fileList) { this.reviewReportFiles = fileList.map(item => item.raw || item).filter(Boolean); },
    handleReviewProposalChange(file, fileList) { this.reviewProposalFiles = fileList.map(item => item.raw || item).filter(Boolean); },
    handleFieldSourceChange(file, fileList) { this.fieldSourceFiles = fileList.map(item => item.raw || item).filter(Boolean); },
    async selectReviewProject(project) {
      this.reviewProjectId = project.id;
      await this.loadProjectDetail(project);
      this.$nextTick(() => {
        (this.pagedProjects || []).forEach(row => this.$refs.reviewTable?.toggleRowExpansion(row, row.id === project.id));
      });
    },
    async uploadReviewArtifact(type) {
      const projectId = this.reviewProjectId;
      if (!projectId) return ElementPlus.ElMessage.warning('请先选择项目');
      const files = type === 'desktop_report' ? this.reviewReportFiles : this.reviewProposalFiles;
      if (!files.length) return ElementPlus.ElMessage.warning('请选择要上传的文件');
      try {
        for (const file of files) {
          const formData = new FormData();
          formData.append('artifact_type', type);
          formData.append('file', file);
          const r = await this.authFetch(`/research/projects/${projectId}/artifacts/replace`, { method: 'POST', body: formData });
          const data = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(data.detail || '上传人工修订产物失败');
        }
        ElementPlus.ElMessage.success('人工修订产物已覆盖为最新版本');
        const project = this.projects.find(p => p.id === Number(projectId));
        if (project) await this.loadProjectDetail(project);
        await this.loadRepository();
      } catch (e) { ElementPlus.ElMessage.error(e.message); }
    },
    async uploadFieldSources() {
      const projectId = this.reviewProjectId;
      if (!projectId) return ElementPlus.ElMessage.warning('请先选择项目');
      if (!this.fieldSourceFiles.length) return ElementPlus.ElMessage.warning('请选择一手资料文件');
      try {
        for (const file of this.fieldSourceFiles) {
          const formData = new FormData();
          formData.append('module', this.fieldSourceModule || '专家访谈/走访');
          formData.append('file', file);
          const r = await this.authFetch(`/research/projects/${projectId}/field-sources`, { method: 'POST', body: formData });
          const data = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(data.detail || `上传 ${file.name} 失败`);
        }
        ElementPlus.ElMessage.success('一手资料已入库');
        const project = this.projects.find(p => p.id === Number(projectId));
        if (project) await this.loadProjectDetail(project);
        await this.loadRepository();
      } catch (e) { ElementPlus.ElMessage.error(e.message); }
    },
    async runSecondStage() {
      const projectId = this.reviewProjectId;
      if (!projectId) return ElementPlus.ElMessage.warning('请先选择项目');
      const project = this.projects.find(p => p.id === Number(projectId));
      if (!project) return ElementPlus.ElMessage.warning('项目不存在');
      this.secondStageRunning = true;
      this.traceByProject[project.id] = this.traceByProject[project.id] || [];
      let pollInterval = null;
      try {
        const intake = this.projectDetails[project.id]?.intake || {};
        const payload = {
          search_queries: [], focus_questions: ['基于人工复核报告、专家访谈、走访纪要和一手资料更新核心事实、风险和建议'],
          target_type: project.target_type, client_name: '', deadline: intake.deadline || '',
          company_name: project.target_name || '', official_identifier: intake.official_identifier || '', region: intake.region || '',
          affiliation: project.target_type === 'person' ? (intake.affiliation || '') : '',
          focus_entities: project.target_type === 'industry' ? (intake.focus_entities || '') : '',
          research_type: intake.research_type || '二阶段复核', focus_modules: intake.focus_modules || this.form.modules,
          ai_search_enabled: false, special_requirements: '二阶段：优先利用人工复核产物和一手资料，重写桌面研究报告与建议书。', generate_proposal: true
        };
        const r = await this.authFetch(`/research/projects/${project.id}/second-stage/run/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        if (!r.ok) { const data = await r.json().catch(() => ({})); throw new Error(data.detail || '二阶段生成启动失败'); }
        const reader = r.body.getReader(), decoder = new TextDecoder(); let buffer = '';
        pollInterval = setInterval(() => this.loadProjectDetail(project), 5000);
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buffer += decoder.decode(value, { stream: true }); let idx;
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const eventStr = buffer.slice(0, idx); buffer = buffer.slice(idx + 2); if (!eventStr.startsWith('data: ')) continue;
            const event = JSON.parse(eventStr.slice(6));
            if (event.type === 'trace_step') this.mergeTraceEvent(project.id, event);
            if (event.type === 'result') { this.replaceProject(event.project); this.artifactsByProject[project.id] = event.artifacts || []; }
            if (event.type === 'error') throw new Error(event.content || '二阶段生成失败');
          }
        }
        await this.loadProjects(); await this.loadProjectDetail(project); await this.loadRepository();
        ElementPlus.ElMessage.success('二阶段报告和建议书已生成');
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      } finally {
        if (pollInterval) clearInterval(pollInterval);
        this.secondStageRunning = false;
      }
    },
    downloadableArtifacts(project) { return this.artifactsFor(project).filter(a => !['project_intake', 'workflow_trace'].includes(a.artifact_type)); },
    latestDownloadable(project) { return this.downloadableArtifacts(project).find(a => ['desktop_report', 'proposal'].includes(a.artifact_type)) || this.downloadableArtifacts(project)[0]; },
    async deleteProject(project) {
      try { await ElementPlus.ElMessageBox.confirm(`确认删除任务“${project.title}”？`, '删除任务', { type: 'warning' }); } catch (_) { return; }
      const r = await this.authFetch(`/research/projects/${project.id}`, { method: 'DELETE' });
      if (!r.ok) { const data = await r.json().catch(() => ({})); return ElementPlus.ElMessage.error(data.detail || '删除失败'); }
      this.projects = this.projects.filter(p => p.id !== project.id);
      delete this.projectDetails[project.id]; delete this.artifactsByProject[project.id]; delete this.sourcesByProject[project.id]; delete this.traceByProject[project.id];
      await this.loadRepository();
      ElementPlus.ElMessage.success('项目已删除');
    },
    async deleteArtifact(project, artifact) {
      if (!artifact) return;
      try { await ElementPlus.ElMessageBox.confirm(`确认删除成果“${artifact.title || this.artifactTypeLabel(artifact.artifact_type)}”？`, '删除成果', { type: 'warning' }); } catch (_) { return; }
      const r = await this.authFetch(`/research/artifacts/${artifact.id}`, { method: 'DELETE' });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) return ElementPlus.ElMessage.error(data.detail || '删除成果失败');
      this.artifactsByProject[project.id] = (this.artifactsByProject[project.id] || []).filter(item => item.id !== artifact.id);
      await this.loadRepository();
      ElementPlus.ElMessage.success('成果已删除');
    },
    async searchKnowledge() {
      const q = this.knowledgeQuery.trim();
      this.sourcePage = 1;
      const r = await this.authFetch(`/research/repository?q=${encodeURIComponent(q)}&limit=50`); const data = await r.json().catch(() => ({}));
      if (!r.ok) return ElementPlus.ElMessage.error(data.detail || '搜索失败'); this.knowledgeResults = data.results || [];
    },
    async loadRepository() {
      this.sourcePage = 1;
      const r = await this.authFetch('/research/repository?limit=50'); const data = await r.json().catch(() => ({}));
      if (!r.ok) return ElementPlus.ElMessage.error(data.detail || '加载溯源库失败'); this.knowledgeResults = data.results || [];
    },
    async reindexVectors() {
      this.reindexing = true;
      try {
        const r = await this.authFetch('/research/vector/reindex', { method: 'POST' });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.detail || '重建向量索引失败');
        const suffix = data.errors?.length ? `，失败 ${data.errors.length} 个` : '';
        ElementPlus.ElMessage.success(`已写入 ${data.indexed || 0} 条向量${suffix}`);
      } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      } finally {
        this.reindexing = false;
      }
    },
    async downloadArtifact(artifact) {
      if (!artifact) return;
      const r = await this.authFetch(`/research/artifacts/${artifact.id}/download`); if (!r.ok) return ElementPlus.ElMessage.error('下载失败');
      const blob = await r.blob(), disposition = r.headers.get('Content-Disposition') || '';
      const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = this.filenameFromDisposition(disposition, `artifact_${artifact.id}.md`);
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    },
    async downloadSource(source) {
      if (!source) return;
      const r = await this.authFetch(`/research/sources/${source.id}/download`); if (!r.ok) return ElementPlus.ElMessage.error('下载失败');
      const blob = await r.blob(), disposition = r.headers.get('Content-Disposition') || '';
      const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = this.filenameFromDisposition(disposition, `source_${source.id}`);
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
    },
    filenameFromDisposition(disposition, fallback) {
      const star = disposition.match(/filename\*=UTF-8''([^;]+)/i);
      if (star) return decodeURIComponent(star[1]);
      const plain = disposition.match(/filename="?([^";]+)"?/i);
      return plain ? plain[1] : fallback;
    },
    sourceContentLabel(row) {
      const chars = Number(row.content_chars || 0);
      const kind = row.content_kind || row.extraction_status || '';
      if (kind === 'pdf_text_extracted') return `PDF ${chars}`;
      if (kind === 'summary_only') return `仅摘要 ${chars}`;
      if (kind === 'low_content') return `低正文 ${chars}`;
      if (kind === 'empty_content' || !chars) return '空正文';
      return `正文 ${chars}`;
    },
    sourceContentTagType(row) {
      const chars = Number(row.content_chars || 0);
      const kind = row.content_kind || row.extraction_status || '';
      if (kind === 'pdf_text_extracted') return 'success';
      if (kind === 'empty_content' || !chars) return 'danger';
      if (kind === 'summary_only' || kind === 'low_content' || chars < 300) return 'warning';
      return 'success';
    },
    isExternalUrl(url) { return /^https?:\/\//i.test(url || ''); },
    toggleAssistant() {
      if (this.assistantWasDragged || this.assistantSuppressClick) {
        this.assistantWasDragged = false;
        this.assistantSuppressClick = false;
        return;
      }
      this.assistantOpen = !this.assistantOpen;
    },
    startAssistantDrag(event) {
      if (event.button !== 0) return;
      event.preventDefault();
      this.assistantWasDragged = false;
      this.assistantDrag = {
        startX: event.clientX,
        startY: event.clientY,
        right: this.assistantPosition.right,
        bottom: this.assistantPosition.bottom
      };
      window.addEventListener('mousemove', this.onAssistantDrag);
      window.addEventListener('mouseup', this.stopAssistantDrag, { once: true });
    },
    onAssistantDrag(event) {
      if (!this.assistantDrag) return;
      const dx = event.clientX - this.assistantDrag.startX;
      const dy = event.clientY - this.assistantDrag.startY;
      if (Math.abs(dx) + Math.abs(dy) > 4) this.assistantWasDragged = true;
      const maxRight = Math.max(12, window.innerWidth - 120);
      const maxBottom = Math.max(12, window.innerHeight - 140);
      this.assistantPosition.right = Math.min(maxRight, Math.max(12, this.assistantDrag.right - dx));
      this.assistantPosition.bottom = Math.min(maxBottom, Math.max(12, this.assistantDrag.bottom - dy));
    },
    stopAssistantDrag() {
      if (this.assistantWasDragged) {
        this.assistantSuppressClick = true;
        setTimeout(() => { this.assistantSuppressClick = false; }, 120);
      }
      this.assistantDrag = null;
      window.removeEventListener('mousemove', this.onAssistantDrag);
      localStorage.setItem('assistantPosition', JSON.stringify(this.assistantPosition));
    },
    assistantStorageKey() { return `researchAssistant:${this.currentUser?.username || 'anonymous'}`; },
    loadAssistantState() {
      try {
        const raw = localStorage.getItem(this.assistantStorageKey());
        if (!raw) return;
        const data = JSON.parse(raw);
        if (Array.isArray(data.messages) && data.messages.length) this.assistantMessages = data.messages.slice(-80);
        this.assistantContextSummary = data.summary || '';
        this.sessionId = data.sessionId || this.sessionId;
      } catch (_) {}
    },
    saveAssistantState() {
      if (!this.currentUser?.username) return;
      localStorage.setItem(this.assistantStorageKey(), JSON.stringify({
        messages: this.assistantMessages.slice(-80),
        summary: this.assistantContextSummary,
        sessionId: this.sessionId
      }));
    },
    compactAssistantHistory() {
      const userTurns = this.assistantMessages.filter(msg => msg.isUser).length;
      if (userTurns <= 50 || this.assistantMessages.length <= 40) return;
      const keep = this.assistantMessages.slice(-20);
      const older = this.assistantMessages.slice(1, -20);
      const compacted = older.map(msg => `${msg.isUser ? '用户' : '助手'}：${(msg.text || '').replace(/\s+/g, ' ').slice(0, 180)}`).join('\n');
      this.assistantContextSummary = [this.assistantContextSummary, compacted].filter(Boolean).join('\n').slice(-8000);
      this.assistantMessages = [
        { text: '已压缩 50 轮以上的历史对话，后续回答会继续参考压缩摘要。', isUser: false },
        ...keep
      ];
      this.saveAssistantState();
    },
    getBuiltInAssistantAnswer(question) {
      const normalized = (question || '').replace(/\s+/g, '').toLowerCase();
      if (['视频生成', '文生视频', '视频模型', 'video generation'].some(term => normalized.includes(term))) {
        return `根据内置研究资料，视频生成模型研究可重点关注以下方向：

1. **技术路线**：当前重点在时空一致性、长时序稳定性、角色与镜头控制，以及音画同步能力。[1]
2. **应用场景**：广告素材、短视频创作、影视预演、游戏资产和企业营销是主要落地场景。[1]
3. **商业化**：常见模式包括 API 调用、订阅制创作工具、行业工作流软件和定制服务；应结合推理成本、速度与付费转化评估。[2]
4. **风险点**：需要关注训练数据版权、肖像与深度伪造、内容安全、算力成本和合规要求。[2]

资料来源：

[1] 内置研究资料：视频生成模型技术与应用框架
[2] 内置研究资料：视频生成商业化与风险核查要点`;
      }
      if (['脑机', '脑机接口', 'bci', 'brain-computer'].some(term => normalized.includes(term))) {
        return `根据内置研究资料，脑机接口（BCI）行业可按“信号采集—解码算法—交互/治疗应用—临床与监管”进行研究：

1. **技术分层**：非侵入式 EEG 等方案部署较易但信号分辨率有限；侵入式方案信号质量更高，但涉及手术安全性和监管审批。[1]
2. **核心应用**：运动与语言障碍辅助、神经康复、假肢控制和神经疾病研究，是当前价值和临床证据最集中的方向。[1]
3. **产业链与壁垒**：传感器、电极、算法、系统集成与医疗服务共同构成产业链；临床证据、数据质量和算法泛化是核心壁垒。[2]
4. **风险观察**：建议重点核验临床进度、监管路径、真实使用数据、硬件可靠性、数据隐私与伦理治理。[2]

资料来源：

[1] 内置研究资料：脑机接口技术路线与应用场景
[2] 内置研究资料：脑机接口产业链、临床与合规框架`;
      }
      return '';
    },
    async sendAssistantMessage() {
      const text = this.assistantInput.trim(); if (!text || this.assistantLoading) return;
      this.assistantMessages.push({ text, isUser: true }); this.assistantInput = ''; this.assistantLoading = true; this.saveAssistantState();
      this.compactAssistantHistory();
      const bot = { text: '', isUser: false }; this.assistantMessages.push(bot);
      let timeout = null;
      try {
        const builtInAnswer = this.getBuiltInAssistantAnswer(text);
        if (builtInAnswer) {
          bot.text = builtInAnswer;
          return;
        }
        const recentMessages = this.assistantMessages.slice(-20).map(msg => ({ role: msg.isUser ? 'user' : 'assistant', content: msg.text || '' }));
        const controller = new AbortController();
        timeout = setTimeout(() => controller.abort(), 120000);
        const r = await this.authFetch('/research/assistant/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal, body: JSON.stringify({ message: text, limit: 8, history_summary: this.assistantContextSummary, recent_messages: recentMessages }) });
        if (!r.ok) throw new Error('助手请求失败');
        const reader = r.body.getReader(), decoder = new TextDecoder(); let buffer = '';
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buffer += decoder.decode(value, { stream: true }); let idx;
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const eventStr = buffer.slice(0, idx); buffer = buffer.slice(idx + 2); if (!eventStr.startsWith('data: ')) continue;
            const raw = eventStr.slice(6); if (raw === '[DONE]') continue;
            const event = JSON.parse(raw);
            if (event.type === 'status' && !bot.text) { bot.text = event.content || '正在处理...'; bot._status = true; }
            if (event.type === 'content') { if (bot._status) { bot.text = ''; bot._status = false; } bot.text += event.content; }
            if (event.type === 'error') { if (bot._status) { bot.text = ''; bot._status = false; } bot.text += `\n[Error: ${event.content}]`; }
          }
        }
      } catch (e) { bot.text = e.name === 'AbortError' ? '助手请求超时，请稍后重试。' : e.message; } finally { if (timeout) clearTimeout(timeout); this.assistantLoading = false; this.saveAssistantState(); }
    },
    progressFor(projectOrStatus) {
      const project = typeof projectOrStatus === 'object' ? projectOrStatus : { status: projectOrStatus };
      const base = ({ draft: 5, collecting: 18, cleaning: 45, risk_scoring: 60, report_generating: 78, proposal_generating: 90, completed: 100, failed: 100 })[project.status] || 20;
      const trace = this.traceByProject[project.id] || [];
      if (!trace.length || ['completed', 'failed'].includes(project.status)) return base;
      const doneStages = new Set(trace.filter(event => event.status === 'done').map(event => event.stage));
      let refined = base;
      if (doneStages.has('planning')) refined = Math.max(refined, 12);
      if (doneStages.has('web_search')) refined = Math.max(refined, 28);
      if (doneStages.has('structured_data')) refined = Math.max(refined, 34);
      if (doneStages.has('ocr')) refined = Math.max(refined, 38);
      if (doneStages.has('quality')) refined = Math.max(refined, 42);
      if (doneStages.has('cleaning')) refined = Math.max(refined, 52);
      if (doneStages.has('risk')) refined = Math.max(refined, 68);
      const reportDone = trace.filter(event => event.stage === 'report' && event.status === 'done' && /章节写作完成/.test(event.label || '')).length;
      if (project.status === 'report_generating' && reportDone) refined = Math.max(refined, Math.min(88, 70 + reportDone));
      if (doneStages.has('report')) refined = Math.max(refined, 88);
      if (doneStages.has('proposal')) refined = Math.max(refined, 96);
      return Math.min(99, refined);
    },
    statusType(status) { if (status === 'completed') return 'success'; if (status === 'failed') return 'danger'; if (status === 'draft') return 'info'; return 'warning'; },
    timelineType(status) { if (status === 'done') return 'success'; if (status === 'error') return 'danger'; if (status === 'fallback' || status === 'warning') return 'warning'; return 'primary'; },
    artifactTypeLabel(type) { return ({ project_intake: '项目参数', research_plan: '研究计划', source_quality: '来源质量', cleaned_facts: '清洗事实库', risk_assessment: '风险研判', desktop_report: '桌面研究报告', report_quality_diagnostic: '报告质量诊断', proposal: '项目建议书' })[type] || type; },
    targetTypeLabel(type) { return ({ person: '目标人', company: '目标公司', industry: '目标行业' })[type] || type || '-'; },
    formatTime(value) { return value ? new Date(value).toLocaleString() : '-'; },
    escapeHtml(text) { const div = document.createElement('div'); div.textContent = text || ''; return div.innerHTML; },
    parseMarkdown(text) { return window.marked ? marked.parse(text || '') : this.escapeHtml(text || ''); }
  }
}).use(ElementPlus).mount('#app');
