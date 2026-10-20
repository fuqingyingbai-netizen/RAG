const PersonalHome = {
  props: {
    request: { type: Function, required: true },
    currentUser: { type: Object, required: true },
    download: { type: Function, required: true },
  },
  emits: ['navigate', 'open-project'],
  data() { return { home: null, loading: false, error: '', requestId: 0, refreshTimer: null, downloadingId: null }; },
  computed: {
    displayName() { return this.home?.user?.display_name || this.currentUser.username; },
    metrics() {
      return [
        { key: 'total', label: '我的任务', hint: '自己创建的全部任务', icon: 'fa-folder-open' },
        { key: 'running', label: '进行中', hint: '当前正在执行的任务', icon: 'fa-spinner' },
        { key: 'completed', label: '已完成', hint: '已完成工作流的任务', icon: 'fa-circle-check' },
        { key: 'attention', label: '待处理', hint: '未开始、暂停或需检查', icon: 'fa-clipboard-list' },
      ];
    },
  },
  mounted() {
    this.loadHome();
    this.refreshTimer = setInterval(() => { if (document.visibilityState === 'visible' && !this.loading) this.loadHome(); }, 30000);
  },
  beforeUnmount() { ++this.requestId; if (this.refreshTimer) clearInterval(this.refreshTimer); },
  methods: {
    async loadHome() {
      const requestId = ++this.requestId;
      this.loading = true; this.error = '';
      try {
        const response = await this.request('/research/home');
        const data = await response.json().catch(() => ({}));
        if (requestId !== this.requestId) return;
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '首页加载失败，请重试');
        this.home = data;
      } catch (error) { if (requestId === this.requestId) this.error = (this.home ? '刷新失败，以下为上次加载的数据。' : '') + error.message; }
      finally { if (requestId === this.requestId) this.loading = false; }
    },
    async downloadReport(report) {
      if (!report.can_download || this.downloadingId !== null) return;
      this.downloadingId = report.id;
      try { await this.download(report); }
      catch (error) { ElementPlus.ElMessage.error(error.message || '下载失败，请重试'); }
      finally { this.downloadingId = null; }
    },
    statusType(project) { return project.is_running ? 'warning' : project.status === 'completed' ? 'success' : project.status === 'failed' ? 'danger' : 'info'; },
    targetLabel(value) { return ({ company: '公司研究', industry: '行业研究', person: '人物研究' })[value] || '研究任务'; },
    formatTime(value) {
      if (!value) return '暂无时间记录';
      const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : value + 'Z';
      const date = new Date(normalized);
      return Number.isNaN(date.getTime()) ? '暂无时间记录' : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
    },
  },
  template: `
    <section class="personal-home" aria-label="个人工作概览">
      <header class="home-welcome">
        <div><p class="eyebrow">My Workspace</p><h2>你好，{{displayName}}</h2><p class="muted">从这里查看自己的任务进度和研究成果。</p><p v-if="home" class="home-update">最近更新：{{formatTime(home.updated_at)}}</p></div>
        <div class="home-welcome-actions"><el-button :loading="loading" @click="loadHome">刷新首页</el-button><el-button type="primary" @click="$emit('navigate', 'submit')"><i class="fa-solid fa-plus" aria-hidden="true"></i><span>新建任务</span></el-button></div>
      </header>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="home-alert"></el-alert>
      <el-skeleton v-if="!home && loading" :rows="6" animated class="home-skeleton"></el-skeleton>
      <template v-if="home">
        <div class="home-metrics">
          <div v-for="metric in metrics" :key="metric.key" class="home-metric" :data-metric="metric.key"><div class="home-metric-heading"><span>{{metric.label}}</span><i :class="['fa-solid', metric.icon]" aria-hidden="true"></i></div><strong>{{home.summary[metric.key]}}</strong><small>{{metric.hint}}</small></div>
        </div>
        <nav class="home-shortcuts" aria-label="首页快捷入口">
          <button type="button" @click="$emit('navigate', 'tasks')"><i class="fa-solid fa-list-check" aria-hidden="true"></i><span><strong>任务管理</strong><small>查看任务详情与执行进度</small></span><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
          <button type="button" @click="$emit('navigate', 'review')"><i class="fa-solid fa-pen-to-square" aria-hidden="true"></i><span><strong>复核与一手资料</strong><small>复核成果，补充访谈与资料</small></span><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
          <button v-if="currentUser.role === 'admin'" type="button" @click="$emit('navigate', 'accounts')"><i class="fa-solid fa-users-gear" aria-hidden="true"></i><span><strong>账号管理</strong><small>管理账号、邀请码与操作日志</small></span><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
          <button v-else type="button" @click="$emit('navigate', 'sources')"><i class="fa-solid fa-database" aria-hidden="true"></i><span><strong>溯源库</strong><small>查找自己的研究来源和依据</small></span><i class="fa-solid fa-chevron-right" aria-hidden="true"></i></button>
        </nav>
        <div class="home-work-grid">
          <el-card class="panel-card home-projects" shadow="never">
            <template #header><div class="card-header"><div><p class="eyebrow">My Tasks</p><h2>最近任务</h2></div><el-button text type="primary" @click="$emit('navigate', 'tasks')">任务管理</el-button></div></template>
            <div v-if="!home.recent_projects.length" class="home-empty"><i class="fa-solid fa-folder-open" aria-hidden="true"></i><h3>还没有创建任务</h3><p>创建第一个任务后，可在这里查看进度和成果。</p><el-button type="primary" plain @click="$emit('navigate', 'submit')">创建第一个任务</el-button></div>
            <article v-for="project in home.recent_projects" :key="project.id" class="home-list-item" :aria-label="project.title">
              <div class="home-item-heading"><h3>{{project.title}}</h3><el-tag :type="statusType(project)" size="small">{{project.state_label}}</el-tag></div>
              <p class="home-item-context">{{targetLabel(project.target_type)}}<span v-if="project.target_name"> · {{project.target_name}}</span></p>
              <div class="home-item-footer"><time>更新于 {{formatTime(project.updated_at)}}</time><el-button size="small" plain @click="$emit('open-project', project)">查看任务</el-button></div>
            </article>
          </el-card>
          <el-card class="panel-card home-reports" shadow="never">
            <template #header><div class="card-header"><div><p class="eyebrow">Recent Reports</p><h2>最近成果</h2></div><span class="home-section-hint">每项成果显示最新版本</span></div></template>
            <div v-if="!home.recent_reports.length" class="home-empty"><i class="fa-solid fa-file-lines" aria-hidden="true"></i><h3>还没有研究成果</h3><p>生成的研究报告和建议书会显示在这里。</p></div>
            <article v-for="report in home.recent_reports" :key="report.id" class="home-list-item" :aria-label="report.title">
              <div class="home-item-heading"><h3>{{report.title}}</h3><span class="home-version">v{{report.version}}</span></div>
              <p class="home-item-context">{{report.project_title}} · {{report.artifact_type === 'proposal' ? '项目建议书' : '研究报告'}}</p>
              <div class="home-report-tags"><el-tag v-if="report.review_label" type="warning" size="small">{{report.review_label}}</el-tag><el-tag v-if="report.export_error" type="danger" size="small">Word 导出异常</el-tag><el-tag v-if="!report.can_download" type="info" size="small">文件暂不可用</el-tag></div>
              <div class="home-item-footer"><time>{{formatTime(report.created_at)}}</time><div class="home-report-actions"><el-button size="small" plain @click="$emit('open-project', {id:report.project_id})">查看任务</el-button><el-button size="small" type="primary" plain :loading="downloadingId === report.id" :disabled="!report.can_download || (downloadingId !== null && downloadingId !== report.id)" @click="downloadReport(report)">下载</el-button></div></div>
            </article>
          </el-card>
        </div>
      </template>
    </section>`,
};
