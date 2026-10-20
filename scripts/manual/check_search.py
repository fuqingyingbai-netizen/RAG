import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))

env_path = ROOT_DIR / ".env"
print(f"[env] loading: {env_path}")
load_dotenv(env_path)

from backend.web_search import web_search_provider  # noqa: E402


EXA_RATE_LIMIT_SECONDS = 1.2


def _configured(name: str) -> str:
    return "configured" if os.getenv(name) else "missing"


def _try_engine(name: str, func, query: str, limit: int = 3) -> list[dict]:
    print(f"\n[engine] testing {name}...")
    try:
        results = func(query, limit=limit)
        print(f"  {name}: {len(results)} results")
        return results
    except Exception as exc:
        print(f"  {name} error: {exc}")
        return []


def test_search():
    print("\n[env] search provider config")
    print(f"TAVILY_API_KEY: {_configured('TAVILY_API_KEY')}")
    print(f"SERPER_API_KEY: {_configured('SERPER_API_KEY')}")
    print(f"EXA_API_KEY: {_configured('EXA_API_KEY')}")
    print(f"WEB_SEARCH_PROVIDER: {os.getenv('WEB_SEARCH_PROVIDER', 'missing')}")

    query = "人工智能 最新趋势 2026"
    print(f"\n[query] {query}")
    print("-" * 60)

    _try_engine("Tavily", web_search_provider._search_tavily, query)
    _try_engine("Serper", web_search_provider._search_serper, query)

    print(f"\n[engine] waiting {EXA_RATE_LIMIT_SECONDS}s before Exa...")
    time.sleep(EXA_RATE_LIMIT_SECONDS)
    _try_engine("Exa", web_search_provider._search_exa, query)

    print("\n" + "=" * 60)
    print("[multi] testing tavily + serper + exa")
    time.sleep(EXA_RATE_LIMIT_SECONDS)

    original_engines = web_search_provider.engines
    web_search_provider.engines = [
        ("tavily", web_search_provider._search_tavily),
        ("serper", web_search_provider._search_serper),
        ("exa", web_search_provider._search_exa),
    ]

    try:
        results = web_search_provider.multi_engine_search(query, limit=10)
        print(f"\n[multi] total results: {len(results)}")
        for index, result in enumerate(results, 1):
            provider = result.get("metadata", {}).get("provider", "unknown")
            score = result.get("credibility_score", 0)
            print(f"\n{index}. [{provider}] {result.get('title', '')}")
            print(f"   URL: {result.get('url', '')}")
            print(f"   score: {score}/100")
            print(f"   summary: {(result.get('summary') or '')[:100]}...")
    finally:
        web_search_provider.engines = original_engines

    print("\n[done] search test completed")


if __name__ == "__main__":
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    test_search()
