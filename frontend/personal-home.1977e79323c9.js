const PersonalHome = {
  props: {
    request: { type: Function, required: true },
    read: { type: Function, default: null },
    currentUser: { type: Object, required: true },
    download: { type: Function, required: true },
  },
  emits: ['navigate', 'filter-tasks', 'open-project', 'view-versions'],
  data() { return { home: null, loading: false, error: '', requestId: 0, refreshTimer: null, downloadingId: null, readController: null, taskFilter: 'all', showAllReports: false }; },
  computed: {
    displayName() { return this.home?.user?.display_name || this.currentUser.username; },
    priorityProjects() {
      const priority = project => project.is_running ? 0 : project.status === 'completed' ? 2 : 1;
      return [...(this.home?.recent_projects || [])].sort((a, b) => priority(a) - priority(b));
    },
    nextTask() {
      const rows = this.home?.recent_projects || [];
      // Choose from the recent list only; the overview is not a full review queue.
      return rows.find(p => !p.is_running && ['failed','diagnostic'].includes(p.status))
        || rows.find(p => !p.is_running && p.status === 'completed')
        || rows.find(p => !p.is_running && p.status === 'paused')
        || rows.find(p => !p.is_running && p.status === 'draft')
        || rows.find(p => p.is_running) || rows[0] || null;
    },
    avatarText() { return Array.from(this.displayName || '我').slice(0, 2).join('').toUpperCase(); },
    dateLabel() {
      const date = new Date(this.home?.updated_at || Date.now());
      return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN', {timeZone:'Asia/Shanghai', month:'long', day:'numeric', weekday:'long'});
    },
    taskFilters() {
      const rows = this.home?.recent_projects || [];
      return [
        {key:'all', label:'全部', count:rows.length},
        {key:'running', label:'进行中', count:rows.filter(p => p.is_running).length},
        {key:'attention', label:'待处理', count:rows.filter(p => !p.is_running && p.status !== 'completed').length},
      ];
    },
    displayedProjects() {
      return this.priorityProjects.filter(project => this.taskFilter === 'running' ? project.is_running
        : this.taskFilter === 'attention' ? !project.is_running && project.status !== 'completed' : true);
    },
    reportGroups() {
      const groups = new Map();
      const timestamp = report => {
        const value = report.created_at || '';
        return Date.parse(/[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : value + 'Z') || 0;
      };
      const compare = (a, b) => timestamp(a) - timestamp(b) || Number(a.version || 0) - Number(b.version || 0) || Number(a.id || 0) - Number(b.id || 0);
      for (const report of this.home?.recent_reports || []) {
        const key = report.project_id == null ? 'artifact:' + report.id : 'project:' + report.project_id;
        if (!groups.has(key)) groups.set(key, {key, projectId:report.project_id, title:report.project_title || '未命名任务', reports:[]});
        const group = groups.get(key);
        const existing = group.reports.findIndex(item => item.artifact_type === report.artifact_type);
        if (existing === -1) group.reports.push(report);
        else if (compare(report, group.reports[existing]) > 0) group.reports[existing] = report;
      }
      return [...groups.values()].map(group => {
        const latest = group.reports.reduce((a, b) => compare(a, b) >= 0 ? a : b);
        return {...group, updatedAt:latest.created_at, updatedTime:timestamp(latest), reports:group.reports.sort((a, b) => Number(a.artifact_type === 'proposal') - Number(b.artifact_type === 'proposal'))};
      }).sort((a, b) => b.updatedTime - a.updatedTime);
    },
    visibleReportGroups() { return this.showAllReports ? this.reportGroups : this.reportGroups.slice(0, 3); },
    metrics() {
      return [
        { key: 'total', label: '我的任务', hint: '自己创建的全部任务', icon: 'fa-folder-open' },
        { key: 'running', label: '进行中', hint: '当前正在执行的任务', icon: 'fa-spinner' },
        { key: 'completed', label: '生成完成', hint: '报告生成结束，进入复核环节', icon: 'fa-circle-check' },
        { key: 'attention', label: '待处理', hint: '未开始、暂停或需检查', icon: 'fa-clipboard-list' },
      ];
    },
  },
  mounted() {
    this.loadHome();
    this.refreshTimer = setInterval(() => { if (document.visibilityState === 'visible' && !this.loading) this.loadHome(); }, 30000);
  },
  beforeUnmount() { ++this.requestId; this.readController?.abort(); if (this.refreshTimer) clearInterval(this.refreshTimer); },
  methods: {
    async loadHome() {
      const requestId = ++this.requestId;
      this.readController?.abort();
      this.readController = typeof AbortController === 'function' ? new AbortController() : null;
      this.loading = true; this.error = '';
      try {
        let data;
        if (this.read) data = await this.read('/research/home', '首页加载失败，请重试', 30000, {signal:this.readController?.signal});
        else {
          const response = await this.request('/research/home', this.readController ? {signal:this.readController.signal} : {});
          data = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '首页加载失败，请重试');
        }
        if (requestId !== this.requestId) return;
        this.home = data;
      } catch (error) { if (requestId === this.requestId) this.error = (this.home ? '刷新失败，以下为上次加载的数据。' : '') + error.message; }
      finally { if (requestId === this.requestId) { this.loading = false; this.readController = null; } }
    },
    async downloadReport(report) {
      if (!report.can_download || this.downloadingId !== null) return;
      this.downloadingId = report.id;
      try { await this.download(report); }
      catch (error) { ElementPlus.ElMessage.error(error.message || '下载失败，请重试'); }
      finally { this.downloadingId = null; }
    },
    taskActionLabel(project) {
      if (project.is_running) return '查看进度';
      if (project.status === 'draft') return '继续填写';
      if (project.status === 'completed') return '开始复核';
      if (['failed','paused','diagnostic'].includes(project.status)) return '查看原因';
      return '继续处理';
    },
    projectStateLabel(project) { return project.status === 'completed' && !project.is_running ? '生成完成' : project.state_label; },
    statusType(project) { return project.is_running ? 'warning' : project.status === 'completed' ? 'success' : project.status === 'failed' ? 'danger' : 'info'; },
    targetLabel(value) { return ({ company: '公司研究', industry: '行业研究', person: '人物研究' })[value] || '研究任务'; },
    targetIcon(value) { return ({company:'fa-building', industry:'fa-chart-line', person:'fa-user-tie'})[value] || 'fa-folder-open'; },
    recordLabel(version) { return `记录 ${String(version).padStart(3, '0')}`; },
    formatTime(value) {
      if (!value) return '暂无时间记录';
      const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : value + 'Z';
      const date = new Date(normalized);
      return Number.isNaN(date.getTime()) ? '暂无时间记录' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
    },
  },
  template: `
    <section class="personal-home home-dashboard" aria-label="个人工作概览">
      <header class="home-hero">
        <div class="home-identity"><span class="home-avatar" aria-hidden="true">{{avatarText}}</span><div><p class="home-date">{{dateLabel}}</p><h2>你好，{{displayName}}</h2></div></div>
        <div class="home-hero-actions"><el-button :loading="loading" @click="loadHome" aria-label="刷新首页"><i class="fa-solid fa-rotate-right" aria-hidden="true"></i><span>刷新</span></el-button><el-button type="primary" @click="$emit('navigate', 'submit')"><i class="fa-solid fa-plus" aria-hidden="true"></i><span>新建任务</span></el-button></div>
        <div v-if="nextTask" class="home-next-step" aria-label="近期任务下一步"><div class="home-next-copy"><span class="home-next-label"><i class="fa-solid fa-arrow-right" aria-hidden="true"></i>下一步</span><strong :title="nextTask.title">{{nextTask.title}}</strong><span class="home-next-state">{{projectStateLabel(nextTask)}}</span></div><el-button type="primary" plain :aria-label="taskActionLabel(nextTask) + '：' + nextTask.title" @click="$emit('open-project', nextTask)">{{taskActionLabel(nextTask)}}<i class="fa-solid fa-arrow-right" aria-hidden="true"></i></el-button></div>
      </header>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="home-alert"></el-alert>
      <el-skeleton v-if="!home && loading" :rows="6" animated class="home-skeleton"></el-skeleton>
      <template v-if="home">
        <dl class="home-metrics" aria-label="我的任务统计">
          <div v-for="metric in metrics" :key="metric.key" class="home-metric" :data-metric="metric.key" :title="metric.hint"><dt>{{metric.label}}</dt><dd>{{home.summary[metric.key]}}</dd></div>
        </dl>
        <div class="home-main-grid">
          <section class="home-dashboard-card home-projects" aria-labelledby="home-tasks-heading">
            <header class="home-card-header"><div><h2 id="home-tasks-heading">最近任务<span class="home-heading-count">{{home.recent_projects.length}}</span></h2></div><el-button link type="primary" @click="$emit('navigate', 'tasks')">查看全部<i class="fa-solid fa-arrow-right" aria-hidden="true"></i></el-button></header>
            <div class="home-task-filters" role="group" aria-label="筛选最近任务"><button v-for="filter in taskFilters" :key="filter.key" type="button" :class="{'is-active':taskFilter === filter.key}" :aria-pressed="taskFilter === filter.key" @click="taskFilter = filter.key">{{filter.label}}<span>{{filter.count}}</span></button></div>
            <div class="home-task-list" role="region" aria-label="最近任务列表" tabindex="0">
              <div v-if="!home.recent_projects.length" class="home-dashboard-empty"><span class="home-empty-symbol"><i class="fa-solid fa-folder-open" aria-hidden="true"></i></span><h3>从第一份尽调任务开始</h3><p>保存客户需求与研究资料后，再开始生成报告。</p><el-button type="primary" plain @click="$emit('navigate', 'submit')">新建尽调任务</el-button></div>
              <div v-else-if="!displayedProjects.length" class="home-dashboard-empty home-filter-empty"><i class="fa-regular fa-circle-check" aria-hidden="true"></i><h3>最近任务中暂无{{taskFilter === 'running' ? '进行中' : '待处理'}}任务</h3><p>可到任务总览查看其他任务。</p><el-button link type="primary" @click="$emit('filter-tasks', taskFilter)">查看全部{{taskFilter === 'running' ? '进行中' : '待处理'}}任务</el-button></div>
              <article v-for="project in displayedProjects" :key="project.id" class="home-task-row" :aria-label="project.title">
                <span class="home-task-symbol" :data-type="project.target_type" aria-hidden="true"><i :class="['fa-solid',targetIcon(project.target_type)]"></i></span>
                <div class="home-task-info"><div class="home-task-titleline"><h3 :title="project.title">{{project.title}}</h3><el-tag :type="statusType(project)" size="small" effect="light">{{projectStateLabel(project)}}</el-tag></div><div class="home-task-meta"><span>{{targetLabel(project.target_type)}} · {{String(project.target_name || '').trim() || '待补充对象'}}</span><time>更新于 {{formatTime(project.updated_at)}}</time></div></div>
                <div class="home-task-operation"><el-button type="primary" plain :aria-label="taskActionLabel(project) + '：' + project.title" @click="$emit('open-project', project)">{{taskActionLabel(project)}}<i class="fa-solid fa-arrow-right" aria-hidden="true"></i></el-button></div>
              </article>
            </div>
          </section>
            <section class="home-dashboard-card home-reports" aria-labelledby="home-reports-heading">
              <header class="home-card-header"><div><h2 id="home-reports-heading">最新成果</h2></div><el-button link type="primary" @click="$emit('navigate', 'review')">查看成果<i class="fa-solid fa-arrow-right" aria-hidden="true"></i></el-button></header>
              <div class="home-recent-reports" role="region" aria-label="最近成果列表">
                <div v-if="!home.recent_reports.length" class="home-dashboard-empty home-report-empty"><span class="home-empty-symbol"><i class="fa-solid fa-file-lines" aria-hidden="true"></i></span><h3>还没有研究成果</h3><p>生成报告与建议书后，可在这里快速查阅。</p></div>
                <article v-for="group in visibleReportGroups" :key="group.key" class="home-report-group" :aria-label="group.title">
                  <header class="home-report-group-heading"><h3><el-button v-if="group.projectId != null" link type="primary" :title="group.title" @click="$emit('open-project', {id:group.projectId})">{{group.title}}<i class="fa-solid fa-arrow-right" aria-hidden="true"></i></el-button><span v-else>{{group.title}}</span></h3><time>更新于 {{formatTime(group.updatedAt)}}</time></header>
                  <div v-for="report in group.reports" :key="report.id" class="home-group-artifact" :aria-label="report.title">
                    <div class="home-group-artifact-heading"><span class="home-file-type" :title="report.title"><i class="fa-solid fa-file-lines" aria-hidden="true"></i>{{report.artifact_type === 'proposal' ? '建议书' : '研究报告'}}</span><span class="home-record">{{recordLabel(report.version)}}</span></div>
                    <div v-if="report.review_label || report.export_error || !report.can_download" class="home-result-status"><el-tag v-if="report.review_label" type="warning" size="small">{{report.review_label}}</el-tag><el-tag v-if="report.export_error" type="danger" size="small">Word 导出异常</el-tag><el-tag v-if="!report.can_download" type="info" size="small">文件暂不可用</el-tag></div>
                    <div class="home-result-actions"><el-button link :aria-label="(report.artifact_type === 'proposal' ? '建议书' : '研究报告') + '历史版本'" @click="$emit('view-versions', report)">历史版本</el-button><el-button size="small" type="primary" plain :aria-label="'下载' + (report.artifact_type === 'proposal' ? '建议书' : '研究报告')" :loading="downloadingId === report.id" :disabled="!report.can_download || (downloadingId !== null && downloadingId !== report.id)" @click="downloadReport(report)"><i class="fa-solid fa-arrow-down" aria-hidden="true"></i>下载</el-button></div>
                  </div>
                </article>
              </div>
              <footer v-if="reportGroups.length > 3" class="home-report-more"><el-button link type="primary" :aria-expanded="showAllReports" @click="showAllReports = !showAllReports">{{showAllReports ? '收起成果' : '展开其余 ' + (reportGroups.length - 3) + ' 个任务'}}<i :class="['fa-solid',showAllReports ? 'fa-angle-up' : 'fa-angle-down']" aria-hidden="true"></i></el-button></footer>
            </section>
        </div>
        <p class="home-data-stamp"><span><i class="fa-regular fa-clock" aria-hidden="true"></i>数据更新于 {{formatTime(home.updated_at)}}</span><span>仅展示自己创建的任务与成果</span></p>
      </template>
    </section>`,
};
