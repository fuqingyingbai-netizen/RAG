# -*- coding: utf-8 -*-
"""
测试阿里百炼视觉模型 API 连接
"""
import os
import pytest

# Real-provider diagnostic scripts are opt-in; offline regressions must not consume account quota.
pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_PROVIDER_TESTS") != "1", reason="Set RUN_LIVE_PROVIDER_TESTS=1 for live provider diagnostics")
import requests
import base64
from dotenv import load_dotenv
from pathlib import Path

# 加载环境变量
load_dotenv(Path(__file__).resolve().parents[2] / '.env')


def test_text_api():
    """测试文本模型连接"""
    print("=== 测试文本模型 ===")
    api_key = os.getenv("ARK_API_KEY")
    base_url = os.getenv("BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    model = os.getenv("MODEL", "qwen-plus")

    if not api_key:
        print("❌ ARK_API_KEY 未配置")
        return False

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "你好，测试连接"}],
                "temperature": 0.1,
            },
            timeout=30,
        )

        if resp.status_code == 200:
            result = resp.json()
            content = result["choices"][0]["message"]["content"]
            print(f"✅ 文本模型连接成功！")
            print(f"   响应: {content[:50]}...")
            return True
        else:
            print(f"❌ 文本模型请求失败: HTTP {resp.status_code}")
            print(f"   错误: {resp.text}")
            return False

    except requests.exceptions.Timeout:
        print("❌ 文本模型请求超时")
        return False
    except Exception as e:
        print(f"❌ 文本模型请求异常: {str(e)}")
        return False


def test_vision_api(image_path=None):
    """测试视觉模型连接"""
    print("\n=== 测试视觉模型 ===")
    api_key = os.getenv("VISION_API_KEY") or os.getenv("ARK_API_KEY")
    base_url = (os.getenv("VISION_BASE_URL") or os.getenv("BASE_URL") or "").rstrip("/")
    model = os.getenv("VISION_MODEL", "qwen-vl-plus")

    if not api_key:
        print("❌ API_KEY 未配置")
        return False

    if not base_url:
        print("❌ BASE_URL 未配置")
        return False

    # 如果没有提供图片，使用一个在线测试图片
    if not image_path or not os.path.exists(image_path):
        print("⚠️ 未提供本地图片，使用在线测试图片")
        image_url = "https://neeko-copilot.bytedance.net/api/text2image?prompt=cute%20cat%20sitting%20on%20chair&width=512&height=512"
        content = [
            {"type": "text", "text": "请描述这张图片的内容"},
            {"type": "image_url", "image_url": {"url": image_url}}
        ]
    else:
        # 使用本地图片
        print(f"📷 使用本地图片: {image_path}")
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        content = [
            {"type": "text", "text": "请描述这张图片的内容"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
        ]

    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.1,
            },
            timeout=60,
        )

        if resp.status_code == 200:
            result = resp.json()
            content = result["choices"][0]["message"]["content"]
            print(f"✅ 视觉模型连接成功！")
            print(f"   响应: {content[:100]}...")
            return True
        else:
            print(f"❌ 视觉模型请求失败: HTTP {resp.status_code}")
            print(f"   错误: {resp.text}")
            return False

    except requests.exceptions.Timeout:
        print("❌ 视觉模型请求超时（60秒）")
        return False
    except Exception as e:
        print(f"❌ 视觉模型请求异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def check_network():
    """检查网络连接"""
    print("\n=== 检查网络连接 ===")
    try:
        # 测试连接阿里百炼
        resp = requests.get("https://dashscope.aliyuncs.com", timeout=10)
        print(f"✅ 网络连接正常，阿里百炼可访问")
        return True
    except requests.exceptions.Timeout:
        print("❌ 网络连接超时，无法访问阿里百炼")
        return False
    except Exception as e:
        print(f"❌ 网络连接异常: {str(e)}")
        return False


if __name__ == "__main__":
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    print("=" * 50)
    print("阿里百炼 API 测试工具")
    print("=" * 50)

    # 检查网络
    check_network()

    # 测试文本模型
    text_ok = test_text_api()

    # 测试视觉模型
    vision_ok = test_vision_api()

    print("\n" + "=" * 50)
    print("测试结果汇总")
    print("=" * 50)
    print(f"文本模型: {'✅ 通过' if text_ok else '❌ 失败'}")
    print(f"视觉模型: {'✅ 通过' if vision_ok else '❌ 失败'}")

    if not text_ok and not vision_ok:
        print("\n❌ 建议检查：")
        print("   1. 网络连接是否正常")
        print("   2. ARK_API_KEY 是否正确")
        print("   3. 是否需要设置代理")
        print("   4. BASE_URL 是否正确")
