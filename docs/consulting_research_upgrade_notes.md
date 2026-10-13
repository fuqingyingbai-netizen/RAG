# 咨询研究工作流改造说明

本文档记录本次在原有 SuperMew RAG 项目上的功能改造、设计思路、使用方式，以及启动过程中遇到的问题和排查知识点。

## 一、原项目基础能力

原项目已经具备一个比较完整的 RAG 聊天系统：

- FastAPI 后端服务
- 静态 Vue 3 前端页面
- 用户注册、登录、JWT 鉴权
- 管理员上传文档
- 文档解析、分块、向量化
- Milvus 向量库检索
- BM25 稀疏检索
- PostgreSQL 存储用户、会话、消息、父级 chunk
- Redis 缓存会话和文档块
- LangChain Agent 调用工具
- SSE 流式聊天输出

原项目的主要使用方式是：

```text
用户提问
→ Agent 判断是否调用知识库检索工具
→ Milvus/BM25/Rerank 检索
→ Agent 生成回答
→ 前端流式展示
```

这套能力适合“聊天问答式 RAG”，但你的新需求是“咨询项目制研究工作流”，所以本次改造不是重写项目，而是在原系统上新增一条 `/research/*` 业务线。

## 二、新需求目标

你的目标是把项目改造成一个咨询公司的研究工作台，用于：

- 针对某行业大佬、公司或行业做背景调查
- 结合用户上传文件和在线网页信息
- 自动清洗大量脏数据
- 保留来源和证据链
- 形成公司内部知识库
- 多维度风险研判打分
- 自动生成桌面研究报告
- 自动生成项目建议书
- 支持人工介入修改
- 修改后再次生成正式版本
- 报告和建议书入库并可下载

因此我把新功能抽象成：

```text
研究项目
→ 资料收集
→ 在线检索
→ 数据清洗
→ 风险研判
→ 桌面研究报告
→ 项目建议书
→ 人工修订
→ 产物入库和下载
```

## 三、核心设计思路

### 1. 不破坏原聊天 RAG

原聊天功能继续走：

```text
/chat
/chat/stream
/documents/upload
/documents
```

新咨询研究功能新增：

```text
/research/*
```

这样做的好处：

- 原有聊天功能不被大改影响
- 新业务可以独立迭代
- 后续如果咨询研究要做成单独产品，也比较容易拆出去

### 2. 一个模型，多个逻辑 Agent

你问过“模型可以能用一个就用一个，但是可以组装为不同 agent 对吧”。答案是可以。

本次实现里，底层还是使用 `.env` 里的同一个大模型配置：

```env
ARK_API_KEY=...
MODEL=...
BASE_URL=...
```

但是在代码中通过不同 prompt 和不同方法，拆成多个逻辑 Agent：

```text
在线检索 Agent
数据清洗 Agent
风险研判 Agent
桌面研究报告 Agent
项目建议书 Agent
人工修订 Agent
```

它们不是不同模型，而是同一个模型在不同任务上下文里的不同角色。

核心实现位置：

```text
backend/research_workflow.py
```

例如：

- `clean_sources()`：数据清洗 Agent
- `assess_risk()`：风险研判 Agent
- `generate_report()`：桌面研究报告 Agent
- `generate_proposal()`：建议书 Agent
- `revise_artifact()`：人工修订 Agent

### 3. 项目制数据模型

新增了研究项目相关表。

位置：

```text
backend/models.py
```

新增模型：

```text
ResearchProject
ResearchSource
ResearchArtifact
```

含义：

```text
ResearchProject  = 一个咨询研究项目
ResearchSource   = 项目资料来源，包含上传文件、人工补充资料、在线检索资料
ResearchArtifact = 项目产物，包含清洗事实、风险研判、桌面报告、建议书、修订版
```

这样每个咨询项目都有自己的资料池和报告版本。

## 四、本次新增和修改的文件

### 1. 后端新增文件

#### `backend/research_schemas.py`

定义研究功能 API 的 Pydantic 请求/响应模型。

主要包括：

