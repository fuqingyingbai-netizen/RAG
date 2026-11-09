# 服务器备份策略 v2

此策略替代每日在系统盘生成完整 `data.tar.gz` 的旧定时任务。上传原件、数据库、应用服务的日常位置不变。

## 恢复范围与保留规则

- 每日北京时间 03:00 后执行一次加密、去重的 Restic OSS 备份。输入为在线 PostgreSQL 逻辑备份、`shared/data` 下的原件及研究产物、应用配置及运行版本源码。不会停止应用或 Milvus。
- OSS 保留最近 7 天每天的恢复点和最近 4 周的每周恢复点，至少保留最新恢复点。历史数据由 Restic 的 `forget/prune` 管理；禁止给 Restic 的对象前缀设置按文件年龄直接删除对象的 OSS 生命周期规则。
- 每次备份后执行仓库结构校验，恢复并核对本次恢复清单及不超过 1 MB 的业务原件样本；首次及每隔 7 天恢复完整数据库归档到随机命名的独立验证数据库。首次完整演练通过、后续演练未过期且当日样本校验通过后，才允许裁剪本地完整恢复备份及清理云端历史。避免每天完整下载数据库很快耗尽试用下载额度；请求和下载总量仍须核对云账单，不能保证永久免费。
- 本机保留 1 份已校验的旧完整恢复备份、最多 2 份近期数据库归档；本地备份总量预算 8 GB，系统盘可用空间预留 10 GB。空间不足时拒绝新增本地备份，不为满足配额删除最后一份可用恢复备份。
- 每 15 分钟检查容量。持有部署与备份锁后，才可清理超过 24 小时且没有进程使用的失败归档。所有删除严格限定于明确识别的 `/opt/supermew/backups` 直接子目录，并先保存删除清单。
- 云端上传使用独立的 `.offsite-backup.lock`，不会长时间占用发布锁；只在复制当前版本及数据库配置、最终本地归档清理时短暂取得发布锁。发布正在执行时延后清理，由容量定时器重试。
- 发布前的容量检查同时计算已有备份、拟生成备份和可用空间。新版 `activate-release.py` 在暂停应用或开启维护入口前执行检查。

本地 Milvus 的运行中底层文件不直接上传为“完整可恢复备份”。它属于派生检索索引：需从业务原件重建，或使用保留的离线完整备份恢复旧状态。公司知识库检索使用百炼，不依赖这份本地索引。本策略不宣称备份了百炼云端的全部配置和索引。

## OSS 接入

1. 先领取符合资格的新用户试用，再创建独立 Bucket。标准存储、本地冗余 LRS、私有、开启阻止公共访问。试用额度及期限以账号页面为准，下载恢复和请求也可能计费。
2. 创建备份专用 RAM 程序用户，只授权指定 Bucket 中的备份前缀读、写、列举、删除和必要的分片上传操作，不授予主账号权限。Restic 保留策略需要删除旧备份对象的权限。
3. `/etc/supermew/backup-policy.json` 使用 `deploy/backup-policy.example.json` 为模板：

   ```json
   {
     "schema": 2,
     "repository": "s3:https://oss-cn-hangzhou.aliyuncs.com/YOUR-BUCKET/supermew-restic",
     "region": "oss-cn-hangzhou"
   }
   ```

4. 在权限为 0600 的 `/etc/supermew/backup-oss.env` 中配置 `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`、`RESTIC_PASSWORD_FILE=/etc/supermew/backup-repository-password`。如使用临时身份，同时配置 `AWS_SESSION_TOKEN` 并负责续期。禁止把真实密钥提交 Git。
5. 生成独立随机的仓库密码，保存在上述密码文件，另外在服务器之外保存可恢复的受保护副本。仅将密码保存在服务器会导致服务器丢失后无法解密云端备份。
6. 显式执行一次 `backup_policy.py --run --init-repository` 创建专用仓库和首个恢复点。定时任务不会在连接错误时自动重新初始化仓库。

没有 OSS 配置时，备份命令返回非零退出码和 `action_required`，不会创建完整大包，也不会假装异地备份成功。现有完整备份在异地恢复验证前全部保留。

## 安装与检查

固定运行位置为 `/opt/supermew/ops/backup/backup_policy.py`，避免应用切换 `current` 后重新运行旧版备份程序。

安装官方 Restic 0.19.1，校验其官方 `SHA256SUMS`；安装本仓库的 `supermew-backup.service`、原日备份 timer、`supermew-backup-guard.service/timer`。先执行 `systemd-analyze verify`，再 daemon-reload 和启用定时器。替换单元前保存原单元副本。备份源代码不依赖应用 Python 包。

- `python3 /opt/supermew/ops/backup/backup_policy.py`：仅显示计划。
- `python3 /opt/supermew/ops/backup/backup_policy.py --run --guard`：执行容量与残留检查。
- `systemctl start supermew-backup.service`：执行已配置仓库的备份。
- `journalctl -u supermew-backup.service -u supermew-backup-guard.service`：查看日志及告警。
- `/opt/supermew/backup-policy/backup-status.json`、`guard-status.json`：最近结果；`offsite-verified.json`：异地恢复验证回执。

告警目前通过 systemd 失败状态、日志和状态文件暴露；没有未经授权向钉钉、邮件等发送消息。若需要主动通知，应另行配置明确的接收渠道。

## 验证边界

仓库校验和样本恢复验证不等于整台服务器的全量灾难恢复演练。首次上线记录应分别写清：单元测试结果、实际增量去重验证、数据库独立恢复结果、是否真正接通 OSS。缺少 OSS 配置时不得标记整个迁移完成。
