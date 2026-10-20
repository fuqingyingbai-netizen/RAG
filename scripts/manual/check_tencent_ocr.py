import base64
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "backend"))
load_dotenv(ROOT_DIR / ".env")


def image_to_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def mask(value: str) -> str:
    value = value or ""
    return value[:8] + "..." if value else ""


def main() -> int:
    print("[env] 腾讯云 OCR 配置检查")
    print(f"OCR_PROVIDER: {os.getenv('OCR_PROVIDER')}")
    print(f"TENCENT_SECRET_ID: {mask(os.getenv('TENCENT_SECRET_ID', ''))}")
    print(f"TENCENT_SECRET_KEY: {mask(os.getenv('TENCENT_SECRET_KEY', ''))}")
    print(f"TENCENT_OCR_REGION: {os.getenv('TENCENT_OCR_REGION', 'ap-guangzhou')}")

    image_path = ROOT_DIR / "datasets" / "1.jpg"
    if not image_path.exists():
        print(f"[ERROR] 测试图片不存在: {image_path}")
        return 1

    from backend.research_workflow import ResearchWorkflow

    workflow = ResearchWorkflow()

    def emit(event: dict):
        print(f"[trace] {event.get('label')}: {event.get('detail')}")

    print(f"[test] 图片: {image_path}")
    text = workflow._tencent_ocr(image_to_data_url(image_path), emit=emit)
    print("\n=== OCR 识别结果 ===")
    print(text or "空")
    if not text.strip():
        print("\n[WARN] 腾讯云 OCR 调用完成，但没有识别出文本，请看上面的 trace")
        return 2
    print("\n[OK] 腾讯云 OCR 测试成功")
    return 0


if __name__ == "__main__":
    # Handle help before running the legacy manual acceptance steps.
    import argparse as _manual_argparse
    _manual_argparse.ArgumentParser(description=__doc__ or "手工验收工具；直接运行会使用本机配置。").parse_known_args()
    raise SystemExit(main())
