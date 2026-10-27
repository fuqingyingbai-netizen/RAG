# 整合版本后的发布流程

这些工具只做本地准备，不提交、不推送、不合并、不上传，也不会连接数据库或调用模型。
正式候选版本必须包含整合同事代码后的提交，以及本次新增的 scripts/、deploy/ 和文档文件。
未提交文件不会进入部署包；当前工作区的测试结果不能替代整合版本的验收。

## 1. 检查生产配置

以 deploy/app.env.example 为模板，在忽略目录创建本地待配置文件，填写独立的服务器配置。
不要直接复制本机真实资料或沿用本机数据库、文件路径。实际配置不提交、不进入发布包。

```powershell
# 复制一次；如目标已存在，请直接编辑已有文件。
New-Item -ItemType File -Path work/production-app.env -Value (Get-Content deploy/app.env.example -Raw) -ErrorAction Stop
.\.venv\Scripts\python.exe scripts/check-production-config.py --env-file work/production-app.env
# 机器可读的检查结果
.\.venv\Scripts\python.exe scripts/check-production-config.py --env-file work/production-app.env --json
```

只读取显式指定文件，不读取系统环境变量或其他 .env，不导入业务模块，不访问网络。
输出只包含检查项和固定说明，不显示配置值；退出码 0 表示离线规则通过，1 表示存在错误。
原样使用模板会被拒绝，这是预期行为。

配置采用与 systemd EnvironmentFile 兼容的简单子集：每行一个大写 KEY=value；注释独立成行；
含空格或 # 的值使用成对引号；不使用 export、反斜杠、内嵌引号或变量展开。
数据库和 Redis 连接串中的密码须进行 URL 编码。配置检查不执行 shell 内容。

检查覆盖：登录密钥、数据库和缓存口令、模型与搜索配置、Linux 持久路径、向量维度配置、
对象存储、公司知识库配置完整性、Word 渲染和演示数据开关。模型维度须在最终验收中实测。
公司知识库未配置时会给出范围确认提醒；离线通过也不代表该功能已验收。

在 Linux 服务器可增加 --check-paths；它会检查目录和 LibreOffice 可执行文件是否存在。
BM25 文件允许首次启动时尚未存在，但其父目录必须已准备好。
模板使用严格的 Word 渲染验收要求，服务器需要中文字体和 LibreOffice。
本次不修改业务代码的跨域设置，正式开放前仍需完成该项修改和验证。

## 2. 固定发布提交并打包

先确认整合完成、相关测试通过，再用完整提交号替换下面占位值。工具不自动提交任何文件。

```powershell
.\.venv\Scripts\python.exe scripts/build-release.py --ref <整合后的完整提交号>
```

默认输出到忽略目录 work/releases/：源码 tar.gz、逐文件清单 manifest.json、整包 .sha256 校验文件。
清单记录完整提交、Git tree、提交时间、每个文件的大小、权限和 SHA-256。
同一提交使用相同工具版本重复打包，内容相同；工具拒绝覆盖已有输出，可换 --output-dir 指定新目录。

打包边界：

- 仅从指定提交读取 backend/、frontend/、deploy/ 中批准的文件类型和少量运行所需文件。
- 包含 pyproject.toml、uv.lock、README、管理员与迁移脚本、配置检查脚本及发布文档。
- 不读取工作区文件内容；本机未提交修改和未跟踪文件不会进入部署包。
- 不打包 .env、work/、data/、volumes/、真实报告、交付物或虚拟环境。
- 运行目录里出现不在批准范围的文件、链接、常见私钥格式或疑似硬编码凭据时会停止打包。
- 凭据检测是辅助检查，不能替代代码审查；以代码或 JSON 伪装的私人资料仍须人工排除。

工具要求 Git 和 Python 3.12，使用标准库即可运行。检测失败不打印文件内容或凭据。
源码包不包含模型、Python 依赖、浏览器和系统软件，不能仅解压就认定部署完成。

## 3. 最终版本验证

在隔离目录检出候选提交，按 uv.lock 锁定安装依赖并执行该版本的自动测试和前端检查。
核对发布清单包含最新的部署工具，不将此前基线的验证包当作正式发布包。
部署前保留测试记录、发布提交和包校验值；真实业务验收另行执行，会使用外部服务额度。

## 4. 服务器执行顺序

1. 复查端口、资源与原有容器；为新应用使用独立目录和独立依赖服务，保留原有业务。
2. 在暂存目录校验上传包的 SHA-256；按清单确认版本后再解压至 /opt/supermew/releases/提交号/。
3. 使用受控来源安装系统依赖和 Python 3.12，以 uv sync --locked --no-dev 安装锁定依赖。
4. 创建 supermew 专用账号、持久目录和模型缓存；每个版本的 data 链接到 /opt/supermew/shared/data。
5. 将实际配置保存至 /etc/supermew/app.env，设置 root:supermew 所有者及 0640 权限；专用账号仅可读取。
6. 备份数据库、持久文件和当前配置，记录同一恢复时间点；确认没有运行中的研究任务，再停旧应用。
7. 以专用账号和同一 EnvironmentFile 执行迁移；不要直接运行未加载生产环境的迁移脚本。
8. 配置 current 指向候选版本并使用 deploy/supermew.service，单进程启动；启动前自动执行配置检查。
9. 通过 SSH 隧道进行受限验收，核对 /version 的实例和组件版本，以及包内 manifest 的提交。
10. 完成 DNS、HTTPS、跨域与访问权限检查后，再对外开放网站。

迁移与管理员初始化应通过 systemd 临时服务加载同一环境。下例只说明迁移的环境传递方式，
不是自动部署脚本；路径应指向已验证的实际候选版本：

```sh
systemd-run --wait --pipe --collect --unit=supermew-migrate \
  --property=User=supermew --property=Group=supermew \
  --property=WorkingDirectory=/opt/supermew/releases/CANDIDATE_COMMIT \
  --property=EnvironmentFile=/etc/supermew/app.env \
  /opt/supermew/releases/CANDIDATE_COMMIT/.venv/bin/python scripts/migrate-accounts.py --apply
```

不要在日志或命令参数中填写密码。管理员创建需要交互终端，并同样传入生产环境。
账号迁移会改变数据库，必须在备份和版本确认后执行。

## 5. 备份、恢复与验收记录

| 项目 | 上线前需要保留的证据 |
|---|---|
| 数据库 | 可恢复的备份、对应版本、备份时间、隔离恢复结果 |
| 文件 | shared/data 和使用中的对象存储快照，能下载原文件 |
| 配置 | 单独加密保管的配置备份，包含密钥轮换与保管责任人 |
| 回退 | 前一版本和对应依赖；数据库迁移兼容性检查；恢复后权限复验 |
| 账号 | 邀请、登录、禁用、管理员保护及普通用户隔离 |
| 研究线路 | 对应负责人确认公司、人物、行业线路的完整流程和交付物 |
| 稳定性 | 网络中断、刷新、服务重启后的任务状态与恢复指引；实测资源峰值 |
| 对外访问 | DNS、HTTPS、续期、必要端口及下载权限 |

不能只切换代码就宣称回滚成功。恢复数据库时需考虑匹配的文件快照，以及恢复时间点之后的数据。
备份内容、真实报告和验收资料保留在私人存储中，不进入 Git 或源码包。
