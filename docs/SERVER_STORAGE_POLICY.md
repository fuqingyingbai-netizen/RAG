# 缓存与日志空间策略

业务原件、运行环境、容器与完整恢复备份不属于本策略的清理范围。

## 安装缓存

- 每天北京时间 04:30 后低优先级检查 uv、pip 和 APT 下载缓存，三者合计以 500 MB 为清理触发阈值。安装期间可能临时超过，因此不是写入硬配额。
- 每隔 7 天，或缓存超阈值时，使用 uv 原生 `cache prune --ci` 回收预编译安装包、保留有价值的本机构建缓存。pip/APT 缓存各超 100 MB 时使用原生清理命令；合计仍超阈值才清空 uv 缓存。
- 不直接递归删除缓存目录，不使用 `--force`；uv 自身的缓存锁负责处理并发安装。发现发布锁或安装任务时退出让路，15 分钟后重试，不获取发布锁。
- 当前虚拟环境若位于 uv 缓存内部则拒绝清理。已安装依赖不删除；清理后再次安装部分依赖需要重新下载。

## 日志

- journald 持久化日志目标上限 300 MiB，单文件 32 MiB，最长 14 天，并预留约 10 GiB 系统盘空间。容量与时间以先触发者为准；活动日志文件可能造成少量暂时超限，不能保证一定保留满 14 天。
- rsyslog 普通文本日志每日轮转、最多 14 份且不超过 14 天；单文件超过 20 MiB 时允许提前轮转，旧记录压缩。
- logrotate 每小时检查，现有 Nginx/PostgreSQL 等规则继续生效。正在写入的日志通过工具轮转，不直接删除或截断。
- `auth.log` 仍参与常规轮转；`btmp`、`wtmp` 等登录审计文件沿用系统原有策略，不随安装缓存清理。

## 核查与回滚

- `systemctl list-timers supermew-storage-maintenance.timer logrotate.timer` 检查计划。
- `journalctl --disk-usage`、`systemd-analyze cat-config systemd/journald.conf` 检查日志容量和配置。
- `/opt/supermew/backup-policy/cache-maintenance-status.json` 记录缓存清理结果；失败和避让由 systemd 日志及重试状态体现。
- 安装前在 `/opt/supermew/ops/storage-maintenance/rollback-*` 保存原配置。修改日志守护进程配置时仅重启 journald，不重启网站、数据库或容器。

机制参考：[uv 官方缓存清理说明](https://docs.astral.sh/uv/concepts/cache/)、[systemd 日志容量与保留设置](https://www.freedesktop.org/software/systemd/man/latest/journald.conf.html)。
