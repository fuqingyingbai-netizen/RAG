# 公司资料恢复完整验收约束（2026-11-04）

持续目标的显示摘要保持原样；工具只支持状态更新，不能改正文。本清单是该持续目标的完整约束，全部完成、核对最终保存内容且推送 main 后才能 complete。测试通过不代表整份尽调报告验收通过。

## 完整目标
在本会话独立 worktree 中兼容最新 origin/main，完整保留公司旧分支 15 个提交和冻结快照成果，逐项完成九类资料流转问题的通用修复。模型判断资料相关性、语义和章节用途；程序负责原文/任务 ID、结构定位、状态保存和可靠恢复，取消公司内容关键词、普通短字段及平台类别造成的误拦。企查查、天眼查、稀牛原始与结构化返回完整入索引，保留字段原值、零值、未知、主体、期间、单位及来源，不把计数/关联关系升级为事实责任。落实无候选模型补读、长文分块覆盖、跨章复用、表格和上下文补读、时间口径区分，保留真实引用校验。按真实失败类别诊断与有界重试，写作/审稿分阶段保存，只补失败步骤；失败不隐藏成功正文，补回证据同步刷新相关章节、摘要、综合结论、评分和引用。研究生产入口实际使用 deepseek-flash、https://api.deepseek.com，凭据只存 gitignored 本地安全配置，严禁输出或提交。核实开源实际 commit/许可证/函数/适配，完成回归、平台回放和可得真实接口验证、冻结海天/金山前后对比及至少一次真实生产入口端到端验证。审查脱敏与共享链路兼容后重新 fetch，并正常快进推送 HEAD:main，不强推、不部署。不以预算、重试次数、测试通过或模型返回替代证据和交付验收。

## 环境和基线
- 自有 worktree：`C:/Users/wangli/.codex/worktrees/company-recovery/RAG`，分支 `codex/company-recovery-20261104`。
- 起点 origin/main：`514f0327a6a14cd442860e1c4ecd23f74e38703c`；15 个旧提交通过非快进合并完整保留。
- 冻结 patch SHA256：`b81218939fab9af9d2338912d95cf4a67731cd05c0738253ee8cbfadb1236672`，18 个新增文件哈希均核实。
- 三处共享文件冲突已逐块合并；保留新版需求附件和正式方案功能。受保护工作区、旧数据库、服务只读；运行状态、对象和数据库独立。
- 初始章节/审稿回归：47 passed，1 failed；旧 stub 已补齐新版 proposal_context 查询边界，真实 SQLite 生产入口另行验证。初期失败记录保留。

