"""Reproducible person chapter comparison; live services require explicit --live.

Offline source fixtures and model replays are labelled synthetic. They measure
contract behaviour, not the quality of a real investigation.
"""
import argparse
import html
import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from person_evidence import generate_person_report, split_sections, cited_ids, VERSION, name_in_text
from report_agents.person_report_agent import PersonReportAgent

CHANGES = {
    1: "最后生成摘要，仅使用前文已实际引用的事实；移除带具体公司和人物的示例。",
    2: "教育职业时间线保留事件时间及来源归属；低曝光人物不因资料不足被中止；冲突显式保留。",
    3: "人格维度落到公开行为和来源评价，分开事实、观点、研究判断，禁止无证据人格评级。",
    4: "区分个人职责和公司业绩，列战略执行、资本资源、创新迭代及发展阶段的核查维度。",
    5: "按权责、人事、经营核查组织事件；历史职责不自动当作当前控制关系。",
    6: "团队成员的职责与履历分开归属；团队事实不能归给研究对象本人。",
    7: "区分公开评价与授权访谈；未做多方访谈不声称交叉验证；公司信用不充当个人信用。",
    8: "明确可比人物的赛道、阶段、角色和时期，缺少可比资料时不排名。",
    9: "持股、任职、实际控制与司法当事人分开；关联企业信息始终保留间接归属边界。",
    10: "按委托专项范围组织材料，未指定方向明确待确认，不自动编造高敏专项结论。",
    11: "明确实际决策角色与投资场景，分别核查沟通、审批、关键岗位与退出条件。",
    12: "17项风险覆盖单列未知项，缺失、未查询及调用失败不计为风险，不自动评分。",
    13: "在实质章节完成后汇总，依据前文实际引用；不凭声誉生成字母或数值评级。",
    14: "根据正文实际E-ID反向生成索引，保留信息点、原始定位、工具、日期和支持章节。",
    15: "确定性汇总并去重各章缺口、时间冲突与API问题，列优先级、来源和核验完成条件。",
}


def noop(*args, **kwargs):
    pass


def echo(role, prompt, trace=None):
    package = json.loads(prompt[prompt.index('{"chapter":'):])
    return json.dumps({"claims": [{"statement": f["fact"], "evidence_ids": [f["evidence_id"]], "analysis": ""}
                                   for f in package["facts"]]}, ensure_ascii=False)


def malicious(role, prompt, trace=None):
    package = json.loads(prompt[prompt.index('{"chapter":'):])
    return json.dumps({"claims": [{"statement": "OTHER LABS在2099年融资999亿元，研究对象没有任何诉讼且诚信优秀。",
                                   "evidence_ids": [package["facts"][0]["evidence_id"]], "analysis": ""}]}, ensure_ascii=False)


def project(name):
    return SimpleNamespace(target_name=name, target_type="person", title=f"{name}人物研究验收",
                           industry="", description="", sources=[])


