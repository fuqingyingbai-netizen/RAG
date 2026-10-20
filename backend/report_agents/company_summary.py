"""Company chapter one: complete, balanced source cards and a bounded summary.

The workbook's company sheet A2:B2 defines the five blocks below. Its C2 is
empty; assertions from other chapters' few-shots are not evidence for a summary.
This module deliberately does not change person or industry report selection.
"""

import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from .report_prompts import _company_fact_has_trusted_target_anchor


SUMMARY_HEADINGS = ("报告概述", "核心发现点", "需关注信号", "公司所属赛道竞争格局", "总体评估")
SUMMARY_TOPICS = {
    "identity": ("企业名称", "注册资本", "法定代表人", "成立日期", "成立时间", "统一社会信用", "登记状态"),
    "business": ("主营业务", "主要业务", "汽车业务", "汽车相关产品", "刀片电池", "混动", "产品线"),
    "financial": ("营业额", "营业收入", "收入", "净利润", "经营活动产生的现金流", "研发投入", "研发费用"),
    "governance": ("股东", "持股", "董事长", "总裁", "独立董事", "员工持股"),
    "risk": ("裁判文书", "行政处罚", "诉讼", "被执行", "风险扫描", "未决案件"),
    "competition": ("市场份额", "市占率", "竞争格局", "竞争对手", "占有率"),
    "funding": ("募集净额", "所得款项净额", "完成配售"),
}
NO_HIT = re.compile(r"未(?:发现|查询到|检索到|找到).{0,18}(?:记录|信息)|无历史遗留违规|未命中|暂无数据")
PROCESS_NOISE = ("用户查询", "若你需要", "如需更", "请告知", "待核验", "无法确认", "未提供", "未披露")
EVIDENCE_ID = re.compile(r"\bE-[A-Z0-9-]{6,}\b", re.I)
NATIONAL_DATA = re.compile(r"(?:中国|全国|我国)(?:新能源)?汽车(?:全年)?(?:出口|销量)|中国汽车出口")
BOILERPLATE = ("联系人和联系方式", "传真", "电子信箱", "报告期优先股利润分配", "□适用", "适用", "☑适用")


def _get(value: Any, key: str, default: Any = "") -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _topic(text: str) -> str:
    if "员工持股" in text or "股权激励" in text:
        return "governance"
    scores = {name: sum(word in text for word in words) for name, words in SUMMARY_TOPICS.items()}
    # Concrete financial amounts should not lose to an incidental business word.
    if scores["financial"]:
        return "financial"
    return max(scores, key=scores.get) if max(scores.values()) else "other"


def _period(title: str, content: str, fallback: str = "") -> str:
    match = re.search(r"20\d{2}年(?:半年度|年度)(?:报告)?", _compact(title + " " + content[:1800]))
    return match.group(0) if match else str(fallback or "")[:30]


def _structured_claims(content: str, tool: str, target: str) -> list[tuple[str, str]]:
    """Read actual field/row boundaries, rather than a platform's evaluation."""
    result: list[tuple[str, str]] = []
    registration: dict[str, str] = {}
    for line in content.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or any(NO_HIT.search(cell) for cell in cells):
            continue
        if all(re.fullmatch(r"[-: ]*", cell) for cell in cells):
            continue
        if cells[0] in {"字段", "股东名称", "持股比例", "姓名", "股东", "摘要", "搜索结果", "提示"}:
            continue
        if tool == "get_shareholder_info" and len(cells) >= 3 and re.search(r"\d.*%", cells[1]):
            result.append((f"{target}股东记录：{cells[0]}，持股比例{cells[1]}，持股数{cells[2]}股。", "governance"))
        elif tool == "get_key_personnel" and len(cells) >= 4 and cells[1] not in {"姓名", "名称"}:
            result.append((f"{target}主要人员记录：{cells[1]}，源表职务{cells[3]}。", "governance"))
        elif tool == "get_company_risk_scan" and len(cells) >= 3 and cells[0] in {"裁判文书", "立案信息", "开庭公告", "行政处罚"} and cells[1].isdigit() and int(cells[1]) > 0:
            result.append((f"{target}在本次平台风险扫描中，{cells[0]}返回{cells[1]}条记录。", "risk"))
        elif len(cells) == 2 and cells[0] in {"企业名称", "公司名称", "法定代表人", "注册资本", "成立日期", "成立时间", "统一社会信用代码", "登记状态", "经营范围"}:
            if tool == "get_company_registration_info" and cells[0] in {"法定代表人", "注册资本", "成立日期", "成立时间", "登记状态"}:
                registration[cells[0]] = cells[1]
            elif cells[0] not in {"企业名称", "公司名称", "统一社会信用代码", "经营范围"}:
                result.append((f"{target}：{cells[0]}为{cells[1]}。", "business" if cells[0] == "经营范围" else "identity"))
    if registration:
        result.insert(0, (target + "：" + "，".join(k + "为" + v for k, v in registration.items()) + "。", "identity"))
    return result


