# 本地运行验证记录（2026-10-14，北京时间）

## GitHub 连接

- 当前目录：`E:\projects\RAG`，分支 `main`。
- 远程：`https://github.com/fuqingyingbai-netizen/RAG.git`。
- 远程 HEAD / 本地 HEAD：`a8f773a7f62758c02a6cc23eff371375bcd87c48`。
- 直接访问 github.com:443 超时；通过本机代理 `http://127.0.0.1:7897` 后，`git ls-remote`、`git fetch origin` 成功。
- 已设置本仓库的本地 Git 代理配置；`git rev-list --left-right --count HEAD...origin/main` 为 `0 0`。
- 本次代码修改保留在工作区，未提交或推送。

## 环境与启动

最初当前检出目录没有 `.env` / `.venv`，系统 `python` 指向 Microsoft Store 占位程序，`uv` 不在 PATH。已从本机 `E:\RAG.zip` 恢复 `.env`、依赖和 BGE-small-zh 模型；虚拟环境绑定可用的 Python 3.12.14，模型目录改为当前项目路径。模型实际输出 512 维，与原 `.env` 的维度一致。

用户随后提供 `E:\RAG\RAG` 原环境目录。已核对该目录的模型、搜索、专业数据库 API 配置，与压缩包恢复的配置一致；原虚拟环境仍绑定已不存在的 `C:\Program Files\Python312`，模型配置也指向旧 `D:\uv\RAG(1)\RAG`。本次修复均在当前 `E:\projects\RAG` 检出执行。

Docker Desktop 正常。原有 `milvus-standalone`、`milvus-minio`、`milvus-etcd` 属于 `E:\milvus` 的 Compose 部署；启动脚本现在自动复用这些健康容器，避免同名容器冲突或替换原有数据。新增 PostgreSQL 15 和 Redis 7，均通过健康检查。新增 `docker-compose.reuse.yml`，将现有网络声明为 external。

服务地址：`http://127.0.0.1:8010/`；API 文档：`http://127.0.0.1:8010/docs`。

