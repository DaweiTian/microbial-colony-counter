"""密菌落分离 / smart / detector 单元测试。"""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.algorithm import process_image
from backend.core.blobcount import count_from_labels, local_maxima_mask, watershed_labels
from backend.core.detector import DetectorRegistry, detect_colonies
from backend.core.smart import smart_count


def _synthetic_dish(n_blobs=12, size=400):
    img = np.full((size, size, 3), 180, dtype=np.uint8)
    rng = np.random.default_rng(0)
    centers = []
    for i in range(n_blobs):
        x = int(rng.uniform(80, size - 80))
        y = int(rng.uniform(80, size - 80))
        r = int(rng.uniform(8, 14))
        cv2.circle(img, (x, y), r, (245, 245, 245), -1)
        centers.append((x, y))
    return img, centers


def test_labels_mode_not_collapse():
    img, centers = _synthetic_dish(12)
    classic = process_image(img, detect_petri_dish=False, use_watershed=False)
    labels = process_image(
        img, detect_petri_dish=False, use_watershed=True, segment_mode="labels",
        min_area=30, max_area=2000,
    )
    assert classic["error"] is None
    assert labels["error"] is None
    assert labels["count"] >= max(3, classic["count"] // 3)
    # 旧分水岭在 test1 上会塌到 11/95；合成图上 labels 不应接近 0
    assert labels["count"] > 0


def test_peaks_mode_runs():
    img, _ = _synthetic_dish(10)
    r = process_image(img, segment_mode="peaks", min_area=20)
    assert r["error"] is None
    assert r["count"] > 0


def test_classic_default_unchanged_signature():
    img, _ = _synthetic_dish(8)
    r = process_image(img)
    assert "count" in r and "colony_details" in r
    assert r["segment_mode"] == "classic"


def test_watershed_labels_pipeline():
    img, _ = _synthetic_dish(15)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 合成图为亮斑点，亮=前景
    _, th = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    peaks = local_maxima_mask(th, kernel_size=9, min_dist_value=1.5)
    assert peaks is not None
    labels = watershed_labels(th, seed_kernel=9, min_dist_value=1.5)
    res = count_from_labels(labels, min_area=20, max_area=5000)
    assert res["count"] >= 5


def test_smart_count_returns_strategy():
    img, _ = _synthetic_dish(12)
    r = smart_count(img)
    assert r["smart"] is True
    assert r["strategy"] is not None
    assert r["count"] > 0
    assert isinstance(r["candidates"], list) and len(r["candidates"]) >= 3


def test_registry_fallback():
    reg = DetectorRegistry()
    assert reg.get("nope").name == "opencv"
    det = reg.get("opencv-classic")
    img, _ = _synthetic_dish(6)
    out = det.detect(img)
    assert out.count >= 0
    assert out.meta.get("detector") == "opencv-classic"


def test_detect_colonies_helper():
    img, _ = _synthetic_dish(8)
    out = detect_colonies(img, detector="opencv")
    assert out.count > 0


def test_real_images_smoke():
    for name in ("test1.jpg", "test2.jpg"):
        p = ROOT / name
        if not p.exists():
            continue
        img = cv2.imread(str(p))
        labels = process_image(img, detect_petri_dish=True, use_watershed=True, segment_mode="labels")
        classic = process_image(img, detect_petri_dish=True)
        assert labels["error"] is None
        # test1 旧分水岭=11，修复后应与 classic 同量级（>=40%）
        if name == "test1.jpg":
            assert labels["count"] >= classic["count"] * 0.4


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {fn.__name__}: {e}")
    print("OK" if failed == 0 else f"FAILED {failed}")
    raise SystemExit(1 if failed else 0)