def _source_sentences(content: str) -> list[str]:
    content = re.sub(r"--- PDF page \d+ ---", " ", content)
    # Keep sentence/paragraph boundaries and original amounts intact.
    paragraphs = re.split(r"\n\s*\n|(?<=[。！？；])\s*", content)
    return [re.sub(r"\s+", " ", p).strip(" #-\t") for p in paragraphs]


def _disclosure_financial_claims(content: str, period: str) -> list[str]:
    """Use explicit current/prior columns, never OCR or guess a flattened table."""
    results = []
    columns: tuple[int, int, int | None] | None = None
    for line in content.splitlines():
        if not line.strip().startswith("|"):
            if line.strip():
                columns = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        labels = [_compact(c) for c in cells]
        current = next((i for i,c in enumerate(labels) if c in {"本报告期", "本期", "本年度"}), None)
        prior = next((i for i,c in enumerate(labels) if c in {"上年同期", "上期", "上年度"}), None)
        if current is not None and prior is not None:
            change = next((i for i,c in enumerate(labels) if "增减" in c or "同比" in c), None)
            columns = (current, prior, change)
            continue
        if columns is None or len(cells) != 4:
            continue
        if not re.fullmatch(r"(?:营业收入|归属于上市公司股东的净利润|经营活动产生的现金流量净额)[（(]元[）)]", cells[0]):
            continue
        current, prior, change_index = columns
        if max(current, prior, change_index or 0) >= len(cells) or not all(re.fullmatch(r"[\d,]+(?:\.\d+)?", cells[i]) for i in (current, prior)):
            continue
        name = re.sub(r"[（(]元[）)]", "", cells[0])
        change = f"，同比{cells[change_index]}" if change_index is not None and re.fullmatch(r"[-+]?\d+(?:\.\d+)?%", cells[change_index]) else ""
        results.append(f"本集团{period}：{name}为{cells[current]}元，上年同期为{cells[prior]}元{change}。")
        if len(results) == 3:
            break
    return results


def _chapter_summary_cards(packages: dict[str, Any]) -> list[dict[str, Any]]:
    """Use admitted fields, not chapter prose, to synchronize the summary."""
    result = []
    assessment = packages.get('assessment') or {}
    financial = [r for r in assessment.get('financial_observations', [])
                 if r.get('cutoff') and r.get('unit') and not r.get('printed_yoy_conflict')]
    latest = max((r['cutoff'] for r in financial), default='')
    for r in financial:
        if r['cutoff'] != latest:
            continue
        change = '，同比' + r['yoy'] if r.get('yoy') else ''
        result.append({**r, 'summary_topic': 'financial',
                       'fact': f"本集团{r['period']}：{r['metric']}为{r['value']}{r['unit']}{change}。"})
    for dimension in assessment.get('dimensions', []):
        if dimension.get('id') == 'funding':
            for r in dimension.get('records', []):
                if r.get('original_quote_verified'):
                    result.append({**r, 'summary_topic': 'funding'})
    for signal in assessment.get('risk_signals', []):
        r = signal.get('fact_record') or {}
        if r.get('kind') == 'recall' and r.get('recall_number') and r.get('defect_quote'):
            result.append({**r, 'summary_topic': 'risk',
                           'fact': f"{r.get('publication_date') or r.get('effective_date')}，主管部门公告{r['entity']}召回事项，编号{r['recall_number']}：{r['defect_quote']}"})
            break
    benchmarks = [r for r in (packages.get('reputation') or {}).get('facts', []) if r.get('kind') == 'benchmark']
    target = next((r for r in benchmarks if r.get('target_row')), None)
    if target:
        peers = [r for r in benchmarks if not r.get('target_row') and all(
            r.get(k) == target.get(k) for k in ('metric', 'period', 'unit', 'basis', 'source_url'))]
        for r in [target] + peers[:1]:
            result.append({**r, 'summary_topic': 'competition', 'evidence_scope': 'industry_context',
                           'fact': f"{r['period']}，{r['entity']}的{r['metric']}为{r['value']}；统计口径：{r['basis']}。"})
    return result


