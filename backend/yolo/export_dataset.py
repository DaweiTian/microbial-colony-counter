"""
从图片批量导出伪标签数据集（smart_count → YOLO txt）。

用法（仓库根目录）：
  python -m backend.yolo.export_dataset --images test1.jpg test2.jpg --out datasets/colony
  python -m backend.yolo.export_dataset --image-dir /path/to/plates --out datasets/colony --val-ratio 0.2

输出结构：
  datasets/colony/
    images/train/*.jpg
    images/val/*.jpg
    labels/train/*.txt
    labels/val/*.txt
    dataset.yaml
    export_meta.json
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.smart import smart_count
from backend.yolo.labels import details_to_yolo_lines, write_label_file

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def collect_images(paths: Sequence[str], image_dir: Optional[str]) -> List[Path]:
    files: List[Path] = []
    for p in paths or []:
        pp = Path(p)
        if pp.is_file() and pp.suffix.lower() in IMAGE_EXTS:
            files.append(pp)
        elif pp.is_dir():
            files.extend(sorted(q for q in pp.iterdir() if q.suffix.lower() in IMAGE_EXTS))
    if image_dir:
        d = Path(image_dir)
        files.extend(sorted(q for q in d.rglob("*") if q.suffix.lower() in IMAGE_EXTS))
    # 去重保序
    seen = set()
    out: List[Path] = []
    for f in files:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(f)
    return out


def export_one(
    image_path: Path,
    split: str,
    out_root: Path,
    strategy: str = "smart",
) -> Dict:
    image = cv2.imread(str(image_path))
    if image is None:
        return {"image": str(image_path), "ok": False, "error": "decode failed"}

    h, w = image.shape[:2]
    if strategy == "smart":
        result = smart_count(image)
    else:
        from backend.core.algorithm import process_image
        result = process_image(image, detect_petri_dish=True, use_watershed=True, segment_mode="labels")

    if result.get("error"):
        return {"image": str(image_path), "ok": False, "error": result["error"]}

    details = result.get("colony_details") or []
    lines = details_to_yolo_lines(details, w, h)

    stem = image_path.stem
    img_out = out_root / "images" / split / f"{stem}.jpg"
    lbl_out = out_root / "labels" / split / f"{stem}.txt"
    img_out.parent.mkdir(parents=True, exist_ok=True)
    lbl_out.parent.mkdir(parents=True, exist_ok=True)

    # 统一存 JPEG，避免训练管线格式混杂
    cv2.imwrite(str(img_out), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    write_label_file(lbl_out, lines)

    return {
        "image": str(image_path),
        "ok": True,
        "split": split,
        "count": result.get("count"),
        "n_labels": len(lines),
        "strategy": result.get("strategy") or strategy,
        "petri_detected": result.get("petri_detected"),
        "out_image": str(img_out),
        "out_label": str(lbl_out),
        "size": [w, h],
    }


def write_dataset_yaml(out_root: Path, root: Path) -> None:
    # ultralytics 相对路径约定
    yaml_text = (
        f"path: {root.as_posix()}\n"
        "train: images/train\n"
        "val: images/val\n"
        "names:\n"
        "  0: colony\n"
    )
    (out_root / "dataset.yaml").write_text(yaml_text, encoding="utf-8")


def run_export(
    images: Sequence[str],
    image_dir: Optional[str],
    out: str,
    val_ratio: float = 0.2,
    seed: int = 42,
    strategy: str = "smart",
) -> Dict:
    files = collect_images(images, image_dir)
    if not files:
        raise SystemExit("未找到图片，请用 --images 或 --image-dir 指定")

    out_root = Path(out)
    out_root.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    idx = list(range(len(files)))
    rng.shuffle(idx)
    n_val = int(round(len(files) * val_ratio))
    val_set = set(idx[: max(1, n_val) if val_ratio > 0 else 0])

    meta_items: List[Dict] = []
    for i, f in enumerate(files):
        split = "val" if i in val_set else "train"
        item = export_one(f, split, out_root, strategy=strategy)
        meta_items.append(item)
        status = "OK" if item.get("ok") else "FAIL"
        print(f"[{status}] {f.name} → {split} count={item.get('count')} labels={item.get('n_labels')}")

    write_dataset_yaml(out_root, out_root.resolve())
    payload = {
        "out": str(out_root.resolve()),
        "strategy": strategy,
        "val_ratio": val_ratio,
        "n_images": len(files),
        "n_ok": sum(1 for m in meta_items if m.get("ok")),
        "items": meta_items,
    }
    (out_root / "export_meta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n数据集已写入: {out_root.resolve()}")
    print(f"  train/val: {payload['n_ok'] - sum(1 for m in meta_items if m.get('ok') and m.get('split')=='val')}"
          f" / {sum(1 for m in meta_items if m.get('ok') and m.get('split')=='val')}")
    print(f"  yaml: {out_root / 'dataset.yaml'}")
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="导出 YOLO 伪标签数据集")
    parser.add_argument("--images", nargs="*", default=[], help="图片路径（可多个）")
    parser.add_argument("--image-dir", default=None, help="图片目录（递归）")
    parser.add_argument("--out", default="datasets/colony", help="输出数据集根目录")
    parser.add_argument("--val-ratio", type=float, default=0.2, help="验证集比例")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--strategy", default="smart", choices=["smart", "labels"],
        help="伪标签来源：smart 选优 / 固定 labels 分水岭",
    )
    args = parser.parse_args(argv)
    run_export(
        images=args.images,
        image_dir=args.image_dir,
        out=args.out,
        val_ratio=args.val_ratio,
        seed=args.seed,
        strategy=args.strategy,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
