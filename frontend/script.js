const { createApp } = Vue;

const TASK_STAGE_LABELS = Object.freeze({
  planning: '研究规划', collecting: '资料收集', searching: '资料检索', source_assessing: '来源评估',
  cleaning: '资料清洗', risk_scoring: '风险研判', risk_assessing: '风险研判',
  report_generating: '报告生成', proposal_generating: '建议书生成', pausing: '正在暂停',
});
const TASK_STATE_LABELS = Object.freeze({draft: '未开始', paused: '已暂停', completed: '已完成', failed: '执行失败', diagnostic: '待检查'});

function readAssistantPosition() {
  try {
    const saved = JSON.parse(localStorage.getItem('assistantPosition') || '{}');
    const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
    return {right: valid(saved?.right) ? saved.right : 22, bottom: valid(saved?.bottom) ? saved.bottom : 22};
  } catch (_) { return {right: 22, bottom: 22}; }
}

function readAssistantViewport() {
  if (typeof window === 'undefined') return {width: 1280, height: 800, top: 0};
  return {width: window.innerWidth, height: window.visualViewport?.height || window.innerHeight,
    top: window.visualViewport?.offsetTop || 0};
}

function newResearchForm() {
  return {
    projectName: '', startDate: '', endDate: '', companyName: '', identifier: '',
    industry: '', region: '', targetType: 'company', ddType: '商业尽调', targetContext: '', personContext: '', personAliases: '',
    modules: ['公司背景', '诉讼/制裁', '负面新闻', '融资情报', '管理团队'], aiSearchEnabled: true,
    searchQueries: '', focusQuestions: '', keyQuestions: '',
    industryFocus: '', excludedSegments: '', researchPurpose: '日常了解',
    includeCapitalMarkets: false, asOfDate: ''
  };
}

