# 数据清洗的诊断

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
load_dotenv(ROOT_DIR / ".env")

from backend.web_search import web_search_provider
from backend.research_workflow import ResearchWorkflow


def test_cleaning_process():
    """测试数据清洗过程，找出被清洗掉的内容"""
    print("=" * 70)
    print("🎯 数据清洗诊断测试")
    print("=" * 70)

    # 测试查询
    query = "乐奇rokid"
    print(f"\n🔍 测试查询: {query}")
    print("-" * 50)

    # 1. 获取原始搜索结果
    print("\n📥 步骤1: 获取原始搜索结果")
    print("-" * 50)
    raw_results = web_search_provider.search(query, limit=20)
    print(f"原始结果数量: {len(raw_results)}")

    # 显示原始结果
    for i, result in enumerate(raw_results, 1):
        title = result.get("title", "")[:50]
        platform = result.get("metadata", {}).get("platform", "unknown")
        content_len = len(result.get("content", ""))
        print(f"   {i}. [{platform}] {title} | 内容长度: {content_len}")

    # 2. 模拟数据清洗
    print("\n🧹 步骤2: 模拟数据清洗")
    print("-" * 50)

    # 创建工作流实例
    workflow = ResearchWorkflow()

    # 模拟清洗过程
    cleaned_facts = []
    discarded_items = []

    for result in raw_results:
        content = result.get("content", "")
        url = result.get("url", "")
        title = result.get("title", "")

        # 检查是否会被清洗掉
        is_discarded = False
        discard_reason = ""

        # 清洗规则模拟
        if len(content) < 100:
            is_discarded = True
            discard_reason = "内容过短"
        elif len(content) > 5000:
            is_discarded = True
            discard_reason = "内容过长"
        elif "广告" in content or "推广" in content:
            is_discarded = True
            discard_reason = "广告内容"
        elif url.startswith("https://www.baidu.com"):
            is_discarded = True
            discard_reason = "搜索引擎结果页"

        if is_discarded:
            discarded_items.append({
                "title": title,
                "url": url,
                "reason": discard_reason,
                "content_length": len(content)
            })
        else:
            cleaned_facts.append(result)

    # 3. 输出清洗结果
    print(f"\n📊 清洗结果")
    print("-" * 50)
    print(f"✓ 保留事实: {len(cleaned_facts)} 条")
    print(f"✗ 被清洗: {len(discarded_items)} 条")

    if discarded_items:
        print("\n🗑️ 被清洗的内容:")
        for i, item in enumerate(discarded_items, 1):
            print(f"   {i}. {item['title'][:50]}")
            print(f"      原因: {item['reason']}")
            print(f"      URL: {item['url'][:60]}")

    # 4. 检查清洗阈值
    print("\n⚙️ 清洗规则阈值检查")
    print("-" * 50)

    # 统计内容长度分布
    content_lengths = [len(r.get("content", "")) for r in raw_results]
    if content_lengths:
        avg_length = sum(content_lengths) / len(content_lengths)
        print(f"平均内容长度: {avg_length:.0f} 字符")
        print(f"最短内容: {min(content_lengths)} 字符")
        print(f"最长内容: {max(content_lengths)} 字符")

        # 检查有多少内容低于清洗阈值
        below_threshold = sum(1 for l in content_lengths if l < 100)
        print(f"低于阈值(100字符)的内容: {below_threshold} 条")


if __name__ == "__main__":
    test_cleaning_process()