```text
ResearchProjectCreate
ResearchProjectResponse
ResearchSourceCreate
ResearchSourceResponse
ResearchArtifactResponse
ResearchRunRequest
ResearchRunResponse
ResearchRevisionRequest
```

作用：

- 约束前端传参
- 规范后端返回
- 让 `/docs` 自动生成接口文档

#### `backend/research_store.py`

封装研究产物对象存储。

支持两种模式：

```text
local = 默认存到本地 data/research_store
minio = 存到 MinIO
```

配置：

```env
RESEARCH_OBJECT_STORE=minio
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=research
MINIO_SECURE=false
```

注意：

`MINIO_ACCESS_KEY` 和 `MINIO_SECRET_KEY` 不是外部 API Key，而是本地 MinIO 的用户名和密码。

#### `backend/web_search.py`

封装在线检索 Provider。

目前支持：

```text
Tavily
Serper
```

配置 Tavily：

```env
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=你的 Tavily Key
```

配置 Serper：

```env
WEB_SEARCH_PROVIDER=serper
SERPER_API_KEY=你的 Serper Key
```

如果没有配置搜索 Provider，工作流仍然可以跑，但不会新增在线网页来源，只会基于上传资料和人工资料生成。

#### `backend/research_workflow.py`

这是本次最核心的业务工作流文件。

核心流程：

```text
run_project()
  → collect_web_sources()
  → clean_sources()
  → assess_risk()
  → generate_report()
  → generate_proposal()
```

各阶段会把结果保存成 `ResearchArtifact`。

生成的产物包括：

```text
cleaned_facts      清洗事实库
risk_assessment    风险研判
desktop_report     桌面研究报告
proposal           项目建议书
```

另外还支持：

```text
revise_artifact()
```

用于人工修改意见后的再次生成。

#### `backend/research_api.py`

新增研究项目 API。

主要接口：

```text
POST /research/projects
GET  /research/projects
GET  /research/projects/{project_id}

POST /research/projects/{project_id}/upload
POST /research/projects/{project_id}/sources
GET  /research/projects/{project_id}/sources

POST /research/projects/{project_id}/run
GET  /research/projects/{project_id}/artifacts
POST /research/projects/{project_id}/revise

GET  /research/artifacts/{artifact_id}/download
GET  /research/search?q=关键词
```

### 2. 后端修改文件

#### `backend/models.py`

新增三张表对应的 ORM 模型：

```text
ResearchProject
ResearchSource
ResearchArtifact
```

#### `backend/app.py`

挂载新的 research router：

```python
import research_api as research_api_module
app.include_router(research_api_module.router)
```

同时补了一个路径兼容：

```python
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
```

原因是你用下面方式启动时：

```powershell
uv run uvicorn backend.app:app ...
```

Python 会把 `backend.app` 当包导入。原项目里很多模块写的是：

```python
import api
from database import init_db
```

而不是：

```python
from backend import api
```

所以需要把 `backend/` 加进 `sys.path`，否则会报：

```text
ModuleNotFoundError: No module named 'api'
```

#### `pyproject.toml`

新增：

```toml
"minio>=7.2.0"
```

用于 Python 连接 MinIO。

如果启用 MinIO 模式，需要跑：

```powershell
uv sync
```

### 3. 前端修改文件

#### `frontend/index.html`

新增侧边栏入口：

```text
咨询研究
```

新增研究工作台页面，支持：

- 创建研究项目
- 项目列表
- 上传项目资料
- 人工补充资料
- 填写搜索关键词
- 填写重点深挖问题
- 启动研究工作流
- 查看研究产物
- 下载报告
- 输入人工修改意见
- 生成修订版
- 搜索研究知识库

#### `frontend/script.js`

新增前端状态：

```javascript
researchProjects
selectedResearchProject
researchArtifacts
researchSources
researchRunForm
manualSourceForm
revisionForm
```

新增方法：

```javascript
handleResearch()
loadResearchProjects()
createResearchProject()
selectResearchProject()
loadResearchSources()
loadResearchArtifacts()
uploadResearchSource()
addManualResearchSource()
runResearchWorkflow()
reviseResearchArtifact()
searchResearchKnowledge()
downloadArtifact()
```