启动命令：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -Background
.\.venv\Scripts\python.exe .\scripts\check-local.py
```

启动脚本在后台模式等待 API 就绪。日志：`work/environment-recovery/backend.stdout.log`、`backend.stderr.log`；进程记录：`backend.pid`。

新环境起初缺少研究对象桶和向量集合。研究计划归档创建了 MinIO 研究桶，已显式初始化配置对应的 Milvus 集合。初始化后连通性检查为 **0 failed checks**。

## 管理员与权限验证

- 新建管理员 `admin`，密码为随机生成，使用项目现有 PBKDF2 存储。
- 凭据仅保存在本机 `work/local-admin.json`，由 `.gitignore` 排除。
- 新增 `scripts/create-admin.py`：交互输入密码或读取 `BOOTSTRAP_ADMIN_PASSWORD`；遇到已有同名用户退出，不修改其密码或角色。
- 真实 `/auth/login`、`/auth/me` 和网页管理员登录成功。
- 错误密码返回 401；普通用户访问文档管理、其他用户研究项目返回 403；普通用户项目列表为空；错误管理员邀请码返回 403。
- 权限检查创建了一名 `smoke_user_*` 普通测试用户，验证后仅删除了本次创建的测试用户。检查结果：`work/authorization-checks.json`。

## 文档与向量检索验证

使用明确标为合成测试资料的 Word 文件，检查真实管理员上传、解析、三级分块、512 维稠密和 BM25 稀疏向量入库、Milvus 混合检索。成功检索到测试验收编号 `RAG-LOCAL-20261014`。随后删除本次测试文档，确认向量已清理。结果：`work/vector-checks.json`。

## 公司任务

- 项目 ID：`1`。
- 目标：比亚迪股份有限公司。
- 项目名称：`本地端到端验证-比亚迪股份有限公司-202610141051`。
- 使用真实配置调用线上搜索、MinIO、PostgreSQL 和后台研究工作流。
- 新增可复用 `scripts/smoke-research.py`，实际登录、运行 SSE 流程、保存事件和最终详情，并检查桌面研究报告、项目建议书两个 Word 下载包。
- 本次原始记录目录：`work/smoke-research/20261014-105050/`。
- 首次运行于 10:51 开始，采集 216 条来源后为修正失效模型主动暂停；该轮记录状态 `paused`，没有生成最终报告。
- 修正模型后 11:06 在同一项目恢复执行，记录目录为 `work/smoke-research/20261014-110659/`。
- 恢复轮耗时约 **42.3 分钟**，最终业务状态 `completed`；来源 **462** 条、清洗事实 **690** 条、归档产物 **10** 个。
- 登录、采集、清洗、风险研判、报告生成、建议书生成、MinIO 归档和两份 Word 下载的功能链路完成。已下载 `desktop_report-8.docx`、`proposal-10.docx`，验证了 ZIP 包完整性及 `word/document.xml`。
- **正式交付质量未通过**：报告 #8 的 `delivery_status=review_draft`。质量门发现将“公开检索未命中”表述为确定不存在/零风险的结论，已保存质量诊断 #9；待复核稿不能作为正式交付。修复 JSON 解析后重新检查现有报告，该质量问题仍存在，未放宽质量闸门或改写业务结论。
- 恢复轮记录 **32** 条 warning / fallback 事件（包括外部服务认证、网页提取、模型超时和报告质量），完整记录在 `events.jsonl`。
- Word 下载通过基础包结构检查，但本机未发现 LibreOffice soffice，产物 metadata 的 `docx_render_status=unavailable`；本次没有完成 Word 排版渲染验证。
- 本轮 `result.json` 已补充 `workflow_passed=true`、`delivery_passed=false`、`passed=false` 和质量说明；最初只判断流程完成及下载的结果另存为 `result.before-quality-check.json`。

## 已修复问题

1. GitHub 直接网络不通：设置本仓库本地代理，并验证远程一致。
2. 当前检出缺少运行文件、旧路径失效：恢复本地依赖和配置，修正 Python / 模型路径。
3. 原启动脚本会尝试创建同名向量容器：自动复用其他目录的健康部署。
4. 原后台启动仅返回进程号，未保证服务已启动：等待研究 API 就绪。
5. Windows PowerShell 5 的原生命令参数引号导致 Docker Go 模板解析错误：改用 JSON 标签读取；缺失镜像检查改为 `docker images --quiet`，避免 native stderr 使构建分支提前退出。
6. 网页将无时区的后端 UTC 时间直接按本地解析，显示比北京时间早 8 小时：`formatTime` 复用现有 UTC 解析逻辑。
7. 行业策略测试断言沿用旧模块名：与当前策略的“政策与监管”一致。
8. 原主模型 `qwen-vl-plus` 返回 HTTP 404 / `model_not_found`，评分模型 `qwen-urbo` 拼写错误。已实测同一密钥下 `qwen-plus`、`qwen-turbo`、`qwen3-vl-plus` 均返回 200，分别用于主模型、评分和视觉任务；原配置备份在 `.env.before-smoke-model-fix`，不提交 Git。参考 [阿里云文本生成文档](https://www.alibabacloud.com/help/en/model-studio/text-generation) 与 [视觉模型兼容接口文档](https://www.alibabacloud.com/help/en/model-studio/qwen-vl-compatible-with-openai)，实际可用性以本机请求结果为准。
9. 原 Serper / 博查配置在搜索阶段提前抓取正文，使 23 条补充查询用时过长；已关闭两个 provider 的预抓取，由工作流统一抓取、归档和记录正文，`.env.example` 也补充对应配置。
10. 在线 PDF（`https://epaper.cs.com.cn/zgzqb/images/2023-06/09/B060/zqB06009.pdf`）提取文本含 NUL，归档报 `A string literal cannot contain NUL (0x00) characters.`。已在 `ResearchSource` 的数据库文本属性赋值时去除 NUL，保留其余 Unicode / 换行和对象存储的原始文本。真实 PostgreSQL 的插入、重读、更新回归验证通过，测试事务已回滚，未留下测试行。结果：`work/nul-storage-check.json`。修复在本轮研究结束后重启服务生效，避免再次中断采集。
11. 清洗事实 JSON 内引用来源的代码块触发 `_plain_json` 的优先 Markdown 正则，导致有效 JSON 解析为 None。690 条事实原本仅作为一个兜底长文本向量入库。现改为先解析完整 JSON，再尝试外层代码块；实际 3.58 MB 事实库成功解析为 690 条事实。新增两条回归测试通过。已备份并替换本次项目的错误单条向量，重新写入 690 条、同步 BM25 统计、更新产物 metadata，实际公司事实混合检索命中 5 条。记录：`work/fact-vector-rebuild.json`，不涉及其他项目向量。
12. 原下载验证脚本只判断 completed / 两份 Word，会把待复核稿误计为交付通过。现在分别记录功能链路和交付质量，并只检查每种成果的最新版本。页面成果列表也显示“待复核稿”和复核提示。

