# 内容质量的分析


import os
import pytest

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_PROVIDER_TESTS") != "1", reason="Set RUN_LIVE_PROVIDER_TESTS=1 for paid live diagnostics")
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))
load_dotenv(ROOT_DIR / ".env")

from backend.web_search import web_search_provider


def test_content_quality():
    """分析搜索结果的内容质量"""
    print("=" * 70)
    print("🎯 内容质量分析")
    print("=" * 70)

    query = "乐奇rokid"
    print(f"\n🔍 分析查询: {query}")
    print("-" * 50)

    try:
        results = web_search_provider.search(query, limit=20)
        print(f"找到 {len(results)} 条结果")

        # 分析每条结果
        for i, result in enumerate(results, 1):
            title = result.get("title", "")
            url = result.get("url", "")
            content = result.get("content", "")
            provider = result.get("metadata", {}).get("provider", "unknown")
            platform = result.get("metadata", {}).get("platform", "unknown")
            fetched_chars = result.get("metadata", {}).get("fetched_chars", 0)

            print(f"\n📄 结果 {i}")
            print(f"   标题: {title}")
            print(f"   URL: {url}")
            print(f"   来源: {provider} | 平台: {platform}")
            print(f"   爬取字符数: {fetched_chars}")

            # 显示内容预览
            if content:
                preview = content[:200].replace("\n", " ")
                print(f"   内容预览: {preview}...")
            else:
                print("   ❌ 无内容")

            # 检查内容质量
            if len(content) < 100:
                print("   ⚠️ 内容过短，可能只是摘要")
            elif len(content) < 500:
                print("   ⚠️ 内容较短")
            else:
                print("   ✅ 内容充足")

    except Exception as e:
        print(f"❌ 分析失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    test_content_quality()