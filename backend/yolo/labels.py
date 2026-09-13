"""
YOLO 标注契约（单类 colony）。

txt 每行：`class_id cx cy w h`，坐标均相对图像宽高归一化到 [0, 1]。
由中心点+半径生成方框：w = h = 2*r / dim。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

CLASS_NAME = "colony"
CLASS_ID = 0
# 无面积时使用的默认半径（像素）
DEFAULT_RADIUS_PX = 6


def _radius_from_area(area: Optional[float], default: float = DEFAULT_RADIUS_PX) -> float:
    if area is None or area <= 0:
        return float(default)
    # area ≈ pi r^2
    return max(2.0, (float(area) / 3.141592653589793) ** 0.5)


def details_to_yolo_lines(
    details: Sequence[Dict[str, Any]],
    image_width: int,
    image_height: int,
    min_box_px: float = 3.0,
    default_radius: float = DEFAULT_RADIUS_PX,
) -> List[str]:
    """
    colony_details → YOLO txt 行。

    details 项需含 x, y；area 可选。
    """
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image size must be positive")

    lines: List[str] = []
    for d in details:
        x = float(d.get("x", 0))
        y = float(d.get("y", 0))
        r = _radius_from_area(d.get("area"), default=default_radius)
        side = max(min_box_px, 2.0 * r)
        bw = side / image_width
        bh = side / image_height
        cx = x / image_width
        cy = y / image_height
        # 裁剪到合法范围
        bw = min(bw, 1.0)
        bh = min(bh, 1.0)
        cx = min(max(cx, bw / 2), 1.0 - bw / 2)
        cy = min(max(cy, bh / 2), 1.0 - bh / 2)
        lines.append(f"{CLASS_ID} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    return lines


def yolo_lines_to_details(
    lines: Sequence[str],
    image_width: int,
    image_height: int,
) -> List[Dict[str, Any]]:
    """YOLO txt 行 → colony_details（id/x/y/area）。"""
    details: List[Dict[str, Any]] = []
    for i, line in enumerate(lines, start=1):
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        cls = int(float(parts[0]))
        if cls != CLASS_ID:
            continue
        cx, cy, bw, bh = (float(v) for v in parts[1:5])
        x = cx * image_width
        y = cy * image_height
        area = max(1, int(bw * image_width * bh * image_height))
        details.append({"id": i, "x": int(round(x)), "y": int(round(y)), "area": area, "circularity": None})
    return details


def write_label_file(path, lines: Sequence[str]) -> None:
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def read_label_file(path) -> List[str]:
    from pathlib import Path
    text = Path(path).read_text(encoding="utf-8")
    return [ln for ln in text.splitlines() if ln.strip()]
