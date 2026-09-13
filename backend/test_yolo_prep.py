"""YOLO 标签转换与解码单测（不依赖 ultralytics）。"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.yolo.labels import details_to_yolo_lines, yolo_lines_to_details
from backend.core.detector import _decode_yolo_output, _nms_boxes, _letterbox
import cv2


def test_details_roundtrip():
    details = [
        {"x": 100, "y": 50, "area": 100},
        {"x": 200, "y": 150, "area": 0},  # 默认半径
    ]
    lines = details_to_yolo_lines(details, 400, 300)
    assert len(lines) == 2
    parts = lines[0].split()
    assert parts[0] == "0"
    assert 0 <= float(parts[1]) <= 1
    back = yolo_lines_to_details(lines, 400, 300)
    assert len(back) == 2
    assert abs(back[0]["x"] - 100) <= 2
    assert abs(back[0]["y"] - 50) <= 2


def test_decode_v8_layout():
    # 模拟 (1, 5, N)：cx cy w h score，中心 (100,100) 框 20x20
    n = 4
    pred = np.zeros((1, 5, n), dtype=np.float32)
    pred[0, :, 0] = [100, 100, 20, 20, 0.9]
    pred[0, :, 1] = [100, 100, 20, 20, 0.1]  # 低分
    pred[0, :, 2] = [300, 200, 10, 10, 0.8]
    dets = _decode_yolo_output(pred, conf_thres=0.25, img_w=400, img_h=300, scale=1.0, pad_x=0, pad_y=0)
    assert dets.shape[0] == 2
    assert abs(dets[0, 4] - 0.9) < 1e-5


def test_nms_suppresses_overlap():
    boxes = np.array([
        [10, 10, 30, 30],
        [12, 12, 32, 32],
        [100, 100, 120, 120],
    ], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
    keep = _nms_boxes(boxes, scores, iou_thres=0.5)
    assert len(keep) == 2
    assert keep[0] == 0


def test_letterbox_shapes():
    img = np.zeros((300, 400, 3), dtype=np.uint8)
    boxed, scale, px, py = _letterbox(img, 640, 640)
    assert boxed.shape == (640, 640, 3)
    assert scale > 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print("OK" if failed == 0 else f"FAILED {failed}")
    raise SystemExit(1 if failed else 0)
