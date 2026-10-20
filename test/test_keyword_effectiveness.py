# 关键词效果对比，关键词效果的对比

import os
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_PROVIDER_TESTS") != "1", reason="Set RUN_LIVE_PROVIDER_TESTS=1 for paid live diagnostics")
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / ".env")

from backend.web_search import web_search_provider


def test_keyword_effectiveness():
    """测试不同关键词的搜索效果"""
    print("=" * 70)
    print("🎯 关键词效果测试")
    print("=" * 70)

    # 关键词变体测试
    keyword_groups = [
        {"name": "公司名称", "queries": ["乐奇rokid", "Rokid", "乐奇 Rokid"]},
        {"name": "产品相关", "queries": ["乐奇rokid 智能眼镜", "Rokid Glass", "乐奇rokid AR"]},
        {"name": "融资信息", "queries": ["乐奇rokid 融资", "Rokid 投资方", "乐奇rokid 估值"]},
        {"name": "团队信息", "queries": ["乐奇rokid 创始人", "Rokid CEO", "乐奇rokid 团队"]},
        {"name": "新闻动态", "queries": ["乐奇rokid 新闻", "Rokid 最新动态", "乐奇rokid 2026"]},
        {"name": "行业对比", "queries": ["乐奇rokid 竞争对手", "Rokid vs Meta", "智能眼镜 竞品"]},
    ]

    results_by_group = {}

    for group in keyword_groups:
        print(f"\n📌 {group['name']}")
        print("-" * 50)

        total_results = 0
        for query in group["queries"]:
            try:
                results = web_search_provider.search(query, limit=15)
                count = len(results)
                total_results += count
                print(f"   '{query}': {count} 条")
            except Exception as e:
                print(f"   '{query}': ❌ {e}")

        results_by_group[group["name"]] = total_results
        print(f"   合计: {total_results} 条")

    print("\n📊 关键词组效果对比")
    print("-" * 50)
    for group_name, count in sorted(results_by_group.items(), key=lambda x: -x[1]):
        print(f"   {group_name}: {count} 条")


if __name__ == "__main__":
    test_keyword_effectiveness()