## 逐项验收台账
|编号|要求与通过条件|状态|实现位置|验证命令/证据|剩余问题|
|---|---|---|---|---|---|
|1|400/34 入口漏检：词表/名称/长度只定位；零候选模型补读；长文覆盖、跨章缓存；未读不标无关|实现及计划复核完成|company_reading.py / company_model_reading.py / company_corpus.py|frozen-admission-summary.json、两份逐源 ledger、test_company_evidence_recovery.py；真实 source30 分别 30/30、4/4 窗口回执|海天 400/34、金山 497/14 同字节原文均进入计划；没有宣称全库模型重读或全部相关|
|2|25 结构/范围：语义交模型，错列/跨页/缺表头单位期间先补邻文或原页；不猜字段；清楚内容继续|实现与专项验证完成|company_reading_recovery.py / company_page_context.py|recovery-final.xml、reading-format-final.xml、page-ocr-real-smoke.json|真实 OCR 验证为合成留存页面；没有把它当公司原页事实核验，无像素时明确留缺口|
|3|日期：取消发布日期整份拒绝；区分披露/事件/会计期；历史截止标事后披露|实现与日期回归完成|company_time_context.py / source_review / event_evidence / listing_funding / press_releases / reputation|company-research-final.xml、test_company_event_impact_and_dates.py、test_company_evidence_recovery.py|未来事件及未来财务期间仍不支持历史风险评分；URL 日期只是提示|
|4|150 无关：充分阅读及章节/任务范围、理由留存；本章无关不删共享资料|实现与行为验证完成|company_reading.py / company_corpus.py / company_chapter_flow.py|窗口回执、unknown IDs / unreviewed range / cross-chapter reuse 回归及真实保存回读|旧 150 为旧阶段分类，不把“进入计划”写成其全部被推翻|
|5|19 误拦：模型认可不因内容词或编号表示拒绝；合理重路由；冲突只澄清；假原文仍拒|引用校验及真实记录修复完成|company_model_reading.validate_selection / company_reading_recovery.py|*-selection-guard-replay.json、*-real-selection-repairs.json、haitian-legacy-statement-readback.json|海天 19 来源 34 提议中 33 可用、1 撤回；金山 26 来源 31 提议中 29 可用、2 撤回。正文采用另查保存证据|
|6|20 needs_context：列缺字段→文件内补读→必要时原页→再判断；停止原因明确|实现与恢复验证完成|company_reading_recovery.py / question coverage / chapter flow|recovery-final.xml、reading-format-final.xml、*-real-saved-readback.json|文件内上下文穷尽、原页不可得、回执未完分别保存；仍有语义待核时不强行通过|
|7|7633 未完成取舍：真实分类诊断、有界恢复、不截尾；无全库两轮卡点；采用/附件/不采用留存|实现与运输/保存验证完成|company_transport.py / research_workflow.py / company_chapter_placements.py|model-entry-smoke.json、运输回归、实际原始回执及 Word/HTML 回读|旧 7633 不能据旧统一异常推断余额或 HTTP；实际累计调用量单列，不冒充新鲜基线成本|
|8|367 写作审稿：分阶段落盘；相同依赖复用，变化失效；成功保留|实现与中断/续跑验证完成|company_editorial.py / company_flow_state.py / chapter flow|company_editorial_journal、chapter_flow、attribution-final.xml；真实多次续跑记录|回执格式修复只补失败记录；来源语义问题仍交独立审稿，次数上限不等于通过|
|9|组装：成功正文保留；定向修复；关键未完不正式成功；依赖刷新并落入实际保存/导出|工程与最终保存回读完成；报告内容待核|research_workflow._prepare_company_delivery / delivery_contract / corpus_writer|海天 v4/artifact19 的 143 段、金山 v5/artifact25 的 15 段均实际进入 SQLite、对象和 OOXML；HTML 实际下载回读；*-real-saved-readback.json|两份均 review_draft。海天第六章仍有错称年报的已知归因，18 条信息/8 批待审；金山 4 条信息/1 批待审，均保留全文审稿问题，不宣称内容验收通过|
|10|平台专项：完整原始/结构化返回入索引；保留零/未知/主体/口径；真实接口与回放分别验收|实现、完整性回放及可得性探测完成|company_platform.py / source save / model reading|platform-final.xml（18 passed）、platform-real-smoke.json、OPEN_SOURCE.md|QCC 未授权、TYC ReadTimeout、稀牛 quota_exceeded；不能声称三家全部工具在线成功验收|
|11|精确模型生产入口；凭据安全；开源实际源码；共享链路兼容；快进 main 并核实 SHA|工程及最新 main 兼容验证完成；发布只允许正常快进|.env（忽略）/ docs/deliverables / Git|全量快照加较新补测去重 4,945 passed/4 skipped；最新 main 相关 145 项及 17 前端文件、隔离浏览器通过；金山实际生产入口使用当前后端快照；开源源码和脱敏记录齐备|保留初始失败证据，不冒充一次全新全量通过。最终发布按 fetch→祖先检查→普通 HEAD:main 推送→ls-remote 核实执行，远程提交 SHA 以最终核验结果为准；不部署|

## 历史样本口径（不能混算）
海天 artifact143；sources144=1246；corpus145=9363 陈述（9016 原句+347 专用）；usage146=9079 不同记录（9071 可用/8 排除）；editorial147=451 候选、84 信息/122 段通过、367 信息对应38失败批；presentation149=451 主文、987 附件、7633 未完成，对应272失败批（269 proposal/3 review）。旧 CompanyModelUnavailable 不足以推断状态码、余额或真实请求次数。400/34/25/1 与150/20/19是不同阶段分类。旧材料和旧测试只作基线，本轮真实验证证据另记。

## 交付证据
本轮命令、样本前后去向、开源对照、实际调用量/耗时/用量/错误、限制及复现方法保存在 `docs/deliverables/company-recovery-20261104/`。每次更新此台账标明真实状态；未完成不能以计划或旧证据填完成。