所有修复已在研究结束后重启服务生效。重启后使用真实 HTTP API 验证了含 NUL 的手工来源可以保存为合法数据库文本，并清理本次临时项目；原公司项目仍为 1 个、462 条来源、10 个产物。最终连通性检查（包括既有 Word 报告下载）为 **0 failed checks**。结果：`work/nul-api-check.json`、`work/connectivity-final.log`。后台服务保持运行。

修复后的最终 API 详情另存于本轮 `detail.final.json`（事实向量 metadata 为 690）；原 `detail.json` 保留作为重建前的记录。最后再次 `git fetch origin`，`main` 仍为 `0 0`；本次修复未提交或推送。

## 测试与待处理问题

选取了策略、搜索过滤、身份提取、实体候选、Word 结构、人物报告、姓名规范化及证据台账等 117 条现有测试，结果 **111 通过，6 失败**。新增 JSON 解析的两条回归测试通过，合计 **113 通过，6 失败（119 条）**。其中除证据台账文件外的 62 条现有测试全部通过；证据台账文件 49 通过、6 失败，修复解析函数后复测仍为这 6 条失败。原始结果保存在 `work/passing-tests.log`、`work/passing-tests.xml`、`work/evidence-tests.log`、`work/evidence-tests.xml`、`work/parser-regression-tests.log`、`work/parser-regression-tests.xml`。

失败用例均位于 `test/test_evidence_ledger_and_section_packages.py`，保留记录，未修改业务质量闸门：

| 用例 | 观察到的问题 |
| --- | --- |
| `test_person_report_gets_deterministic_audit_index_from_fact_library` | 测试期望旧“审计引用索引”标题，当前生成第 14 章信息来源标题。 |
| `test_industry_report_gets_a_deterministic_ledger_in_chapter_14` | 测试期望旧索引表头，当前索引已经简化。 |
| `test_report_evidence_packages_keep_person_company_and_industry_match_rules_separate` | 人物证据包过滤后为空，与测试期望不同，需要进一步核对身份匹配规则与 fixture。 |
| `test_professional_fields_are_extracted_without_llm_and_keep_person_boundary` | 专业字段测试没有抽取到预期字段，需要核对结构化来源格式与人物边界规则。 |
| `test_company_quality_gate_accepts_sparse_but_fully_traceable_fourteen_chapter_report` | fixture 使用 example.com 占位链接，被现有交付质量闸门拒绝。 |
| `test_report_placeholder_urls_are_removed_before_export` | 占位 URL 已被移除，但替代提示语与测试期望不一致。 |

采集阶段已有一次 `empty_pdf` 警告：外部 PDF 没有提取出正文。搜索也返回部分与目标公司关联弱的结果；最终是否被证据过滤、是否影响交付，须以本次流程最终 trace / 质量诊断为准。

