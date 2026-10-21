# 公司知识工作台

员工在本系统完成上传、分类、阅读与提问。百炼承担文档解析（含扫描件 OCR）、切分、索引、检索与模型推理；不重复导入本地 Milvus。本系统保存原件和权限目录，将通过权限校验的片段交给模型生成答案。

## 配置与启动

根目录 `.env` 配置（密钥仅在后端使用，不提交 Git）：

```env
BAILIAN_KNOWLEDGE_API_KEY=your_api_key
BAILIAN_KNOWLEDGE_BASE_URL=https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com
BAILIAN_KNOWLEDGE_AGENT_ID=your_published_chat_agent_id
BAILIAN_KNOWLEDGE_INDEX_ID=your_knowledge_index_id
BAILIAN_KNOWLEDGE_CATEGORY_ID=default
COMPANY_KNOWLEDGE_USERS=employee_username_1,employee_username_2
COMPANY_KNOWLEDGE_OBJECT_STORE=local
COMPANY_KNOWLEDGE_LOCAL_STORE=E:/persistent-data/company-knowledge
COMPANY_KNOWLEDGE_BUCKET=company-knowledge
```

原件默认位于项目 `data/company_knowledge`，通过认证接口读取，不暴露为静态目录。worktree 建议使用持久化绝对路径，避免清理代码时带走资料。可设 `COMPANY_KNOWLEDGE_OBJECT_STORE=minio`，使用现有 `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_SECURE`；原件专用桶由 `COMPANY_KNOWLEDGE_BUCKET` 指定。原件和数据库需同时备份，已有资料时不要直接切换存储配置。

沿用 `scripts/start-local.ps1 -Background` 启动。数据库初始化新增 `company_documents` 表，不修改既有研究表。未完成任务会在重启后恢复扫描。

## 已实现功能

- 表格资料库：按项目、行业、分类、处理状态、复核状态筛选；收藏按当前账号保存在浏览器。
- 批量上传：支持 PDF、DOC/DOCX、XLS/XLSX、PPT/PPTX、TXT/MD、JPG/JPEG/PNG，每个文件最大 32 MiB。Word、PDF、图片使用智能文档解析，其他格式自动选择解析器。
- 同上传者、项目和文件名下，相同内容返回重复提示；不同内容作为新版本保留。旧版本独立展示和授权，也参与检索，比较时需选择对应版本。
- 状态：等待、上传、解析/OCR、建立索引、可检索、失败。浏览器每 6 秒刷新，只有文件状态 FINISH 才视为可检索。
- 原件阅读：本系统上传的 PDF 逐页渲染原件（支持翻页），图片直接预览原件，Office 等展示云端解析片段并提供原件下载。解析文字不保证保留原件版式。历史云端文件的原件入口使用返回的临时链接。
- 全部资料或勾选最多 20 份已完成索引的文件提问；阅读区可围绕原件提问。范围变化开始新对话。
- 上传者和管理员可管理分类、复核状态及可见范围，重试失败任务或删除资料。处理中的资料需等待完成后删除。

## 权限与问答路径

普通账号须由管理员在“账号管理”中开启公司知识库权限，管理员默认有权限。`COMPANY_KNOWLEDGE_USERS` 仅在账号功能首次迁移时导入已有授权，后续以数据库设置为准。文档进一步支持 `members`（知识库授权成员共享）及 `restricted`（上传者、管理员、指定系统账号）。指定账号仍须获得知识库授权。项目/行业用于分类，不等同于项目权限组。详见 [账号管理说明](ACCOUNT_MANAGEMENT.md)。

目录、原件、预览、问答均在后端校验。后端计算可访问的云端文件 ID，传递 `search_filters: [{doc_id: [...]}]` 给百炼检索，再校验每个返回片段的文件 ID 和知识库 ID。提问中明确出现可访问资料的项目或行业完整标签时，先在相应目录范围检索；项目标签无需出现在正文中。检索显式设置 rerank_top_n=20，避免默认只返回五条片段；生成证据先保留不同文件，再限制同文件片段数量，防止大量表格行挤掉其他文件。空范围或无命中直接说明“当前资料中未找到依据”，绝不退回不受限的全库问答。

原云端问答接口没有公开的逐请求文件范围参数，因此采用：受权限约束的云端检索 → 后端校验证据 → 百炼模型流式生成。模型取已发布 Agent 最新数字版本的 `agent_model`，提示词在后端统一管理，保留引用、资料不足、冲突和待复核说明。控制台的其他 Agent 工具规划/策略不参与此路径；只修改控制台提示词不会修改本系统提示词。

仅用户问题用于承接对话，历史助手回答不再作为模型上下文，避免范围变化或权限撤销后带入旧证据。SSE 展示连接、检索、生成及用时，每 3 秒空闲发送心跳；断开时取消生成，不暴露模型内部推理。引用按文件 ID 合并，片段保留独立编号。