下载逻辑使用 `authFetch`，因为下载接口需要 Bearer Token。

不能直接：

```javascript
window.open('/research/artifacts/1/download')
```

原因：

浏览器直接打开链接不会自动带上 `Authorization: Bearer xxx`，容易 401。

所以现在改成：

```javascript
fetch → blob → 创建临时 a 标签下载
```

#### `frontend/style.css`

新增研究工作台样式：

```text
.research-panel
.research-layout
.research-card
.research-project-item
.research-artifact
.research-markdown
...
```

风格上保持和原项目兼容，但研究区更偏工作台和后台系统。

## 五、新功能运行流程

登录后进入：

```text
咨询研究
```

推荐操作顺序：

```text
1. 创建研究项目
2. 上传客户资料或行业资料
3. 可选：人工粘贴网页资料/客户补充材料
4. 填写在线检索关键词
5. 填写重点深挖问题
6. 点击运行工作流
7. 查看清洗事实库、风险研判、桌面报告、建议书
8. 下载报告
9. 如需修改，输入人工修改意见并生成修订版
```

## 六、环境变量配置

### 1. Tavily 在线搜索

```env
WEB_SEARCH_PROVIDER=tavily
TAVILY_API_KEY=你的_tavily_key
```

### 2. MinIO 存储

本地开发可以这样：

```env
RESEARCH_OBJECT_STORE=minio
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=research
MINIO_SECURE=false
```

其中：

```text
MINIO_ACCESS_KEY = 本地 MinIO 用户名
MINIO_SECRET_KEY = 本地 MinIO 密码
```

不是第三方 API Key。

### 3. 如果暂时不用 MinIO

可以不配置：

```env
RESEARCH_OBJECT_STORE=minio
```

默认会落本地：

```text
data/research_store/
```

## 七、启动命令

在项目根目录：

```powershell
cd D:\uv\rag_yuyin\RAG
```

启动 Docker 依赖：

```powershell
docker compose up -d
```

同步依赖：

```powershell
uv sync
```

启动后端：

```powershell
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8010
```

访问：

```text
http://127.0.0.1:8010/
```

接口文档：

```text
http://127.0.0.1:8010/docs
```

## 八、本次遇到的问题和解决过程

### 问题 1：8000 端口无法绑定

你一开始运行：

