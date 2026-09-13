"""一键智能计数：估参 + 多策略试跑 + 无真值选优。"""

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from backend.core.algorithm import detect_petri_dish_circle, process_image


def _odd(v: int) -> int:
    v = int(max(1, v))
    return v if v % 2 == 1 else v + 1


def estimate_base_params(image: np.ndarray, petri_circle: Optional[Tuple[int, int, int]]) -> Dict[str, Any]:
    """从图像统计估计基础参数（在 process_image 内部缩放之前的坐标系）。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]

    if petri_circle is not None:
        cx, cy, r = petri_circle
        mask = np.zeros_like(gray)
        cv2.circle(mask, (int(cx), int(cy)), int(r * 0.92), 255, -1)
        roi = gray[mask > 0]
        dish_r = float(r)
    else:
        roi = gray.ravel()
        dish_r = float(min(h, w) * 0.45)

    if roi.size == 0:
        roi = gray.ravel()

    mean_v = float(np.mean(roi))
    std_v = float(np.std(roi))
    # Otsu on ROI
    otsu, _ = cv2.threshold(roi.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 经验映射：对比度低 → 更强自适应 C；高光多 → 中等模糊
    if std_v < 25:
        adaptive_c = 4
        blur = 9
    elif std_v < 45:
        adaptive_c = 3
        blur = 7
    else:
        adaptive_c = 2
        blur = 5

    # 面积先验：典型菌落半径约为皿半径的 0.8%～4%
    min_area = max(12, int(np.pi * (dish_r * 0.008) ** 2))
    max_area = max(min_area * 8, int(np.pi * (dish_r * 0.045) ** 2))

    return {
        "blur_ksize": _odd(blur),
        "thresh_method": "adaptive",
        "thresh_val": int(otsu),
        "adaptive_block_size": _odd(11 if mean_v > 90 else 15),
        "adaptive_c": adaptive_c,
        "min_area": min_area,
        "max_area": max_area,
        "min_distance_from_edge": max(8, int(dish_r * 0.03)),
        "detect_petri_dish": petri_circle is not None,
        "use_watershed": False,
        "min_circularity": 0.0,
        "seed_kernel": _odd(max(9, int(dish_r * 0.035))),
        "min_dist_value": max(1.5, dish_r * 0.008),
        "_mean": mean_v,
        "_std": std_v,
        "_otsu": float(otsu),
        "_dish_r": dish_r,
    }


def _score_result(result: Dict[str, Any], base: Dict[str, Any]) -> float:
    """无真值时的启发式评分（越高越好）。"""
    details = result.get("colony_details") or []
    count = int(result.get("count") or 0)
    if result.get("error") or count <= 0:
        return -1e9

    circs = [d.get("circularity") for d in details if d.get("circularity") is not None]
    areas = [float(d.get("area") or 0) for d in details if d.get("area") is not None]

    shape_score = 0.0
    if circs:
        med_c = float(np.median(circs))
        if 0.45 <= med_c <= 0.95:
            shape_score = 1.2
        elif 0.30 <= med_c < 0.45:
            shape_score = 0.3
        elif med_c > 0.95:
            shape_score = 0.5
        else:
            shape_score = -1.0

    area_score = 0.0
    if areas:
        med_a = float(np.median(areas))
        q1, q3 = np.percentile(areas, [25, 75])
        iqr = float(q3 - q1)
        if med_a > 0 and iqr / med_a < 1.5:
            area_score = 1.0
        elif med_a > 0 and iqr / med_a < 3.0:
            area_score = 0.4
        else:
            area_score = -0.6
        ref_min = max(10, float(base.get("min_area") or 50) * 0.4)
        tiny_ratio = float(np.mean([a < ref_min for a in areas]))
        area_score -= tiny_ratio * 2.0

    # 计数密度：极低/极高都不可信
    if count < 12:
        density_score = -2.5
    elif count < 25:
        density_score = -0.5
    elif 25 <= count <= 1200:
        density_score = 1.0
    elif 1200 < count <= 2500:
        density_score = 0.0
    else:
        density_score = -2.0

    petri_bonus = 0.4 if result.get("petri_circle") is not None else 0.0
    return 1.4 * shape_score + 1.0 * area_score + 1.2 * density_score + petri_bonus


def smart_count(image: np.ndarray, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    一键智能计数。返回 process_image 兼容超集。

    额外字段：strategy, params, candidates, smart=True
    """
    if image is None or image.size == 0:
        return {
            "count": 0, "error": "empty image", "colony_details": [],
            "processed_image": None, "binary_image": None, "petri_circle": None,
            "strategy": None, "params": {}, "candidates": [], "smart": True,
        }

    petri_circle = detect_petri_dish_circle(image)
    base = estimate_base_params(image, petri_circle)
    has_petri = petri_circle is not None

    est_public = {
        "blur_ksize": base["blur_ksize"],
        "thresh_method": base["thresh_method"],
        "adaptive_block_size": base["adaptive_block_size"],
        "adaptive_c": base["adaptive_c"],
        # 面积上限放宽，避免把融合菌落整块丢掉
        "min_area": max(15, int(base["min_area"] * 0.7)),
        "max_area": max(int(base["max_area"]), 4000),
        "min_distance_from_edge": base["min_distance_from_edge"],
        "seed_kernel": base["seed_kernel"],
        "min_dist_value": base["min_dist_value"],
        "detect_petri_dish": has_petri,
    }

    if overrides:
        est_public.update({k: v for k, v in overrides.items() if not str(k).startswith("_")})

    # 1) 库存默认参数（与 v1.1.2 经典路径对齐）——应作为主候选
    # 2) 估参变体  3) otsu 手动阈值
    strategies = [
        ("default_petri" if has_petri else "default", {
            "segment_mode": "classic",
            "use_watershed": False,
            "detect_petri_dish": has_petri,
        }),
        ("default_labels" if has_petri else "default_labels", {
            "segment_mode": "labels",
            "use_watershed": True,
            "seed_kernel": 11,
            "min_dist_value": 1.8,
            "detect_petri_dish": has_petri,
        }),
        ("est_contour", {
            "segment_mode": "classic",
            "use_watershed": False,
            **est_public,
        }),
        ("est_labels", {
            "segment_mode": "labels",
            "use_watershed": True,
            **est_public,
        }),
        ("default_peaks", {
            "segment_mode": "peaks",
            "use_watershed": False,
            "seed_kernel": 11,
            "min_dist_value": 1.8,
            "detect_petri_dish": has_petri,
        }),
        ("default_otsu", {
            "segment_mode": "classic",
            "use_watershed": False,
            "thresh_method": "manual",
            "thresh_val": int(base.get("_otsu") or 100),
            "detect_petri_dish": has_petri,
        }),
    ]

    candidates: List[Dict[str, Any]] = []
    best: Optional[Dict[str, Any]] = None
    best_name = None
    best_score = -1e18
    best_params: Dict[str, Any] = {}

    public_keys = [
        "blur_ksize", "thresh_method", "thresh_val", "adaptive_block_size", "adaptive_c",
        "min_area", "max_area", "min_distance_from_edge", "detect_petri_dish",
        "use_watershed", "min_circularity", "seed_kernel", "segment_mode", "min_dist_value",
    ]

    for i, (name, extra) in enumerate(strategies):
        # 默认策略：只传 extra，让 process_image 用库内默认
        if name.startswith("default"):
            call_kwargs = {k: extra[k] for k in public_keys if k in extra}
        else:
            params = dict(est_public)
            params.update(extra)
            call_kwargs = {k: params[k] for k in public_keys if k in params}
        try:
            r = process_image(image, **call_kwargs)
        except Exception as e:  # pragma: no cover
            candidates.append({"strategy": name, "count": 0, "score": -1e9, "error": str(e)})
            continue
        score = _score_result(r, base)
        candidates.append({
            "strategy": name,
            "count": r.get("count", 0),
            "score": round(float(score), 4),
            "error": r.get("error"),
            "params": call_kwargs,
        })
        if score > best_score:
            best_score = score
            best = r
            best_name = name
            best_params = call_kwargs
        # 默认策略已足够好时，跳过后续估参变体，缩短密菌落等待
        if i >= 1 and best_score >= 3.0 and name.startswith("default"):
            # 仍保留已跑过的候选，供 UI 展示
            remaining_skipped = [s[0] for s in strategies[i + 1:]]
            if remaining_skipped:
                candidates.append({
                    "strategy": "_skipped",
                    "count": 0,
                    "score": None,
                    "note": f"跳过 {remaining_skipped}（默认策略已足够）",
                })
            break

    if best is None:
        return {
            "count": 0, "error": "all strategies failed", "colony_details": [],
            "processed_image": None, "binary_image": None, "petri_circle": petri_circle,
            "strategy": None, "params": {}, "candidates": candidates, "smart": True,
        }

    best = dict(best)
    best["strategy"] = best_name
    best["params"] = best_params
    best["candidates"] = candidates
    best["smart"] = True
    if best.get("petri_circle") is None:
        best["petri_circle"] = petri_circle
    best["petri_detected"] = has_petri
    return best
