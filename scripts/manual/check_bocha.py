import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# 修复 Windows 终端 UTF-8 编码问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

env_path = ROOT_DIR / ".env"
print(f"[env] loading: {env_path}")
load_dotenv(env_path)

BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
BOCHA_URL = "https://api.bocha.cn/v1/web-search"


def _search_bocha(
    query: str,
    count: int = 10,
    freshness: str = "noLimit",
    summary: bool = True,
    include: str | None = None,
    exclude: str | None = None,
) -> dict:
    """直接调用博查 API"""
    headers = {
        "Authorization": f"Bearer {BOCHA_API_KEY}",
        "Content-Type": "application/json",
    }
    body: dict = {
        "query": query,
        "count": count,
        "freshness": freshness,
        "summary": summary,
    }
    if include:
        body["include"] = include
    if exclude:
        body["exclude"] = exclude

    print(f"[request] POST {BOCHA_URL}")
    print(f"[request] body: {json.dumps(body, ensure_ascii=False)}")

    resp = requests.post(BOCHA_URL, headers=headers, json=body, timeout=30)
    if not resp.ok:
        print(f"[error] HTTP {resp.status_code}")
        print(f"[error] response body: {resp.text[:500]}")
    resp.raise_for_status()
    raw = resp.json()
    # 博查返回格式: {"code": 200, "data": {...}}，结果都在 data 里
    data = raw.get("data", raw)
    return data


def print_web_pages(payload: dict):
    """打印网页搜索结果"""
    web_pages = payload.get("webPages", {})
    total = web_pages.get("totalEstimatedMatches", 0)
    results = web_pages.get("value", [])

    print(f"\n[webPages] totalEstimatedMatches={total}, returned={len(results)}")
    print("-" * 60)

    for i, page in enumerate(results, 1):
        print(f"\n{i}. {page.get('name', '')}")
        print(f"   URL:        {page.get('url', '')}")
        print(f"   snippet:    {(page.get('snippet', '') or '')[:150]}")
        if page.get("summary"):
            print(f"   summary:    {(page.get('summary', '') or '')[:200]}")
        print(f"   siteName:   {page.get('siteName', '')}")
        if page.get("datePublished"):
            print(f"   published:  {page.get('datePublished', '')}")


def print_images(payload: dict):
    """打印图片搜索结果"""
    images = payload.get("images", {}).get("value", [])
    if not images:
        print("\n[images] (none)")
        return

    print(f"\n[images] returned={len(images)}")
    print("-" * 60)
    for i, img in enumerate(images[:5], 1):
        print(f"\n{i}. contentUrl:  {img.get('contentUrl', '')[:120]}")
        print(f"   hostPageUrl: {img.get('hostPageUrl', '')[:120]}")
        print(f"   size:        {img.get('width', '?')}x{img.get('height', '?')}")


# ── 测试用例 ──────────────────────────────────────────────

def test_basic_search():
    print("\n" + "=" * 60)
    print("  测试 1：基础企业搜索")
    print("=" * 60)

    payload = _search_bocha("字节跳动 2025 2026 AI大模型 业务进展", count=5)
    print_web_pages(payload)
    print_images(payload)


def test_freshness_filter():
    print("\n" + "=" * 60)
    print("  测试 2：时间范围过滤（近一个月）")
    print("=" * 60)

    payload = _search_bocha("AI Agent 行业趋势", count=5, freshness="oneMonth")
    print_web_pages(payload)


def test_domain_include():
    print("\n" + "=" * 60)
    print("  测试 3：定向域名搜索（36kr + 虎嗅）")
    print("=" * 60)

    payload = _search_bocha(
        "大模型 应用 融资",
        count=5,
        include="36kr.com|huxiu.com",
    )
    print_web_pages(payload)


def test_domain_exclude():
    print("\n" + "=" * 60)
    print("  测试 4：排除百度系低价值域名")
    print("=" * 60)

    payload = _search_bocha(
        "人工智能 最新进展",
        count=5,
        exclude="baijiahao.baidu.com|zhihu.com",
    )
    print_web_pages(payload)


def test_no_summary():
    print("\n" + "=" * 60)
    print("  测试 5：不请求摘要模式（节省 token）")
    print("=" * 60)

    payload = _search_bocha("新能源汽车 政策", count=3, summary=False)
    print_web_pages(payload)


def test_research_style():
    """模拟研究报告实际使用的搜索 query"""
    print("\n" + "=" * 60)
    print("  测试 6：研究报告风格搜索")
    print("=" * 60)

    queries = [
        "字节跳动 火山引擎 AI大模型 营收 2025",
        "华为 智能汽车 业务 估值 融资",
        "OpenAI GPT-5 发布 进展 2026",
    ]
    for q in queries:
        print(f"\n{'─' * 50}")
        payload = _search_bocha(q, count=3)
        web_pages = payload.get("webPages", {})
        results = web_pages.get("value", [])
        print(f"[query] {q}")
        print(f"[total] {web_pages.get('totalEstimatedMatches', 0)} | returned {len(results)}")
        for i, page in enumerate(results, 1):
            print(f"  {i}. [{page.get('siteName', '?')}] {page.get('name', '')[:80]}")
            print(f"     {page.get('url', '')[:100]}")


# ── Main ──────────────────────────────────────────────────

if __name__ == "__main__":
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    print(f"[config] BOCHA_API_KEY: {'configured' if BOCHA_API_KEY else 'MISSING!'}")
    if not BOCHA_API_KEY:
        print("[ERROR] BOCHA_API_KEY 未配置，请检查 .env 文件")
        sys.exit(1)

    try:
        test_basic_search()
        test_freshness_filter()
        test_domain_include()
        test_domain_exclude()
        test_no_summary()
        test_research_style()
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("  [done] 博查 API 测试完成")
    print("=" * 60)
