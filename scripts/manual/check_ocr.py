"""
百度 OCR 通用文字识别测试
- 支持本地图片 base64 上传
- 支持 URL 方式
- 测试真实背景调查场景的图片
"""
import base64
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

BAIDU_API_KEY = os.getenv("BAIDU_OCR_API_KEY", "")
BAIDU_SECRET_KEY = os.getenv("BAIDU_OCR_SECRET_KEY", "")

TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"


def get_access_token() -> str:
    """使用 API Key / Secret Key 获取 access_token"""
    resp = requests.post(
        TOKEN_URL,
        params={
            "grant_type": "client_credentials",
            "client_id": BAIDU_API_KEY,
            "client_secret": BAIDU_SECRET_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token", "")
    if not token:
        print(f"[ERROR] 获取 token 失败: {data}")
        sys.exit(1)
    print(f"[token] 获取成功: {token[:20]}...")
    return token


def ocr_by_url(image_url: str, access_token: str) -> dict:
    """通过图片 URL 调用百度 OCR"""
    resp = requests.post(
        f"{OCR_URL}?access_token={access_token}",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        data={
            "url": image_url,
            "detect_direction": "false",
            "detect_language": "false",
            "paragraph": "false",
            "probability": "false",
        },
        timeout=30,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.json()


def ocr_by_base64(image_path: str, access_token: str) -> dict:
    """通过本地图片 base64 调用百度 OCR"""
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    file_size_kb = os.path.getsize(image_path) / 1024
    print(f"[image] {image_path} ({file_size_kb:.1f} KB, base64 {len(encoded)} chars)")

    resp = requests.post(
        f"{OCR_URL}?access_token={access_token}",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        data={
            "image": encoded,
            "detect_direction": "false",
            "detect_language": "false",
            "paragraph": "false",
            "probability": "false",
        },
        timeout=30,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.json()


def print_result(label: str, result: dict):
    """格式化打印 OCR 结果"""
    print(f"\n{'─' * 50}")
    print(f"  [{label}]")
    print(f"{'─' * 50}")

    if result.get("error_code"):
        print(f"  [ERROR] code={result['error_code']}, msg={result.get('error_msg', '')}")
        return

    words_result = result.get("words_result", [])
    words_num = result.get("words_result_num", 0)
    print(f"  识别文字数: {words_num}")

    if not words_result:
        print("  (无识别结果)")
        return

    full_text_lines: list[str] = []
    for i, item in enumerate(words_result):
        text = item.get("words", "")
        full_text_lines.append(text)
        if i < 20:
            print(f"  [{i+1:02d}] {text}")
        elif i == 20:
            print(f"  ... (省略 {words_num - 20} 条)")

    full_text = "\n".join(full_text_lines)
    print(f"\n  ── 完整文本 ──")
    print(f"  {full_text[:500]}")
    if len(full_text) > 500:
        print(f"  ... (总长度 {len(full_text)} 字符)")


# ── Main ──────────────────────────────────────────────────

def main():
    print(f"[config] BAIDU_OCR_API_KEY: {'configured' if BAIDU_API_KEY else 'MISSING!'}")
    print(f"[config] BAIDU_OCR_SECRET_KEY: {'configured' if BAIDU_SECRET_KEY else 'MISSING!'}")
    if not BAIDU_API_KEY or not BAIDU_SECRET_KEY:
        print("[ERROR] 百度 OCR Key 未配置，请检查 .env")
        sys.exit(1)

    access_token = get_access_token()

    # ── 测试 1: URL 方式（百度官方 demo 图片） ──
    print("\n" + "=" * 50)
    print("  测试 1: URL 方式（百度 demo 图片）")
    print("=" * 50)
    try:
        result = ocr_by_url(
            "https://baidu-ai.bj.bcebos.com/ocr/general.png",
            access_token,
        )
        print_result("URL demo", result)
    except Exception as e:
        print(f"[ERROR] {e}")

    # ── 测试 2: 本地图片 ──
    print("\n" + "=" * 50)
    print("  测试 2: 本地图片 base64 上传")
    print("=" * 50)
    candidates = [
        ROOT_DIR / "img.png",
        ROOT_DIR / "datasets" / "1.jpg",
        ROOT_DIR / "datasets" / "aizhushou.png",
    ]
    for img_path in candidates:
        if img_path.exists():
            try:
                result = ocr_by_base64(str(img_path), access_token)
                print_result(f"本地: {img_path.name}", result)
            except Exception as e:
                print(f"[ERROR] {img_path.name}: {e}")
        else:
            print(f"[skip] 文件不存在: {img_path}")

    print("\n" + "=" * 50)
    print("  [done] 百度 OCR 测试完成")
    print("=" * 50)


if __name__ == "__main__":
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    main()