def run_live(out):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import requests
    from bs4 import BeautifulSoup
    from company_platform import failure_kind
    from web_search import web_search_provider
    from research_workflow import ResearchWorkflow
    previous = json.loads((out / "live.json").read_text(encoding="utf-8")) if (out / "live.json").exists() else {}
    attempts, discoveries = [], []
    query = '"Lisa Su" AMD official biography'
    for provider in ("bocha", "exa", "tavily"):
        prior = next((r for r in previous.get("attempts", []) if r.get("provider") == provider), None)
        if prior:
            attempts.append({**prior, "probe_reused": True})
            continue
        if not os.getenv(provider.upper() + "_API_KEY"):
            attempts.append({"provider": provider, "status": "not_configured"})
            continue
        try:
            fn = getattr(web_search_provider, "_search_" + provider)
            results = fn(query, 2)
            discoveries.extend(results)
            attempts.append({"provider": provider, "status": "returned", "result_count": len(results)})
        except Exception as exc:
            response = getattr(exc, "response", None)
            error = str(exc)
            if response is not None:
                try:
                    error += json.dumps(response.json(), ensure_ascii=False)
                except ValueError:
                    pass
            attempts.append({"provider": provider, "status": "failed", "reason": failure_kind({"error": error}),
                             "http_status": getattr(response, "status_code", None), "exception_type": type(exc).__name__})
        print(json.dumps(attempts[-1], ensure_ascii=False), flush=True)
    # Public original documents: search snippets alone are not used as verified facts.
    urls = [str(r.get("url") or "") for r in discoveries if "amd.com/" in str(r.get("url") or "")]
    if not urls:
        urls = [r["url"] for r in previous.get("attempts", []) if r.get("provider") == "original_web" and r.get("status") == "returned"]
    if not urls:
        urls = ["https://www.amd.com/en/corporate/leadership/lisa-su.html"]
    # A second official original exercises current governance alongside a dated event.
    urls.append("https://ir.amd.com/governance/board-of-directors")
    p = project("Lisa Su")
    for url in list(dict.fromkeys(urls))[:2]:
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text("\n", strip=True)
            identity = name_in_text("Lisa Su", text) and "AMD" in text
            attempts.append({"provider": "original_web", "url": url, "status": "returned", "identity_anchor_match": identity})
            if identity:
                p.sources.append(SimpleNamespace(title="AMD official leadership biography", url=url, content=text, summary="",
                    source_type="official", credibility_score=90,
                    source_metadata={"identity_confidence": "high", "module": "教育与履历"}))
        except Exception as exc:
            attempts.append({"provider": "original_web", "url": url, "status": "failed", "exception_type": type(exc).__name__})
    workflow = ResearchWorkflow()
    facts = workflow._extract_sentence_facts(p.sources, p)
    payload = {"facts": facts, "information_gaps": ["此次为有界真实检索与模型验收，未执行完整多轮人物调查。"]}
    if facts:
        os.environ["PERSON_REPORT_SECTION_TIMEOUT_SECONDS"] = "45"
        os.environ["PERSON_REPORT_SECTION_MAX_RETRIES"] = "0"
        report = generate_person_report(p, json.dumps(payload, ensure_ascii=False), "{}", PersonReportAgent.outline,
                                       workflow._invoke_person_report_section, noop)
        (out / "live-report.md").write_text(report, encoding="utf-8")
        attempts.extend(p.person_delivery_diagnostic["api_attempts"])
        live = {"scope": "bounded_live_search_original_fetch_and_report", "fact_count": len(facts),
                "diagnostic": p.person_delivery_diagnostic, "attempts": attempts}
    else:
        # Still test one actual structured chapter request, explicitly using
        # synthetic source data; this does not count as a real investigation.
        package = {"chapter": 2, "title": "接口格式验收", "facts": [{"fact": "合成接口验收记录", "evidence_id": "E-SYNTHETIC0001"}]}
        try:
            response = workflow._invoke_person_report_section("BDD人物章节 Agent - 接口格式验收",
                '仅返回JSON {"claims":[{"statement":"合成接口验收记录","evidence_ids":["E-SYNTHETIC0001"],"analysis":""}]}', None)
            attempts.append({"provider": "person_model", "status": "returned", "response_chars": len(response), "scope": "synthetic_schema_probe"})
        except Exception as exc:
            attempts.append({"provider": "person_model", "status": "failed", "reason": failure_kind({"error": str(exc)}), "exception_type": type(exc).__name__})
        live = {"scope": "search_probe_and_synthetic_model_probe", "fact_count": 0, "attempts": attempts}
    (out / "live.json").write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    return live


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--work", type=Path, default=ROOT / "work/person-optimization")
    args = parser.parse_args()
    out = args.work
    out.mkdir(parents=True, exist_ok=True)
    stored = json.loads((ROOT / "test/fixtures/person_template_audit.json").read_text(encoding="utf-8"))
    fixture = stored["fixture"]
    before = stored["baseline_report"]
    cases = []
    for name in ("林知远", "陈雨安", "Amelia Hart"):
        payload = json.loads(json.dumps(fixture, ensure_ascii=False).replace("林知远", name))
        for mode, invoke in (("positive_replay", echo), ("adversarial_replay", malicious)):
            p = project(name)
            report = generate_person_report(p, json.dumps(payload, ensure_ascii=False), "{}", PersonReportAgent.outline, invoke, noop)
            (out / f"after-{name}-{mode}.md").write_text(report, encoding="utf-8")
            cases.append({"name": name, "mode": mode, "scope": "synthetic_offline", "report": report, "audit": p.person_delivery_diagnostic})
    live = run_live(out) if args.live else json.loads((out / "live.json").read_text(encoding="utf-8")) if (out / "live.json").exists() else {"scope": "not_run"}
    before_sections = split_sections(before)
    after = split_sections(cases[0]["report"])
    adversarial = split_sections(cases[1]["report"])
    rows = []
    for i, (title, requirements) in enumerate(PersonReportAgent.outline, 1):
        rows.append({"chapter": i, "title": title, "requirements": requirements, "change": CHANGES[i],
            "before": {"chars": len(before_sections.get(i, "")), "actual_citations": len(cited_ids(before_sections.get(i, ""))),
                       "foreign_example_hits": before_sections.get(i, "").count("OTHER LABS"), "text": before_sections.get(i, "")},
            "after": {"chars": len(after.get(i, "")), "actual_citations": len(cited_ids(after.get(i, ""))),
                      "foreign_example_hits": adversarial.get(i, "").count("OTHER LABS"), "text": adversarial.get(i, "")},
            "diagnostic": {**cases[1]["audit"]["chapters"][i-1], "generation": cases[1]["audit"]["section_diagnostics"].get(i, {})},
            "verification": "same_input_offline_positive_and_adversarial_replay"})
    test_summary = {"status": "not_recorded"}
    test_file = out / "tests-final.xml"
    if test_file.exists():
        root = ET.parse(test_file).getroot()
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        test_summary = {key: sum(int(s.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
        test_summary["passed"] = test_summary["tests"] - test_summary["failures"] - test_summary["errors"] - test_summary["skipped"]
    validation_path = ROOT / "docs/PERSON_OPTIMIZATION_VALIDATION.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else {}
    platform_rows = validation.get("platform_probes_20261020", [])
    platform_html = "".join(f"<tr><td>{esc_name}</td><td>{esc_status}</td><td>{esc_note}</td></tr>"
        for esc_name, esc_status, esc_note in ((html.escape(str(r['provider'])), html.escape(str(r['status'])), html.escape(str(r['note']))) for r in platform_rows))
    result = {"version": VERSION, "tests": test_summary, "scope": "离线合成用例同输入前后对照，非真实人物调查效果评分", "chapters": rows,
              "completion_level": "engineering_first_pass_real_chapter_acceptance_pending", "platform_probes_20261020": platform_rows,
              "cases": [{k: v for k, v in c.items() if k != "report"} for c in cases], "live": live}
    (out / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    esc = html.escape
    cards = []
    for row in rows:
        i = row["chapter"]
        cards.append(f'''<article id="ch{i}"><h2>{i}. {esc(row['title'])}</h2><p>{esc(row['change'])}</p>
        <p class="note">模板要求：{esc('；'.join(row['requirements']))}</p>
        <table><tr><th>同输入离线对照</th><th>改进前</th><th>改进后</th></tr>
        <tr><td>正文可识别证据编号</td><td>{row['before']['actual_citations']}</td><td>{row['after']['actual_citations']}</td></tr>
        <tr><td>故障回放中混入的外部示例次数</td><td>{row['before']['foreign_example_hits']}</td><td>{row['after']['foreign_example_hits']}</td></tr></table>
        <details><summary>查看本章改前与改后文本</summary><div class="compare"><section><h3>改前 · 故障输出回放</h3><pre>{esc(row['before']['text'])}</pre></section>
        <section><h3>改后 · 等价错误事实注入被拦截后的底稿</h3><pre>{esc(row['after']['text'])}</pre></section></div></details>
        <details><summary>查看逐章验收记录</summary><pre>{esc(json.dumps(row['diagnostic'],ensure_ascii=False,indent=2))}</pre></details></article>''')
    nav = "".join(f'<a href="#ch{i}">{i} {esc(t)}</a>' for i, (t, _) in enumerate(PersonReportAgent.outline, 1))
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>人物背景调查全流程与15章改进对照</title><style>
    *{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:#f3f6f9;color:#192b3e;font:16px/1.75 "Microsoft YaHei",sans-serif}}header,main{{max-width:1320px;margin:auto;padding:28px}}h1{{font-size:30px}}.layout{{display:grid;grid-template-columns:240px 1fr;gap:24px}}nav{{position:sticky;top:12px;max-height:95vh;overflow:auto}}nav a{{display:block;color:#087f7a;padding:6px;text-decoration:none}}article,.overview{{background:white;padding:26px;border:1px solid #dce5ed;border-radius:12px;margin-bottom:22px;scroll-margin-top:14px}}.note{{color:#617186}}table{{width:100%;border-collapse:collapse;margin:16px 0}}th,td{{border:1px solid #dce5ed;padding:10px;text-align:left}}th{{background:#eaf4f2}}.compare{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}pre{{white-space:pre-wrap;word-break:break-word;font:13px/1.7 monospace;max-height:650px;overflow:auto;background:#f7f9fb;padding:16px}}summary{{cursor:pointer;color:#087f7a;padding:10px 0}}@media(max-width:850px){{.layout,.compare{{grid-template-columns:1fr}}nav{{position:static;max-height:240px}}header,main{{padding:16px}}}}
    </style><header><p>工作流改进与可复核验收 · {VERSION}</p><h1>人物背景调查 全流程与15章改进对照</h1>
    <p>分支 codex/company · 基线 f637636 · 参考创始人桌面研究模板 A/B列；C列表达案例不作为事实输入。</p></header>
    <main><div class="overview"><h2>验证范围</h2><p><strong>状态：第一轮工程改造完成，完整真实人物报告的逐章内容与Word逐页排版尚未验收。</strong></p><p>离线回归记录：{esc(json.dumps(test_summary,ensure_ascii=False))}。Word已验证结构、外链和证据跳转；逐页视觉排版尚未验收。</p><p>15章均有工程改动和合成回放记录。中文不同姓名与英文名共3组、正向与故障输出共6个离线合成案例。上述数字衡量引用和错误隔离，不代表真实调查准确率。</p>
    <h3>2026-10-20 平台重新实测</h3><table><tr><th>平台</th><th>状态</th><th>范围与阻碍</th></tr>{platform_html}</table>
    <p>专业平台测试主体为比亚迪股份有限公司，仅证明所测接口与主体的返回情况。人物关联企业风险的司法明细仍未达到公司链路相同采集深度。</p>
    <p>处理顺序：先第2—12章，再第13章综合评估、第1章摘要，最后第14章来源与第15章核验计划。API失败保留来源底稿并记录待复核，不显示为模型成功。</p>
    <p><a href="search-three-engine-experiment.html">查看充值后三家检索实验</a>：8组问题、网站过滤修复与原文抽查。完整人物报告的逐章验收仍待完成。</p>
    <details><summary>上一轮人物章节API与原文验收（历史记录）</summary><pre>{esc(json.dumps(live,ensure_ascii=False,indent=2))}</pre></details></div>
    <div class="layout"><nav>{nav}</nav><div>{''.join(cards)}</div></div></main></html>'''
    target = ROOT / "deliverables/person-report-optimization.html"
    target.parent.mkdir(exist_ok=True)
    target.write_text(document, encoding="utf-8")
    print(json.dumps({"html": str(target), "chapters": len(rows), "offline_cases": len(cases), "live_scope": live["scope"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