```powershell
uv run uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

报错：

```text
[WinError 10013] 以一种访问权限不允许的方式做了一个访问套接字的尝试。
```

常见原因：

- 端口被占用
- Windows 权限限制
- 防火墙或安全软件拦截
- 使用 `0.0.0.0` 监听所有网卡触发限制

解决方式：

改成本机回环地址和新端口：

```powershell
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8010 --reload
```

知识点：

```text
0.0.0.0 = 监听所有网卡，局域网其他机器也可能访问
127.0.0.1 = 只允许本机访问
```

本地开发一般用：

```text
127.0.0.1
```

更稳。

### 问题 2：访问错端口

后端实际启动在：

```text
http://127.0.0.1:8010
```

但浏览器访问的是：

```text
localhost:8000
```

所以页面显示：

```text
ERR_CONNECTION_REFUSED
```

解决方式：

访问正确地址：

```text
http://127.0.0.1:8010/
```

知识点：

服务在哪个端口启动，就必须访问哪个端口。

### 问题 3：`ModuleNotFoundError: No module named 'api'`

报错：

```text
ModuleNotFoundError: No module named 'api'
```

原因：

你用的是：

```powershell
uv run uvicorn backend.app:app ...
```

此时 Python 以包方式导入：

```text
backend.app
```

但原来的 `backend/app.py` 里写的是：

```python
import api as api_module
```

这要求 Python 的模块搜索路径里直接包含 `backend/`。

解决方式：

在 `backend/app.py` 中加入：

```python
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))
```

这样 `api.py`、`database.py`、`research_api.py` 都能被找到。

### 问题 4：页面一直加载

你后面访问 `8010` 时页面一直转圈。

排查发现：

```text
8010 端口上有多个 uvicorn reload 进程残留
```

现象：

- Uvicorn 显示启动成功
- 浏览器一直等待
- 请求 `/`、`/docs`、`/script.js` 都超时

原因：

使用 `--reload` 时，Uvicorn 会启动：

```text
reloader process
server process
```

如果之前的进程没有正常退出，端口上可能残留多个 Python 进程，导致连接异常。

解决方式：

先按：

```powershell
Ctrl + C
```

如果不行，杀进程：

```powershell
taskkill /PID 33108 /F
taskkill /PID 39124 /F
taskkill /PID 33780 /F
```

然后不带 reload 启动：

```powershell
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8010
```

知识点：

开发时 `--reload` 很方便，但在 Windows 上有时会残留子进程。排查端口可以用：

```powershell
netstat -ano | Select-String ':8010'
```

查看进程：

```powershell
Get-Process -Id 进程ID
```

杀进程：

```powershell
taskkill /PID 进程ID /F
```

### 问题 5：浏览器空白和 CDN/Vue 的区别

如果后端正常返回 HTML，但页面空白，常见原因是：

- Vue CDN 加载失败
- `script.js` 语法错误
- 前端接口 401
- 控制台有 JS 报错

但这次我测试：

```text
http://127.0.0.1:8010/
http://127.0.0.1:8010/docs
http://127.0.0.1:8010/script.js
```

都超时，所以不是单纯前端问题，而是后端请求没有正常返回。

排查思路：

```text
先测 /docs
如果 /docs 也打不开，优先看后端进程和端口
如果 /docs 能打开但首页空白，再看前端控制台
```

## 九、验证命令

后端语法检查：

```powershell
.\.venv\Scripts\python.exe -m compileall -q backend
```

前端 JS 语法检查：

```powershell
node --check frontend\script.js
```

本次修改后，这两个检查都通过。

## 十、当前已实现和未实现的边界

### 已实现

- 研究项目管理
- 上传研究资料
- 人工补充资料
- Tavily/Serper 在线检索适配
- 数据清洗 Agent
- 风险研判 Agent
- 桌面研究报告 Agent
- 建议书 Agent
- 人工修改后再生成
- 研究产物入库
- 研究产物下载
- 简单研究知识库搜索
- MinIO/本地对象存储切换
- 前端研究工作台

### 还可以继续增强

当前是第一版可用闭环，后续建议增强：

1. 把研究产物和清洗事实写入 Milvus，支持真正向量检索
2. 报告下载支持 `.docx` 和 `.pdf`
3. 在线检索增加网页正文抓取和快照保存
4. 风险评分维度可配置
5. 每个 Agent 的运行日志可视化
6. 长任务改为后台队列，避免 HTTP 请求等待太久
7. 报告支持人工段落级编辑
8. 增加项目权限和团队协作
9. 增加搜索来源可信度规则
10. 增加事实引用脚注和来源编号

## 十一、推荐下一步

建议下一步优先做：

```text
报告导出 DOCX/PDF
```

原因：

你的业务场景最终要给客户交付桌面研究报告和建议书，Markdown 适合系统内部存储，但正式交付通常需要 Word 或 PDF。

其次做：

```text
研究产物写入 Milvus
```

这样公司人员就可以真正基于历史项目进行语义检索。

## 十二、实时 Trace 和终端 CLI 演示补充

为了让项目从“点击按钮后等待结果”升级成“过程可展示、架构可讲、能力可拆解”，新增了两类能力：

```text
1. 前端运行工作流实时 Trace
2. 终端 CLI 单 Agent / 全流程演示脚本
```

### 1. 后端 Trace 原理

核心文件：

```text
backend/research_workflow.py
```

新增了统一 Trace 事件函数：

```python
def _emit(emit, stage, agent, label, detail="", **extra):
    ...