def build_company_summary_package(
    cleaned: dict[str, Any], target: str, sources: list[Any] | None = None,
    *, limit: int = 12500, max_facts: int = 18, chapter_packages: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recover concise original claims; never slice a serialized fact package."""
    source_by_url = {str(_get(s, "url")): s for s in sources or []}
    candidates: list[dict[str, Any]] = []
    observations: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    raw_processed: set[str] = set()

    def add(fact: dict[str, Any], text: str, topic: str, *, raw: bool = False, period: str = "", verified: bool = False) -> None:
        text = re.sub(r"\s+", " ", text).strip()
        if topic not in SUMMARY_TOPICS or not 10 <= len(text) <= 650 or NATIONAL_DATA.search(text) or any(x in text for x in PROCESS_NOISE) or re.search(r"(?:的企业名称|：企业名称)为", text):
            counts["unsuitable_claim"] += 1
            return
        key = (str(fact.get("source_url") or ""), _compact(text))
        if key in seen:
            counts["duplicate_claim"] += 1
            return
        seen.add(key)
        original_source = source_by_url.get(str(fact.get("source_url") or ""))
        is_disclosure = raw and original_source is not None and re.search(
            r"(?:年度|半年度)报告", _compact(str(_get(original_source, "content"))[:1000])
        )
        structured_governance = topic == 'governance' and str(fact.get('source_url') or '').startswith('structured://')
        if structured_governance:
            text = '平台本次返回的登记记录（数据基准日未载）：' + text
        candidates.append({
            "evidence_id": fact["evidence_id"], "fact": text,
            "evidence_quote": text, "source_title": str(fact.get("source_title") or "")[:150],
            "source_url": str(fact.get("source_url") or ""),
            "evidence_scope": fact.get('evidence_scope') or "target_direct", "summary_topic": topic,
            "period": period or str(fact.get("date") or "")[:30],
            "source_grade": str(fact.get("source_grade") or ""),
            "source_kind": "checked_chapter_field" if verified else "disclosure" if is_disclosure else "other",
            "claim_type": "original_source_claim" if raw else str(fact.get("claim_type") or "fact"),
            "temporal_basis": 'undated_platform_snapshot' if structured_governance else 'source_period',
        })

    for fact in _chapter_summary_cards(chapter_packages or {}):
        if EVIDENCE_ID.fullmatch(str(fact.get('evidence_id') or '')):
            add(fact, fact['fact'], fact['summary_topic'], period=str(fact.get('period') or ''), verified=True)

    for fact in cleaned.get("facts") or []:
        if not isinstance(fact, dict) or not EVIDENCE_ID.fullmatch(str(fact.get("evidence_id") or "")):
            counts["invalid_card"] += 1
            continue
        if str(fact.get("evidence_scope") or "") not in {"", "target_direct"} or not _company_fact_has_trusted_target_anchor(fact, target):
            counts["out_of_scope"] += 1
            continue
        source = source_by_url.get(str(fact.get("source_url") or ""))
        meta = (_get(source, "source_metadata", {}) or {}) if source is not None else {}
        if meta.get("entity_validation") == "rejected":
            counts["rejected_source"] += 1
            continue
        raw = str(_get(source, "content") or "") if source is not None else ""
        title = str(fact.get("source_title") or "")
        url = str(fact.get("source_url") or "")
        is_structured = url.startswith("structured://") or bool(fact.get("is_structured_evidence"))
        if is_structured and NO_HIT.search(raw or str(fact.get("fact") or "")):
            observations.append({"source_title": title, "status": "no_record_in_returned_query", "boundary": "平台本次返回未命中，不证明不存在风险。"})
            if is_structured:
                continue
        # Once per source, use the original body instead of summary+body[:1600].
        if raw and url not in raw_processed:
            raw_processed.add(url)
            period = _period(title, raw, fact.get("date", ""))
            if is_structured:
                period = period or ("查询日期" + str(_get(source, "created_at"))[:10] if _get(source, "created_at") else "")
                entity = re.search(r"(?:企业名称|公司名称)\s*[|：:]\s*([^|\n]+)", raw)
                if not entity or _compact(entity.group(1)) != _compact(target):
                    counts["structured_entity_unconfirmed"] += 1
                    continue
                for text, topic in _structured_claims(raw, str(meta.get("tool") or ""), target):
                    add(fact, text, topic, raw=True, period=period)
            else:
                sentences = _source_sentences(raw)
                by_topic: Counter[str] = Counter()
                filing = bool(re.search(r"(?:年度|半年度)报告", _compact(title + raw[:1000])))
                if filing:
                    for claim in _disclosure_financial_claims(raw, period):
                        add(fact, claim, "financial", raw=True, period=period)
                    business = re.search(r"(?:本集团|本公司)主要从事[^。]{20,450}。", raw)
                    if business:
                        add(fact, business[0], "business", raw=True, period=period)
                for sentence in sentences:
                    if len(sentence) < 25 or "|" in sentence or "http" in sentence:
                        continue
                    if any(marker in sentence for marker in BOILERPLATE):
                        continue
                    if len(re.findall(r"第[一二三四五六七八九十]+节", sentence)) > 1 or "目录和释义" in sentence:
                        continue
                    topic = _topic(sentence)
                    if not any(word in sentence for words in SUMMARY_TOPICS.values() for word in words):
                        continue
                    if by_topic[topic] >= 2:
                        continue
                    if filing and topic not in {"financial", "business", "governance", "risk", "competition"}:
                        continue
                    # A national industry review in a company filing is not a company KPI.
                    if NATIONAL_DATA.search(sentence) or (filing and topic == "financial" and not re.search(r"本集团|本公司|公司|研发投入", sentence)):
                        continue
                    if topic == "financial" and not re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:亿元|百万元|万元|亿美元|万元人民币)", sentence):
                        continue
                    if topic == "competition" and not re.search(r"(?:本集团|本公司|比亚迪|" + re.escape(target) + r").{0,45}(?:市占率|市场份额|占有率)", sentence):
                        continue
                    if topic == "competition" and not re.search(r"\d+(?:\.\d+)?\s*%", sentence):
                        continue
                    if topic == "risk" and not re.search(r"本集团|本公司|发行人|" + re.escape(target), sentence):
                        continue
                    if topic == "risk" and (re.search(r"本案|该诉讼|上述|本公司及部分", sentence) or not re.search(r"20\d{2}|案号|[（(]\d{4}[）)]", sentence)):
                        continue
                    if topic == "governance" and ("证券投资" in sentence or not re.search(r"持股|股权|董事长|总裁|员工持股|审计委员会", sentence)):
                        continue
                    if topic == "business" and not re.search(r"主要包括|涵盖|业务包括|汽车|新能源|生产|销售|制造|开发|推出|收入|销量|平台|服务", sentence):
                        continue
                    before = len(candidates)
                    add(fact, sentence, topic, raw=True, period=period)
                    if len(candidates) > before:
                        by_topic[topic] += 1
        # Atomic cleaned facts retain priority over page-level excerpts.
        if fact.get("claim_type") != "source_excerpt":
            text = str(fact.get("fact") or "")
            add(fact, text, _topic(text), period=str(fact.get("date") or ""))
        elif not raw:
            for sentence in _source_sentences(str(fact.get("evidence_quote") or fact.get("fact") or "")):
                if _compact(target) in _compact(sentence) or ("本集团" in sentence and "报告" in title):
                    add(fact, sentence, _topic(sentence))

    # Prefer original structured/disclosure records and explicit data periods.
    def rank(card: dict[str, Any]) -> tuple[int, int, int]:
        year = re.search(r"20\d{2}", card["period"])
        structured = card["source_url"].startswith("structured://")
        primary = 4 if card['source_kind'] == 'checked_chapter_field' else 3 if structured else 2 if card["source_kind"] == "disclosure" else int(card["source_grade"].startswith("A"))
        concrete = int(bool(re.search(r"(?:营业收入|净利润|现金流量净额).{0,8}为[\d,]+", card["fact"]))) if card["summary_topic"] == "financial" else int(bool(re.search(r"\d+(?:\.\d+)?%", card["fact"])))
        return primary, int(year[0]) if year else 0, concrete

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in sorted(candidates, key=rank, reverse=True):
        buckets[card["summary_topic"]].append(card)
    latest_year = max((int(m[0]) for c in candidates if (m := re.search(r"20\d{2}", c["period"]))), default=0)
    buckets["competition"] = [c for c in buckets["competition"] if not (m := re.search(r"20\d{2}", c["period"])) or int(m[0]) >= latest_year - 2]
    selected: list[dict[str, Any]] = []
    used_text: set[str] = set()
    per_source: Counter[str] = Counter()
    last_source: dict[str, str] = {}
    # Round robin prevents many registration rows from crowding out financials.
    topics = list(SUMMARY_TOPICS)
    quotas = {"identity": 1, "business": 1, "financial": 3, "governance": 3, "risk": 1, "competition": 2, "funding": 1}
    topic_counts: Counter[str] = Counter()
    package: dict[str, Any] = {"facts": [], "query_observations": list({x["source_title"]: x for x in observations}.values())[:3],
                               "evidence_boundary": "仅摘要所需的目标主体原文事实；其他主体或全库未覆盖状态不得由本章推定。"}
    for _ in range(4):
        for topic in topics:
            if topic_counts[topic] >= quotas[topic]:
                continue
            if topic == "governance" and topic in last_source:
                # Keep a second structured platform table from being crowded
                # out by all the shareholder rows from the first table.
                buckets[topic].sort(key=lambda c: c["source_url"] == last_source[topic])
            while buckets[topic]:
                card = buckets[topic].pop(0)
                key = _compact(card["fact"])
                if key in used_text or per_source[card["source_url"]] >= 4:
                    continue
                # Near-identical facts from mirrored annual reports add no coverage.
                if not card["source_url"].startswith("structured://") and any(_numbers(key) == _numbers(text) and SequenceMatcher(None, key, text).ratio() > .9 for text in used_text):
                    continue
                trial = dict(package, facts=selected + [card])
                if len(json.dumps(trial, ensure_ascii=False)) > limit:
                    counts["budget_excluded"] += 1
                    continue
                selected.append(card)
                used_text.add(key)
                per_source[card["source_url"]] += 1
                topic_counts[topic] += 1
                last_source[topic] = card["source_url"]
                break
            if len(selected) >= max_facts:
                break
        if len(selected) >= max_facts:
            break
    package["facts"] = selected
    package["selection_diagnostic"] = {"candidates": len(candidates), "delivered_cards": len(selected), "filters": dict(counts)}
    # Diagnostics are not evidence and must not push the package beyond its budget.
    if len(json.dumps(package, ensure_ascii=False)) > limit:
        package.pop("selection_diagnostic")
    return package


def build_company_summary_prompt(project: Any, package: dict[str, Any], completed_sections: dict[int, str]) -> str:
    delivered = {f["evidence_id"] for f in package["facts"]}
    chapter_map = {
        str(i): sorted(set(EVIDENCE_ID.findall(text)) & delivered)
        for i, text in completed_sections.items() if 2 <= i <= 12
    }
    return f"""请撰写目标公司桌面研究报告第一章，且只输出第一章。
模板来源：工作簿“目标公司桌面研究”A2:B2。该行C2为空；其他章节few-shot只作表达参考，不能借用其中的事实和安全结论。
研究对象：{project.target_name}
研究任务：{project.description or '目标公司的公开资料桌面研究'}
行业：{project.industry or '以已核验资料为准'}

内容结构（稍后由程序排版，不要自行输出Markdown）：
## 1. 摘要
### 报告概述
一段说明主体、业务和本次研究范围。
### 核心发现点
最多4项不同发现，每项一至两句。优先覆盖经营数据、股权/团队、融资或已证实风险。财务发现可在同一项中概括营收、利润与经营现金流的变化。资料不足的方向不要硬凑。
### 需关注信号
最多2项。优先列存在司法记录但影响未知等具体事项的核验动作；不把记录数量或名义持股安排定性为异常。不重复核心发现或罗列所有缺口。
### 公司所属赛道竞争格局
一段概括证据明确支持的市场位置。没有可比口径数据时只写本章未形成可比结论，待核验。不能编竞品能力、排名、毛利或市占率。
### 总体评估
两句以内概括证据支持程度和下一步关键核验，不新增数值或重新列发现，不给信用等级或投资建议。

写作边界：
- 目标650至1000字，硬上限1400字（不计E-ID），不使用表格，不添加额外小标题。
- 每条事实和基于事实的判断就近引用本章提供的[E-ID]。编号可复用，但同一事实只讲一次。
- 数字原样保留币种、单位、年度和统计主体；不得把全国/行业数据写成目标公司指标。
- 原文的“本集团/母公司/子公司”分别保留，不得把关联主体收入归给目标公司，不推定一致行动关系。
- 名义持有人与实际控制人分别表述；HKSCC等名义登记节点不得直接写成实控人，股东排序须注明登记口径。
- HKSCC NOMINEES LIMITED与香港中央结算有限公司必须按平台原文分别保留名称，不合并、不翻译成同一个节点。
- 主要人员表的任期只能按原字段列示，不得推断其所有角色（尤其法定代表人）均在同一天开始任职。
- 摘要不列人员任职起始日，任职历史留给团队章节；法定代表人的依据是工商登记卡，当前董事长/总裁的依据是主要人员卡，涉及两者时要分别引用。
- 只能依据完整事实卡，不凭常识补数据。不得把本章证据没覆盖写成全库未检索到、企业未披露或确认不存在。
- 平台未命中只是查询结果，不是零风险、合规或经营良好的证据。信息缺口不直接评为高风险或低风险。
- 登记存续不能证明经营稳健或持续经营能力；裁判文书数量不能直接判为异常或已证实的风险敞口。
- 不生成BBB+、小数评分、签署TS条件，也不把没有合同/访谈材料说成已经核验。
- 不输出“所有判断均基于证据”“未引入外部常识”等过程说明，不把原始来源清单或图像URL放进摘要。
- 不写本章完整卡条数，不以“只给了这些卡”为由推断全报告没有季度、分部收入或融资材料；总体评估限两句，聚焦已支持的经营变化和需要进一步核验的具体事件。
- 已完成章节只用于查看问题覆盖和引证位置；不得从其正文复制未受本章事实卡支持的判断。

已完成正文的引证分布（不是已完成事实核验的声明）：
{json.dumps(chapter_map, ensure_ascii=False)}

本章完整事实卡（合法JSON，已按完整卡预算，不允许再次截断）：
{json.dumps(package, ensure_ascii=False)}

只返回以下JSON对象，不要输出代码块。五个键必须原样保留，每个条目的text只表达一个意思，evidence_ids只填本章已有编号：
{{"报告概述":{{"text":"研究范围的一至两句，不写底稿或事实卡数量","evidence_ids":[]}},
"核心发现点":[{{"text":"一个已证实发现，带原单位与数据期","evidence_ids":["实际编号"]}}],
"需关注信号":[{{"text":"一个具体核验事项，不把缺口判作风险","evidence_ids":["实际编号"]}}],
"公司所属赛道竞争格局":{{"text":"一至两句，保留客车、乘用车等细分口径","evidence_ids":["实际编号"]}},
"总体评估":{{"text":"两句以内：证据支持的经营变化和下一步核验","evidence_ids":["实际编号"]}}}}
"""


NUMBER = re.compile(r"(?<![A-Za-z\d])(?P<n>[-+]?\d[\d,]*(?:\.\d+)?)(?P<u>\s*(?:万亿|亿|万|百)?(?:美元|港元|人民币|元|人|辆|股)|\s*[%％])?")


def _numbers(text: str) -> set[tuple[Decimal, str]]:
    values = set()
    text = EVIDENCE_ID.sub("", text)
    text = re.sub(r"(?:下降|下滑|减少|降低)\s*(\d+(?:\.\d+)?)\s*[%％]", r"-\1%", text)
    for m in NUMBER.finditer(text):
        unit = _compact(m["u"] or "")
        amount = Decimal(m["n"].replace(",", ""))
        for prefix, scale in (("万亿", "1000000000000"), ("亿", "100000000"), ("万", "10000"), ("百", "100")):
            if unit.startswith(prefix):
                amount *= Decimal(scale)
                unit = unit[len(prefix):]
                break
        values.add((amount, unit.replace("％", "%")))
    return values


def normalize_company_summary(text: str) -> str:
    """Normalize Markdown whitespace, never change a fact to make it pass."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    if text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict) and set(parsed) == set(SUMMARY_HEADINGS):
            lines = ["## 1. 摘要"]
            for heading in SUMMARY_HEADINGS:
                lines += ["", "### " + heading]
                values = parsed[heading] if isinstance(parsed[heading], list) else [parsed[heading]]
                for item in values:
                    if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not isinstance(item.get("evidence_ids"), list):
                        return ""  # schema failure is repaired, never silently omitted
                    inline = re.findall(r"\[(E-[A-Z0-9-]{6,})\]", item["text"], re.I)
                    ids = list(dict.fromkeys(inline + [eid for eid in item["evidence_ids"] if isinstance(eid, str)]))
                    refs = "".join(f"[{eid}]" for eid in ids)
                    content = re.sub(r"\[E-[A-Z0-9-]{6,}\]", "", item["text"], flags=re.I).strip()
                    prefix = "- " if heading in {"核心发现点", "需关注信号"} else ""
                    lines.append(prefix + content + refs)
            text = "\n".join(lines)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def summary_errors(text: str, package: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in package["facts"]:
        by_id[fact["evidence_id"]].append(fact)
    if not text.startswith("## 1. 摘要") or re.findall(r"^### (.+)$", text, re.M) != list(SUMMARY_HEADINGS):
        errors.append("必须保留模板的一个章节标题和五个小标题")
    if re.search(r"^\s*\|", text, re.M):
        errors.append("摘要不得出现表格")
    body = EVIDENCE_ID.sub("", re.sub(r"(?m)^#+.*$", "", text))
    if len(_compact(body)) > 1400:
        errors.append("摘要超过1400字")
    unknown = set(EVIDENCE_ID.findall(text)) - set(by_id)
    if unknown:
        errors.append("未知或未投递的证据编号：" + "、".join(sorted(unknown)))
    if re.search(r"BBB[+-]?|\d(?:\.\d)?\s*/\s*5|零数据即高风险|(?:无|不存在)(?:任何)?(?:行政处罚|诉讼|失信)|无历史遗留违规|暂缓签署TS|全库(?:没有|未检索到)", text, re.I):
        errors.append("包含无依据评级、绝对免责或信息缺口扩大结论")
    if re.search(r"量化异常信号|已验证的司法风险敞口|持续运营法律基础", text):
        errors.append("把登记状态或案件数量扩大为经营能力或风险定性")
    if re.search(r'任期|任职自|自\d{4}年[^。]{0,24}(?:起|至今)',text):
        errors.append('摘要不列任职起始日或至今任期；对应职位与历史变动留在第七章')
    seen: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "HKSCCNOMINEESLIMITED" in _compact(line).upper() and "香港中央结算有限公司" in line and not re.search(r"不同|分别|并非|不是|区分", line):
            errors.append("把HKSCC NOMINEES LIMITED与香港中央结算有限公司混为同一登记节点")
        ids = set(EVIDENCE_ID.findall(line))
        if not ids and not re.search(r"待核验|未形成可比|证据覆盖|本次研究|本报告|本章基于|人工复核", line):
            errors.append("事实段落没有就近引用")
        if not ids and _numbers(line) and not line.startswith(("本报告", "本次研究", "本章基于")):
            errors.append("带数值的判断不能仅用待核验代替来源引用")
        if re.search(r"本章所有|完整事实卡|严格锚定|未引入外部常识|(?:缺乏|未披露|亦无).{0,20}(?:分部|季度|融资活动|业务板块收入)", line):
            errors.append("包含重复过程说明或将摘要材料范围扩大为全库信息缺失")
        if ids and ids <= set(by_id):
            support = " ".join(f["fact"] + " " + f.get("period", "") for eid in ids for f in by_id[eid])
            supported_cards = [f for eid in ids for f in by_id[eid]]
            undated = any(f.get('temporal_basis') == 'undated_platform_snapshot' for f in supported_cards)
            if undated and re.search(r'当前|现任|目前|至今|第一大股东|最大股东',line):
                errors.append('未载数据基准日的平台记录不能写成当前任职或股东排序')
            if undated and re.search(r'持股|股东|职务|董事长|总裁',line) and not re.search(r'平台|源表|登记记录|基准日未载',line):
                errors.append('摘要引用平台股东或人员表时须保留登记记录及未载基准日的边界')
            if _numbers(line) - _numbers(support):
                errors.append("数值、单位或年份未被本段引用原文支持")
            if re.search(r"营收|营业收入|利润|经营.{0,5}现金流", line) and not re.search(r"营业收入|利润|现金流", support):
                errors.append("财务判断引用了不含财务事实的编号：" + line[:90])
            if "法定代表人" in line and "法定代表人" not in support:
                errors.append("法定代表人判断未引用工商登记事实卡：" + line[:90])
            if "法定代表人" in line and re.search(r"任期|自\d{4}年.{0,12}起", line):
                errors.append("不得把主要人员任期起始日同时归给法定代表人角色")
        key = re.sub(r"[\W_]+", "", EVIDENCE_ID.sub("", line))
        if len(key) > 20 and any(_numbers(key) == _numbers(old) and SequenceMatcher(None, key, old).ratio() > .88 for old in seen):
            errors.append("摘要存在重复事实段落")
        seen.append(key)
    return list(dict.fromkeys(errors))


def fallback_company_summary(project: Any, package: dict[str, Any]) -> str:
    """Rebuild all five template blocks from literal, already-budgeted cards.

    This is a complete evidence summary, not an invented narrative or a list of
    failure placeholders. It receives the same validator as a model draft.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fact in package["facts"]:
        groups[fact["summary_topic"]].append(fact)

    def refs(cards):
        return "".join(f"[{eid}]" for eid in dict.fromkeys(f["evidence_id"] for f in cards))

    def literal(fact):
        # A personnel row's term is not the start date of every current role.
        text = re.sub(r"，任期[^。]+", "", fact["fact"]).strip().rstrip("。")
        return text + "。"

    lines = ["## 1. 摘要", "", "### 报告概述", f"本报告围绕{project.target_name}的公司背景、主营业务和公开风险证据开展桌面研究。", "", "### 核心发现点"]
    identity = groups["identity"][:1]
    management = [f for f in groups["governance"] if "主要人员记录" in f["fact"]][:1]
    if identity or management:
        cards = identity + management
        lines.append("- " + "".join(literal(f) for f in cards) + refs(cards))
    if groups["business"]:
        f = groups["business"][0]
        lines.append("- " + literal(f) + refs([f]))
    financial = groups["financial"][:3]
    if financial:
        period = financial[0].get("period", "")
        financial = [f for f in financial if f.get("period", "") == period]
        # Keep the data period once, and keep every original amount and unit.
        claims = [re.sub(r"^本集团[^：]{0,40}：", "", literal(f)).rstrip("。") for f in financial]
        lines.append("- " + (f"{period}，" if period else "") + "；".join(claims) + "。" + refs(financial))
    shareholders = [f for f in groups["governance"] if "股东记录" in f["fact"]][:1]
    if groups['funding']:
        lines.append('- ' + literal(groups['funding'][0]) + refs(groups['funding'][:1]))
    elif shareholders:
        lines.append("- " + literal(shareholders[0]) + refs(shareholders))
    if not any(line.startswith("- ") for line in lines):
        lines.append("本章尚未形成可直接摘录的事实，待核验。")
    lines += ["", "### 需关注信号"]
    if groups["risk"]:
        f = groups["risk"][0]
        followup = ("应追踪整改覆盖、后续状态和实际影响；公告不证明已发生事故或损失。"
                    if f['source_kind'] == 'checked_chapter_field' else "本次仅确认平台返回记录，案件性质、审理状态及实际影响需调取明细核验。")
        lines.append("- " + literal(f) + followup + refs([f]))
    else:
        lines.append("本章尚未形成可直接引用的风险事件明细，相关判断待核验；平台未命中不构成安全结论。")
    lines += ["", "### 公司所属赛道竞争格局"]
    competitors = groups["competition"][:2]
    if competitors:
        for f in competitors:
            period = f.get("period", "")
            lines.append((f"{period}，" if period and not f['fact'].startswith(period) else "") + literal(f) + refs([f]))
        lines.append("统计范围与数据期按各来源分别保留，相关份额不能外推其他市场或整车排名。" + refs(competitors))
    else:
        lines.append("本章未形成统一口径的同业比较结论，待核验。")
    lines += ["", "### 总体评估"]
    if financial:
        lines.append("现有资料可支持经营数据的桌面核对，经营稳健性仍需结合业务分部、回款及资金结构进一步评估。" + refs(financial))
    else:
        lines.append("本章证据覆盖有限，经营判断待核验。")
    if groups["risk"]:
        lines.append("具体风险事项的实际影响及后续处理仍需核验，不能根据记录数量给出风险等级。" + refs(groups["risk"][:1]))
    if not package["facts"]:
        lines.append("综合判断需人工复核。")
    return "\n".join(lines)


def package_fingerprint(package: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(package, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
