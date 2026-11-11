# 企业知识库问答质量与文件导出

本轮范围为质量评测、常规检索与证据组织、基于回答的文件导出。不引入 GraphRAG、Agentic RAG 或新的模型服务。沿用百炼检索与现有回答模型。

## 证据组织

`company_retrieval.select_evidence` 在服务端权限过滤后，对完整片段去重。普通问题最多24个片段、48000字符；跨对象比较和汇总最多48个片段、80000字符。先为命中的不同文件保留位置，再补充片段。普通多文件问题保留每文件4片段的抗挤占规则；汇总问题取消该固定配额。

长片段保留与问题相关的连续窗口，并记录片段内起止位置、原片段长度及证据指纹。起止位置属于云端解析片段，不冒充原件页码。没有真实页码时不编造页码。云端查询按每100个文件分批，最多3批并发；任一批失败均报错，不将部分批次误报为完整检索。

简单事实问题要求直接回答所问，避免把相邻主题、人物或期间合并归因。文件名日期不能当作访谈、事件或指标日期；仅保留原文明确与当前事实绑定的时间。生成内容出现不存在的引用编号时，该轮不会标为完成或开放文件导出。

完整性优先于默认三句限制。定位、模式和客群问题保留原文明确的收费方式、服务方式、用户特征与使用门槛；比较表格逐对象核对，避免用宽泛的 B/C 端标签替代具体事实。模型上下文使用 JSON 数组，一个 `citation` 只绑定同对象的 `text`。提示要求直接引语和关键结论逐句核对所标片段，不能用同文件其他片段代替来源。这仍是生成约束，不保证模型始终标对引用。

`evidence_scope` 流事件向使用者说明回答只依据本轮召回内容。任何路径均不声称已经通读全文或完成全量统计。已有的目录项目统计仍使用服务端目录数据；文档内容的穷尽性分析需另行完整遍历。

## 可复跑的真实评测

```powershell
python scripts/manual/evaluate_company_knowledge.py --corpus private-corpus.json --dataset private-gold.json --output-dir private-results --concurrency 3
```

评测脚本只读现有知识库，不上传文档、不写业务表。原文、题目与结果保存在私有目录，不提交到Git、静态网站或外部追踪平台。评测调用既有检索与模型服务，会产生调用费用。

原件集合为JSON数组，每项包含 `id, cloud_id, title, format, version, sha256, project, index_id, parts`，`parts`为含`text`和可选`page`的数组。金标准题目为数组，每项包括：

```json
{
  "id": "Q001", "group": "fact-001", "split": "development",
  "category": "single_fact", "question": "问题",
  "expected_answer": "必要答案要点", "scope_ids": ["local-document-id"],
  "unanswerable": false,
  "evidence": [{"document_id":"local-document-id", "quote":"原文引句", "source_sha256":"原件哈希", "page":3}]
}
```

原文引句及哈希必须通过校验。同一事实的改写题必须在同一开发/验收分组。无答案题不虚构召回率。候选召回、最终上下文召回、引用编号有效性、自动事实核对、完整性、忠实度、引用支持程度分别记录。模型评分使用独立调用，保留逐题理由，不等同于人工审核。

同一次成对运行共享云端召回结果，比较旧12片段选择策略与新证据组织。生成提示保持相同，以隔离证据选择的影响；这不是旧线上系统与新系统全部差异的A/B测试。输出 `ragas-input.jsonl` 可供Ragas进一步评测；不新增生产运行时依赖。

定位生成问题后，可使用`--policies optimized --replay-from first-run-results`重放已录制的候选证据，同时重新调用真实回答模型和评分模型。每个候选指纹必须能在原始解析快照中找到，避免边改检索边比较提示。所有题目绑定启动时固定的生成/选择代码哈希及模型配置；验收报告拒绝混入其他生成版本。`--case-id Q001`仅重试指定题目，不覆盖全量摘要；原失败记录保留。

如果评测期间合并已发布的部门管理接口，可向报告提供`--generation-reference`冻结的被测模块。报告只允许部门选择、上传和元数据相关五个定义变化，并用AST确认问答、证据组织、权限范围准备、导入、全局常量及其他定义未变，且没有受保护函数调用改动接口；任意提示变化或新全局语句均拒绝验收。报告保留被测模块与候选模块的两个哈希，部门集成接口另做软件回归。

`rescore_company_knowledge.py`可在不重新调用模型的情况下，重算原文证据指标；会保留旧指标，并校验每个已记录候选ID。云端表格里的HTML换行标记不应被误判为原文遗漏。`report_company_knowledge_quality.py`生成私有HTML/JSON报告，分别展示最终得分、生成重试、评分重试和参考条目修订。经过验收反馈后再次运行的保留题属于回归，不能冒称未见问题的泛化测试。

