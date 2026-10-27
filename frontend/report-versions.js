const ReportVersions = {
  props: {
    project: {type: Object, required: true}, initialType: {type: String, default: 'desktop_report'},
    request: {type: Function, required: true}, download: {type: Function, required: true},
    read: {type: Function, default: null},
  },
  emits: ['close'],
  data() { return {type: this.initialType, page: 1, pageSize: 10, total: 0, records: [],
    loading: false, error: '', selected: null, preview: null, previewLoading: false,
    previewError: '', listRequestId: 0, previewRequestId: 0, downloadingId: null,
    listController: null, previewController: null, previewPromise: null}; },
  mounted() { this.loadRecords(); },
  beforeUnmount() { ++this.listRequestId; ++this.previewRequestId; this.listController?.abort(); this.previewController?.abort(); },
  methods: {
    resetPreview() { ++this.previewRequestId; this.previewController?.abort(); this.previewController = null; this.previewPromise = null; this.selected = null; this.preview = null; this.previewError = ''; this.previewLoading = false; },
    async readData(url, message, signal) {
      if (this.read) return this.read(url, message, 30000, {signal});
      const response = await this.request(url, signal ? {signal} : {});
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : message);
      return data;
    },
    async changeType() { this.page = 1; await this.loadRecords(); },
    async loadRecords() {
      const requestId = ++this.listRequestId;
      this.listController?.abort();
      this.listController = typeof AbortController === 'function' ? new AbortController() : null;
      this.loading = true; this.error = ''; this.records = []; this.total = 0; this.resetPreview();
      try {
        const data = await this.readData(`/research/projects/${this.project.id}/report-versions?artifact_type=${this.type}&page=${this.page}&page_size=${this.pageSize}`, '历史版本加载失败', this.listController?.signal);
        if (requestId !== this.listRequestId) return;
        const lastPage = Math.max(1, Math.ceil(data.total / this.pageSize));
        if (this.page > lastPage) { this.page = lastPage; return this.loadRecords(); }
        this.records = data.records; this.total = data.total;
        this.loading = false; this.listController = null;
        if (this.records.length) await this.selectRecord(this.records[0]);
      } catch (error) { if (requestId === this.listRequestId) this.error = error.message || '历史版本加载失败，请重试'; }
      finally { if (requestId === this.listRequestId) { this.loading = false; this.listController = null; } }
    },
    selectRecord(record) {
      if (this.selected?.id === record.id && this.previewLoading && this.previewPromise) return this.previewPromise;
      const requestId = ++this.previewRequestId;
      this.previewController?.abort();
      this.previewController = typeof AbortController === 'function' ? new AbortController() : null;
      this.selected = record; this.preview = null; this.previewError = ''; this.previewLoading = true;
      const promise = (async () => {
        try {
          const data = await this.readData(`/research/artifacts/${record.id}/preview`, '正文预览加载失败', this.previewController?.signal);
          if (requestId !== this.previewRequestId) return;
          this.preview = data;
        } catch (error) { if (requestId === this.previewRequestId) this.previewError = error.message || '正文预览加载失败'; }
        finally { if (requestId === this.previewRequestId) { this.previewLoading = false; this.previewController = null; this.previewPromise = null; } }
      })();
      this.previewPromise = promise;
      return promise;
    },
    async downloadRecord(record) {
      if (!record.can_download || this.downloadingId !== null) return;
      this.downloadingId = record.id;
      try { await this.download(record); }
      catch (error) { ElementPlus.ElMessage.error(error.message || '下载失败'); }
      finally { this.downloadingId = null; }
    },
    formatTime(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '时间未记录' : date.toLocaleString('zh-CN'); },
    renderContent(value) { return window.SafeMarkdown ? window.SafeMarkdown.render(value) : String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); },
  },
  template: `
    <el-dialog :model-value="true" title="报告历史版本" width="min(1080px, 96vw)" class="report-versions-dialog" @close="$emit('close')" :close-on-click-modal="false">
      <p class="rv-project">{{project.title || '研究任务'}}</p>
      <div class="rv-toolbar"><el-radio-group v-model="type" @change="changeType" aria-label="成果类型"><el-radio-button value="desktop_report">研究报告</el-radio-button><el-radio-button value="proposal">项目建议书</el-radio-button></el-radio-group><el-button :loading="loading" @click="loadRecords">刷新记录</el-button></div>
      <p class="rv-help">按保存顺序编号，最新记录在前。生成方式以已有记录为准，每条记录保留当时的内容和复核提示。</p>
      <p v-if="loading" role="status" class="rv-help">正在读取历史记录，请稍候…</p>
      <p class="rv-scroll-hint">表格可左右滑动，查看保存时间与生成方式。</p>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon></el-alert>
      <div class="rv-table-scroll" v-loading="loading"><el-table :data="records" row-key="id" class="rv-table" empty-text="暂无此类成果记录" :max-height="280">
        <el-table-column label="记录" min-width="170"><template #default="{row}"><strong>{{row.record_label}}</strong><el-tag v-if="row.is_latest" size="small" type="success">最新</el-tag></template></el-table-column>
        <el-table-column label="保存时间" min-width="180"><template #default="{row}">{{formatTime(row.created_at)}}</template></el-table-column>
        <el-table-column prop="origin_label" label="生成方式" min-width="130"></el-table-column>
        <el-table-column label="复核提示" min-width="150"><template #default="{row}"><el-tag v-if="row.review_label" type="warning" size="small">{{row.review_label}}</el-tag><span v-else>—</span><el-tag v-if="row.export_error" type="danger" size="small">导出异常</el-tag></template></el-table-column>
        <el-table-column label="操作" width="170" fixed="right"><template #default="{row}"><el-button size="small" :type="selected?.id === row.id ? 'primary' : 'default'" plain @click="selectRecord(row)">查看</el-button><el-button size="small" :disabled="!row.can_download || downloadingId !== null" :loading="downloadingId === row.id" @click="downloadRecord(row)">下载</el-button></template></el-table-column>
      </el-table></div>
      <el-pagination v-if="total > pageSize" class="rv-pagination" background layout="prev, pager, next, total" :total="total" :page-size="pageSize" v-model:current-page="page" @current-change="loadRecords"></el-pagination>
      <p v-if="selected && previewLoading" role="status" class="rv-help">正在读取此版本正文；仍可下载文件或选择其他记录。</p>
      <section v-if="selected" class="rv-preview" :aria-label="selected.record_label + '正文预览'" v-loading="previewLoading">
        <header><div><h3>{{selected.record_label}} · 正文预览</h3><p>{{selected.origin_label}} · {{formatTime(selected.created_at)}}</p><p v-if="selected.original_filename">原文件：{{selected.original_filename}}</p></div><el-tag v-if="selected.review_label" type="warning">{{selected.review_label}}</el-tag></header>
        <el-alert v-if="previewError" :title="previewError" type="error" :closable="false" show-icon></el-alert><el-button v-if="previewError" plain @click="selectRecord(selected)">重试预览</el-button>
        <p v-if="preview?.truncated" class="rv-help">正文较长，此处显示前12万字；完整内容请下载查看。</p>
        <p v-if="preview && !preview.has_preview" class="rv-help">此记录暂无可预览正文，请下载原文件查看。</p>
        <div v-if="preview?.has_preview" class="rv-body" v-html="renderContent(preview.content)"></div>
      </section>
      <template #footer><el-button @click="$emit('close')">关闭</el-button></template>
    </el-dialog>`,
};
