# 公司原文恢复与实际验证（2026-11-04）

本目录记录本轮实现和验证。自动测试通过、模型返回、原文进入阅读计划、单个样本跑通，均不等于整份公司尽调验收通过。实际生成报告保留全文审稿、问题覆盖和导出状态；未解决的内容继续作为待复核稿保存。

## 实现与约束

- 新公司流程使用完整本任务原文分块。词表只排序，不以公司名称、普通字段长度、来源类别或发布日期作入口否决。每窗须有阅读回执；未确认窗口定向补读，明确保留未读范围。共享阅读结果改变时，即使原文字节未变，也刷新依赖章节。
- 模型判断章节用途、主体范围与重要性。程序校验任务/来源/窗口 ID、连续原文、偏移、哈希和已保存回执。纯编号表示差异可以规范化；逐字匹配的同源邻文可以纠正窗口定位，但不得进行模糊语义配对或编造原文。
- 缺姓名、单位、期间、表头或指代时，先补同版本邻文，再请求原页。已留存页面图像/PDF 可用实际本地 OCR；结果保留物理页、坐标、图像哈希和置信度。没有像素或不能定位物理页时明确记录缺口。文本模型未看过原图，不声明视觉模型审阅。
- 披露日、事件日、会计期、网页显示时间和 URL 日期提示分别保存。晚发布材料仍可阅读；不得当作历史截至日已知事实，未来事件和未来会计期不进入历史风险结论，资料缺口不自动成为高风险或低风险分数。
- 一个公司模型请求只有一层运输重试，SDK 重试为零。暂时故障有界重试，每步最多三次；认证、权限、余额、配置、上下文超限、输出不完整、格式、暂停和预算分别记录。无 HTTP 响应不猜状态码；预请求阻止不计为已发请求。输出格式问题不打开整个服务的故障熔断。
- 阅读、结构补读、记录修复、问题覆盖、写作草稿、独立审稿与全文审稿分别持久化。正文已通过部分继续保留。主文/附件/不采用由同一次写作提出并独立核对，关键限制和反向证据不能以附件取舍隐藏。
- 补读回执先保存原始返回，再解析。PDF 引文中的真实换行按既有 JSON 解析器保留；语法仍错误时，只对失败窗口做有界回执格式核对。暂停或失败后优先修复已保存回执，不重写成功正文；未知 ID 和无法定位的引文仍拒绝。
- 已接纳正文的全文审稿不因其他批次待核而跳过。来源标题用于文类核对，股东会会议材料不能套写“年报披露”；具体引文问题只定位到对应信息批次。通过审稿的修复及其约束照常保存并续用；原文或期间变化仍使旧回执失效，其他未完成项继续阻止正式交付。
- 平台完整原始返回按任务保存并进入阅读索引，零、null、False、空字段和长表保留。凭据回显脱敏。计数、股权关联、挂牌、计划或募集上限不自动升级为败诉、责任、到账或实际使用。

## 证据怎么读