运行期间 Milvus 于 10:59:35 退出（ExitCode 1，OOMKilled false），日志显示 etcd applied index 请求超时和多个组件服务租约失效。etcd 日志也出现请求耗时超过预期。11:02 已重新启动原容器并恢复 healthy，连通性复查通过；没有删除或替换数据。此问题的根因尚未完全确认，需要继续观察长时间运行稳定性。记录：`work/milvus-state.json`、`work/etcd-tail.log`、`work/milvus-recovery.log`。

恢复运行时天眼查 MCP 的 8 次搜索和 4 次工具调用返回 401 / `invalid_token`，接口明确提示普通 OpenAPI Token 不受支持，需要 OAuth 或 MCP API key。本次未更换或猜测凭据。稀牛的企业基本信息、融资、市场行业、团队招聘、风险查询未命中有效数据。工作流通过其他专业来源继续，新增了 7 条结构化来源；这不代表上述两个服务已经可用。

部分既有 cleaning / LLM trace 的 Agent 名称或标签存在乱码；网页已有部分标签修复逻辑，但原始日志仍可见。另有外部网页正文超时、空 PDF / 提取失败警告，流程会保留搜索摘要或跳过缺少内容的来源。完整清单保留在本轮 `events.jsonl`。

页面历史 trace 的心跳条目在项目 completed 后仍可能显示“可能卡住”，因为按当前时间判定历史心跳过期，属于待修复的展示问题；后台项目已完成，最终状态应以 completed 和最终 done 事件为准。最终页面截图：`work/final-project-check.png`。

性能观察：公司采集会自动展开权威检索和补充查询，配置的三个重点模块仍会带来较多来源和模型处理。恢复轮精洗选择了 91 条来源、初始 26 个批次；11:23:24 记录一次 `Request timed out.`，随后 `batch=1, depth=1` 自动二分重试。默认模型超时和重试会显著延长整轮耗时，不能将“后台进程已启动”当作“公司报告已完成”。

本机未发现旧业务数据库，当前 PostgreSQL 是新建数据库；本次没有导入备份中的历史数据库数据。验证结论不涵盖旧项目迁移，也不等于研究报告业务内容已经人工核验。

## 公司知识库前端预览

在 `codex/company` 分支新增“公司知识库”侧边栏入口。资料库包含知识空间、搜索、分类、临时收藏和文档阅读预览；知识问答包含资料范围选择、文档内提问、示例回答及可点击的资料引用。问答页采用紧凑顶部，优先展示对话与输入框。新组件和样式分别保存在 `frontend/company-knowledge.js`、`frontend/company-knowledge.css`，现有页面只增加入口、组件注册和页面标题。

当前六份资料、正文、页数和回答均为示例。现有公司项目的名称只用于展示项目空间，不表示该项目资料已经同步到新知识库。添加资料只保留浏览器内的文件名与大小，不上传或读取文件正文；收藏与对话在离开模块或刷新后重置。尚未接入云端知识库、真实原件阅读、权限过滤、索引状态或真实 RAG 问答。

浏览器验证通过：资料搜索、收藏、阅读目录切换、针对文档提问、Enter 发送、范围传递、回答引用返回阅读页、本地文件选择与移除。原有提交、任务、复核和溯源页面均可正常打开；任务仍显示已完成的公司项目，溯源表仍正常加载，原 AI 小助手在原页面仍可见。本次检查浏览器无 error / warn，两个 JavaScript 文件语法检查与 `git diff --check` 均通过；未重新执行报告生成或后台完整测试。窄屏采用单列知识空间与独立的问答布局，当前视觉验证使用默认桌面视口。

效果图：`work/company-knowledge-preview.png`、`work/company-knowledge-chat-preview.png`。本次未提交或推送代码。

## 公司与行业分支集成检查（2026-10-15）