```

每个 Agent 阶段都会发出事件，例如：

```text
workflow                 初始化研究工作流
online_search_agent      正在检索关键词
online_search_agent      命中网页，准备归档
data_cleaning_agent      数据清洗 Agent 启动
risk_assessment_agent    风险研判 Agent 启动
desktop_report_agent     桌面研究报告 Agent 启动
proposal_agent           项目建议书 Agent 启动
workflow                 研究工作流完成
```

事件结构：

```json
{
  "type": "trace_step",
  "stage": "web_search",
  "agent": "online_search_agent",
  "label": "正在检索关键词",
  "detail": "某行业大佬 背景调查",
  "status": "running",
  "timestamp": "2026-06-28T..."
}
```

如果命中网页，会带上：

```json
{
  "url": "https://example.com/...",
  "title": "网页标题"
}
```

这样前端和终端都能知道：

```text
当前是哪个 Agent
执行到哪个阶段
正在处理什么 query
命中了哪个网页
有没有进入降级逻辑
哪个 artifact 已经入库
```

### 2. 流式接口

新增接口：

```text
POST /research/projects/{project_id}/run/stream
```

位置：

```text
backend/research_api.py
```

这个接口使用：

```python
StreamingResponse
```

返回 SSE：

```text
data: {"type":"trace_step", ...}

data: {"type":"result", ...}

data: {"type":"done"}
```

为什么要用 SSE：

- 浏览器不用等整个工作流完成
- 后端可以边执行边推送状态
- 前端能实时画时间线
- 和原项目 `/chat/stream` 的思路一致

### 3. 前端实时 Timeline

修改文件：

```text
frontend/script.js
frontend/index.html
frontend/style.css
```

前端新增状态：

```javascript
researchTraceEvents: []
```

运行工作流时调用：

```javascript
runResearchWorkflowStream()
```

它会请求：

```text
/research/projects/{id}/run/stream
```

然后逐条解析 SSE，把事件追加到：

```javascript
researchTraceEvents
```

页面上会显示：

```text
实时执行 Trace
  online_search_agent
    正在检索关键词
    某行业大佬 背景调查

  online_search_agent
    命中网页，准备归档
    https://...

  data_cleaning_agent
    模型清洗完成
```

不同状态有不同视觉标识：

```text
running  蓝色
done     绿色
skipped  灰色
fallback 橙色
```

### 4. 终端 CLI 演示脚本

新增文件：

```text
scripts/research_demo.py
```

这个脚本用于不打开前端，在编辑器终端中演示每个 Agent 的能力。

查看帮助：

```powershell
uv run python scripts/research_demo.py --help
```

演示在线检索 Agent：

```powershell
uv run python scripts/research_demo.py search --query "某行业大佬 背景调查" --limit 5
```

演示数据清洗 Agent：

```powershell
uv run python scripts/research_demo.py clean --project-id 1
```

演示风险研判 Agent：

```powershell
uv run python scripts/research_demo.py risk --project-id 1
```

演示桌面报告 Agent：

```powershell
uv run python scripts/research_demo.py report --project-id 1
```

演示建议书 Agent：

```powershell
uv run python scripts/research_demo.py proposal --project-id 1
```

演示完整工作流：

```powershell
uv run python scripts/research_demo.py full --project-id 1 --query "某行业大佬 背景调查" --focus "是否存在监管处罚或负面舆情"
```

保存单步生成结果：

```powershell
uv run python scripts/research_demo.py risk --project-id 1 --save
```

### 5. CLI 演示价值

这套 CLI 可以用于：

```text
1. 给老板演示某个 Agent 的能力
2. 不依赖前端直接测试后端逻辑
3. 排查 Tavily 搜索是否可用
4. 单独验证数据清洗、风险评分、报告生成
5. 展示多 Agent 工作流不是黑盒
```

比如终端输出会类似：

```text
[RUNNING ] web_search   online_search_agent      正在检索关键词
           detail: 某行业大佬 背景调查

[DONE    ] web_search   online_search_agent      检索返回结果
           detail: query=某行业大佬 背景调查, result_count=5

[RUNNING ] cleaning     data_cleaning_agent      数据清洗 Agent 启动

[DONE    ] risk         risk_assessment_agent    风险研判已入库
```

这比只展示一个前端按钮更适合汇报架构：

```text
不是“点一下生成报告”
而是“可观测、可拆解、可单独验证的咨询研究 Agent 工作流”
```