|证据|说明与边界|
|---|---|
|`frozen-admission-summary.json`、两份 `*-frozen-admission-ledger.json`|只读旧海天/金山数据库，逐来源比较原文哈希及新阅读计划。海天 1,246 来源中 1,093 有原文、43,758 窗口；金山 1,459 来源中 1,242 有原文、40,870 窗口。没有做全库模型重读。|
|`*-selection-guard-replay.json`|旧模型提议在新引用校验上的离线回放，不是正文采纳或事实验证。|
|`*-real-selection-repairs.json`|实际 deepseek-flash 记录修复及用量。海天 19 个来源、34 条旧提议，33 条在真实原文与范围校验下可用，1 条明确撤回；不能把近似公司名称当同一法人。|
|`*-real-saved-readback.json`|实际 ResearchWorkflow、独立 SQLite 和对象存储中的最终保存回读；校验原文偏移、数据库/保存文件一致、通过正文进入实际 Word，以及导出和审稿状态。实际范围为各一个冻结 source30 原件，不是整库尽调完成。|
|`*-legacy-statement-readback.json`|旧误拦原文范围与当前逐字原文、信息 ID、已保存正文的定位链。范围重叠只作定位，不由程序推断结论等价。金山 source30 不在该类冻结误拦提议中，空列表不代表其没有资料。|
|`model-entry-smoke.json`|实际生产公司编辑入口的精确模型 `deepseek-flash`、`https://api.deepseek.com`、SDK 重试为零及实际 token 用量。|
|`platform-real-smoke.json`|真实接口可得性：企查查初始化未授权；天眼查初始化 ReadTimeout，无 HTTP 状态可推断；稀牛一次工具调用返回 quota_exceeded。均为采集缺口，未据此生成公司风险判断。|
|`page-ocr-real-smoke.json`|真实 RapidOCR 引擎读取留存的合成页面像素，9 行转录；不是海天/金山原页事实核验。|
|`kingsoft-word-visual-qa.json`、三张 contact 图片|实际保存的金山待复核稿 v4，经 bundled documents renderer 生成 31 页，逐页缩略检查并抽查第 8/21 页。版式通过不替代正文审稿；长核验表仍较密集。|
|`verification-summary.json` 及其引用 XML|全量快照 4,918 passed／2 failed／4 skipped；修复后公司研究 2,271 项、恢复专项 209 项、阅读格式专项 105 项、格式与 HTML 专项 58 项、归因及组装专项 139 项、平台 18 项分别通过。合并最新 main 后知识库/工作区/指南/公司流程 145 项通过。较新结果去重为 4,945 passed／4 skipped，未观察到剩余失败；这不是一次全新单命令全量通过，也不能把各组数量相加。全部 17 个前端脚本通过。初期失败 XML 保留，不冒充通过。|
|`knowledge-merge-ui.json`、`served-assets.json`|合并 main 5098c1d 后，隔离浏览器实际加载生产页面，验证正文搜索、来源定位、Word 原文匹配、快速归档与移动端无横向溢出；使用合成接口数据，不冒充真实业务接口验收。公司与知识库共 5 组页面资源引用与当前源文件逐字节一致。|
|`privacy-review.json`|扫描当前可提交文件、实际暂存 blob 及基线后合并历史，检查本地凭据、疑似令牌和禁止提交的运行数据路径；仅保存计数与安全路径，不输出凭据。|
|[开源逐函数适配](OPEN_SOURCE.md)|固定 commit、许可证、真实函数、本项目落点和未采用行为；对应源码读取与字节哈希另见 audit/fetch JSON。|

## 复现

使用隔离工作区及 gitignored 本地 `.env`，配置精确模型和凭据。不要覆盖运行服务的配置，不要对原始数据库写入。以下 `<legacy-root>` 指旧成果目录，`<native-root>` 是其中包含 haitian/kingsoft 子目录的 native 目录。

```powershell
python scripts/build-company-assets.py
python -m pytest -q --junitxml=work/regression.xml
Get-ChildItem test/*.cjs | ForEach-Object { node $_.FullName }
python scripts/manual/company_recovery_frozen_census.py --native-root <native-root>
python scripts/manual/company_recovery_reconstruct_proposals.py --legacy-root <legacy-root>
python scripts/manual/company_recovery_selection_repairs.py --cases-root work/replay-native --company haitian --native-root <native-root>
python scripts/manual/company_recovery_page_ocr_smoke.py
python scripts/manual/company_recovery_real_run.py --input-db <native-root>/kingsoft/acceptance.sqlite --source-id 30 --directory recovery-kingsoft-source30
# 同一参数加 --resume 续跑；本任务独立目录中的 request-stop 文件在下一检查点暂停。
python scripts/manual/company_recovery_saved_artifacts.py --directory recovery-kingsoft-source30 --company kingsoft
python scripts/manual/company_recovery_verification_summary.py
```

真实接口脚本是 `company_recovery_platform_smoke.py`，参数见 `--help`。真实调用耗时和额度不稳定；达到额度不会转为验收通过。自动测试禁止外部请求，也不会加载真实向量模型。

## 当前交付边界

真实接口权限、配额或超时未得到成功数据，不能声称三家平台全工具在线验收完成。没有全库重新阅读 2,705 个来源，也没有把旧来源的无关判断全部推翻。摘要、综合评估和风险结论仍服从原文范围与独立审稿；具体待核问题保存在实际结果中。凭据、运行数据库、原始对象和临时日志未提交；运行服务未部署。