集成分支为 `codex/integration`，公司侧基于 `ae0a88a`（含知识库提交 `bf78133`），行业侧基于 `109d95d`。本次解决 `.env.example`、`backend/research_workflow.py`、`frontend/index.html`、`scripts/start-local.ps1` 四处合并冲突。

- 配置示例同时保留百炼知识库配置和行业清洗、章节超时配置。
- 公共 JSON 解析优先调用行业侧的完整 JSON / 外层围栏解析器，保留字符串内部代码围栏。公司、人物路径保留原先允许说明文字包围 JSON 代码块的行为；行业模型清洗和风险评分显式采用严格解析，未放宽行业证据或质量检查。
- 报告成果区同时保留公司侧待复核提示，以及行业侧的章节降级、核验问题、Word 文件检查、版式未校验和事实质量信息，避免重复展示待复核标签。
- 启动脚本保留外部健康向量服务复用和后台就绪等待；需要本地 MinIO 时采用行业侧带异常处理的镜像检查，仍校验源码归档哈希。
- 自动合并后的行业前端测试原先没有加载知识库组件；测试现按实际组件注册关系加载并验证，行业参数、续跑和知识库前端回归均通过。
- 搜索归一化测试显式开启它所验证的 `BOCHA_FETCH_ENABLED`，避免本机关闭预抓取的配置污染离线用例；未改生产搜索开关。

离线后端回归共 259 项，254 通过、5 失败。覆盖行业从采集到 Word 的模拟流程、行业范围和评分、公司与人物隔离、JSON 解析、异步索引、知识库鉴权与流式问答等。失败项均可在合并前的公司提交 `ae0a88a` 单独复现：

1. `test_person_report_gets_deterministic_audit_index_from_fact_library`：旧索引标题、提示语预期与当前输出不一致。
2. `test_report_evidence_packages_keep_person_company_and_industry_match_rules_separate`：人物证据过滤结果与 fixture 预期不一致。
3. `test_professional_fields_are_extracted_without_llm_and_keep_person_boundary`：专业字段抽取未命中 fixture 预期。
4. `test_company_quality_gate_accepts_sparse_but_fully_traceable_fourteen_chapter_report`：fixture 中占位链接被现有质量闸门拒绝。
5. `test_report_placeholder_urls_are_removed_before_export`：替代提示语与测试预期不一致。

上述 5 项均位于 `test/test_evidence_ledger_and_section_packages.py`，本次未通过放宽质量规则或修改断言掩盖它们。初次回归另有搜索预抓取测试失败，旧公司提交也能复现，已通过用例配置隔离修复。回归日志：`work/integration-tests.log`、`work/integration-tests.xml`；旧提交对照日志：`work/integration-baseline-tests.log`、`work/integration-baseline-tests.xml`。

前端两组 Node 回归通过：行业参数及组件注册验证、知识库的 3 个引用合并/进度用例。两个前端 JS 通过语法检查，PowerShell 启动脚本通过 AST 语法检查，`git diff --check` 通过。Docker 的 PostgreSQL、Redis、Milvus、MinIO、etcd 当前均 healthy；未额外执行缺镜像重建或首次安装分支。

浏览器使用 `127.0.0.1:8011` 的临时集成服务及独立 SQLite 数据库，仅创建公司、行业兼容示例项目，不写原项目数据库。已检查登录、公司/行业表单切换、行业研究范围和资本开关、公司与行业成果展开、待复核提示、行业事实质量弹窗及公司知识库菜单；知识库真实读取到 5 份云端资料。控制台无 error / warn。截图：`work/integration-industry-form.png`、`work/integration-task-quality.png`、`work/integration-knowledge.png`。本次未运行真实的公司或行业新报告，也未新增云端资料、发起付费模型问答或重建原项目索引。

本次只在集成分支准备冲突修复与验证记录，未执行合并提交、推送或修改 `main`。存在上述基线失败，因此不应将本次结论表述为全库测试通过；正式合入主分支前仍需双方复核，并跟踪原有失败。
