# -*- coding: utf-8 -*-
r"""
python scripts/manual/extract_ocr.py "datasets/1.jpg"
百度OCR API测试脚本
使用百度智能云OCR服务识别图片中的文字
"""
import os
import sys
import requests
import base64
from dotenv import load_dotenv
from pathlib import Path


def get_access_token(api_key, secret_key):
    """获取百度OCR访问令牌"""
    token_url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": api_key,
        "client_secret": secret_key
    }
    try:
        response = requests.post(token_url, params=params, timeout=10)
        response.raise_for_status()
        result = response.json()
        if "access_token" in result:
            print(f"✅ 获取访问令牌成功")
            return result["access_token"]
        else:
            print(f"❌ 获取访问令牌失败: {result.get('error_description', '未知错误')}")
            return None
    except Exception as e:
        print(f"❌ 获取访问令牌异常: {str(e)}")
        return None


def baidu_ocr(image_path, access_token):
    """调用百度OCR识别图片文字"""
    # 支持的图片格式：JPG/JPEG/PNG/BMP/GIF
    ocr_url = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"

    # 读取图片并编码
    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"❌ 读取图片失败: {str(e)}")
        return None

    # 调用OCR API
    try:
        response = requests.post(
            ocr_url,
            data={
                "image": image_data,
                "access_token": access_token,
                "language_type": "CHN_ENG"  # 中英混合识别
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print("❌ OCR请求超时")
        return None
    except Exception as e:
        print(f"❌ OCR请求异常: {str(e)}")
        return None


def parse_ocr_result(result):
    """解析OCR识别结果"""
    if not result or "words_result" not in result:
        return None

    # 提取所有识别到的文字
    text_lines = []
    for item in result["words_result"]:
        text_lines.append(item["words"])

    return "\n".join(text_lines)


def test_ocr(image_path):
    """测试OCR识别"""
    print("=" * 60)
    print("百度OCR API测试工具")
    print("=" * 60)

    # 加载环境变量
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')

    # 获取配置
    api_key = os.getenv("OCR_API_KEY")
    secret_key = os.getenv("OCR_SECRET_KEY")

    if not api_key or not secret_key:
        print("❌ 请配置 OCR_API_KEY 和 OCR_SECRET_KEY")
        return

    print(f"📋 API Key: {api_key[:10]}...")
    print(f"📋 Secret Key: {secret_key[:10]}...")
    print(f"📷 测试图片: {image_path}")

    # 检查图片文件
    if not os.path.exists(image_path):
        print(f"❌ 图片文件不存在: {image_path}")
        return

    # 获取访问令牌
    access_token = get_access_token(api_key, secret_key)
    if not access_token:
        return

    # 调用OCR识别
    print("\n🔍 正在识别图片...")
    result = baidu_ocr(image_path, access_token)

    if not result:
        return

    # 解析结果
    text = parse_ocr_result(result)

    if text:
        print("\n🎉 OCR识别成功！")
        print("=" * 60)
        print("识别结果：")
        print("-" * 60)
        print(text)
        print("-" * 60)
        print(f"共识别 {len(text)} 个字符")
    else:
        print("❌ 未识别到文字")

    # 打印完整API响应（调试用）
    print("\n📊 API响应详情:")
    print(f"状态码: {result.get('log_id', 'N/A')}")
    print(f"识别数量: {len(result.get('words_result', []))} 个文字块")


if __name__ == "__main__":
    # 获取图片路径参数
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    if len(sys.argv) < 2:
        print("用法: python scripts/manual/extract_ocr.py <图片路径>")
        print("示例: python scripts/manual/extract_ocr.py datasets/test_image.png")
        sys.exit(1)

    image_path = sys.argv[1]
    test_ocr(image_path)
