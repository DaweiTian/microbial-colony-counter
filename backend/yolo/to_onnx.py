"""
将训练好的 best.pt 导出为 ONNX，供本地 OnnxYoloDetector 使用。

用法：
  python -m backend.yolo.to_onnx --weights runs/detect/colony/weights/best.pt --out models/colony_yolo.onnx
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "models" / "colony_yolo.onnx"


def export_onnx(
    weights: str,
    out: str = str(DEFAULT_OUT),
    imgsz: int = 640,
    half: bool = False,
) -> Path:
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError as e:
        raise SystemExit(
            "未安装 ultralytics。请先执行: pip install -r requirements-ml.txt"
        ) from e

    w = Path(weights)
    if not w.exists():
        raise SystemExit(f"权重不存在: {w}")

    yolo = YOLO(str(w))
    exported = yolo.export(format="onnx", imgsz=imgsz, half=half, simplify=True)
    exported_path = Path(str(exported))
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if exported_path.resolve() != out_path.resolve():
        shutil.copy2(exported_path, out_path)
        # 清理 ultralytics 旁路导出文件（若不同路径）
        if exported_path.exists() and exported_path.suffix == ".onnx":
            try:
                exported_path.unlink()
            except OSError:
                pass
    print(f"ONNX 已写入: {out_path.resolve()}")
    return out_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="导出 YOLO ONNX")
    parser.add_argument("--weights", required=True, help="best.pt 路径")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--half", action="store_true")
    args = parser.parse_args(argv)
    export_onnx(args.weights, args.out, imgsz=args.imgsz, half=args.half)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
