"""Kimi API 连通性测试：从项目根目录 .env 读取配置。

运行：uv run python test/kimi_api_smoke.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


def main() -> int:
    api_key = os.getenv("MOONSHOT_API_KEY", "").strip()
    base_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1").strip()
    model = os.getenv("MOONSHOT_MODEL", "kimi-k2.6").strip()
    if not api_key:
        print("[error] 未配置 MOONSHOT_API_KEY；请写入项目根目录 .env。")
        return 2

    client = OpenAI(api_key=api_key, base_url=base_url)
    print(f"[request] model={model}, base_url={base_url}")
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "用一句话介绍 Kimi K3。"}],
            # Moonshot 的当前模型配置要求 temperature=1。
            temperature=1,
        )
    except AuthenticationError:
        print("[error] Kimi 鉴权失败：请检查 MOONSHOT_API_KEY。")
        return 3
    except APIStatusError as exc:
        print(f"[error] Kimi API 返回 HTTP {exc.status_code}。")
        # API 错误正文通常会说明模型、额度或请求参数问题；不输出请求头，避免泄露密钥。
        detail = (exc.response.text or "").strip().replace("\n", " ")[:1000]
        if detail:
            print(f"[error] 服务端详情：{detail}")
        return 4
    except APIConnectionError:
        print("[error] 无法连接 Kimi API：请检查网络或 MOONSHOT_BASE_URL。")
        return 5

    content = completion.choices[0].message.content or ""
    print("[success] 响应：")
    print(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
