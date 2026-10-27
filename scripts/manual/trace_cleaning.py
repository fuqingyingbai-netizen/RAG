# 完整清洗流程追踪
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))
load_dotenv(ROOT_DIR / ".env")

from backend.web_search import web_search_provider


def trace_cleaning_process():
    """追踪完整的数据清洗流程"""
    print("=" * 70)
    print("🎯 数据清洗流程追踪")
    print("=" * 70)

    query = "乐奇rokid"
    print(f"\n🔍 查询: {query}")
    print("-" * 50)

    # 获取搜索结果
    results = web_search_provider.search(query, limit=20)
    print(f"搜索结果: {len(results)} 条")

    # 模拟清洗阶段
    stages = [
        {"name": "原始数据", "results": results.copy()},
    ]

    # 阶段1: 去重
    seen_urls = set()
    deduplicated = []
    for r in results:
        url = r.get("url", "")
        if url not in seen_urls:
            seen_urls.add(url)
            deduplicated.append(r)
    stages.append({"name": "去重后", "results": deduplicated})

    # 阶段2: 内容过滤
    filtered = []
    for r in deduplicated:
        content = r.get("content", "")
        if len(content) >= 50:  # 最小内容长度
            filtered.append(r)
    stages.append({"name": "内容过滤后", "results": filtered})

    # 阶段3: 质量评分
    scored = []
    for r in filtered:
        score = 0
        url = r.get("url", "")
        content = r.get("content", "")

        # 域名权重
        if "gov.cn" in url:
            score += 30
        elif "qcc.com" in url or "tianyancha.com" in url:
            score += 20
        elif "36kr.com" in url or "jiemian.com" in url:
            score += 15

        # 内容长度评分
        score += min(len(content) // 100, 20)

        if score >= 15:  # 最低质量分
            scored.append(r)
    stages.append({"name": "质量评分后", "results": scored})

    # 输出各阶段结果
    print("\n📊 清洗流程各阶段统计")
    print("-" * 50)
    for i, stage in enumerate(stages):
        count = len(stage["results"])
        if i > 0:
            prev_count = len(stages[i - 1]["results"])
            removed = prev_count - count
            percent = (removed / prev_count) * 100
            print(f"   {stage['name']}: {count} 条 (-{removed}条, -{percent:.1f}%)")
        else:
            print(f"   {stage['name']}: {count} 条")


if __name__ == "__main__":
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    trace_cleaning_process()