createApp({
  components: { 'account-management': AccountManagement, 'personal-home': PersonalHome, 'report-versions': ReportVersions },
  data() {
    const viewport = readAssistantViewport();
    return {
      token: localStorage.getItem('accessToken') || '', currentUser: null,
      authStep: 'role', authRole: 'user', authMode: 'login', authLoading: false,
      authForm: { username: '', password: '', confirm_password: '', invitation: '' },
      inviteStatus: '', inviteValid: false, inviteChecking: false, inviteRequestId: 0,
      passwordOpen: false, passwordLoading: false, passwordForm: { current_password: '', new_password: '', confirm_password: '' },
      activeView: 'home', mobileNavOpen: false, projects: [], projectMeta: {}, projectDetails: {}, artifactsByProject: {}, sourcesByProject: {}, traceByProject: {},
      taskSearch: '', taskStatusFilter: '', taskTargetFilter: '', selectedFiles: [], submitting: false, reindexing: false,
      taskStatusOptions: [{value: '', label: '全部状态'}, {value: 'draft', label: '未开始'},
        {value: 'active', label: '进行中'}, {value: 'paused', label: '已暂停'}, {value: 'completed', label: '已完成'},
        {value: 'failed', label: '执行失败'}, {value: 'diagnostic', label: '待检查'}, {value: 'other', label: '其他状态'}],
      reportVersionsOpen: false, reportVersionsProject: null, reportVersionsType: 'desktop_report',
      taskPage: 1, taskPageSize: 12, sourcePage: 1, sourcePageSize: 50,
      nowTick: Date.now(), nowTimer: null, taskRefreshTimer: null, taskRefreshBusy: false, taskRefreshTicks: 0,
      reviewProjectId: '', reviewReportFiles: [], reviewProposalFiles: [], fieldSourceFiles: [], fieldSourceModule: '专家访谈/走访', secondStageRunning: false,
      knowledgeQuery: '', knowledgeResults: [],
      assistantOpen: false, assistantInput: '', assistantLoading: false,
      assistantPosition: readAssistantPosition(), assistantDrag: null, assistantWasDragged: false, assistantSuppressClick: false, assistantContextSummary: '',
      assistantViewportWidth: viewport.width, assistantViewportHeight: viewport.height, assistantViewportTop: viewport.top, assistantFollowLatest: true,
      assistantMessages: [{ text: '你好，我是系统使用向导。可以教你提交任务、下载报告、复核资料和使用知识库，也可以查天气、联网查公开信息和日常聊天。', isUser: false }],
      assistantNavigation: [],
      assistantSessionId: '', assistantSessions: [], assistantHasMore: false, assistantReady: false,
      assistantSyncing: false, assistantMemoryStatus: '', assistantController: null, assistantEpoch: 0,
      modulesByTarget: { company: [
        { label: '公司背景', value: '公司背景' }, { label: '负面新闻', value: '负面新闻' },
        { label: '诉讼 / 制裁', value: '诉讼/制裁' }, { label: '股东高管', value: '股东高管' },
        { label: '融资情报', value: '融资情报' }, { label: '管理团队', value: '管理团队' },
        { label: '创始人背景', value: '创始人背景' }, { label: '竞品公司', value: '竞品公司' },
        { label: '上下游业务', value: '上下游业务' }, { label: '竞品情况', value: '竞品情况' },
        { label: '收入情况', value: '收入情况' }, { label: '行业政策', value: '行业政策' },
        { label: '舆情', value: '舆情' }
      ], person: ['创始人底色画像（家庭/教育/履历）', '人格特质与诚信评估', '商业操守与行业口碑', '经营胜任力（战略/执行/创新）', '识人用人与团队管控', '关联利益冲突（体外公司/代持/关联交易）', '司法负面与诉讼核查', '个人信用与财务风险', '投后治理与退出风险', '同业对标评估', '核心管理团队背景'].map(x => ({ label: x, value: x })), industry: ['行业定义与边界', '细分赛道与产业链', '政策与监管', '市场规模与增长', '竞争格局与代表企业', '商业模式与盈利逻辑', '技术演进与平台生态', '技术路线对比', '投融资与资本市场', '行业风险与不确定性'].map(x => ({ label: x, value: x })) },
      form: newResearchForm()
    };
  },
  computed: {
    isAuthenticated() { return !!this.token && !!this.currentUser; },
    authRoleLabel() { return this.authRole === 'admin' ? '管理员' : '普通用户'; },
    pageTitle() { if (this.activeView === 'home') return '个人首页'; if (this.activeView === 'accounts') return '账号管理'; return this.activeView === 'company-knowledge' ? '公司知识库' : this.activeView === 'tasks' ? '任务管理' : this.activeView === 'sources' ? '溯源库' : this.activeView === 'review' ? '复核与一手资料' : '提交尽调任务'; },
    pageSubtitle() {
      if (this.activeView === 'home') return '查看自己的任务、研究成果与常用入口。';
      if (this.activeView === 'accounts') return '管理公司账号、管理员角色、知识库授权与注册邀请。';
      if (this.activeView === 'company-knowledge') return '让每一份资料，成为下一次决策的起点。';
      if (this.activeView === 'tasks') return '查看任务成果、下载报告，并跟踪工作流 trace。';
      if (this.activeView === 'sources') return '查看来源记录，打开原始网站核对；报告问答请前往公司知识库。';
      if (this.activeView === 'review') return '上传人工修订报告、专家访谈和走访资料，触发二阶段再生成。';
      return '填写核心输入，提交一个新的 AI 尽调任务。';
    },
    generatingCount() { return this.projects.filter(p => !['completed', 'failed', 'draft', 'paused'].includes(p.status)).length; },
    readyCount() { return this.projects.filter(p => p.status === 'completed').length; },
    sourceCount() { return this.knowledgeResults.length; },
    assistantFabStyle() {
      const clamp = (value, maximum) => Math.min(Math.max(16, maximum), Math.max(16, value));
      return {right: `${clamp(this.assistantPosition.right, this.assistantViewportWidth - 84)}px`,
        bottom: `${clamp(this.assistantPosition.bottom, this.assistantViewportHeight - 84)}px`};
    },
    assistantPanelStyle() {
      const width = this.assistantViewportWidth, height = this.assistantViewportHeight;
      if (width <= 600) return {width: `${Math.max(0, width - 24)}px`, height: `${Math.max(0, height - 24)}px`,
        right: '12px', top: `${this.assistantViewportTop + 12}px`, bottom: 'auto'};
      const panelWidth = Math.min(460, width - 32), panelHeight = Math.min(640, height - 32);
      const clamp = (value, maximum) => Math.min(Math.max(16, maximum), Math.max(16, value));
      return {width: `${panelWidth}px`, height: `${panelHeight}px`,
        right: `${clamp(this.assistantPosition.right, width - panelWidth - 16)}px`,
        bottom: `${clamp(this.assistantPosition.bottom, height - panelHeight - 16)}px`};
    },
    fileLabel() { return this.selectedFiles.length ? this.selectedFiles.map(f => f.name).join('、') : 'BP、公司介绍、工商截图、新闻、访谈纪要等'; },
    modules() { return this.modulesByTarget[this.form.targetType] || this.modulesByTarget.company; },
    ddTypes() { if (this.form.targetType === 'person') return ['人物背景尽调', '诚信与声誉核查', '投前人物综合评估']; if (this.form.targetType === 'industry') return ['行业全景研究', '赛道投资研究', '竞争与技术研究']; return ['商业尽调', '合规尽调', '负面新闻筛查', '综合桌面研究']; },
    targetPrimaryLabel() { return this.form.targetType === 'person' ? '目标人物姓名' : this.form.targetType === 'industry' ? '目标行业 / 赛道' : '目标公司名称'; },
    targetSecondaryLabel() { return this.form.targetType === 'person' ? '身份与关联机构（选填）' : this.form.targetType === 'industry' ? '核心企业（选填，多个用顿号分隔）' : '官网 / 统一社会信用代码'; },
    targetSecondaryPlaceholder() { return this.form.targetType === 'person' ? '可填写现任或曾任机构及职位；多个机构用 / 分隔' : this.form.targetType === 'industry' ? '填写需开展公开资料尽调的公司名称；关注产品可写在重点问题中' : ''; },
    filteredProjects() {
      const keyword = this.taskSearch.trim().toLowerCase();
      return this.projects.filter(p => (!this.taskStatusFilter || this.taskStatusGroup(p.status) === this.taskStatusFilter)
        && (!this.taskTargetFilter || p.target_type === this.taskTargetFilter)
        && (!keyword || [p.title, p.target_name, p.industry, p.status, this.taskStatusLabel(p.status),
          this.taskStatusGroup(p.status) === 'active' ? '进行中' : '',
          this.targetTypeLabel(p.target_type)].join(' ').toLowerCase().includes(keyword)));
    },
    hasTaskFilters() { return !!(this.taskSearch.trim() || this.taskStatusFilter || this.taskTargetFilter); },
    pagedProjects() { const start = (this.taskPage - 1) * this.taskPageSize; return this.filteredProjects.slice(start, start + this.taskPageSize); },
    pagedKnowledgeResults() { const start = (this.sourcePage - 1) * this.sourcePageSize; return this.knowledgeResults.slice(start, start + this.sourcePageSize); }
  },
  watch: {
    taskSearch() { this.taskPage = 1; },
    taskStatusFilter() { this.taskPage = 1; },
    taskTargetFilter() { this.taskPage = 1; },
    taskPageSize() { this.taskPage = 1; },
    filteredProjects(projects) {
      this.taskPage = Math.min(this.taskPage, Math.max(1, Math.ceil(projects.length / this.taskPageSize)));
    },
    pagedProjects(projects) {
      if (this.reviewProjectId && !projects.some(project => project.id === this.reviewProjectId)) this.clearReviewSelection();
    },
    knowledgeQuery() { this.sourcePage = 1; },
    'form.targetType'(value) { const defaults = { company: ['公司背景', '诉讼/制裁', '负面新闻', '融资情报', '管理团队'], person: this.modulesByTarget.person.map(x => x.value), industry: this.modulesByTarget.industry.map(x => x.value) }; this.form.modules = defaults[value] || defaults.company; this.form.ddType = this.ddTypes[0]; this.form.targetContext = ''; this.form.personContext = ''; this.form.personAliases = ''; if (value === 'person' || value === 'industry') { this.form.industry = ''; this.form.region = ''; } }
  },
    async mounted() {
      this.updateAssistantViewport();
      window.addEventListener('resize', this.updateAssistantViewport);
      window.visualViewport?.addEventListener('resize', this.updateAssistantViewport);
      window.visualViewport?.addEventListener('scroll', this.updateAssistantViewport);
      this.nowTimer = setInterval(() => { this.nowTick = Date.now(); }, 1000);
      this.taskRefreshTimer = setInterval(() => this.refreshVisibleTaskProgress(), 5000);
      this.readInvitationFromUrl();
      if (this.token) { try { await this.fetchMe(); if (!this.currentUser.must_change_password) { this.ensureAllowedView(); await this.loadAssistantState(); await this.loadProjects(); } } catch (_) { this.handleLogout(); } }
    },
  beforeUnmount() {
    if (this.nowTimer) clearInterval(this.nowTimer);
    if (this.taskRefreshTimer) clearInterval(this.taskRefreshTimer);
    window.removeEventListener('resize', this.updateAssistantViewport);
    window.visualViewport?.removeEventListener('resize', this.updateAssistantViewport);
    window.visualViewport?.removeEventListener('scroll', this.updateAssistantViewport);
    this.stopAssistantDrag();
  },
  methods: {
    authHeaders(extra = {}) { return this.token ? { ...extra, Authorization: `Bearer ${this.token}` } : extra; },
    async authFetch(url, options = {}) {
      const sentToken = this.token;
      const opts = { ...options, headers: this.authHeaders(options.headers || {}) };
      const response = await fetch(url, opts);
      if (sentToken !== this.token) throw new Error('登录账号已变更，请重试');
      if (response.headers.get('X-Password-Change-Required') === 'true' && this.currentUser) { this.currentUser.must_change_password = true; }
      if (response.status === 401) { this.handleLogout(); throw new Error('登录已过期，请重新登录'); }
      return response;
    },
    async fetchMe() { const r = await this.authFetch('/auth/me'); if (!r.ok) throw new Error('认证失败'); this.currentUser = await r.json(); },
    ensureAllowedView() { if (!['home', 'submit', 'tasks', 'review', 'sources', 'company-knowledge', 'accounts'].includes(this.activeView) || (this.activeView === 'accounts' && this.currentUser?.role !== 'admin')) { this.activeView = 'home'; localStorage.setItem('activeView', 'home'); } },
    readInvitationFromUrl() {
      const url = new URL(window.location.href);
      const invitation = new URLSearchParams(url.hash.slice(1)).get('invite') || url.searchParams.get('invite');
      if (!invitation) return;
      url.hash = ''; url.searchParams.delete('invite');
      window.history.replaceState(null, '', url.pathname + url.search);
      if (this.token) { ElementPlus.ElMessage.info('请先退出当前账号，再使用邀请注册链接'); return; }
      this.authRole = 'user'; this.authStep = 'form'; this.authMode = 'register';
      this.authForm.invitation = invitation; this.checkInvitation();
    },
    async checkInvitation() {
      const requestId = ++this.inviteRequestId;
      this.inviteValid = false; this.inviteStatus = '';
      if (!this.authForm.invitation.trim()) return false;
      this.inviteChecking = true;
      try {
        const r = await fetch('/auth/invitations/validate', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({invitation:this.authForm.invitation.trim()}) });
        const data = await r.json();
        if (requestId !== this.inviteRequestId) return;
        if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '邀请码格式有误');
        this.inviteValid = true;
        if (this.authMode === 'register') this.authRole = data.role === 'admin' ? 'admin' : 'user';
        this.inviteStatus = (data.role === 'admin' ? '管理员' : '普通账号') + '邀请有效，到期时间：' + new Date(data.expires_at).toLocaleString();
        return true;
      } catch (e) { if (requestId === this.inviteRequestId) this.inviteStatus = e.message; }
      finally { if (requestId === this.inviteRequestId) this.inviteChecking = false; }
    },
    selectAuthRole(role) {
      this.authRole = role === 'admin' ? 'admin' : 'user'; this.authStep = 'form'; this.authMode = 'login';
      this.authForm.password = ''; this.authForm.confirm_password = '';
    },
    backToRoleSelect() { this.authStep = 'role'; this.authMode = 'login'; this.authForm.password = ''; this.authForm.confirm_password = ''; },
    switchAuthMode() { this.authMode = this.authMode === 'login' ? 'register' : 'login'; this.authForm.password = ''; this.authForm.confirm_password = ''; },
    async acceptAuthentication(data, { openHome = true } = {}) {
      this.token = data.access_token; this.currentUser = {username:data.username, role:data.role, must_change_password:data.must_change_password};
      localStorage.setItem('accessToken', this.token);
      if (openHome) { this.activeView = 'home'; localStorage.setItem('activeView', 'home'); }
      this.ensureAllowedView();
      if (!data.must_change_password) { await this.loadAssistantState(); await this.loadProjects(); }
    },
    async handleAuthSubmit() {
      if (this.authLoading) return;
      const username = this.authForm.username.trim(), password = this.authForm.password;
      if (!username || !password) return ElementPlus.ElMessage.warning('请填写用户名和密码');
      if (this.authMode === 'register') {
        if (!this.authForm.invitation.trim()) return ElementPlus.ElMessage.warning('请填写邀请码');
        if (password !== this.authForm.confirm_password) return ElementPlus.ElMessage.warning('两次输入的密码不一致');
      }
      this.authLoading = true;
      try {
        if (this.authMode === 'register' && !(await this.checkInvitation())) return;
        const payload = {username, password};
        if (this.authMode === 'register') { payload.invitation = this.authForm.invitation.trim(); payload.confirm_password = this.authForm.confirm_password; }
        const r = await fetch(this.authMode === 'login' ? '/auth/login' : '/auth/register', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '输入格式有误，请检查后重试');
        if (this.authMode === 'login' && data.role !== this.authRole) throw new Error(`该账号是${data.role === 'admin' ? '管理员' : '普通用户'}，请从对应入口登录`);
        this.authForm.password = ''; this.authForm.confirm_password = ''; this.authForm.invitation = '';
        this.inviteStatus = ''; this.inviteValid = false;
        await this.acceptAuthentication(data);
      } catch (e) { ElementPlus.ElMessage.error(e.message); } finally { this.authLoading = false; }
    },
    handleLogout() {
      this.assistantEpoch++; this.assistantController?.abort(); this.assistantController = null; this.assistantSessionId = ''; this.assistantSessions = []; this.assistantReady = false; this.assistantSyncing = false; this.assistantMemoryStatus = ''; this.assistantHasMore = false;
      this.activeView = 'home'; this.mobileNavOpen = false; localStorage.setItem('activeView', 'home');
      this.token = ''; this.currentUser = null; this.authStep = 'role'; this.authMode = 'login';
      this.authForm = {username:'',password:'',confirm_password:'',invitation:''}; this.inviteStatus = ''; this.inviteValid = false; this.inviteRequestId++;
      this.passwordOpen = false; this.passwordForm = {current_password:'',new_password:'',confirm_password:''};
      this.projects = []; this.knowledgeResults = []; this.assistantOpen = false; localStorage.removeItem('accessToken');
      this.projectMeta = {}; this.projectDetails = {}; this.artifactsByProject = {}; this.sourcesByProject = {}; this.traceByProject = {};
      this.assistantMessages = []; this.assistantContextSummary = ''; this.assistantInput = ''; this.assistantLoading = false; this.assistantNavigation = []; this.selectedFiles = [];
      this.form = newResearchForm(); this.resetTaskFilters();
      this.clearReviewSelection();
      this.closeReportVersions();
      this.knowledgeQuery = '';
    },
    openPasswordChange() { this.passwordForm = {current_password:'',new_password:'',confirm_password:''}; this.passwordOpen = true; },
    async changePassword() {
      if (this.passwordLoading) return;
      if (!this.passwordForm.current_password || !this.passwordForm.new_password) return ElementPlus.ElMessage.warning('请填写原密码和新密码');
      if (this.passwordForm.new_password !== this.passwordForm.confirm_password) return ElementPlus.ElMessage.warning('两次输入的新密码不一致');
      this.passwordLoading = true;
      try {
        const r = await this.authFetch('/auth/change-password', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(this.passwordForm)});
        const data = await r.json();
        if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '输入格式有误');
        this.passwordOpen = false; this.passwordForm = {current_password:'',new_password:'',confirm_password:''};
        await this.acceptAuthentication(data, { openHome: !!this.currentUser?.must_change_password }); ElementPlus.ElMessage.success('密码已修改，其他登录凭证已失效');
      } catch (e) { ElementPlus.ElMessage.error(e.message); } finally { this.passwordLoading = false; }
    },
    switchView(view) {
      if (!['home', 'submit', 'tasks', 'review', 'sources', 'company-knowledge', 'accounts'].includes(view)) return;
      if (view === 'accounts' && this.currentUser?.role !== 'admin') return;
      this.activeView = view; this.mobileNavOpen = false; localStorage.setItem('activeView', view);
      if (view === 'tasks' || view === 'review') { this.loadProjects(); this.refreshVisibleTaskProgress(); }
      if (view === 'sources') this.loadRepository();
    },
    async openHomeProject(project) {
      const sentToken = this.token;
      try {
        await this.loadProjects();
        if (sentToken !== this.token) return;
        const index = this.projects.findIndex(item => item.id === project.id);
        if (index < 0) throw new Error('任务已不存在或当前账号无法访问，请刷新首页');
        this.resetTaskFilters();
        await this.$nextTick();
        if (sentToken !== this.token) return;
        this.taskPage = Math.floor(index / this.taskPageSize) + 1;
        this.activeView = 'tasks'; localStorage.setItem('activeView', 'tasks');
        await this.$nextTick();
        if (sentToken !== this.token) return;
        await this.viewProject(this.projects[index]);
      } catch (error) { ElementPlus.ElMessage.error(error.message || '加载任务失败'); }
    },
    splitLines(text) { return (text || '').split('\n').map(x => x.trim()).filter(Boolean); },
    industryRunFields(targetType, intake = null) {
      if (targetType !== 'industry') return {};
      if (intake) return {
        industry_focus: intake.industry_focus || '',
        industry_segments: intake.industry_segments || intake.industry_scope?.segments || [],
        excluded_segments: intake.excluded_segments || intake.industry_scope?.excluded_segments || [],
        research_purpose: intake.research_purpose || intake.industry_scope?.purpose || '',
        include_capital_markets: intake.include_capital_markets ?? (intake.industry_scope?.capital_market ? intake.industry_scope.capital_market !== 'none' : null),
        as_of_date: intake.as_of_date || intake.industry_scope?.as_of_date || '',
        industry_scope: intake.industry_scope || {}
      };
      return {
        industry_focus: this.form.industryFocus.trim(),
        excluded_segments: this.form.excludedSegments.split(/[、,，;；\n]+/).map(x => x.trim()).filter(Boolean),
        research_purpose: this.form.researchPurpose,
        include_capital_markets: this.form.includeCapitalMarkets,
        as_of_date: this.form.asOfDate || ''
      };
    },
    handleFileChange(file, fileList) { this.selectedFiles = fileList.map(item => item.raw || item).filter(Boolean); },
    handleFileRemove(file, fileList) { this.selectedFiles = fileList.map(item => item.raw || item).filter(Boolean); },
    async loadProjects() {
      const sentToken = this.token;
      const r = await this.authFetch('/research/projects'); const data = await r.json().catch(() => ({}));
      if (sentToken !== this.token) throw new Error('登录账号已变更，请重试');
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
            ...this.industryRunFields(this.form.targetType),
            start_date: this.form.startDate,
            deadline: this.form.endDate,
            company_name: this.form.companyName,
            official_identifier: this.form.identifier,
            affiliation: this.form.targetType === 'person' ? this.form.targetContext : '',
            person_context: this.form.targetType === 'person' ? this.form.personContext : '',
            person_aliases: this.form.targetType === 'person' ? this.splitLines(this.form.personAliases) : [],
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
        this.resetTaskFilters(); this.projects.unshift(project); this.switchView('tasks'); ElementPlus.ElMessage.success('任务已提交，正在上传资料并启动工作流');
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
        ...this.industryRunFields(this.form.targetType),
        search_queries: this.splitLines(this.form.searchQueries), focus_questions: this.splitLines(this.form.focusQuestions || this.form.keyQuestions),
        target_type: this.form.targetType, client_name: '', deadline: this.form.endDate || '',
        company_name: this.form.companyName || project.target_name || '', official_identifier: this.form.targetType === 'company' ? (this.form.identifier || '') : '', region: this.form.region || '',
        affiliation: this.form.targetType === 'person' ? this.form.targetContext : '',
            person_context: this.form.targetType === 'person' ? this.form.personContext : '',
            person_aliases: this.form.targetType === 'person' ? this.splitLines(this.form.personAliases) : [], focus_entities: this.form.targetType === 'industry' ? this.form.targetContext : '',
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
        ...this.industryRunFields(project.target_type, intake),
        search_queries: intake.search_queries || [],
        focus_questions: intake.focus_questions || [],
        target_type: project.target_type,
        client_name: intake.client_name || '',
        deadline: intake.deadline || '',
        company_name: intake.company_name || project.target_name || '',
        official_identifier: intake.official_identifier || '',
        affiliation: project.target_type === 'person' ? (intake.affiliation || '') : '',
        person_context: intake.person_context || '', person_aliases: intake.person_aliases || [],
        identity_anchors: intake.identity_anchors || '', uploaded_identity_clues: intake.uploaded_identity_clues || [],
        ...(project.target_type === 'person' ? { as_of_date: intake.as_of_date || '' } : {}),
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
      this.$nextTick(() => this.$refs.taskTable?.toggleRowExpansion(this.projects.find(item => item.id === project.id) || project, true));
    },
    async loadProjectDetail(project) {
      const sentToken = this.token;
      const r = await this.authFetch(`/research/projects/${project.id}/detail`); const data = await r.json().catch(() => ({}));
      if (sentToken !== this.token) throw new Error('登录账号已变更，请重试');
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
      if (!this.token || !this.currentUser || this.currentUser.must_change_password || !['tasks', 'review'].includes(this.activeView) || this.taskRefreshBusy) return;
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
    clearReviewSelection() { this.reviewProjectId = ''; this.reviewReportFiles = []; this.reviewProposalFiles = []; this.fieldSourceFiles = []; },
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
          ...this.industryRunFields(project.target_type, intake),
          search_queries: [], focus_questions: [...(intake.focus_questions || []), '基于人工复核报告、专家访谈、走访纪要和一手资料更新核心事实、风险和建议'],
          target_type: project.target_type, client_name: '', deadline: intake.deadline || '',
          company_name: project.target_name || '', official_identifier: intake.official_identifier || '', region: intake.region || '',
          affiliation: project.target_type === 'person' ? (intake.affiliation || '') : '',
        person_context: intake.person_context || '', person_aliases: intake.person_aliases || [],
        identity_anchors: intake.identity_anchors || '', uploaded_identity_clues: intake.uploaded_identity_clues || [],
        ...(project.target_type === 'person' ? { as_of_date: intake.as_of_date || '' } : {}),
          focus_entities: project.target_type === 'industry' ? (intake.focus_entities || '') : '',
          research_type: intake.research_type || '二阶段复核', focus_modules: intake.focus_modules || this.form.modules,
          ai_search_enabled: false, special_requirements: [intake.special_requirements, '二阶段：优先利用人工复核产物和一手资料，重写桌面研究报告与建议书。'].filter(Boolean).join('\n'), generate_proposal: true
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
    recordLabel(version) { return Number.isInteger(version) && version > 0 ? `记录 ${String(version).padStart(3, '0')}` : '历史记录'; },
    openReportVersions(project, artifactType = 'desktop_report') {
      this.reportVersionsProject = {id: project.id, title: project.title || project.project_title || ''};
      this.reportVersionsType = artifactType === 'proposal' ? 'proposal' : 'desktop_report'; this.reportVersionsOpen = true;
    },
    closeReportVersions() { this.reportVersionsOpen = false; this.reportVersionsProject = null; },
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
    async retryArtifactIndex(project, artifact) {
      const response = await this.authFetch(`/research/artifacts/${artifact.id}/reindex`, { method: 'POST' });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        return ElementPlus.ElMessage.error(result.detail || '索引重试失败');
      }
      const result = await response.json();
      Object.assign(artifact, result);
      ElementPlus.ElMessage.success('已单独启动事实索引，报告不会重跑');
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
    isExternalUrl(value) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !!url.hostname && !url.username && !url.password; } catch { return false; } },
    updateAssistantViewport() {
      const viewport = readAssistantViewport();
      this.assistantViewportWidth = viewport.width; this.assistantViewportHeight = viewport.height; this.assistantViewportTop = viewport.top;
    },
    toggleAssistant() {
      if (this.assistantWasDragged || this.assistantSuppressClick) {
        this.assistantWasDragged = false;
        this.assistantSuppressClick = false;
        return;
      }
      this.assistantOpen = !this.assistantOpen;
      if (this.assistantOpen) {
        if (!this.assistantReady) this.loadAssistantState();
        this.updateAssistantViewport(); this.scrollAssistant(true);
        this.$nextTick?.(() => this.$refs?.assistantComposer?.focus());
      }
    },
    closeAssistant() {
      this.assistantOpen = false; this.stopAssistantDrag();
      this.$nextTick?.(() => this.$refs?.assistantLauncher?.focus());
    },
    goToAssistantPage(view) { this.switchView(view); this.closeAssistant(); },
    onAssistantInputKeydown(event) {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault(); this.sendAssistantMessage();
      }
    },
    startAssistantDrag(event, kind = 'launcher') {
      if (event.button !== 0 || event.target?.closest?.('button:not(.assistant-fab), input, textarea, a, summary')) return;
      if (this.assistantViewportWidth <= 600) return;
      event.preventDefault();
      this.assistantWasDragged = false;
      const style = kind === 'panel' ? this.assistantPanelStyle : this.assistantFabStyle;
      this.assistantDrag = {
        kind,
        startX: event.clientX,
        startY: event.clientY,
        right: parseFloat(style.right),
        bottom: parseFloat(style.bottom)
      };
      window.addEventListener('mousemove', this.onAssistantDrag);
      window.addEventListener('mouseup', this.stopAssistantDrag, { once: true });
    },
    onAssistantDrag(event) {
      if (!this.assistantDrag) return;
      const dx = event.clientX - this.assistantDrag.startX;
      const dy = event.clientY - this.assistantDrag.startY;
      if (Math.abs(dx) + Math.abs(dy) > 4) this.assistantWasDragged = true;
      const panel = this.assistantDrag.kind === 'panel';
      const width = panel ? parseFloat(this.assistantPanelStyle.width) : 68;
      const height = panel ? parseFloat(this.assistantPanelStyle.height) : 68;
      const maxRight = Math.max(16, this.assistantViewportWidth - width - 16);
      const maxBottom = Math.max(16, this.assistantViewportHeight - height - 16);
      this.assistantPosition.right = Math.min(maxRight, Math.max(16, this.assistantDrag.right - dx));
      this.assistantPosition.bottom = Math.min(maxBottom, Math.max(16, this.assistantDrag.bottom - dy));
    },
    stopAssistantDrag() {
      const changed = this.assistantDrag && this.assistantWasDragged;
      if (changed && this.assistantDrag.kind === 'launcher') {
        this.assistantSuppressClick = true;
        setTimeout(() => { this.assistantSuppressClick = false; this.assistantWasDragged = false; }, 120);
      } else { this.assistantWasDragged = false; }
      this.assistantDrag = null;
      if (typeof window !== 'undefined') {
        window.removeEventListener('mousemove', this.onAssistantDrag);
        window.removeEventListener('mouseup', this.stopAssistantDrag);
      }
      if (changed) localStorage.setItem('assistantPosition', JSON.stringify(this.assistantPosition));
    },
    assistantStorageKey() { return `systemGuide:v1:${this.currentUser?.username || 'anonymous'}`; },
    applyAssistantState(data) {
      this.assistantFollowLatest = true;
      this.assistantSessionId = data.session_id;
      this.assistantSessions = data.sessions || [];
      this.assistantMessages = data.messages?.length ? data.messages : [{ text: '你好，我是系统使用向导。可以解答系统操作、查天气和公开信息，也可以日常聊天。', isUser: false }];
      this.assistantContextSummary = data.summary || '';
      this.assistantHasMore = !!data.has_more; this.assistantReady = true;
      this.assistantMemoryStatus = data.busy ? '此对话正在生成，可稍后重新加载' : (data.summarized_through ? '已保存到账号 · 较早对话已整理为摘要' : '已保存到账号');
    },
    async assistantJson(url, options = {}) {
      const response = await this.authFetch(url, options);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '对话同步失败，请重试');
      return data;
    },
    async loadAssistantState() {
      if (this.assistantSyncing || !this.currentUser) return;
      const epoch = ++this.assistantEpoch, key = this.assistantStorageKey();
      this.assistantController?.abort(); this.assistantLoading = false; this.assistantSyncing = true; this.assistantReady = false;
      this.assistantMessages = [{ text: '你好，我是系统使用向导。可以解答系统操作、查天气和公开信息，也可以日常聊天。', isUser: false }];
      this.assistantContextSummary = ''; this.assistantInput = ''; this.assistantNavigation = [];
      try {
        let data = await this.assistantJson('/research/assistant/state');
        if (epoch !== this.assistantEpoch) return;
        const raw = localStorage.getItem(key);
        if (raw && !data.legacy_imported) {
          let legacy; try { legacy = JSON.parse(raw); } catch (_) { legacy = {}; }
          data = await this.assistantJson('/research/assistant/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: (Array.isArray(legacy.messages) ? legacy.messages : []).slice(-80), summary: String(legacy.summary || '').slice(-8000) }) });
          if (epoch !== this.assistantEpoch) return;
        }
        localStorage.removeItem(key); // Remove old plaintext cache only after a successful cloud load/import.
        this.applyAssistantState(data); this.scrollAssistant();
      } catch (error) { if (epoch === this.assistantEpoch) this.assistantMemoryStatus = error.message; }
      finally { if (epoch === this.assistantEpoch) this.assistantSyncing = false; }
    },
    async changeAssistantSession(action, sessionId = '') {
      if (this.assistantSyncing) return;
      const startingEpoch = this.assistantEpoch;
      if (action === 'clear') {
        try { await ElementPlus.ElMessageBox.confirm('将删除当前账号全部小助手对话和记忆，无法撤销。公司知识库资料不受影响。', '清空小助手记录', { confirmButtonText: '删除全部记录', cancelButtonText: '取消', type: 'warning' }); } catch (_) { return; }
      }
      if (startingEpoch !== this.assistantEpoch || !this.currentUser) return;
      const epoch = ++this.assistantEpoch;
      this.assistantController?.abort(); this.assistantController = null; this.assistantLoading = false; this.assistantSyncing = true;
      try {
        const url = action === 'clear' ? '/research/assistant/history' : action === 'new' ? '/research/assistant/sessions' : `/research/assistant/sessions/${encodeURIComponent(sessionId)}/activate`;
        const data = await this.assistantJson(url, { method: action === 'clear' ? 'DELETE' : 'POST' });
        if (epoch !== this.assistantEpoch) return;
        localStorage.removeItem(this.assistantStorageKey()); this.assistantInput = ''; this.assistantNavigation = [];
        this.applyAssistantState(data); this.scrollAssistant();
      } catch (error) { if (epoch === this.assistantEpoch) { this.assistantMemoryStatus = error.message; this.assistantReady = false; } }
      finally { if (epoch === this.assistantEpoch) this.assistantSyncing = false; }
    },
    async loadOlderAssistant() {
      if (!this.assistantHasMore || this.assistantSyncing || this.assistantLoading) return;
      const first = this.assistantMessages.find(msg => msg.id), epoch = this.assistantEpoch;
      if (!first) return;
      this.assistantSyncing = true;
      try {
        const data = await this.assistantJson(`/research/assistant/sessions/${this.assistantSessionId}/messages?before_id=${first.id}`);
        if (epoch !== this.assistantEpoch) return;
        this.assistantMessages = [...data.messages, ...this.assistantMessages]; this.assistantHasMore = !!data.has_more;
      } catch (error) { if (epoch === this.assistantEpoch) this.assistantMemoryStatus = error.message; }
      finally { if (epoch === this.assistantEpoch) this.assistantSyncing = false; }
    },
    askGuide(question) { this.assistantInput = question; return this.sendAssistantMessage(); },
    async retryKnowledge(artifact) {
      try {
        const response = await this.authFetch('/research/artifacts/' + artifact.id + '/knowledge/retry', { method: 'POST' });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || '重试失败');
        artifact.metadata = result.metadata;
        ElementPlus.ElMessage[result.metadata.knowledge_sync_status === 'failed' ? 'warning' : 'success'](
          result.metadata.knowledge_sync_status === 'failed' ? '归档暂未完成，请联系管理员检查配置。' : '报告已加入知识库处理队列');
      } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    openMyKnowledgeProjects() { sessionStorage.setItem("companyKnowledgeOpenMyProjects", "1"); this.switchView("company-knowledge"); },
    knowledgeStatus(artifact) {
      return ({ queued: '等待索引', uploading: '上传中', parsing: '解析中', indexing: '索引中', ready: '可问答', failed: '入库失败', deleted: '已从知识库移除' })[artifact.metadata?.knowledge_sync_status] || '尚未归档';
    },
    onAssistantScroll() {
      const feed = this.$refs?.assistantMessages;
      if (feed) this.assistantFollowLatest = feed.scrollHeight - feed.clientHeight - feed.scrollTop < 64;
    },
    scrollAssistant(force = false) {
      if (force) this.assistantFollowLatest = true;
      if (!this.assistantFollowLatest) return;
      this.$nextTick?.(() => {
        const feed = this.$refs?.assistantMessages;
        if (feed && this.assistantFollowLatest) feed.scrollTop = feed.scrollHeight;
      });
    },
    async sendAssistantMessage() {
      const text = this.assistantInput.trim(); if (!text || this.assistantLoading || this.assistantSyncing) return;
      if (!this.assistantReady) { this.assistantMemoryStatus = '请先重新加载对话，确保账号历史已同步'; return; }
      const epoch = this.assistantEpoch, sessionId = this.assistantSessionId;
      this.assistantMessages.push({ text, isUser: true }); this.assistantInput = ''; this.assistantLoading = true; this.assistantMemoryStatus = '正在保存并生成回答…';
      const userMessage = this.assistantMessages[this.assistantMessages.length - 1];
      this.assistantMessages.push({ text: '', isUser: false });
      const bot = this.assistantMessages[this.assistantMessages.length - 1]; this.scrollAssistant(true);
      let timeout = null, saved = false;
      try {
        const controller = new AbortController(); this.assistantController = controller;
        timeout = setTimeout(() => controller.abort(), 135000);
        const r = await this.authFetch('/research/assistant/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal, body: JSON.stringify({ message: text, current_page: this.activeView, session_id: sessionId, request_id: globalThis.crypto?.randomUUID?.() }) });
        if (epoch !== this.assistantEpoch) return;
        if (!r.ok) { const data = await r.json().catch(() => ({})); throw new Error(data.detail || '助手请求失败'); }
        const reader = r.body.getReader(), decoder = new TextDecoder(); let buffer = '';
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          if (epoch !== this.assistantEpoch) { await reader.cancel?.(); return; }
          buffer += decoder.decode(value, { stream: true }); let idx;
          while ((idx = buffer.indexOf('\n\n')) !== -1) {
            const eventStr = buffer.slice(0, idx); buffer = buffer.slice(idx + 2); if (!eventStr.startsWith('data: ')) continue;
            const raw = eventStr.slice(6); if (raw === '[DONE]') continue;
            const event = JSON.parse(raw);
            if (event.type === 'status' && (!bot.text || bot._status)) { bot.text = event.content || '正在处理...'; bot._status = true; }
            if (event.type === 'sources') bot.sources = (Array.isArray(event.sources) ? event.sources : []).filter(source => this.isExternalUrl(source.url)).slice(0, 10);
            if (event.type === 'memory') { saved = !!event.saved; userMessage.id = event.user_message_id; bot.id = event.assistant_message_id; const session = this.assistantSessions.find(item => item.id === sessionId); if (session && event.session_title) session.title = event.session_title; this.assistantMemoryStatus = event.status === 'deferred' ? '已保存 · 摘要暂未完成，当前仅参考部分历史，后续重试' : (event.summarized ? '已保存到账号 · 较早对话已整理为摘要' : '已保存到账号'); }
            if (event.type === 'navigation') this.assistantNavigation = (event.items || []).filter(item =>
              ['home','submit','tasks','review','sources','company-knowledge'].includes(item.view) || (item.view === 'accounts' && this.currentUser?.role === 'admin'));
            if (event.type === 'content') { if (bot._status) { bot.text = ''; bot._status = false; } bot.text += event.content; }
            if (event.type === 'error') { if (bot._status) { bot.text = ''; bot._status = false; } bot.text += `\n[Error: ${event.content}]`; }
            this.scrollAssistant();
          }
        }
        if (epoch === this.assistantEpoch && !saved) this.assistantMemoryStatus = '回答未确认保存，请重新加载核对';
      } catch (e) { if (epoch === this.assistantEpoch) { bot.text = e.name === 'AbortError' ? '请求已中断，请重新加载查看保存状态。' : e.message; this.assistantMemoryStatus = '请重新加载核对服务器记录'; } }
      finally { if (timeout) clearTimeout(timeout); if (epoch === this.assistantEpoch) { this.assistantLoading = false; this.assistantController = null; } }
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
    taskStatusLabel(status) {
      if (Object.hasOwn(TASK_STATE_LABELS, status)) return TASK_STATE_LABELS[status];
      return Object.hasOwn(TASK_STAGE_LABELS, status) ? TASK_STAGE_LABELS[status] : '待处理';
    },
    taskStatusGroup(status) {
      if (Object.hasOwn(TASK_STATE_LABELS, status)) return status;
      return Object.hasOwn(TASK_STAGE_LABELS, status) ? 'active' : 'other';
    },
    resetTaskFilters() { this.taskSearch = ''; this.taskStatusFilter = ''; this.taskTargetFilter = ''; this.taskPage = 1; },
    statusType(status) { if (status === 'completed') return 'success'; if (status === 'failed') return 'danger'; return this.taskStatusGroup(status) === 'active' ? 'warning' : 'info'; },
    timelineType(status) { if (status === 'done') return 'success'; if (status === 'error') return 'danger'; if (status === 'fallback' || status === 'warning') return 'warning'; return 'primary'; },
    artifactTypeLabel(type) { return ({ project_intake: '项目参数', research_plan: '研究计划', source_quality: '来源质量', cleaned_facts: '清洗事实库', risk_assessment: '风险研判', desktop_report: '桌面研究报告', report_quality_diagnostic: '报告质量诊断', industry_claim_ledger: '结论证据台账', industry_run: '运行记录', proposal: '项目建议书' })[type] || type; },
    targetTypeLabel(type) { return ({ person: '目标人', company: '目标公司', industry: '目标行业' })[type] || type || '-'; },
    formatTime(value) {
      const timestamp = this.eventTimestampMs({ timestamp: value });
      return timestamp ? new Date(timestamp).toLocaleString() : '-';
    },
    escapeHtml(text) { const div = document.createElement('div'); div.textContent = text || ''; return div.innerHTML; },
    parseMarkdown(text) { return window.SafeMarkdown ? window.SafeMarkdown.render(text) : this.escapeHtml(text); }
  }
}).component('company-knowledge', CompanyKnowledge).use(ElementPlus).mount('#app');