历史云端资料首次同步默认共享，管理员可调整权限；带本系统上传标签的未知文件不会被自动归类成共享资料。权限目录必须与云端索引一并保留。百炼管理权限/API Key 持有人仍可访问云端资源，应用权限不替代云账号治理。旧版无范围问答实例应下线后，再上传真实受限资料。

## 任务恢复与删除

保存原件和元信息 → 上传租约 → 预签名 PUT → addFile 注册 → 指定 DATA_CENTER_FILE 和 docIds 提交索引 → 查询每份文件状态。API Key 不发往 OSS，前端不接收密钥、租约或存储路径。

云端文件 ID、任务 ID 分阶段持久化。正常重试复用已注册文件；任务超时则继续查询原任务。数据库租约避免重复领取，启动后每 8 秒扫描可接管任务。注册成功但本地 ID 尚未写回时进程崩溃，仍存在不确定窗口，管理员需核对云端孤立文件，系统不盲目公开未知文件。

删除先从本系统可检索范围移除，再删除指定知识库中的文件和切片；云端失败可再次删除重试。不删除其他知识库或数据中心文件。本系统保留不可再通过 API 访问的原件恢复副本，运维需另行管理保留周期。

## 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /company-knowledge/status | 配置与账号状态 |
| GET | /company-knowledge/my-projects | 按当前账号 ID 统计本人上传的项目与资料 |
| POST | /company-knowledge/documents/{id}/access-requests | 提交受限资料访问申请 |
| GET | /company-knowledge/access-requests/mine | 查看本人申请和审批结果 |
| GET | /company-knowledge/access-requests | 管理员查看权限申请 |
| POST | /company-knowledge/access-requests/{id}/decision | 管理员批准或拒绝，保存处理说明 |
| GET | /company-knowledge/documents | 分页目录，refresh=true 同步云端历史资料 |
| POST | /company-knowledge/uploads | multipart 单文件上传，前端批量逐份提交，返回 202 |
| PATCH | /company-knowledge/documents/{id} | 修改分类、复核与权限 |
| POST | /company-knowledge/documents/{id}/retry | 重试失败任务 |
| DELETE | /company-knowledge/documents/{id} | 移除索引与目录 |
| GET | /company-knowledge/documents/{id}/original | 原件预览，download=true 下载 |
| GET | /company-knowledge/documents/{id}/preview?page=1 | 分页解析片段 |
| GET | /company-knowledge/documents/{id}/page?page=1 | PDF 原件逐页图片，响应头返回总页数 |
| POST | /company-knowledge/chat/stream | SSE，可传 document_ids（本地目录 ID）或 scope=my-projects |