验收需同时满足：软件回归通过、导出实际可用、引用编号无越界、无答案和范围限制题不编造，以及保留题的事实/依据表现不退化。所有调用失败单独保留，不能删掉失败样本后宣称全通过。评测分数只代表所测资料与题目，不能外推全部知识库。

## 原生 Ragas 基线与回答修复

Ragas 在独立评测虚拟环境安装，不加入生产依赖。`requirements-ragas.txt` 固定 Ragas 0.4.3 和已验证兼容的 LangChain 版本。

```powershell
python -m pip install -r scripts/manual/requirements-ragas.txt
python scripts/manual/evaluate_company_knowledge.py --corpus private-corpus.json --dataset private-gold.json --output-dir private-answers --policies optimized --answers-only --replay-from first-run-results --concurrency 1
python scripts/manual/evaluate_company_ragas.py --answers private-answers.json --output private-ragas --cache private-ragas-cache --concurrency 3
python scripts/manual/report_company_ragas.py --root private-paired-run --output private-acceptance
```

`private-answers.json` 是按固定金标准顺序排列的逐题记录数组，包含 `id, split, question, expected_answer, answer, references, unanswerable`。引用保留原始 `id` 与 `text`；无答案标记从冻结题集获取，不能靠回答是否拒答推定。调用模型通过 `RAG_EVAL_MODEL / RAG_EVAL_BASE_URL / RAG_EVAL_API_KEY / RAG_EVAL_MODEL_OPTIONS` 环境变量注入，仅沿用已批准的服务。评测禁用外部追踪。逐次请求、响应及原始资料只保留在受限私有目录，不打印密钥、不提交 Git。

原生指标为 ContextRecall（参考事实是否已召回）、Faithfulness（回答事实是否有片段支持）、FactualCorrectness 的 F1 和 recall 模式（与参考必要事实核对）。均为 0–1 分，不等于题目通过率或人工准确率。参考之外但有原文支持的补充，也可能降低事实 F1。90 道有答案题计算这些指标，10 道无答案题单独复核拒答和边界，不能把它们强行记成满分召回。

引用专项探针使用原生 Faithfulness，但只输入回答实际标注的片段；同文件未引用片段不能补证。它仍不是逐句引用准确率，已知问题需结合原文逐句复核。正确拒答且未引用的题记为不适用，不能记成满分。

每次运行锁定完整输入、模型选项、库版本与脚本哈希，逐指标保存检查点。`--retry-errors` 只重试调用/格式错误，保留历史；不得因为事实分数低而反复生成再挑高分。前后对照必须固定题目、参考和全部证据。基线可使用已保存的真实回答，但须证明当前生成逻辑、原模型配置与记录一致，并在报告明确标注其来源。保留题一旦用于定位修复，后续结果属于回归评测。

本轮只更新 main。评测脚本在独立进程调用模型，不重启服务、不切换线上版本。

## 文件导出

`POST /company-knowledge/conversations/{session_id}/messages/{message_id}/export`

请求为 `{"format":"xlsx|docx|png","table_index":0,"value_column":1}`，后二项用于选择表格和图表指标。只接受服务器已保存的完整助手回答，不接受客户端上传答案、任意脚本、文件路径或下载URL。

- Word导出回答及原文依据。宽表展开为记录，避免挤成不可读的窄列。
- Excel每次导出所选表格，同时附原文依据、版本、页码（确实存在时）和证据编号；缺失项原样保留。任何以公式开头的模型文字都作为文本保存。
- PNG以同一表格的同单位数值列绘图。每条数据需要有效行引用，数值须在对应原文中出现；此检查不声称已证明对象和统计口径。计算结果尚未具备逐项计算依据时拒绝绘图，不编造来源。
- PNG最多30条有数值记录，不截断。表格最多1000行、30列；过大时要求缩小范围。
- 文件标注下载账号、北京时间和追踪编号。下载前后重查会话归属、原件版本、当前权限及保存内容；撤权、删除或更新后要求重新提问。返回`Cache-Control: no-store`并记录`answer.export`审计。
- 浏览器离开会话或切换账号时，不触发迟到文件下载。

## 验证

后端测试覆盖证据丢失、长片段尾部定位、范围与索引过滤、评分分母、版本变更、账号隔离、导出中撤权、缺失行引用、混合单位和公式注入。前端测试覆盖迟到文件与账号切换；浏览器走完整提问、保存、三种下载及刷新历史流程。

运行隔离测试前显式设置一次性`DATABASE_URL`并禁用`.env`自动加载，避免后台任务接触生产数据库。文件质量验收包含重新读取XLSX/DOCX、渲染表格与Word、检查桌面和手机布局。
