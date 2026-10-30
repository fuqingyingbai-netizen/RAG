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
      activeView: 'home', mobileNavOpen: false, projects: [], projectSummary: {}, projectMeta: {}, projectDetails: {}, artifactsByProject: {}, sourcesByProject: {}, traceByProject: {},
      artifactHistory: {}, artifactHistoryRequests: {},
      traceActivityByProject: {},
      taskSearch: '', taskStatusFilter: '', taskTargetFilter: '', selectedFiles: [], submitting: false, reindexing: false,
      startingProjects: {}, recoveryBusy: {}, taskUploadIssues: {},
      pendingActions: {}, actionPromises: {}, actionErrors: {}, actionSequence: 0,
      reviewIntakes: {}, reviewSelectionSeq: 0, detailLoadedAt: {}, repositoryRequestId: 0,
      taskStatusOptions: [{value: '', label: '全部状态'}, {value: 'draft', label: '未开始'},
        {value: 'active', label: '进行中'}, {value: 'paused', label: '已暂停'}, {value: 'completed', label: '已完成'},
        {value: 'failed', label: '执行失败'}, {value: 'diagnostic', label: '待检查'}, {value: 'waiting', label: '待继续'}, {value: 'other', label: '其他状态'}],
      reportVersionsOpen: false, reportVersionsProject: null, reportVersionsType: 'desktop_report',
      taskPage: 1, taskPageSize: 12, sourcePage: 1, sourcePageSize: 50,
      nowTick: Date.now(), nowTimer: null, taskRefreshTimer: null, taskRefreshBusy: false, taskRefreshTicks: 0,
      reviewProjectId: '', reviewReportFiles: [], reviewProposalFiles: [], fieldSourceFiles: [], fieldSourceModule: '专家访谈/走访', secondStageRunning: false, secondStageProjectId: '',
      knowledgeQuery: '', knowledgeResults: [],
      assistantOpen: false, assistantInput: '', assistantLoading: false,
      assistantImages: [], assistantImageBusy: false, assistantDraftEpoch: 0,
      assistantPosition: readAssistantPosition(), assistantDrag: null, assistantWasDragged: false, assistantSuppressClick: false, assistantContextSummary: '',
      assistantViewportWidth: viewport.width, assistantViewportHeight: viewport.height, assistantViewportTop: viewport.top, assistantFollowLatest: true,
      assistantMessages: [{ text: '你好，我主要负责本系统的使用指南。可以点“功能目录”查找具体操作，或直接问任务、报告、资料和权限怎么使用，也可以日常聊天和查公开信息。', isUser: false }],
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
    visibleActions() { return Object.values(this.pendingActions).slice(0, 4); },
    visibleActionErrors() { return Object.entries(this.actionErrors).slice(-3); },
    reviewWriteBusy() { return Object.keys(this.pendingActions).some(key => key.startsWith('review-upload:') || key.startsWith('field-upload:')); },
    reviewInputsLocked() { return this.reviewWriteBusy || (this.secondStageRunning && this.secondStageProjectId === this.reviewProjectId); },
    repositoryLoading() { return Object.keys(this.pendingActions).some(key => key.startsWith('repository:')); },
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
    generatingCount() { return this.projects.filter(p => this.projectIsRunning(p)).length; },
    readyCount() { return this.projects.filter(p => p.status === 'completed').length; },
    sourceCount() { return Number.isInteger(this.projectSummary.source_count) ? this.projectSummary.source_count : '—'; },
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
      return this.projects.filter(p => (!this.taskStatusFilter || this.projectStatusGroup(p) === this.taskStatusFilter)
        && (!this.taskTargetFilter || p.target_type === this.taskTargetFilter)
        && (!keyword || [p.title, p.target_name, p.industry, p.status, this.projectStateLabel(p),
          this.projectStatusGroup(p) === 'active' ? '进行中' : '',
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
      if (this.token) {
        try { await this.fetchMe(); } catch (_) { this.handleLogout(); return; }
        if (!this.currentUser.must_change_password) {
          this.ensureAllowedView(); this.loadAssistantState(); await this.loadProjects().catch(() => null);
        }
      }
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
    actionPending(key) { return !!this.pendingActions[key]; },
    actionWaitText(action) {
      const seconds = Math.max(0, Math.floor((this.nowTick - action.startedAt) / 1000));
      return `${action.phase || action.label} · 已等待 ${seconds} 秒` + (seconds >= 10
        ? (action.readOnly ? '，仍在读取，请稍候；可以继续浏览其他页面。' : '，尚未确认完成，请勿重复提交。') : '');
    },
    runAction(key, label, work, {readOnly = false, silent = false, retryAdvice = ''} = {}) {
      if (this.actionPromises[key]) return this.actionPromises[key];
      const sentToken = this.token, id = ++this.actionSequence;
      delete this.actionErrors[key];
      if (!silent) this.pendingActions[key] = {id, label, phase: label, startedAt: Date.now(), readOnly, retryAdvice};
      const phase = (text, options = {}) => {
        if (sentToken === this.token && this.pendingActions[key]?.id === id) {
          this.pendingActions[key].phase = text;
          if (typeof options?.readOnly === 'boolean') this.pendingActions[key].readOnly = options.readOnly;
          if (typeof options?.retryAdvice === 'string') this.pendingActions[key].retryAdvice = options.retryAdvice;
        }
      };
      const promise = (async () => {
        await Promise.resolve();
        try { return await work(phase); }
        catch (error) {
          const uploadIssue = /^(?:review-upload|field-upload):/.test(key) ? this.taskUploadIssues[key.split(':').at(-1)] : null;
          const failedReadOnly = this.pendingActions[key]?.readOnly ?? readOnly;
          if (!silent && sentToken === this.token) this.actionErrors[key] = {label,
            message: uploadIssue ? uploadIssue.title + '。' + uploadIssue.advice : error.message || '操作未完成，请检查网络后重试',
            advice: this.pendingActions[key]?.retryAdvice || (failedReadOnly ? '可重新点击按钮读取；不会启动研究。' : '请先核对任务或资料的保存状态，再决定是否重试，避免重复提交。')};
          throw error;
        } finally {
          if (sentToken === this.token) {
            if (this.pendingActions[key]?.id === id) delete this.pendingActions[key];
            if (this.actionPromises[key] === promise) delete this.actionPromises[key];
          }
        }
      })();
      this.actionPromises[key] = promise;
      return promise;
    },
    readJSON(url, failureMessage, timeoutMs = 30000, options = {}) {
      return this.readWithTimeout(url, response => response.json(), failureMessage, timeoutMs, options);
    },
    readDownload(url, failureMessage) {
      return this.readWithTimeout(url, async response => response.ok
        ? {blob:await response.blob(), disposition:response.headers.get('Content-Disposition') || ''}
        : response.json().catch(() => ({})), failureMessage, 120000);
    },
    async readWithTimeout(url, parse, failureMessage, timeoutMs, {signal} = {}) {
      const sentToken = this.token;
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      const stopped = () => { const error = new Error('已停止读取'); error.name = 'AbortError'; return error; };
      if (signal?.aborted) throw stopped();
      let timer, onAbort;
      const cancelled = signal ? new Promise((_, reject) => {
        onAbort = () => { controller?.abort(); reject(stopped()); };
        signal.addEventListener('abort', onAbort, {once:true});
      }) : null;
      const request = (async () => {
        let response, data;
        try { response = await this.authFetch(url, controller ? {signal: controller.signal} : {}); }
        catch (error) {
          if (error.name === 'TypeError' && sentToken === this.token && !controller?.signal.aborted)
            throw new Error(`${failureMessage}：网络连接失败，请检查服务后重试。`);
          throw error;
        }
        try { data = await parse(response); }
        catch (error) {
          if (sentToken !== this.token) throw new Error('登录账号已变更，请重试');
          if (error.name === 'AbortError' || controller?.signal.aborted) throw error;
          throw new Error(`${failureMessage}：${response.ok ? '响应内容暂时无法读取' : '服务暂时不可用'}，请稍后重试。`);
        }
        if (sentToken !== this.token) throw new Error('登录账号已变更，请重试');
        if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : failureMessage);
        return data;
      })();
      try {
        const waiting = [request];
        if (cancelled) waiting.push(cancelled);
        if (typeof setTimeout === 'function') waiting.push(new Promise((_, reject) => {
          timer = setTimeout(() => { controller?.abort(); reject(new Error(`${failureMessage}：读取超时，请重试；未启动任何研究任务。`)); }, timeoutMs);
        }));
        return await Promise.race(waiting);
      } finally { if (timer) clearTimeout(timer); if (onAbort) signal.removeEventListener('abort', onAbort); }
    },
    authHeaders(extra = {}) { return this.token ? { ...extra, Authorization: `Bearer ${this.token}` } : extra; },
    async authFetch(url, options = {}) {
      const sentToken = this.token;
      const assertCurrent = () => { if (sentToken !== this.token) throw new Error('登录账号已变更，请重试'); };
      const opts = { ...options, headers: this.authHeaders(options.headers || {}) };
      const response = await fetch(url, opts);
      assertCurrent();
      if (response.headers.get('X-Password-Change-Required') === 'true' && this.currentUser) { this.currentUser.must_change_password = true; }
      if (response.status === 401) { this.handleLogout(); throw new Error('登录已过期，请重新登录'); }
      return new Proxy(response, {get(target, key) {
        assertCurrent();
        const value = Reflect.get(target, key, target);
        if (['json','blob','text','arrayBuffer'].includes(key) && typeof value === 'function') return async (...args) => {
          assertCurrent(); const body = await value.apply(target, args); assertCurrent(); return body;
        };
        return typeof value === 'function' ? value.bind(target) : value;
      }});
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
      this.resetAssistantImages();
      this.assistantEpoch++; this.assistantController?.abort(); this.assistantController = null; this.assistantSessionId = ''; this.assistantSessions = []; this.assistantReady = false; this.assistantSyncing = false; this.assistantMemoryStatus = ''; this.assistantHasMore = false;
      this.activeView = 'home'; this.mobileNavOpen = false; localStorage.setItem('activeView', 'home');
      this.token = ''; this.currentUser = null; this.authStep = 'role'; this.authMode = 'login';
      this.authForm = {username:'',password:'',confirm_password:'',invitation:''}; this.inviteStatus = ''; this.inviteValid = false; this.inviteRequestId++;
      this.passwordOpen = false; this.passwordForm = {current_password:'',new_password:'',confirm_password:''};
      this.projects = []; this.projectSummary = {}; this.artifactHistory = {}; this.artifactHistoryRequests = {}; this.traceActivityByProject = {}; this.knowledgeResults = []; this.assistantOpen = false; localStorage.removeItem('accessToken');
      this.projectMeta = {}; this.projectDetails = {}; this.artifactsByProject = {}; this.sourcesByProject = {}; this.traceByProject = {}; this.recoveryBusy = {}; this.taskUploadIssues = {};
      this.pendingActions = {}; this.actionPromises = {}; this.actionErrors = {}; this.reviewIntakes = {}; this.detailLoadedAt = {};
      this.startingProjects = {}; this.secondStageRunning = false; this.secondStageProjectId = '';
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
      if (view === 'tasks' || view === 'review') { this.loadProjects().catch(() => null); this.refreshVisibleTaskProgress(); }
      if (view === 'sources') this.loadRepository().catch(() => null);
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
      return this.runAction('projects', '正在读取任务列表', async () => {
        const sentToken = this.token;
        const data = await this.readJSON('/research/projects', '加载任务失败');
        if (sentToken !== this.token) return;
        this.projects = data.projects || [];
        this.projectSummary = data.summary || {};
      }, {readOnly: true});
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
      await this.postTaskUpload(projectId, `/research/projects/${projectId}/upload`, formData);
    },
    async postTaskUpload(projectId, url, formData) {
      const sentToken = this.token;
      try {
        const response = await this.authFetch(url, {method: 'POST', body: formData});
        const data = await response.json().catch(() => ({}));
        if (sentToken !== this.token) throw new Error('登录账号已变更，请重试');
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '资料上传未完成');
        delete this.taskUploadIssues[projectId];
        return data;
      } catch (error) {
        if (sentToken === this.token) {
          const parsing = /解析|提取文本|extract|parse/i.test(error.message || '');
          this.taskUploadIssues[projectId] = {
            kind: 'upload', title: parsing ? '本次文件解析未完成' : '本次上传尚未确认成功', stage: parsing ? '文件解析' : '资料上传',
            reason: '本次请求未获成功确认，保存情况以刷新后的系统记录为准。',
            advice: parsing ? '请检查文件能否正常打开、文字是否清晰，可换用文字版后上传。先核对已保存记录，再决定是否补传。'
              : '请先刷新并核对已有资料，避免重复上传；再检查文件格式和网络状态，决定是否重试。',
            actions: [{kind: 'review', label: '检查或补充资料'}],
          };
          if (this.projectDetails[projectId]) {
            try { await this.loadProjectDetail({id: Number(projectId)}); } catch (_) { /* Never claim an unconfirmed upload was saved. */ }
          }
        }
        throw error;
      }
    },
    async readWorkflowEvents(response, sentToken, onEvent) {
      if (!response.body) throw new Error('浏览器未收到进度连接，请在任务管理核对状态，不要重复启动。');
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = '';
      const consume = block => {
        const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n');
        if (!data) return '';
        let event;
        try { event = JSON.parse(data); }
        catch (_) { throw new Error('收到的进度消息不完整，请在任务管理核对状态，不要重复启动。'); }
        onEvent(event);
        return ['result','paused'].includes(event.type) ? event.type : '';
      };
      try {
        while (true) {
          const {done, value} = await reader.read();
          if (sentToken !== this.token) return 'account_changed';
          buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
          buffer = buffer.replace(/\r\n/g, '\n');
          let boundary;
          while ((boundary = buffer.indexOf('\n\n')) >= 0) {
            const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
            const terminal = consume(block); if (terminal) return terminal;
          }
          if (done) break;
        }
        return buffer.trim() ? consume(buffer) || 'closed' : 'closed';
      } finally {
        try { await reader.cancel?.(); } catch (_) { /* The backend job continues independently of this connection. */ }
        reader.releaseLock?.();
      }
    },
    async runWorkflow(project) {
      const sentToken = this.token;
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
      const pollInterval = setInterval(() => { if (sentToken === this.token) this.refreshProjectProgress(project).catch(() => null); }, 5000);
      try {
        const outcome = await this.readWorkflowEvents(r, sentToken, event => {
            if (event.type === 'trace_step') this.mergeTraceEvent(project.id, event);
            if (event.type === 'result') { this.replaceProject(event.project); this.artifactsByProject[project.id] = event.artifacts || []; }
            if (event.type === 'paused') { project.status = 'paused'; ElementPlus.ElMessage.info(event.content || '任务已暂停'); }
            if (event.type === 'error') throw new Error(event.content || '工作流失败');
        });
        if (outcome === 'closed') throw new Error('进度连接已结束，尚未确认任务完成。请在任务管理核对状态，不要重复启动。');
      } finally { clearInterval(pollInterval); await this.refreshAfterWorkflow(project, sentToken); }
    },
    async rerunProject(project) {
      if (this.startingProjects[project.id]) return;
      const sentToken = this.token;
      this.startingProjects[project.id] = true;
      try {
        await this.runAction(`rerun:${project.id}`, '正在读取重跑参数', async phase => {
          const data = await this.readJSON(`/research/projects/${project.id}/run-intake`, '加载重跑参数失败');
          phase('正在提交重跑请求，请勿重复点击', {readOnly:false, retryAdvice:''});
          await this.runExistingWorkflow(project, data.intake || {}, () => {
            phase('重跑已在后台执行，可在任务管理查看进度');
            ElementPlus.ElMessage.success('重跑请求已接收，正在更新任务进度');
            this.refreshProjectProgress(project).catch(() => null);
          });
        }, {readOnly:true, retryAdvice:'参数未读成功，本次未启动研究；重新点击“重跑”将在参数读取成功后提交研究请求。'});
      } catch (e) {
        if (sentToken === this.token) ElementPlus.ElMessage.error(e.message);
      } finally {
        if (sentToken === this.token) delete this.startingProjects[project.id];
      }
    },
    projectIsRunning(project) {
      if (!project) return false;
      if (typeof project?.is_running === 'boolean') return project.is_running;
      return this.taskStatusGroup(project.status) === 'active';
    },
    projectStateLabel(project) {
      if (project?.state_label) return project.state_label;
      if (project?.is_running === false && this.taskStatusGroup(project.status) === 'active') return '待继续';
      return this.taskStatusLabel(project?.status);
    },
    projectStatusGroup(project) {
      if (this.projectIsRunning(project)) return 'active';
      return this.taskStatusGroup(project.status) === 'active' ? 'waiting' : this.taskStatusGroup(project.status);
    },
    projectStateType(project) {
      return this.projectIsRunning(project) ? 'warning' : this.projectStatusGroup(project) === 'waiting' ? 'info' : this.statusType(project.status);
    },
    canPauseProject(project) { return this.projectIsRunning(project); },
    async pauseProject(project) {
      try { await this.runAction(`pause:${project.id}`, '正在提交暂停请求', async () => {
      const r = await this.authFetch(`/research/projects/${project.id}/pause`, { method: 'POST' });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || '暂停失败');
      project.status = data.status || 'pausing';
      ElementPlus.ElMessage.success(data.message || '已提交暂停请求');
      this.loadProjects().catch(() => null);
      }); } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    async runExistingWorkflow(project, savedIntake = null, onConnected = null) {
      const sentToken = this.token;
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
      if (onConnected) onConnected();
      const pollInterval = setInterval(() => { if (sentToken === this.token) this.refreshProjectProgress(project).catch(() => null); }, 5000);
      try {
        const outcome = await this.readWorkflowEvents(r, sentToken, event => {
            if (event.type === 'trace_step') this.mergeTraceEvent(project.id, event);
            if (event.type === 'result') { this.replaceProject(event.project); this.artifactsByProject[project.id] = event.artifacts || []; }
            if (event.type === 'paused') { project.status = 'paused'; ElementPlus.ElMessage.info(event.content || '任务已暂停'); }
            if (event.type === 'error') throw new Error(event.content || '工作流失败');
        });
        if (outcome === 'closed') throw new Error('进度连接已结束，尚未确认任务完成。请在任务管理核对状态，不要重复启动。');
      } finally { clearInterval(pollInterval); await this.refreshAfterWorkflow(project, sentToken); }
    },
    async refreshAfterWorkflow(project, sentToken) {
      if (sentToken !== this.token) return;
      try { await this.loadProjects(); } catch (_) { /* A refresh must not replace the original failure reason. */ }
      if (sentToken !== this.token || !this.projectDetails[project.id]) return;
      try { await this.loadProjectDetail(project, {force: true}); } catch (_) { /* The panel retains its last confirmed snapshot. */ }
    },
    recoveryFor(project) {
      const detail = this.projectDetails[project.id];
      if (detail?.project?.status !== project.status || !detail.recovery) return null;
      const upload = this.taskUploadIssues[project.id];
      return upload ? {...detail.recovery, issues: [upload, ...(detail.recovery.issues || [])]} : detail.recovery;
    },
    async runRecoveryAction(project, action) {
      if (this.recoveryBusy[project.id] || this.startingProjects[project.id]) return;
      const sentToken = this.token;
      this.recoveryBusy[project.id] = true;
      try {
        if (action.kind === 'run') {
          if (this.recoveryFor(project)?.running) return;
          try {
            await ElementPlus.ElMessageBox.confirm(action.description || this.recoveryFor(project)?.run_notice,
              `确认${action.label || '继续任务'}`, {type: 'warning', confirmButtonText: action.label || '继续任务', cancelButtonText: '取消'});
          } catch (_) { return; }
          if (sentToken === this.token) await this.rerunProject(project);
        } else if (action.kind === 'history') {
          this.openReportVersions(project, action.artifact_type);
        } else if (action.kind === 'review') {
          this.resetTaskFilters();
          await this.loadProjects();
          if (sentToken !== this.token) return;
          const index = this.projects.findIndex(row => row.id === project.id);
          if (index < 0) throw new Error('该任务已不存在或当前账号无法访问');
          this.switchView('review');
          await this.$nextTick();
          if (sentToken !== this.token) return;
          this.taskPage = Math.floor(index / this.taskPageSize) + 1;
          await this.$nextTick();
          if (sentToken === this.token) await this.selectReviewProject(this.projects[index]);
        } else if (['download', 'retry_knowledge'].includes(action.kind)) {
          const artifact = (this.artifactsByProject[project.id] || []).find(row => row.id === action.artifact_id);
          if (!artifact) throw new Error('成果记录已变化，请刷新详情后重试');
          if (action.kind === 'download') await this.downloadArtifact(artifact);
          else await this.retryKnowledge(artifact);
        }
      } catch (error) { if (sentToken === this.token) ElementPlus.ElMessage.error(error.message || '操作未完成，请刷新详情后重试'); }
      finally { if (sentToken === this.token) delete this.recoveryBusy[project.id]; }
    },
    replaceProject(project) { const i = this.projects.findIndex(p => p.id === project.id); if (i >= 0) this.projects.splice(i, 1, project); else this.projects.unshift(project); },
    async onTaskExpand(row, expandedRows) {
      if (!expandedRows.some(item => item.id === row.id)) return;
      try { await this.loadProjectDetail(row); } catch (_) { /* The inline error keeps the retry action available. */ }
    },
    async viewProject(project) {
      this.$nextTick(() => this.$refs.taskTable?.toggleRowExpansion(this.projects.find(item => item.id === project.id) || project, true));
      try { await this.loadProjectDetail(project); } catch (_) { /* Loading/error feedback is visible in the expanded row. */ }
    },
    async loadProjectDetail(project, {force = false} = {}) {
      if (!force && this.projectDetails[project.id]?.project?.status === project.status
          && Date.now() - (this.detailLoadedAt[project.id] || 0) < 5000) return this.projectDetails[project.id];
      return this.runAction(`detail:${project.id}`, '正在读取任务详情', async () => {
      const sentToken = this.token;
      const data = await this.readJSON(`/research/projects/${project.id}/detail?latest_only=true`, '加载项目详情失败');
      if (sentToken !== this.token) throw new Error('登录账号已变更，请重试');
      if (data.project) this.replaceProject(data.project);
      this.projectDetails[project.id] = data;
      this.artifactsByProject[project.id] = data.artifacts || [];
      this.sourcesByProject[project.id] = data.sources || [];
      if (data.trace?.length || data.activity) this.mergeTraceList(project.id, data.trace || [], data.activity);
      const intake = data.intake || {};
      this.projectMeta[project.id] = {
        startDate: intake.start_date || this.projectMeta[project.id]?.startDate || '',
        endDate: intake.deadline || this.projectMeta[project.id]?.endDate || ''
      };
      this.detailLoadedAt[project.id] = Date.now();
      return data;
      }, {readOnly: true});
    },
    refreshProjectProgress(project) {
      return this.runAction(`progress:${project.id}`, '正在更新任务进度', async () => {
        const previousStatus = project.status;
        const data = await this.readJSON(`/research/projects/${project.id}/progress`, '加载任务进度失败');
        if (data.project) this.replaceProject(data.project);
        if (data.trace?.length || data.activity) this.mergeTraceList(project.id, data.trace || [], data.activity);
        if (data.project && previousStatus !== data.project.status && ['failed', 'paused', 'completed'].includes(data.project.status)
            && this.projectDetails[project.id]) await this.loadProjectDetail(data.project, {force: true});
      }, {readOnly:true, silent:true});
    },
    async refreshVisibleTaskProgress() {
      if (!this.token || !this.currentUser || this.currentUser.must_change_password || !['tasks', 'review'].includes(this.activeView) || this.taskRefreshBusy) return;
      const sentToken = this.token;
      const activeProjects = this.projects.filter(project => this.projectIsRunning(project));
      this.taskRefreshBusy = true;
      this.taskRefreshTicks += 1;
      try {
        await Promise.all(activeProjects.slice(0, 8).map(project => this.refreshProjectProgress(project).catch(() => null)));
        if (this.taskRefreshTicks % 4 === 0) {
          const r = await this.authFetch('/research/projects');
          const data = await r.json().catch(() => ({}));
          if (r.ok && sentToken === this.token) {
            this.projects = data.projects || this.projects;
            this.projectSummary = data.summary || {};
          }
        }
      } finally {
        this.taskRefreshBusy = false;
      }
    },
    mergeTraceEvent(projectId, event) {
      this.mergeTraceList(projectId, [event]);
    },
    mergeTraceList(projectId, events, activity = null) {
      if (!events?.length && !activity) return;
      // An init starts a new timeline. Never merge prior-run heartbeats into it.
      let saved = this.traceByProject[projectId] || [];
      if (activity) {
        const previous = this.traceActivityByProject[projectId] || {};
        const time = a => this.eventTimestampMs({timestamp:a.run_started_at});
        if (time(previous) > time(activity)) return;
        if (activity.run_id && previous.run_id && activity.run_id !== previous.run_id) saved = [];
        this.traceActivityByProject[projectId] = activity;
      }
      const newestStart = rows => Math.max(0, ...rows.filter(e => e.stage === 'init').map(e => this.eventTimestampMs(e)));
      const start = Math.max(newestStart(saved), newestStart(events));
      events = events.filter(e => !start || !this.eventTimestampMs(e) || this.eventTimestampMs(e) >= start);
      const keyFor = event => [event.timestamp || '', event.stage || '', event.agent || '', event.label || '', event.detail || '', event.status || '', event.section || ''].join('|');
      const list = saved.filter(e => !start || !this.eventTimestampMs(e) || this.eventTimestampMs(e) >= start), keys = list.map(keyFor), counts = new Map();
      for (const key of keys) counts.set(key, (counts.get(key) || 0) + 1);
      let first = 0;
      for (const event of events) {
        const key = keyFor(event);
        if (!counts.has(key)) { list.push(event); keys.push(key); counts.set(key, 1); }
        while (list.length - first > 500) {
          const removed = keys[first++], remaining = counts.get(removed) - 1;
          if (remaining) counts.set(removed, remaining); else counts.delete(removed);
        }
      }
      this.traceByProject[projectId] = list.slice(first);
    },
    async loadProjectArtifacts(project) {
      const r = await this.authFetch(`/research/projects/${project.id}/artifacts?include_content=false`); const data = await r.json().catch(() => []);
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
      const uploadCount = this.projectDetails[project.id]?.upload_count ?? sources.filter(s => s.source_type === 'upload').length;
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
    heartbeatState(event, project) {
      if (!event?.heartbeat || !this.projectIsRunning(project)) return 'history';
      const events = this.traceByProject[project.id] || [];
      const latest = Math.max(0, ...events.filter(e => e.heartbeat).map(e => this.eventTimestampMs(e)));
      if (!latest || latest !== this.eventTimestampMs(event)) return 'history';
      const actual = events.filter(e => !e.heartbeat && e.type !== 'heartbeat');
      const activity = this.traceActivityByProject[project.id] || {};
      const lastActual = this.eventTimestampMs({timestamp:activity.last_backend_event_timestamp})
        || Math.max(0, ...actual.map(e => this.eventTimestampMs(e)));
      if (lastActual && this.nowTick - lastActual > 300000) return 'stalled';
      const timestamp = this.eventTimestampMs(event);
      return timestamp && this.nowTick - timestamp > 60000 ? 'delayed' : 'active';
    },
    heartbeatStale(event, project) { return this.heartbeatState(event, project) === 'stalled'; },
    heartbeatLabel(event, project) { return {history:'历史记录', active:'活跃', delayed:'进度连接延迟', stalled:'超过5分钟无实际进展'}[this.heartbeatState(event, project)]; },
    heartbeatType(event, project) { return {history:'info', active:'success', delayed:'info', stalled:'warning'}[this.heartbeatState(event, project)]; },
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
        if (this.projectIsRunning(project) && current !== -1 && !hasCurrentRunning) {
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
      if (!this.projectIsRunning(project) && !['completed', 'failed'].includes(project.status)) return [];
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
    uploadDisplayFiles(files) { return files.map((file, index) => ({name:file.name, raw:file, uid:file.uid || index + 1, status:'ready'})); },
    clearReviewSelection() { ++this.reviewSelectionSeq; this.reviewProjectId = ''; this.reviewReportFiles = []; this.reviewProposalFiles = []; this.fieldSourceFiles = []; },
    async selectReviewProject(project) {
      if (this.reviewWriteBusy) return;
      if (this.reviewProjectId !== project.id) this.clearReviewSelection();
      const sentToken = this.token, selection = ++this.reviewSelectionSeq;
      this.reviewProjectId = project.id;
      delete this.reviewIntakes[project.id];
      this.$nextTick(() => {
        if (selection === this.reviewSelectionSeq && sentToken === this.token)
          (this.pagedProjects || []).forEach(row => this.$refs.reviewTable?.toggleRowExpansion(row, row.id === project.id));
      });
      try {
        const data = await this.runAction(`review:${project.id}`, '正在准备复核资料',
          () => this.readJSON(`/research/projects/${project.id}/run-intake`, '加载复核参数失败'), {readOnly: true});
        if (sentToken === this.token && selection === this.reviewSelectionSeq && this.reviewProjectId === project.id)
          this.reviewIntakes[project.id] = data.intake || {};
      } catch (_) { /* The expanded panel contains the failure and retry action. */ }
    },
    async uploadReviewArtifact(type) {
      const projectId = this.reviewProjectId;
      if (!projectId) return ElementPlus.ElMessage.warning('请先选择项目');
      const files = type === 'desktop_report' ? this.reviewReportFiles : this.reviewProposalFiles;
      if (!files.length) return ElementPlus.ElMessage.warning('请选择要上传的文件');
      if (this.reviewInputsLocked) return;
      const sentToken = this.token, selectedFiles = [...files];
      try { await this.runAction(`review-upload:${type}:${projectId}`, '正在保存人工修订成果', async phase => {
        for (const [index, file] of selectedFiles.entries()) {
          phase(`正在上传并解析修订文件 ${index + 1}/${selectedFiles.length}`);
          const formData = new FormData();
          formData.append('artifact_type', type);
          formData.append('file', file);
          await this.postTaskUpload(projectId, `/research/projects/${projectId}/artifacts/replace`, formData);
          if (sentToken !== this.token) return;
        }
        delete this.detailLoadedAt[projectId];
        ElementPlus.ElMessage.success('人工修订产物已覆盖为最新版本');
        if (this.reviewProjectId === projectId) {
          if (type === 'desktop_report') this.reviewReportFiles = [];
          else this.reviewProposalFiles = [];
        }
      });
      } catch (e) { ElementPlus.ElMessage.error(this.taskUploadIssues[projectId]?.title || e.message); }
    },
    async uploadFieldSources() {
      const projectId = this.reviewProjectId;
      if (!projectId) return ElementPlus.ElMessage.warning('请先选择项目');
      if (!this.fieldSourceFiles.length) return ElementPlus.ElMessage.warning('请选择一手资料文件');
      if (this.reviewInputsLocked) return;
      const sentToken = this.token, files = [...this.fieldSourceFiles], module = this.fieldSourceModule;
      try { await this.runAction(`field-upload:${projectId}`, '正在保存一手资料', async phase => {
        for (const [index, file] of files.entries()) {
          phase(`正在上传、解析并入库 ${index + 1}/${files.length} 个文件`);
          const formData = new FormData();
          formData.append('module', module || '专家访谈/走访');
          formData.append('file', file);
          await this.postTaskUpload(projectId, `/research/projects/${projectId}/field-sources`, formData);
          if (sentToken !== this.token) return;
          if (this.reviewProjectId === projectId) this.fieldSourceFiles = this.fieldSourceFiles.filter(item => item !== file);
        }
        delete this.detailLoadedAt[projectId];
        ElementPlus.ElMessage.success('一手资料处理完成，可在任务详情核对保存及入库状态');
      });
      } catch (e) { ElementPlus.ElMessage.error(this.taskUploadIssues[projectId]?.title || e.message); }
    },
    async runSecondStage() {
      if (this.secondStageRunning || this.reviewWriteBusy || this.actionPending(`review:${this.reviewProjectId}`)) return;
      const sentToken = this.token;
      const projectId = this.reviewProjectId;
      if (!projectId) return ElementPlus.ElMessage.warning('请先选择项目');
      const project = this.projects.find(p => p.id === Number(projectId));
      if (!project) return ElementPlus.ElMessage.warning('项目不存在');
      this.secondStageRunning = true;
      this.secondStageProjectId = project.id;
      this.traceByProject[project.id] = this.traceByProject[project.id] || [];
      let pollInterval = null;
      try { await this.runAction(`second-stage:${project.id}`, '正在提交二阶段生成请求：' + (project.title || project.id), async phase => {
        const intake = this.reviewIntakes[project.id] || this.projectDetails[project.id]?.intake || {};
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
        phase('二阶段正在处理：' + (project.title || project.id) + '，可在任务管理查看进度');
        ElementPlus.ElMessage.success('二阶段请求已接收，正在处理；进度会持续更新');
        pollInterval = setInterval(() => { if (sentToken === this.token) this.refreshProjectProgress(project).catch(() => null); }, 5000);
        const outcome = await this.readWorkflowEvents(r, sentToken, event => {
            if (event.type === 'trace_step') { this.mergeTraceEvent(project.id, event); phase(event.label || '二阶段正在处理'); }
            if (event.type === 'result') { this.replaceProject(event.project); this.artifactsByProject[project.id] = event.artifacts || []; }
            if (event.type === 'paused') { project.status = 'paused'; ElementPlus.ElMessage.info(event.content || '任务已暂停'); }
            if (event.type === 'error') throw new Error(event.content || '二阶段生成失败');
        });
        if (sentToken !== this.token) return;
        if (outcome === 'paused') return;
        if (outcome !== 'result') throw new Error('连接已结束，但尚未确认生成完成。请在任务管理核对状态，不要重复启动。');
        delete this.detailLoadedAt[project.id];
        ElementPlus.ElMessage.success('二阶段报告和建议书已生成');
        this.refreshAfterWorkflow(project, sentToken).catch(() => null);
      });
      } catch (e) {
        if (sentToken === this.token) {
          ElementPlus.ElMessage.error(e.message);
          await this.refreshAfterWorkflow(project, sentToken);
        }
      } finally {
        if (pollInterval) clearInterval(pollInterval);
        if (sentToken === this.token) { this.secondStageRunning = false; this.secondStageProjectId = ''; }
      }
    },
    recordLabel(version) { return Number.isInteger(version) && version > 0 ? `记录 ${String(version).padStart(3, '0')}` : '历史记录'; },
    openReportVersions(project, artifactType = 'desktop_report') {
      this.reportVersionsProject = {id: project.id, title: project.title || project.project_title || ''};
      this.reportVersionsType = artifactType === 'proposal' ? 'proposal' : 'desktop_report'; this.reportVersionsOpen = true;
    },
    closeReportVersions() { this.reportVersionsOpen = false; this.reportVersionsProject = null; },
    downloadableArtifacts(project) {
      const latest = new Map();
      const rows = this.artifactsFor(project).filter(a => !['project_intake', 'workflow_trace'].includes(a.artifact_type));
      for (const row of [...rows].sort((a,b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0) || b.version-a.version || b.id-a.id)) {
        if (!latest.has(row.artifact_type)) latest.set(row.artifact_type, row);
      }
      return [...latest.values()].filter(a => ['desktop_report', 'proposal', 'report_quality_diagnostic'].includes(a.artifact_type));
    },
    async loadArtifactHistory(project, page = 1) {
      const key = `artifact-history:${project.id}`;
      if (this.actionPromises[key]) return this.actionPromises[key];
      const requestId = (this.artifactHistoryRequests[project.id] || 0) + 1;
      this.artifactHistoryRequests[project.id] = requestId;
      return this.runAction(key, '正在读取历史产物', async () => {
        const sentToken = this.token;
        const data = await this.readJSON(`/research/projects/${project.id}/artifact-history?page=${page}&page_size=20`, '历史产物加载失败');
        if (sentToken === this.token && this.artifactHistoryRequests[project.id] === requestId) this.artifactHistory[project.id] = data;
      }, {readOnly:true});
    },
    closeArtifactHistory(project) {
      this.artifactHistoryRequests[project.id] = (this.artifactHistoryRequests[project.id] || 0) + 1;
      delete this.artifactHistory[project.id];
    },
    latestDownloadable(project) { return this.downloadableArtifacts(project).find(a => ['desktop_report', 'proposal'].includes(a.artifact_type)) || this.downloadableArtifacts(project)[0]; },
    async deleteProject(project) {
      try { await ElementPlus.ElMessageBox.confirm(`确认删除任务“${project.title}”？`, '删除任务', { type: 'warning' }); } catch (_) { return; }
      try { await this.runAction(`delete-project:${project.id}`, '正在删除任务', async () => {
      const r = await this.authFetch(`/research/projects/${project.id}`, { method: 'DELETE' });
      if (!r.ok) { const data = await r.json().catch(() => ({})); throw new Error(data.detail || '删除失败'); }
      this.projects = this.projects.filter(p => p.id !== project.id);
      delete this.projectDetails[project.id]; delete this.artifactsByProject[project.id]; delete this.sourcesByProject[project.id]; delete this.traceByProject[project.id];
      delete this.detailLoadedAt[project.id]; delete this.reviewIntakes[project.id];
      if (this.reviewProjectId === project.id) this.clearReviewSelection();
      this.loadRepository().catch(() => null);
      ElementPlus.ElMessage.success('项目已删除');
      }); } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    async deleteArtifact(project, artifact) {
      if (!artifact) return;
      try { await ElementPlus.ElMessageBox.confirm(`确认删除成果“${artifact.title || this.artifactTypeLabel(artifact.artifact_type)}”？`, '删除成果', { type: 'warning' }); } catch (_) { return; }
      try { await this.runAction(`delete-artifact:${artifact.id}`, '正在删除成果', async () => {
      const r = await this.authFetch(`/research/artifacts/${artifact.id}`, { method: 'DELETE' });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || '删除成果失败');
      this.artifactsByProject[project.id] = (this.artifactsByProject[project.id] || []).filter(item => item.id !== artifact.id);
      delete this.detailLoadedAt[project.id];
      this.loadRepository().catch(() => null);
      ElementPlus.ElMessage.success('成果已删除');
      }); } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    async searchKnowledge() {
      return this.readRepository(this.knowledgeQuery.trim()).catch(() => null);
    },
    async loadRepository() {
      return this.readRepository('').catch(() => null);
    },
    readRepository(query) {
      const key = `repository:${query}`;
      if (this.actionPromises[key]) return this.actionPromises[key];
      const requestId = ++this.repositoryRequestId;
      this.sourcePage = 1;
      return this.runAction(key, query ? '正在搜索溯源记录' : '正在读取溯源记录', async () => {
        const data = await this.readJSON(`/research/repository?${query ? 'q=' + encodeURIComponent(query) + '&' : ''}limit=50`, '加载溯源库失败');
        if (requestId === this.repositoryRequestId) this.knowledgeResults = data.results || [];
      }, {readOnly:true});
    },
    async reindexVectors() {
      if (this.reindexing) return;
      this.reindexing = true;
      try { await this.runAction('reindex-vectors', '正在重建向量索引', async () => {
        const r = await this.authFetch('/research/vector/reindex', { method: 'POST' });
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.detail || '重建向量索引失败');
        const suffix = data.errors?.length ? `，失败 ${data.errors.length} 个` : '';
        ElementPlus.ElMessage.success(`已写入 ${data.indexed || 0} 条向量${suffix}`);
      }); } catch (e) {
        ElementPlus.ElMessage.error(e.message);
      } finally {
        this.reindexing = false;
      }
    },
    async retryArtifactIndex(project, artifact) {
      try { await this.runAction(`index:${artifact.id}`, '正在提交事实索引请求', async () => {
      const response = await this.authFetch(`/research/artifacts/${artifact.id}/reindex`, { method: 'POST' });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.detail || '索引重试失败');
      }
      const result = await response.json();
      Object.assign(artifact, result);
      ElementPlus.ElMessage.success('已单独启动事实索引，报告不会重跑');
      }); } catch (error) { ElementPlus.ElMessage.error(error.message); }
    },
    async downloadArtifact(artifact) {
      if (!artifact) return;
      const sentToken = this.token;
      try { return await this.runAction(`download-artifact:${artifact.id}`, '正在准备成果下载', async phase => {
      phase('正在准备并接收成果文件');
      const {blob, disposition} = await this.readDownload(`/research/artifacts/${artifact.id}/download`, '下载成果失败');
      if (sentToken !== this.token) return;
      const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = this.filenameFromDisposition(disposition, `artifact_${artifact.id}.md`);
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
      ElementPlus.ElMessage.success('文件已交给浏览器下载，请查看下载列表');
      return true;
      }, {readOnly:true}); } catch (error) { ElementPlus.ElMessage.error(error.message); return false; }
    },
    async downloadSource(source) {
      if (!source) return;
      const sentToken = this.token;
      try { return await this.runAction(`download-source:${source.id}`, '正在准备资料下载', async phase => {
      phase('正在准备并接收资料文件');
      const {blob, disposition} = await this.readDownload(`/research/sources/${source.id}/download`, '下载资料失败');
      if (sentToken !== this.token) return;
      const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = this.filenameFromDisposition(disposition, `source_${source.id}`);
      document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
      ElementPlus.ElMessage.success('文件已交给浏览器下载，请查看下载列表');
      return true;
      }, {readOnly:true}); } catch (error) { ElementPlus.ElMessage.error(error.message); return false; }
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
    resetAssistantImages() {
      this.assistantDraftEpoch++; this.assistantImages = []; this.assistantImageBusy = false;
    },
    async addAssistantImages(files) {
      if (this.assistantImageBusy || this.assistantLoading || this.assistantSyncing || !this.assistantReady) return;
      const selected = Array.from(files || []);
      if (!selected.length) return;
      if (selected.length + this.assistantImages.length > 2) return ElementPlus.ElMessage.warning('每次最多发送2张截图');
      if (selected.some(file => !['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 3 * 1024 * 1024)) {
        return ElementPlus.ElMessage.warning('请使用单张不超过3 MB的PNG、JPEG或WebP图片');
      }
      const epoch = this.assistantEpoch, draft = this.assistantDraftEpoch;
      this.assistantImageBusy = true;
      try {
        const items = [];
        for (const file of selected) {
          const url = await new Promise((resolve, reject) => {
            const reader = new FileReader(); reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error('图片读取失败，请重新选择')); reader.readAsDataURL(file);
          });
          items.push({name: file.name || '粘贴截图', url});
        }
        if (epoch === this.assistantEpoch && draft === this.assistantDraftEpoch) this.assistantImages.push(...items);
      } catch (error) {
        if (epoch === this.assistantEpoch && draft === this.assistantDraftEpoch) ElementPlus.ElMessage.warning(error.message);
      } finally {
        if (epoch === this.assistantEpoch && draft === this.assistantDraftEpoch) this.assistantImageBusy = false;
      }
    },
    chooseAssistantImages(event) {
      this.addAssistantImages(event.target.files); event.target.value = '';
    },
    pasteAssistantImage(event) {
      const files = Array.from(event.clipboardData?.items || []).filter(item => item.kind === 'file' && item.type.startsWith('image/')).map(item => item.getAsFile()).filter(Boolean);
      if (files.length) { event.preventDefault(); this.addAssistantImages(files); }
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
      this.assistantMessages = data.messages?.length ? data.messages : [{ text: '你好，我主要负责本系统的使用指南。可以点“功能目录”查找功能，或问我具体的操作问题，也支持日常聊天和公开信息查询。', isUser: false }];
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
      this.resetAssistantImages();
      const epoch = ++this.assistantEpoch, key = this.assistantStorageKey();
      this.assistantController?.abort(); this.assistantLoading = false; this.assistantSyncing = true; this.assistantReady = false;
      this.assistantMessages = [{ text: '你好，我主要负责本系统的使用指南。可以点“功能目录”查找功能，或问我具体的操作问题，也支持日常聊天和公开信息查询。', isUser: false }];
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
      this.resetAssistantImages();
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
      const sentToken = this.token;
      try { await this.runAction(`knowledge:${artifact.id}`, '正在提交知识库入库请求', async () => {
        const response = await this.authFetch('/research/artifacts/' + artifact.id + '/knowledge/retry', { method: 'POST' });
        const result = await response.json();
        if (sentToken !== this.token) return;
        if (!response.ok) throw new Error(result.detail || '重试失败');
        artifact.metadata = result.metadata;
        ElementPlus.ElMessage[result.metadata.knowledge_sync_status === 'failed' ? 'warning' : 'success'](
          result.metadata.knowledge_sync_status === 'failed' ? '归档暂未完成，请联系管理员检查配置。' : '报告已加入知识库处理队列');
        if (this.projectDetails[artifact.project_id]) {
          delete this.detailLoadedAt[artifact.project_id];
          this.loadProjectDetail({id: artifact.project_id}, {force:true}).catch(() => null);
        }
      }); } catch (error) { ElementPlus.ElMessage.error(error.message); }
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
      const text = this.assistantInput.trim();
      if ((!text && !this.assistantImages.length) || this.assistantLoading || this.assistantSyncing || this.assistantImageBusy) return;
      if (!this.assistantReady) { this.assistantMemoryStatus = '请先重新加载对话，确保账号历史已同步'; return; }
      const epoch = this.assistantEpoch, sessionId = this.assistantSessionId;
      const images = this.assistantImages.map(image => ({...image})); this.resetAssistantImages();
      this.assistantMessages.push({ text: text || '请描述这张图片。', images, isUser: true }); this.assistantInput = ''; this.assistantLoading = true; this.assistantMemoryStatus = '正在保存并生成回答…';
      const userMessage = this.assistantMessages[this.assistantMessages.length - 1];
      this.assistantMessages.push({ text: '', isUser: false });
      const bot = this.assistantMessages[this.assistantMessages.length - 1]; this.scrollAssistant(true);
      let timeout = null, saved = false;
      try {
        const controller = new AbortController(); this.assistantController = controller;
        timeout = setTimeout(() => controller.abort(), 135000);
        const r = await this.authFetch('/research/assistant/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal, body: JSON.stringify({ message: text, ...(images.length ? {images: images.map(image => image.url)} : {}), current_page: this.activeView, session_id: sessionId, request_id: globalThis.crypto?.randomUUID?.() }) });
        if (epoch !== this.assistantEpoch) return;
        if (!r.ok) { const data = await r.json().catch(() => ({})); throw new Error(Array.isArray(data.detail) ? data.detail.map(item => item.msg).join('；') : data.detail || '助手请求失败'); }
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
    artifactTypeLabel(type) { return ({ project_intake: '项目参数', research_plan: '研究计划', source_quality: '来源质量', cleaned_facts: '清洗事实库', risk_assessment: '风险研判', desktop_report: '桌面研究报告', report_quality_diagnostic: '报告质量诊断', person_claim_ledger: '人物证据与验收台账', person_evidence_appendix: '完整证据附录与采用去向', industry_claim_ledger: '结论证据台账', industry_run: '运行记录', proposal: '项目建议书' })[type] || type; },
    targetTypeLabel(type) { return ({ person: '目标人', company: '目标公司', industry: '目标行业' })[type] || type || '-'; },
    formatTime(value) {
      const timestamp = this.eventTimestampMs({ timestamp: value });
      return timestamp ? new Date(timestamp).toLocaleString() : '-';
    },
    escapeHtml(text) { const div = document.createElement('div'); div.textContent = text || ''; return div.innerHTML; },
    parseMarkdown(text) { return window.SafeMarkdown ? window.SafeMarkdown.render(text) : this.escapeHtml(text); }
  }
}).component('company-knowledge', CompanyKnowledge).use(ElementPlus).mount('#app');
