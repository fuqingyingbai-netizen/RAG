import re

# Canonical heading format: ``## N. Title`` where N is 1-2 digits.
# Accepts: ``.``, ``．``, ``、``, ``）``, ``)`` as separator after the number.
# This is the SINGLE definition — all code paths must reference this constant.
REPORT_CHAPTER_HEADING_RE = re.compile(
    r"(?m)^##\s*(\d{1,2})\s*(?:\.(?!\d)|[、。．）):：\-])\s*[^\n]+$"
)


def normalize_report_headings(report: str, expected_headings: dict[int, str]) -> str:
    """Normalize malformed chapter headings to canonical ``## N. Title`` format.

    Runs BEFORE the quality gate and audit-index builder.  Handles common LLM
    formatting mistakes:

    - ``# 1. Title`` (single hash) → ``## 1. Title``
    - ``### 1. Title`` (triple hash) → ``## 1. Title``
    - ``## 1: Title`` / ``## 1 - Title`` / ``## 1）Title`` → ``## 1. Title``
    - ``## 1) Title`` → ``## 1. Title``

    ``expected_headings`` maps chapter numbers to canonical titles, e.g.
    ``{1: "摘要", 2: "主体工商基本信息核查股东关系与治理底盘", ...}``.
    Only chapters whose number appears in this dict are normalized; sub-headings
    (``### 1.1``) and unexpected chapters are left unchanged.

    Returns the report with all recognized chapter headings normalized.
    """
    if not report or not expected_headings:
        return report

    lines = report.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Match: 1-5 hash marks, optional whitespace, then 1-2 digits, then
        # a separator that is NOT "digit. digit" (sub-heading guard — ``1.1``
        # must never be mistaken for chapter 1).
        # Accepted separators: ideographic comma/period/paren, ASCII colon,
        # dash, or an ASCII period NOT immediately followed by a digit.
        match = re.match(
            r"^(#{1,5})\s*(\d{1,2})\s*(?:\.(?!\d)|[、。．）):：\-])\s*[^\n]*$",
            line,
        )
        if match:
            hashes = match.group(1)
            chapter_num = int(match.group(2))
            if chapter_num in expected_headings:
                # Rewrite to canonical form regardless of original format
                canonical_title = expected_headings[chapter_num]
                result.append(f"## {chapter_num}. {canonical_title}")
                i += 1
                continue
        result.append(line)
        i += 1

    return "\n".join(result)


def sanitize_nested_report_chapter_headings(report: str, expected_headings: dict[int, str]) -> str:
    """Demote repeated standard chapter headings that appear inside a chapter.

    Section writers sometimes use the global outline as labels inside a single
    chapter, for example chapter 10 containing ``## 1. 摘要`` under a scenario
    analysis subsection.  Those lines are valid-looking chapter headings, so
    Word treats them as real top-level navigation nodes.  Keep the first
    canonical 1..N sequence as report chapters and demote any out-of-order or
    repeated standard heading to an internal subheading.
    """
    if not report or not expected_headings:
        return report

    highest_seen = 0
    result: list[str] = []
    pattern = re.compile(r"^##\s*(\d{1,2})\s*(?:\.(?!\d)|[、。．:：)\-])\s*(.*?)\s*$")
    for line in report.split("\n"):
        match = pattern.match(line)
        if not match:
            result.append(line)
            continue
        chapter_num = int(match.group(1))
        title = (match.group(2) or "").strip()
        if chapter_num not in expected_headings:
            result.append(line)
            continue
        if chapter_num > highest_seen:
            result.append(f"## {chapter_num}. {expected_headings[chapter_num]}")
            highest_seen = chapter_num
            continue
        # The heading names a real report chapter but appears in the wrong
        # place. It is section content, not a top-level chapter.
        result.append(f"### {title or expected_headings[chapter_num]}")
    return "\n".join(result)


REFERENCE_REPORT_STYLE = """
参考交付风格来自 Keymed 桌面研究报告：
1. 开头给出报告标题、编制时间、调研对象；如涉及关键人物，列出目标人物及职务。
2. 正文使用清晰编号章节，章节内用“事实说明 + 要点清单 + 表格”承载信息，避免空泛判断。
3. 公司/行业报告优先沉淀：基本信息、主要业务板块、核心产品/管线、研发阶段、IPO/融资/BD合作、区域或组织角色、经营与财务数据。
4. 人物报告优先沉淀：任职时间、岗位职责、入职前背景、资本/研发/管理成果、公开发言、失败经历或风险事件。
5. 适合表格化的信息必须表格化，例如产品代号-靶点-适应症-研发阶段-进展、年度收入-研发支出-净利润、BD交易时间-产品-合作方-金额-角色。
6. 结尾必须包含“信息来源汇总”“总结与建议”“报告编制说明”；来源要列标题和 URL，编制说明要提示本报告基于公开信息、需访谈或实地调研复核。
7. 可以使用 Mermaid 或 Markdown 表格表达时间线、股权/组织关系、产业链、风险矩阵，但不得为了图表编造数据。
8. 证据不足时正文只写“待核验”，并把待核验事项放入集中式待核验清单/后续研究点。
"""


def ensure_delivery_sections(project, report: str, report_kind: str) -> str:
    header = (
        f"# {project.title or report_kind}\n\n"
        f"- 报告类型：{report_kind}\n"
        f"- 调研对象：{project.target_name or project.title}\n"
        f"- 对象类型：{project.target_type}\n"
        f"- 所属行业：{project.industry or '待核验'}\n"
        f"- 编制说明：本报告由系统基于公开检索、上传资料、清洗事实和风险研判自动生成，正式交付前建议人工复核。\n"
    )
    body = report.strip()
    if not body.startswith("# "):
        body = header + "\n" + body

    additions = []
    if "信息来源" not in body:
        additions.append(
            "## 信息来源汇总\n\n"
            "待核验。请以后续检索入库来源、上传资料和人工复核来源为准，正式交付时列出核心来源标题与 URL。"
        )
    if "后续研究点" not in body and "后续研究建议" not in body:
        additions.append(
            "## 后续研究点\n\n"
            "- 补充权威工商、监管、司法、公告、年报、研报和主流媒体来源。\n"
            "- 对关键结论进行人工复核，必要时安排访谈或实地调研。\n"
            "- 对图表、财务数据、产品管线、人物履历和风险事件进行交叉验证。"
        )
    if "报告编制说明" not in body:
        additions.append(
            "## 报告编制说明\n\n"
            "本报告基于公开信息和系统检索结果整理，自动生成内容可能存在信息缺口。报告中的判断应结合客户资料、访谈、实地调研和付费数据库进一步验证。"
        )
    if additions:
        body = body.rstrip() + "\n\n" + "\n\n".join(additions)
    return body
