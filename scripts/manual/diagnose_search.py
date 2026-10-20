# 搜索结果的诊断



import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))
load_dotenv(ROOT_DIR / ".env")

from backend.web_search import web_search_provider


def test_search_results():
    """测试搜索结果数量和平台覆盖"""
    print("=" * 70)
    print("🎯 搜索结果诊断测试")
    print("=" * 70)

    # 测试查询词
    queries = [
        "乐奇rokid",
        "乐奇rokid 智能眼镜",
        "乐奇rokid 融资",
        "Rokid 公司",
        "Rokid 技术",
        "乐奇rokid 创始人",
    ]

    all_results = []
    platform_counts = {}

    for query in queries:
        print(f"\n🔍 查询: {query}")
        print("-" * 50)

        try:
            results = web_search_provider.search(query, limit=30)
            print(f"✅ 找到 {len(results)} 条结果")

            for result in results:
                platform = result.get("metadata", {}).get("platform", "unknown")
                platform_counts[platform] = platform_counts.get(platform, 0) + 1
                all_results.append(result)

                # 显示前3条结果
                if len([r for r in all_results if r.get("query") == query]) <= 3:
                    title = result.get("title", "")[:60]
                    url = result.get("url", "")[:80]
                    provider = result.get("metadata", {}).get("provider", "unknown")
                    print(f"   [{provider}] [{platform}] {title}")
                    print(f"      URL: {url}")

        except Exception as e:
            print(f"❌ 搜索失败: {e}")

    print("\n📊 平台覆盖统计")
    print("-" * 50)
    for platform, count in sorted(platform_counts.items(), key=lambda x: -x[1]):
        print(f"   {platform}: {count} 条")

    print(f"\n📈 总计: {len(all_results)} 条搜索结果")

    # 检查内容质量
    print("\n📝 内容质量检查")
    print("-" * 50)
    content_lengths = []
    for result in all_results[:20]:
        content = result.get("content", "")
        content_lengths.append(len(content))

    if content_lengths:
        avg_length = sum(content_lengths) / len(content_lengths)
        print(f"   平均内容长度: {avg_length:.0f} 字符")
        print(f"   最短内容: {min(content_lengths)} 字符")
        print(f"   最长内容: {max(content_lengths)} 字符")


if __name__ == "__main__":
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    test_search_results()