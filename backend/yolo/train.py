"""
YOLO 训练入口（ultralytics，可选依赖）。

先准备数据集：
  python -m backend.yolo.export_dataset --images test1.jpg test2.jpg --out datasets/colony

再训练（需 pip install -r requirements-ml.txt）：
  python -m backend.yolo.train --data datasets/colony/dataset.yaml --epochs 50 --imgsz 640

权重输出默认 runs/detect/colony/weights/best.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def train(
    data: str,
    model: str = "yolov8n.pt",
    epochs: int = 50,
    imgsz: int = 640,
    batch: int = 8,
    device: str = "cpu",
    project: str = "runs/detect",
    name: str = "colony",
    workers: int = 2,
    patience: int = 15,
) -> Path:
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError as e:
        raise SystemExit(
            "未安装 ultralytics。请先执行: pip install -r requirements-ml.txt"
        ) from e

    data_path = Path(data)
    if not data_path.exists():
        raise SystemExit(f"数据集配置不存在: {data_path}（先运行 export_dataset）")

    yolo = YOLO(model)
    yolo.train(
        data=str(data_path),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        project=project,
        name=name,
        workers=workers,
        patience=patience,
        pretrained=True,
    )
    best = Path(project) / name / "weights" / "best.pt"
    if not best.exists():
        # 兼容不同 ultralytics 版本输出目录
        candidates = list(Path(project).glob(f"**/{name}/**/best.pt"))
        best = candidates[0] if candidates else best
    print(f"训练完成，权重: {best}")
    return best


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="训练菌落 YOLO 模型")
    parser.add_argument("--data", default="datasets/colony/dataset.yaml")
    parser.add_argument("--model", default="yolov8n.pt", help="初始权重，如 yolov8n.pt / yolov8s.pt")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="cpu", help="cpu / 0 / 0,1")
    parser.add_argument("--project", default="runs/detect")
    parser.add_argument("--name", default="colony")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--patience", type=int, default=15)
    args = parser.parse_args(argv)

    train(
        data=args.data,
        model=args.model,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=args.project,
        name=args.name,
        workers=args.workers,
        patience=args.patience,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
