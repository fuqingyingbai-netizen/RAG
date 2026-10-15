/* Company knowledge uses the authenticated backend; cloud credentials stay on the server. */
const CompanyKnowledge = {
  props: { projects: { type: Array, default: () => [] } },
  data() {
    return {
      mode: 'library', query: '', category: '全部资料', space: 'all', favoritesOnly: false,
      favorites: [], readerOpen: false, selectedDoc: null, readerPage: 0,
      uploadOpen: false, stagedFiles: [], draft: '', scope: 'all', messages: [],
      cloudDocuments: [], totalDocuments: 0, documentPage: 0, loading: false,
      service: { configured: false, access_allowed: false }, serviceError: '',
      busy: false, answerStatus: '', controller: null, activityClock: null,
      categories: ['全部资料', '项目原件', '研究成果', '方法与模板'],
      suggestions: ['你好', '请概括已上传的比亚迪背景调查报告，并标注来源', '请总结星门项目研究资料的主要内容，并标注来源'],
    };
  },
  computed: {
    companyProject() { return this.projects.find(p => (p.target_type || p.metadata?.target_type || 'company') === 'company'); },
    projectName() { return this.companyProject?.target_name || this.companyProject?.title || '公司项目示例'; },
    spaces() { return [{ id: 'company', title: this.service.name || '公司资料测试库', subtitle: '云端资料 · 自动检索问答', icon: 'fa-building', count: this.totalDocuments }]; },
    documents() { return this.cloudDocuments.map(doc => ({ ...doc, space: 'company', project: this.service.name || '公司资料测试库', label: doc.status === 'FINISH' ? '可检索' : doc.status_message || doc.status, summary: doc.tags?.join(' · ') || doc.status_message || '', date: doc.modified_at ? new Date(doc.modified_at).toLocaleDateString('zh-CN') : '', chapters: [] })); },
    filteredDocuments() {
      const keyword = this.query.trim().toLowerCase();
      return this.documents.filter(doc =>
        (this.category === '全部资料' || doc.category === this.category) &&
        (this.space === 'all' || doc.space === this.space) &&
        (!this.favoritesOnly || this.favorites.includes(doc.id)) &&
        (!keyword || [doc.title, doc.summary, doc.project, doc.format].join(' ').toLowerCase().includes(keyword)));
    },
    scopeLabel() { return this.service.name || '公司资料测试库'; },
    canAsk() { return this.service.configured && this.service.access_allowed; },
    consoleUrl() { return 'https://bailian.console.aliyun.com/cn-beijing/rag/knowledge'; },
    allReferences() { const references = new Map(); for (const message of this.messages) for (const reference of message.references || []) references.set((reference.document_id || reference.url) + ':' + reference.id, reference); return [...references.values()]; },
  },
  mounted() { this.loadService(); },
  beforeUnmount() { this.controller?.abort(); clearInterval(this.activityClock); },
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
        await this.loadDocuments();
      } catch (error) { this.serviceError = error.message; }
    },
    async loadDocuments(more = false) {
      if (this.loading) return;
      this.loading = true; this.serviceError = '';
      try {
        const page = more ? this.documentPage + 1 : 1;
        const response = await this.apiFetch('/company-knowledge/documents?page_number=' + page + '&page_size=100');
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || '资料加载失败。');
        this.cloudDocuments = more ? [...this.cloudDocuments, ...result.documents] : result.documents;
        this.totalDocuments = result.total_count; this.documentPage = page;
        this.categories = ['全部资料', ...new Set(this.cloudDocuments.map(doc => doc.category))];
      } catch (error) { this.serviceError = error.message; }
      finally { this.loading = false; }
    },
    showMode(mode) { this.mode = mode; },
    selectSpace(id) { this.space = this.space === id ? 'all' : id; },
    resetFilters() { this.query = ''; this.category = '全部资料'; this.space = 'all'; this.favoritesOnly = false; },
    toggleFavorite(id) { this.favorites = this.favorites.includes(id) ? this.favorites.filter(x => x !== id) : [...this.favorites, id]; },
    openDocument(doc) { this.selectedDoc = { ...doc, references: this.allReferences.filter(ref => ref.document_id === doc.id) }; this.readerPage = 0; this.readerOpen = true; },
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
    openCitation(group) { this.selectedDoc = { id: group.document_id, title: group.title, references: group.references }; this.readerOpen = true; },
    referenceIds(group) { return group.references.map(reference => 'id_' + reference.id).join('、'); },
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
    askDocument() { this.draft = '请根据《' + this.selectedDoc.title + '》回答：'; this.readerOpen = false; this.mode = 'chat'; this.$nextTick(() => this.$refs.composer?.focus()); },
    originalUrl(value) { try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password ? url.href : ''; } catch { return ''; } },
    sizeLabel(bytes) { return bytes < 1048576 ? Math.max(1, Math.round(bytes / 1024)) + ' KB' : (bytes / 1048576).toFixed(1) + ' MB'; },
    newConversation() { this.controller?.abort(); this.messages = []; this.draft = ''; },
    scrollChat() { this.$nextTick(() => { const feed = this.$refs.chatFeed; if (feed) feed.scrollTop = feed.scrollHeight; }); },
    async sendQuestion(question) {
      const content = (typeof question === 'string' ? question : this.draft).trim();
      if (!content || this.busy || !this.canAsk) return;
      if (content.length > 1500) { ElementPlus.ElMessage.warning('问题请控制在 1500 字以内。'); return; }
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
        const response = await this.apiFetch('/company-knowledge/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: this.controller.signal, body: JSON.stringify({ message: content, history }) });
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
    <div class="ckb-workspace" :class="{ 'ckb-chat-workspace': mode === 'chat' }">
      <section class="ckb-hero">
        <div class="ckb-hero-copy">
          <div class="ckb-kicker"><span></span> GUANFU / KNOWLEDGE WORKSPACE</div>
          <h2>让经验沉淀，让知识生长。</h2>
          <p>读原始资料，理解项目脉络。与知识对话，找到新的启发。</p>
          <button class="ckb-button ckb-button-light" @click="showMode('chat')">开始知识问答 <i class="fa-solid fa-arrow-up-right-from-square"></i></button>
          <span class="ckb-hero-caption">每一次阅读，都为下一次判断积累底气。</span>
        </div>
        <div class="ckb-hero-art" aria-hidden="true">
          <div class="ckb-orbit ckb-orbit-one"></div><div class="ckb-orbit ckb-orbit-two"></div>
          <div class="ckb-paper ckb-paper-back"></div>
          <div class="ckb-paper ckb-paper-front"><span>GUANFU RESEARCH</span><div class="ckb-paper-symbol">知<span>识</span></div><div class="ckb-paper-rule"></div><small>READ. CONNECT. GROW.</small></div>
          <div class="ckb-art-index">01 / THE KNOWLEDGE COLLECTION</div>
        </div>
      </section>

      <div class="ckb-navigation">
        <div class="ckb-tabs" role="tablist" aria-label="知识库视图">
          <button id="ckb-library-tab" role="tab" :aria-selected="mode === 'library'" aria-controls="ckb-library-panel" :class="{ active: mode === 'library' }" @click="showMode('library')"><i class="fa-solid fa-book-open"></i> 资料库 <span>{{ documents.length.toString().padStart(2, '0') }}</span></button>
          <button id="ckb-chat-tab" role="tab" :aria-selected="mode === 'chat'" aria-controls="ckb-chat-panel" :class="{ active: mode === 'chat' }" @click="showMode('chat')"><i class="fa-solid fa-wand-magic-sparkles"></i> 知识问答</button>
        </div>
        <div class="ckb-preview-note"><span></span> {{ canAsk ? "云端知识库 · 已配置" : "等待连接" }}</div>
      </div>

      <div v-if="serviceError" class="ckb-service-error" role="alert">{{ serviceError }} <button @click="loadService">重试</button></div>
      <section v-if="mode === 'library'" id="ckb-library-panel" role="tabpanel" aria-labelledby="ckb-library-tab">
        <div class="ckb-section-heading"><div><h3>知识空间</h3><p>按项目与主题，找到需要的知识。</p></div><span class="ckb-heading-aside">精选 · 有序 · 可追溯</span></div>
        <div class="ckb-spaces">
          <button v-for="(item, index) in spaces" :key="item.id" :class="['ckb-space', 'ckb-space-' + index, { selected: space === item.id }]" :aria-pressed="space === item.id" @click="selectSpace(item.id)">
            <span class="ckb-space-icon"><i :class="['fa-solid', item.icon]"></i></span>
            <div><h4>{{ item.title }}</h4><p>{{ item.subtitle }}</p></div>
            <span class="ckb-space-count">{{ item.count }}<small>份</small></span>
          </button>
        </div>

        <div class="ckb-section-heading ckb-docs-heading"><div><h3>{{ favoritesOnly ? '我的收藏' : '资料馆藏' }} <span>{{ filteredDocuments.length.toString().padStart(2, '0') }}</span></h3></div><div><button class="ckb-button ckb-button-outline" :disabled="loading || !canAsk" @click="loadDocuments()">{{ loading ? "加载中…" : "刷新资料" }}</button> <button v-if="service.is_admin" class="ckb-button ckb-button-primary" @click="uploadOpen = true"><i class="fa-solid fa-plus"></i> 管理资料</button></div></div>
        <div class="ckb-library-tools">
          <label class="ckb-search"><i class="fa-solid fa-magnifying-glass"></i><input v-model="query" aria-label="搜索知识库资料" placeholder="搜索文件、项目或知识主题…"><button v-if="query" @click="query = ''" aria-label="清空搜索"><i class="fa-solid fa-xmark"></i></button><span v-else>SEARCH</span></label>
          <button :class="['ckb-favorites', { active: favoritesOnly }]" :aria-pressed="favoritesOnly" @click="favoritesOnly = !favoritesOnly"><i :class="favoritesOnly ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark'"></i> 我的收藏 <span>{{ favorites.length }}</span></button>
        </div>
        <div class="ckb-filters"><button v-for="item in categories" :key="item" :class="{ active: category === item }" @click="category = item">{{ item }}</button><button v-if="space !== 'all'" class="ckb-filter-reset" @click="space = 'all'">清除空间筛选 <i class="fa-solid fa-xmark"></i></button><span class="ckb-sort"><i class="fa-solid fa-arrow-down-wide-short"></i> 最近更新</span></div>
        <div v-if="filteredDocuments.length" class="ckb-document-grid">
          <article v-for="doc in filteredDocuments" :key="doc.id" class="ckb-document">
            <div class="ckb-doc-top"><span :class="['ckb-file-icon', 'ckb-file-' + doc.format.toLowerCase()]"><i :class="['fa-regular', doc.format === 'PDF' ? 'fa-file-pdf' : doc.format === 'XLSX' ? 'fa-file-excel' : 'fa-file-word']"></i></span><span class="ckb-doc-label">{{ doc.label }}</span><button class="ckb-bookmark" :aria-label="(favorites.includes(doc.id) ? '取消收藏：' : '收藏：') + doc.title" :aria-pressed="favorites.includes(doc.id)" @click="toggleFavorite(doc.id)"><i :class="favorites.includes(doc.id) ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark'"></i></button></div>
            <button class="ckb-doc-title" @click="openDocument(doc)">{{ doc.title }}</button>
            <p class="ckb-doc-summary">{{ doc.summary }}</p>
            <div class="ckb-doc-meta"><span>{{ doc.format }} · {{ sizeLabel(doc.size || 0) }}</span><span>{{ doc.date }} 更新</span></div>
            <div class="ckb-doc-bottom"><span :title="doc.project"><i class="fa-regular fa-folder"></i> {{ doc.project }}</span><button @click="openDocument(doc)">详情 <i class="fa-solid fa-arrow-right"></i></button></div>
          </article>
        </div>
        <div v-else class="ckb-empty"><i class="fa-regular fa-folder-open"></i><h3>{{ favoritesOnly ? '还没有符合筛选条件的收藏' : '没有找到相关资料' }}</h3><p>{{ loading ? "正在加载云端资料…" : "试试其他关键词，或刷新资料列表。" }}</p><button class="ckb-button ckb-button-outline" @click="resetFilters">清除筛选</button></div>
        <footer class="ckb-library-footer"><span><i class="fa-solid fa-shield-halved"></i> 资料来自百炼知识库。已加载 {{ documents.length }} / {{ totalDocuments }} 份。</span><button v-if="documents.length < totalDocuments" :disabled="loading" @click="loadDocuments(true)">加载更多资料</button><span>GUANFU KNOWLEDGE</span></footer>
      </section>

      <section v-else id="ckb-chat-panel" class="ckb-chat-layout" role="tabpanel" aria-labelledby="ckb-chat-tab">
        <aside class="ckb-chat-aside">
          <button class="ckb-button ckb-button-outline" @click="newConversation" :disabled="busy"><i class="fa-solid fa-plus"></i> 开始新对话</button>
          <div class="ckb-aside-label">对话范围 <span>CONTEXT</span></div>
          <label class="ckb-scope-label" for="ckb-scope">从哪些资料中寻找答案</label>
          <select id="ckb-scope" v-model="scope"><option value="all">{{ scopeLabel }} · 全部资料</option></select>
          <div class="ckb-context-card"><i class="fa-regular fa-file-lines"></i><strong>{{ scopeLabel }}</strong><p>围绕选定资料阅读、提问，保留答案与原文之间的联系。</p></div>
          <div class="ckb-aside-label">阅读与学习 <span>EXPLORE</span></div>
          <button v-for="doc in documents.slice(0, 3)" :key="doc.id" class="ckb-reading-link" @click="openDocument(doc)"><i class="fa-regular fa-file-lines"></i><span>{{ doc.title }}</span><i class="fa-solid fa-arrow-up-right-from-square"></i></button>
          <div class="ckb-chat-aside-foot"><i class="fa-solid fa-circle-info"></i> 回答由云端知识库生成，可点击引用核对资料。</div>
        </aside>
        <div class="ckb-chat-main">
          <header class="ckb-chat-header"><span><i class="fa-solid fa-wand-magic-sparkles"></i> 知识助手</span><small>基于资料 · 附带引用 <span>百炼</span></small></header>
          <div ref="chatFeed" class="ckb-chat-feed" aria-live="polite" aria-relevant="additions">
            <div v-if="!messages.length" class="ckb-chat-welcome">
              <div class="ckb-knowledge-mark"><i class="fa-solid fa-book-open"></i><span>✦</span></div>
              <span class="ckb-welcome-kicker">YOUR KNOWLEDGE, CONNECTED.</span><h3>把资料读懂，把经验串起来。</h3><p>从一个问题开始，探索项目背后的研究思路。<br>每一次回答，都可以回到资料本身。</p>
              <div class="ckb-suggestions"><button v-for="(question, index) in suggestions" :key="question" @click="sendQuestion(question)"><span>0{{ index + 1 }}</span>{{ question }}<i class="fa-solid fa-arrow-right"></i></button></div>
            </div>
            <div v-for="(message, index) in messages" :key="index" :class="['ckb-message', 'ckb-message-' + message.role]">
              <template v-if="message.role === 'user'"><span class="ckb-user-question">{{ message.text }}</span><small>范围：{{ message.scope }}</small></template>
              <template v-else>
                <div class="ckb-answer-heading"><span><i class="fa-solid fa-wand-magic-sparkles"></i> 知识助手</span><small>{{ message.complete ? '云端回答' : message.error ? '生成未完成' : answerStatus }}</small></div>
                <details v-if="message.progress.length" class="ckb-progress" :open="!message.complete">
                  <summary><span :class="['ckb-progress-indicator', { active: !message.complete && !message.error }]"></span><strong>{{ message.complete ? '处理完成' : message.error ? '处理已停止' : '正在处理' }}</strong><span class="ckb-progress-current">{{ !message.complete && !message.error ? message.progress[message.progress.length - 1].label : '查看处理过程' }}</span><small>{{ message.elapsedSeconds }} 秒</small></summary>
                  <ol class="ckb-progress-steps"><li v-for="(step, n) in message.progress" :key="n" :class="step.state"><span class="ckb-step-mark"><i :class="step.state === 'done' ? 'fa-solid fa-check' : step.state === 'error' ? 'fa-solid fa-exclamation' : 'fa-solid fa-circle'"></i></span><div><strong>{{ step.label }}</strong><p>{{ step.detail }}</p></div></li></ol>
                  <p v-if="!message.complete && !message.error" class="ckb-wait-note">{{ message.text ? '回答正在实时更新。' : '等待云端下一步进度，回答生成后会逐步显示。' }}</p>
                </details>
                <div class="ckb-live-answer">{{ message.text }}</div><p v-if="message.error" class="ckb-service-error" role="alert">{{ message.error }}</p>
                <div v-if="message.references.length" class="ckb-citation-heading">参考文件 <span>{{ referenceGroups(message.references).length }} 份文件 · {{ message.references.length }} 个片段</span></div>
                <button v-for="(group, n) in referenceGroups(message.references)" :key="group.key" class="ckb-citation" @click="openCitation(group)"><span>{{ n + 1 }}</span><i class="fa-regular fa-file-lines"></i><div><strong>{{ group.title }}</strong><small>{{ group.references.length }} 个片段 · 引用 {{ referenceIds(group) }} · 点击展开</small></div><i class="fa-solid fa-angle-right"></i></button>
              </template>
            </div>
          </div>
          <div class="ckb-composer-area"><div class="ckb-composer"><textarea ref="composer" v-model="draft" maxlength="1500" :disabled="!canAsk" aria-label="知识问答问题" placeholder="提问、梳理研究思路，或从一份资料开始…" rows="2" @keydown="onComposerKey"></textarea><div><span><i class="fa-regular fa-folder-open"></i> {{ scopeLabel }}</span><button v-if="busy" aria-label="停止生成" @click="controller?.abort()"><i class="fa-solid fa-stop"></i></button><button v-else :disabled="!draft.trim() || !canAsk" aria-label="发送问题" @click="sendQuestion"><i class="fa-solid fa-arrow-up"></i></button></div></div><p>Enter 发送 · Shift + Enter 换行 <span>{{ busy ? answerStatus : "云端问答 · 请核对引用依据" }}</span></p></div>
        </div>
      </section>

      <el-dialog v-model="readerOpen" width="960px" class="ckb-dialog ckb-reader-dialog" append-to-body :title="selectedDoc?.title || '资料阅读'">
        <template v-if="selectedDoc"><div class="ckb-reader-toolbar"><span>{{ selectedDoc.format || '引用资料' }} · {{ selectedDoc.status_message || '来源片段' }}</span><button class="ckb-button ckb-button-primary" :disabled="busy || !canAsk" @click="askDocument"><i class="fa-solid fa-wand-magic-sparkles"></i> 参考这份资料提问</button></div><div v-if="selectedDoc.references?.length" class="ckb-source-reader"><section v-for="reference in selectedDoc.references" :key="reference.id"><div class="ckb-citation-heading">引用 id_{{ reference.id }}</div><pre>{{ reference.text }}</pre><a v-if="originalUrl(reference.url)" class="ckb-button ckb-button-outline" :href="originalUrl(reference.url)" target="_blank" rel="noopener noreferrer">打开原件 / 下载</a></section></div><div v-else class="ckb-empty"><p>该资料{{ selectedDoc.status === 'FINISH' ? '已可检索' : '正在处理或处理失败，请查看资料状态' }}。先围绕这份资料提问，可从回答引用查看片段与原件。</p></div></template>
      </el-dialog>

      <el-dialog v-model="uploadOpen" title="管理公司资料" width="580px" class="ckb-dialog" append-to-body><p>在百炼知识管理中上传或更新资料，等待索引完成后，回到这里点击“刷新资料”。</p><a class="ckb-button ckb-button-primary" :href="consoleUrl" target="_blank" rel="noopener noreferrer">打开百炼知识管理</a></el-dialog>
    </div>`
};