官方参考：[RAG API](https://help.aliyun.com/zh/model-studio/rag-api-overview)、[上传租约](https://help.aliyun.com/zh/model-studio/rag-api-upload-lease)、[注册文件](https://help.aliyun.com/zh/model-studio/rag-api-add-file)、[任务状态](https://help.aliyun.com/zh/model-studio/rag-api-get-sync-job-status)。

## 验证（2026-10-15）

```powershell
$env:PYTHONPATH='backend'
.venv/Scripts/python.exe -m pytest test/test_company_knowledge.py test/test_company_workspace.py -q
node --test test/company-knowledge-ui.test.cjs
```

自动化验证：37 条后端、7 条前端测试通过。覆盖认证、文档权限隔离/撤销、文件大小与格式、版本去重、明确文件导入、上传头不泄密、重试复用文件 ID、检索前过滤及生成前片段校验、空范围不退回全库、删除同步、预览片段、心跳与连接取消。

真实百炼使用自生成 TXT、DOCX、扫描 PDF 验证，三份均完成上传解析索引，原件与片段接口返回 200，问答正确引用测试编号并保留待复核说明。扫描 PDF 正确识别 SCAN-BETA-921。截图和验收输出位于被 Git 排除的 work/knowledge-workbench/；验收内容不作为真实业务结论。


## 2026-10-16 研究工作区界面调整

本轮仅调整公司知识库前端，开发目录为 `company-knowledge-workbench/RAG`，分支为 `codex/company`。

公开参考包括麦肯锡 [Lilli](https://www.mckinsey.com/about-us/new-at-mckinsey-blog/meet-lilli-our-generative-ai-tool)、BCG [Knowledge Navigator 案例](https://www.bcg.com/publications/2025/value-in-automotive-ai)、德勤 [PairD](https://www.deloitte.com/uk/en/about/story/impact/pairing-deloitte-human-insights-with-ai-technology.html)。这些资料能够验证任务导向、检索归纳和来源核查的方向，未提供足够完整的内部产品界面。本轮是结合现有数据能力进行的原创设计，不声称复刻咨询公司的内部系统。

- 研究首页：问题入口、项目资料集合、最新资料、继续阅读与真实知识概览。
- 资料库：分类、项目筛选、更新时间/名称排序、明确的收藏文字。
- 研究问答：保留引用和处理进度，显示实际检索范围；当前筛选范围内最多 20 份可检索文件可直接作为问答范围，显式选择文件优先。
- 阅读：调整正文及核对侧栏的空间分配，继续使用原有真实预览接口。
- 阅读历史仅在本浏览器按账号保存文档 ID；已无权访问或删除的文件不会显示在继续阅读中。首页概览基于当前已加载且有权访问的资料；有更多分页时明确说明统计范围。

验证：15 条前端测试通过，覆盖项目聚合、排序、阅读历史过滤、范围传递和原有筛选/上传状态逻辑。浏览器检查项目到资料列表、原文阅读到单文件问答等操作。


## 2026-10-16 资料分页与固定导航

资料库默认每页 10 条，支持 20/50 条、页码和上一页/下一页。分类、搜索、筛选、排序或每页数量变化会回到第一页；手动刷新和自动轮询保留有效页码，删除导致总页数减少时自动收回到有效页。页码和每页数量按账号在当前浏览器保存。勾选文件可跨页保留，问答范围仍由选择和筛选结果决定。

沿用客户端筛选架构，目录接口分页完整读取有权限的元数据后，再进行筛选、排序及显示分页，避免只筛选第一批 100 份文件。原件和预览内容不随目录批量加载。

桌面宽度大于 960px 时，公司知识库使用视口高度布局。系统侧栏固定，知识分类侧栏独立保留；右侧搜索、筛选、表头和底部分页保持可见，文件行在单独区域滚动。较小屏幕保留流式布局，避免固定区域挤占操作空间。

19 条前端测试通过，新增空列表/末页、筛选重置、页码边界、超过 100 份目录完整读取验证。真实浏览器确认：列表滚至底部时，系统导航、知识分类、搜索筛选、表头及分页栏均仍可见。

## 2026-10-19 我的项目、保密等级与权限审批

研究首页新增“我的项目”统计图，资料库侧栏可仅查看本人上传的资料。新上传写入 owner_user_id，旧资料仅在缺少 ID 时兼容上传者账号名。云端历史导入且无上传者的资料不会自动算成某个员工的项目。这是上传归属，不等同于个人参与职责认定。

可点击“AI 总结我的项目”，或直接提问“总结我做了哪些项目”。后端按登录账号计算归属，不接受客户端指定其他账号 ID。项目、资料数量来自本人目录全量统计；内容总结仍依据已完成索引的片段。无命中时只展示目录统计，不编造成果。回答中的 Markdown 表格渲染为可读表格，单元格用文本绑定，不执行文档 HTML。

保密等级为 internal（内部）、confidential（敏感）、secret（机密）。敏感和机密文件在上传/修改时都由后端强制 restricted，仅上传者、管理员及已授权成员能读取。旧资料保持原可见范围，保密等级初始为内部；管理员应按实际内容调整。当前等级设置在文件级，同项目文件可以有不同等级。

已获知识库资格的普通账号可看到受限资料的基础目录（标题、项目、等级）并申请权限，看不到原件、解析文本、云端 ID 或成员名单。管理员顶部“权限审批”每 6 秒刷新待审数量，可批准或拒绝，拒绝后可重新申请。审批结果保存在 company_access_requests；批准后读取、下载和后续问答同时生效。新注册账号仍须由管理员在“账号管理”中授予公司知识库权限；COMPANY_KNOWLEDGE_USERS 仅用于首次迁移已有授权。

启动时以可重复执行的加列操作升级既有目录，新增 owner_user_id、confidentiality 和申请表。数据库与原件路径保持沿用。

本轮自动化验证：42 项后端测试、22 项前端测试通过；覆盖个人归属、自然语言项目总结、强制保密、申请/审批、普通员工越权拦截及原有索引、预览、对话流程。

真实验收：管理员和 kb_employee_test 两个独立浏览器会话均通过登录页进入；管理员上传机密 TXT，普通员工申请，管理员先拒绝再批准重新申请，验证授权前后的预览、下载和真实百炼问答。员工上传另一份项目资料，项目统计和 AI 总结表格仅包含本人归属，无浏览器运行错误。合成验收资料已通过删除接口移除；结果和截图保存于忽略提交的 work/knowledge-workbench/。

## 研究会话记忆（2026-10-21）

知识库新增按账号保存的研究会话、历史恢复、追问补全与长对话任务摘要。每轮重新校验资料权限并检索；失效历史与旧引用不能作为新答案的依据。完整机制、边界和验证入口见 [研究会话记忆说明](COMPANY_KNOWLEDGE_MEMORY.md)。
