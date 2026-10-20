const AccountManagement = {
  props: { request: { type: Function, required: true } },
  emits: ['session-invalidated'],
  data() {
    return {
      tab: 'users', users: [], userTotal: 0, userPage: 1, query: '', state: 'all', userRole: 'user', activeAdminCount: 0,
      invitations: [], inviteTotal: 0, invitePage: 1, loading: false, busy: false,
      error: '', expiresHours: 6, inviteRole: 'user', secretOpen: false, secretTitle: '', secretValue: '',
      secretDescription: '', userRequestId: 0, inviteRequestId: 0, refreshTimer: null,
      profileOpen: false, profileSaving: false, profileError: '',
      profileForm: { id: null, username: '', display_name: '', notes: '' },
      audits: [], auditTotal: 0, auditPage: 1, auditActor: '', auditTarget: '', auditAction: 'all',
      auditRange: [], auditActions: [], auditLoading: false, auditRequestId: 0,
    };
  },
  mounted() {
    this.loadUsers();
    this.refreshTimer = setInterval(() => {
      if (this.tab === 'invitations' && !this.busy && !this.loading) this.loadInvitations();
    }, 30000);
  },
  beforeUnmount() { if (this.refreshTimer) clearInterval(this.refreshTimer); },
  methods: {
    async api(url, options = {}) {
      const response = await this.request(url, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败，请稍后重试');
      return data;
    },
    async loadUsers(reset = false) {
      if (reset) this.userPage = 1;
      const requestId = ++this.userRequestId;
      this.loading = true; this.error = '';
      try {
        const params = new URLSearchParams({ q: this.query, state: this.state, role: this.userRole, page: this.userPage, page_size: 20 });
        const data = await this.api('/admin/users?' + params);
        if (requestId === this.userRequestId) {
          const lastPage = Math.max(1, Math.ceil(data.total / 20));
          if (this.userPage > lastPage) { this.userPage = lastPage; await this.loadUsers(); return; }
          this.users = data.items; this.userTotal = data.total; this.activeAdminCount = data.active_admin_count;
        }
      } catch (error) { this.error = error.message; }
      finally { if (requestId === this.userRequestId) this.loading = false; }
    },
    async loadInvitations() {
      const requestId = ++this.inviteRequestId;
      this.loading = true; this.error = '';
      try {
        const data = await this.api(`/admin/invitations?page=${this.invitePage}&page_size=20`);
        if (requestId !== this.inviteRequestId) return;
        const lastPage = Math.max(1, Math.ceil(data.total / 20));
        if (this.invitePage > lastPage) { this.invitePage = lastPage; await this.loadInvitations(); return; }
        if (requestId === this.inviteRequestId) { this.invitations = data.items; this.inviteTotal = data.total; }
      } catch (error) { this.error = error.message; }
      finally { if (requestId === this.inviteRequestId) this.loading = false; }
    },
    onTabChange() {
      if (this.tab === 'users') this.loadUsers();
      else if (this.tab === 'invitations') this.loadInvitations();
      else this.loadAudits();
    },
    editProfile(row) {
      if (this.busy) return;
      this.profileForm = { id: row.id, username: row.username, display_name: row.display_name || '', notes: row.notes || '' };
      this.profileError = ''; this.profileOpen = true;
    },
    clearProfile() { this.profileForm = { id: null, username: '', display_name: '', notes: '' }; this.profileError = ''; },
    async saveProfile() {
      if (this.profileSaving || !this.profileForm.id) return;
      this.profileSaving = true; this.busy = true; this.profileError = '';
      try {
        const data = await this.api(`/admin/users/${this.profileForm.id}/profile`, {
          method: 'PATCH', body: JSON.stringify({ display_name: this.profileForm.display_name, notes: this.profileForm.notes }),
        });
        this.profileOpen = false;
        await this.loadUsers(); ElementPlus.ElMessage.success(data.message);
      } catch (error) { this.profileError = error.message; }
      finally { this.profileSaving = false; this.busy = false; }
    },
    async loadAudits(reset = false) {
      if (reset) this.auditPage = 1;
      const requestId = ++this.auditRequestId;
      this.auditLoading = true; this.error = '';
      try {
        const params = new URLSearchParams({ actor: this.auditActor, target: this.auditTarget, action: this.auditAction, page: this.auditPage, page_size: 20 });
        if (this.auditRange && this.auditRange.length === 2) {
          const start = new Date(this.auditRange[0]), end = new Date(this.auditRange[1]);
          start.setHours(0, 0, 0, 0); end.setHours(0, 0, 0, 0); end.setDate(end.getDate() + 1);
          params.set('start', start.toISOString()); params.set('end', end.toISOString());
        }
        const data = await this.api('/admin/audits?' + params);
        if (requestId !== this.auditRequestId) return;
        const lastPage = Math.max(1, Math.ceil(data.total / 20));
        if (this.auditPage > lastPage) { this.auditPage = lastPage; await this.loadAudits(); return; }
        this.audits = data.items; this.auditTotal = data.total; this.auditActions = data.actions;
      } catch (error) { if (requestId === this.auditRequestId && this.tab === 'audits') this.error = error.message; }
      finally { if (requestId === this.auditRequestId) this.auditLoading = false; }
    },
    resetAuditFilters() {
      this.auditActor = ''; this.auditTarget = ''; this.auditAction = 'all'; this.auditRange = [];
      this.loadAudits(true);
    },
    showSecret(title, value, description) {
      this.secretTitle = title; this.secretValue = value; this.secretDescription = description; this.secretOpen = true;
    },
    clearSecret() { this.secretValue = ''; this.secretDescription = ''; },
    async copySecret() {
      try { await navigator.clipboard.writeText(this.secretValue); ElementPlus.ElMessage.success('已复制'); }
      catch (_) { ElementPlus.ElMessage.warning('请选中下方内容手动复制'); }
    },
    async confirmAction(action, targetId = null) {
      let password;
      try {
        const result = await ElementPlus.ElMessageBox.prompt('请输入当前管理员的登录密码，确认本次操作。', '验证管理员身份', {
          inputType: 'password', inputPlaceholder: '当前管理员密码', inputValidator: value => !!value || '请输入密码',
          confirmButtonText: '验证并继续', cancelButtonText: '取消', closeOnClickModal: false,
        });
        password = result.value;
      } catch (_) { return null; }
      try {
        const data = await this.api('/auth/confirm-admin', { method: 'POST', body: JSON.stringify({ password, action, target_user_id: targetId }) });
        return { 'X-Admin-Confirmation': data.confirmation_token };
      } finally { password = ''; }
    },
    lastAdmin(row) { return row.role === 'admin' && row.is_active && this.activeAdminCount <= 1; },
    async createInvitation() {
      this.busy = true; this.error = '';
      try {
        const headers = this.inviteRole === 'admin' ? await this.confirmAction('create_admin_invitation') : {};
        if (!headers) return;
        const data = await this.api('/admin/invitations', { method: 'POST', headers, body: JSON.stringify({ expires_in_hours: this.expiresHours, role: this.inviteRole }) });
        this.showSecret(data.role === 'admin' ? '管理员邀请码' : '普通账号邀请码', data.token, `有效期至 ${this.formatDate(data.expires_at)}，仅可注册一个${data.role === 'admin' ? '管理员' : '普通账号'}。在网站注册页粘贴此邀请码即可；邀请码仅展示本次，请复制保存。`);
        this.invitePage = 1; await this.loadInvitations();
      } catch (error) { this.error = error.message; }
      finally { this.busy = false; }
    },
    async revokeInvitation(row) {
      try { await ElementPlus.ElMessageBox.confirm('撤销后，此邀请码将无法再用于注册。', '撤销邀请', { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' }); }
      catch (_) { return; }
      this.busy = true;
      try { await this.api(`/admin/invitations/${row.id}/revoke`, { method: 'POST' }); await this.loadInvitations(); }
      catch (error) { this.error = error.message; }
      finally { this.busy = false; }
    },
    async deleteInvitation(row) {
      if (this.busy || !['used', 'revoked'].includes(row.status)) return;
      try { await ElementPlus.ElMessageBox.confirm(`删除邀请 #${row.id} 后，将从邀请列表移除，历史记录保留在操作日志中，已注册的账号不受影响。`, '删除邀请', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }); }
      catch (_) { return; }
      this.busy = true; this.error = '';
      try {
        const data = await this.api(`/admin/invitations/${row.id}`, { method: 'DELETE' });
        await this.loadInvitations(); ElementPlus.ElMessage.success(data.message);
      } catch (error) { this.error = error.message; }
      finally { this.busy = false; }
    },
    async archiveUser(row) {
      if (this.busy || row.is_active || row.archived_at || row.is_self) return;
      try { await ElementPlus.ElMessageBox.confirm(`归档 ${row.username} 后，账号默认从列表隐藏，任务、报告和历史资料全部保留。可在“已归档”筛选中恢复。`, '归档账号', { type: 'warning', confirmButtonText: '确认归档', cancelButtonText: '取消' }); }
      catch (_) { return; }
      this.busy = true; this.error = '';
      try {
        const data = await this.api(`/admin/users/${row.id}/archive`, { method: 'POST' });
        await this.loadUsers(); ElementPlus.ElMessage.success(data.message);
      } catch (error) { this.error = error.message; }
      finally { this.busy = false; }
    },
    async restoreUser(row) {
      if (this.busy || !row.archived_at) return;
      try { await ElementPlus.ElMessageBox.confirm(`恢复 ${row.username} 后，账号仍保持停用。需要重新使用时，请在未归档列表中单独启用。`, '恢复归档账号', { type: 'info', confirmButtonText: '恢复', cancelButtonText: '取消' }); }
      catch (_) { return; }
      this.busy = true; this.error = '';
      try {
        const data = await this.api(`/admin/users/${row.id}/restore`, { method: 'POST' });
        await this.loadUsers(); ElementPlus.ElMessage.success(data.message);
      } catch (error) { this.error = error.message; }
      finally { this.busy = false; }
    },
    async updateUser(row, values) {
      if ('is_active' in values) {
        try { await ElementPlus.ElMessageBox.confirm(values.is_active ? '启用后，该用户可以重新登录。' : '停用后，该用户无法登录，已有登录凭证也将失效。历史资料会保留。', values.is_active ? '启用账号' : '停用账号', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }); }
        catch (_) { return; }
      }
      this.busy = true; this.error = '';
      try {
        const headers = row.role === 'admin' && 'is_active' in values ? await this.confirmAction(values.is_active ? 'enable_admin' : 'disable_admin', row.id) : {};
        if (!headers) return;
        const data = await this.api(`/admin/users/${row.id}`, { method: 'PATCH', headers, body: JSON.stringify(values) });
        if (data.requires_relogin) { this.$emit('session-invalidated'); ElementPlus.ElMessage.success('账号已更新，请重新登录'); return; }
        await this.loadUsers(); ElementPlus.ElMessage.success('账号已更新');
      }
      catch (error) { this.error = error.message; }
      finally { this.busy = false; }
    },
    async resetPassword(row) {
      try { await ElementPlus.ElMessageBox.confirm(`重置 ${row.username} 的密码后，旧密码和已有登录凭证将失效。`, '重置密码', { type: 'warning', confirmButtonText: '重置', cancelButtonText: '取消' }); }
      catch (_) { return; }
      this.busy = true; this.error = '';
      try {
        const headers = await this.confirmAction('reset_password', row.id);
        if (!headers) return;
        const data = await this.api(`/admin/users/${row.id}/reset-password`, { method: 'POST', headers });
        this.showSecret('临时密码', data.temporary_password, `请将临时密码交给 ${row.username}。临时密码仅展示本次，用户登录后必须修改。`);
        await this.loadUsers();
      } catch (error) { this.error = error.message; }
      finally { this.busy = false; }
    },
    async promoteUser(row) {
      try { await ElementPlus.ElMessageBox.confirm(`确定将 ${row.username} 提升为管理员？该账号将获得账号管理和公司资料等管理员权限，已有登录凭证将失效。`, '提升为管理员', { type: 'warning', confirmButtonText: '确认提升', cancelButtonText: '取消' }); }
      catch (_) { return; }
      this.busy = true; this.error = '';
      try {
        const headers = await this.confirmAction('promote_user', row.id);
        if (!headers) return;
        const data = await this.api(`/admin/users/${row.id}/promote`, { method: 'POST', headers });
        await this.loadUsers(); ElementPlus.ElMessage.success(data.message);
      } catch (error) { this.error = error.message; }
      finally { this.busy = false; }
    },
    async demoteUser(row) {
      try { await ElementPlus.ElMessageBox.confirm(`确定将 ${row.username} 降为普通账号？管理员权限将被收回，已有登录凭证将失效${row.is_self ? '，你将退出当前登录' : ''}。`, '降为普通账号', { type: 'warning', confirmButtonText: '确认降级', cancelButtonText: '取消' }); }
      catch (_) { return; }
      this.busy = true; this.error = '';
      try {
        const headers = await this.confirmAction('demote_user', row.id);
        if (!headers) return;
        const data = await this.api(`/admin/users/${row.id}/demote`, { method: 'POST', headers });
        if (data.requires_relogin) { this.$emit('session-invalidated'); ElementPlus.ElMessage.success(data.message); return; }
        await this.loadUsers(); ElementPlus.ElMessage.success(data.message);
      } catch (error) { this.error = error.message; }
      finally { this.busy = false; }
    },
    formatDate(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'; },
    statusLabel(value) { return ({ active: '可使用', used: '已使用', revoked: '已撤销', expired: '已过期' })[value] || value; },
  },
  template: `
    <el-card class="panel-card account-management" shadow="never">
      <template #header><div class="card-header"><div><p class="eyebrow">Company Accounts</p><h2>账号管理</h2></div></div></template>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="account-alert"></el-alert>
      <el-tabs v-model="tab" @tab-change="onTabChange">
        <el-tab-pane label="账号列表" name="users">
          <form class="account-toolbar" @submit.prevent="loadUsers(true)">
            <el-input v-model="query" placeholder="搜索用户名、姓名或备注" clearable maxlength="100" aria-label="搜索账号"></el-input>
            <el-select v-model="userRole" @change="loadUsers(true)" aria-label="账号类型"><el-option label="普通账号" value="user"></el-option><el-option label="管理员" value="admin"></el-option><el-option label="全部类型" value="all"></el-option></el-select>
            <el-select v-model="state" @change="loadUsers(true)" aria-label="账号状态"><el-option label="未归档（全部）" value="all"></el-option><el-option label="正常" value="active"></el-option><el-option label="已停用" value="disabled"></el-option><el-option label="已归档" value="archived"></el-option></el-select>
            <el-button native-type="submit" type="primary">搜索</el-button><el-button @click="loadUsers()">刷新</el-button>
          </form>
          <p class="account-help">当前有 {{activeAdminCount}} 个启用的管理员，至少保留一个。角色变更或停用后，原登录凭证立即失效。</p>
          <p class="account-help">{{state === 'archived' ? '归档账号的历史资料保留；恢复后仍为停用状态，需单独启用。' : '不用的账号可先停用再归档，从默认列表隐藏；在“已归档”筛选中可恢复。'}}</p>
          <el-table :data="users" v-loading="loading" empty-text="暂无匹配账号" style="width:100%">
            <el-table-column prop="username" label="账号资料" min-width="190"><template #default="{row}">{{row.username}}<div class="table-subtext">{{row.display_name ? row.display_name + ' · ' : ''}}{{row.role === 'admin' ? '管理员' : '普通账号'}}{{row.is_self ? ' · 当前账号' : ''}}</div><el-tooltip v-if="row.notes" :content="row.notes" placement="top" :show-after="300"><div class="account-note">{{row.notes}}</div></el-tooltip></template></el-table-column>
            <el-table-column label="状态" width="95"><template #default="{row}"><el-tag :type="row.is_active && !row.archived_at ? 'success' : 'info'">{{row.archived_at ? '已归档' : row.is_active ? '正常' : '已停用'}}</el-tag></template></el-table-column>
            <el-table-column label="注册时间" min-width="165"><template #default="{row}">{{formatDate(row.created_at)}}<div v-if="row.archived_at" class="table-subtext">归档 {{formatDate(row.archived_at)}}</div></template></el-table-column>
            <el-table-column label="最近登录" min-width="165"><template #default="{row}">{{formatDate(row.last_login_at)}}</template></el-table-column>
            <el-table-column label="邀请来源" min-width="135"><template #default="{row}">{{row.invitation_id ? '#' + row.invitation_id + ' · ' + row.invited_by : '已有账号'}}</template></el-table-column>
            <el-table-column label="公司知识库" width="130"><template #default="{row}"><span v-if="row.role === 'admin'" class="table-subtext">管理员权限</span><el-switch v-else :model-value="row.knowledge_access" :disabled="busy || !!row.archived_at" :aria-label="row.username + '的知识库权限'" @change="value => updateUser(row, {knowledge_access:value})"></el-switch></template></el-table-column>
            <el-table-column label="操作" width="230" fixed="right">
              <template #default="{row}">
                <div v-if="row.archived_at" class="account-actions"><div class="account-primary-actions"><el-button size="small" plain type="primary" :disabled="busy" @click="restoreUser(row)">恢复账号</el-button></div><div class="table-subtext">历史资料已保留</div></div>
                <div v-else class="account-actions">
                  <div class="account-primary-actions">
                    <el-button size="small" plain :type="row.is_active ? 'danger' : 'success'" :disabled="busy || lastAdmin(row)" @click="updateUser(row, {is_active:!row.is_active})">{{row.is_active ? '停用' : '启用'}}</el-button>
                    <el-button v-if="!row.is_self" size="small" plain type="primary" :disabled="busy" @click="resetPassword(row)">重置密码</el-button>
                  </div>
                  <div class="account-secondary-actions">
                    <el-button v-if="row.role === 'user'" class="account-role-action" size="small" plain type="warning" :disabled="busy || !row.is_active" @click="promoteUser(row)">提升为管理员</el-button>
                    <el-button v-else class="account-role-action" size="small" plain type="warning" :disabled="busy || lastAdmin(row)" @click="demoteUser(row)">降为普通账号</el-button>
                    <el-button size="small" plain type="primary" :disabled="busy" @click="editProfile(row)">编辑资料</el-button>
                  </div>
                  <div v-if="!row.is_active && !row.is_self" class="account-secondary-actions"><el-button size="small" plain type="info" :disabled="busy" @click="archiveUser(row)">归档账号</el-button><span class="table-subtext">保留历史资料</span></div>
                  <div v-if="lastAdmin(row)" class="table-subtext">最后一个启用的管理员</div>
                  <div v-if="row.must_change_password" class="table-subtext">登录后须修改密码</div>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <div class="pagination-bar"><el-pagination background layout="prev, pager, next, total" :total="userTotal" v-model:current-page="userPage" :page-size="20" @current-change="loadUsers()"></el-pagination></div>
        </el-tab-pane>
        <el-tab-pane label="邀请管理" name="invitations">
          <div class="account-toolbar"><el-select v-model="inviteRole" aria-label="邀请类型"><el-option label="普通账号" value="user"></el-option><el-option label="管理员" value="admin"></el-option></el-select><span>有效期（小时）</span><el-input-number v-model="expiresHours" :min="1" :max="168" :precision="0" aria-label="邀请有效期（小时）"></el-input-number><el-button type="primary" :loading="busy" @click="createInvitation">生成邀请码</el-button><el-button @click="loadInvitations">刷新</el-button></div>
          <p class="muted account-help">每个邀请码限注册一个对应类型的账号，仅在生成时展示。新用户进入网站注册页粘贴邀请码即可；可提前撤销。已撤销、已使用的邀请可删除，过期邀请自动清理，操作日志保留。</p>
          <el-table :data="invitations" v-loading="loading" empty-text="暂无邀请，点击上方按钮生成" style="width:100%">
            <el-table-column prop="id" label="编号" width="85"></el-table-column><el-table-column prop="created_by" label="创建人" min-width="120"></el-table-column>
            <el-table-column label="邀请类型" width="110"><template #default="{row}"><el-tag :type="row.role === 'admin' ? 'warning' : 'info'">{{row.role === 'admin' ? '管理员' : '普通账号'}}</el-tag></template></el-table-column>
            <el-table-column label="创建时间" min-width="175"><template #default="{row}">{{formatDate(row.created_at)}}</template></el-table-column>
            <el-table-column label="到期时间" min-width="175"><template #default="{row}">{{formatDate(row.expires_at)}}</template></el-table-column>
            <el-table-column label="状态" width="115"><template #default="{row}"><el-tag :type="row.status === 'active' ? 'success' : 'info'">{{statusLabel(row.status)}}</el-tag></template></el-table-column>
            <el-table-column prop="used_by" label="注册账号" min-width="145"></el-table-column>
            <el-table-column label="操作" width="95" fixed="right"><template #default="{row}"><el-button v-if="row.status === 'active'" size="small" plain type="danger" :disabled="busy" @click="revokeInvitation(row)">撤销</el-button><el-button v-else-if="['used','revoked'].includes(row.status)" size="small" plain type="danger" :disabled="busy" @click="deleteInvitation(row)">删除</el-button></template></el-table-column>
          </el-table>
          <div class="pagination-bar"><el-pagination background layout="prev, pager, next, total" :total="inviteTotal" v-model:current-page="invitePage" :page-size="20" @current-change="loadInvitations"></el-pagination></div>
        </el-tab-pane>
        <el-tab-pane label="操作日志" name="audits">
          <form class="account-toolbar account-audit-toolbar" @submit.prevent="loadAudits(true)">
            <el-input v-model="auditActor" placeholder="操作人：用户名或姓名" clearable maxlength="100" aria-label="日志操作人"></el-input>
            <el-input v-model="auditTarget" placeholder="操作对象：用户名或姓名" clearable maxlength="100" aria-label="日志操作对象"></el-input>
            <el-select v-model="auditAction" @change="loadAudits(true)" aria-label="日志操作类型"><el-option label="全部操作" value="all"></el-option><el-option v-for="item in auditActions" :key="item.value" :label="item.label" :value="item.value"></el-option></el-select>
            <el-date-picker v-model="auditRange" type="daterange" format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" aria-label="日志日期范围" @change="loadAudits(true)"></el-date-picker>
            <el-button native-type="submit" type="primary" :loading="auditLoading">查询</el-button><el-button @click="resetAuditFilters">重置筛选</el-button><el-button @click="loadAudits()">刷新</el-button>
          </form>
          <p class="account-help">按最新时间排列，展示账号资料、权限、密码和邀请操作的历史记录。“系统清理”的操作人显示对应邀请的创建人。</p>
          <el-table :data="audits" v-loading="auditLoading" empty-text="暂无匹配的操作日志" style="width:100%">
            <el-table-column prop="id" label="编号" width="80"></el-table-column>
            <el-table-column label="操作时间" min-width="170"><template #default="{row}">{{formatDate(row.created_at)}}</template></el-table-column>
            <el-table-column label="操作人" min-width="160"><template #default="{row}"><span v-if="row.is_system">系统清理</span><span v-else>{{row.actor_username}}</span><div class="table-subtext">{{row.is_system ? '创建人：' + row.actor_username : row.actor_name}}</div></template></el-table-column>
            <el-table-column label="操作对象" min-width="160"><template #default="{row}">{{row.target_username || (row.invitation_id ? '邀请码 #' + row.invitation_id : '—')}}<div v-if="row.target_name" class="table-subtext">{{row.target_name}}</div></template></el-table-column>
            <el-table-column prop="action_label" label="操作类型" width="140"></el-table-column>
            <el-table-column prop="summary" label="变更摘要" min-width="260"></el-table-column>
          </el-table>
          <div class="pagination-bar"><el-pagination background layout="prev, pager, next, total" :total="auditTotal" v-model:current-page="auditPage" :page-size="20" @current-change="loadAudits()"></el-pagination></div>
        </el-tab-pane>
      </el-tabs>
      <el-dialog v-model="profileOpen" title="编辑账号资料" width="min(520px, 94vw)" :close-on-click-modal="false" :close-on-press-escape="!profileSaving" :show-close="!profileSaving" @closed="clearProfile">
        <el-alert v-if="profileError" :title="profileError" type="error" :closable="false" show-icon class="account-alert"></el-alert>
        <el-form label-position="top" @submit.prevent="saveProfile">
          <el-form-item label="用户名"><el-input :model-value="profileForm.username" disabled aria-label="资料用户名"></el-input></el-form-item>
          <el-form-item label="姓名"><el-input v-model="profileForm.display_name" maxlength="100" show-word-limit placeholder="填写姓名（选填）" aria-label="账号姓名" :disabled="profileSaving"></el-input></el-form-item>
          <el-form-item label="备注"><el-input v-model="profileForm.notes" type="textarea" :rows="4" maxlength="1000" show-word-limit placeholder="填写账号备注（选填）" aria-label="账号备注" :disabled="profileSaving"></el-input></el-form-item>
          <p class="account-help">姓名和备注供管理员识别与管理账号，普通用户仍使用原用户名登录。</p>
          <div class="account-profile-footer"><el-button :disabled="profileSaving" @click="profileOpen=false">取消</el-button><el-button native-type="submit" type="primary" :loading="profileSaving">保存资料</el-button></div>
        </el-form>
      </el-dialog>
      <el-dialog v-model="secretOpen" :title="secretTitle" width="min(600px, 94vw)" :close-on-click-modal="false" @closed="clearSecret">
        <p class="account-help">{{secretDescription}}</p><el-input :model-value="secretValue" type="textarea" readonly :rows="3" aria-label="复制内容"></el-input>
        <template #footer><el-button @click="copySecret">复制</el-button><el-button type="primary" @click="secretOpen=false">已保存，关闭</el-button></template>
      </el-dialog>
    </el-card>`,
};
