import os
import pytest

# Real-provider diagnostic scripts are opt-in; offline regressions must not consume account quota.
pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_PROVIDER_TESTS") != "1", reason="Set RUN_LIVE_PROVIDER_TESTS=1 for live provider diagnostics")
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

env_path = ROOT_DIR / ".env"
print(f"[env] loading: {env_path}")
load_dotenv(env_path)

from backend.web_search import web_search_provider  # noqa: E402


def test_serper():
    print("\n[env] Serper config")
    print(f"SERPER_API_KEY: {'configured' if os.getenv('SERPER_API_KEY') else 'missing'}")
    print(f"SERPER_FETCH_ENABLED: {os.getenv('SERPER_FETCH_ENABLED', 'true')}")

    queries = [
        "人工智能 最新趋势 2026",
        "新能源汽车 市场分析 2026",
        "半导体 芯片 技术突破",
        "生物医药 创新药 研发进展",
    ]

    for query in queries:
        print(f"\n[query] {query}")
        print("-" * 60)

        try:
            results = web_search_provider._search_serper(query, limit=5)
            print(f"[serper] found {len(results)} results")

            for index, result in enumerate(results, 1):
                metadata = result.get("metadata", {})
                print(f"\n{index}. {result.get('title', '')}")
                print(f"   URL: {result.get('url', '')}")
                print(f"   score: {result.get('credibility_score', 0)}/100")
                print(f"   fetch: {metadata.get('fetch_status', '')}")
                print(f"   content chars: {len(result.get('content') or '')}")
                print(f"   summary: {(result.get('summary') or '')[:150]}...")

        except Exception as exc:
            print(f"[serper] error: {exc}")

    print("\n[done] Serper test completed")


if __name__ == "__main__":
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    test_serper()
