"""密菌落分离与计数：距离变换局部极大 + 分水岭标签直计数。"""

from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


def _odd(v: int) -> int:
    v = int(max(3, v))
    return v if v % 2 == 1 else v + 1


def distance_map(binary: np.ndarray, open_iterations: int = 1) -> Tuple[np.ndarray, np.ndarray]:
    """返回 (opening, smoothed_distance)。"""
    kernel = np.ones((3, 3), np.uint8)
    opening = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, kernel, iterations=max(1, open_iterations)
    )
    if cv2.countNonZero(opening) == 0:
        return opening, np.zeros(binary.shape, dtype=np.float32)
    dist = cv2.distanceTransform(opening, cv2.DIST_L2, 5)
    dist_s = cv2.GaussianBlur(dist, (5, 5), 0)
    return opening, dist_s


def _nms_on_distance(
    dist_s: np.ndarray,
    candidate_mask: np.ndarray,
    min_sep: int,
) -> np.ndarray:
    """在候选极大上按距离场强度做 NMS，抑制过密种子。"""
    if min_sep <= 1 or cv2.countNonZero(candidate_mask) == 0:
        return candidate_mask
    ys, xs = np.where(candidate_mask > 0)
    if ys.size == 0:
        return candidate_mask
    vals = dist_s[ys, xs]
    order = np.argsort(-vals)
    suppressed = np.zeros(dist_s.shape, dtype=bool)
    keep = np.zeros(dist_s.shape, dtype=np.uint8)
    r = int(min_sep)
    for idx in order:
        y, x = int(ys[idx]), int(xs[idx])
        if suppressed[y, x]:
            continue
        keep[y, x] = 255
        y0, y1 = max(0, y - r), min(dist_s.shape[0], y + r + 1)
        x0, x1 = max(0, x - r), min(dist_s.shape[1], x + r + 1)
        suppressed[y0:y1, x0:x1] = True
    return keep


def local_maxima_mask(
    binary: np.ndarray,
    kernel_size: int = 11,
    min_dist_value: float = 1.8,
    open_iterations: int = 1,
    min_peak_sep: Optional[int] = None,
) -> np.ndarray:
    """
    距离变换上的稳健局部极大作为菌落种子。
    - 对距离场做高斯平滑后再取极大，避免一个菌落多个种子
    - min_dist_value：极大处距离变换值下限，抑制噪点
    - min_peak_sep：种子最小间距（NMS），默认取 kernel_size//2
    """
    kernel_size = _odd(kernel_size)
    opening, dist_s = distance_map(binary, open_iterations=open_iterations)
    if cv2.countNonZero(opening) == 0:
        return np.zeros_like(binary)

    local_max = cv2.dilate(dist_s, np.ones((kernel_size, kernel_size), np.uint8))
    peaks = ((dist_s >= local_max - 1e-6) & (dist_s >= float(min_dist_value))).astype(np.uint8)

    sep = int(min_peak_sep) if min_peak_sep else max(3, kernel_size // 2)
    peaks = _nms_on_distance(dist_s, peaks, sep)
    peaks = (peaks > 0).astype(np.uint8) * 255

    n = cv2.connectedComponents(peaks)[0] - 1
    k = kernel_size
    while n > 1200 and k < 41:
        k = _odd(k + 4)
        local_max = cv2.dilate(dist_s, np.ones((k, k), np.uint8))
        cand = ((dist_s >= local_max - 1e-6) & (dist_s >= float(min_dist_value))).astype(np.uint8)
        peaks = ( _nms_on_distance(dist_s, cand, max(sep, k // 2)) > 0 ).astype(np.uint8) * 255
        n = cv2.connectedComponents(peaks)[0] - 1
    return peaks


def watershed_labels(
    binary: np.ndarray,
    seed_kernel: int = 11,
    min_dist_value: float = 1.8,
    open_iterations: int = 1,
    min_peak_sep: Optional[int] = None,
) -> np.ndarray:
    """
    对二值前景做分水岭，返回标签图：
    0 = 背景/边界，>=2 = 各菌落区域标签。
    """
    kernel = np.ones((3, 3), np.uint8)
    opening, dist_s = distance_map(binary, open_iterations=open_iterations)
    if cv2.countNonZero(opening) == 0:
        return np.zeros(binary.shape, dtype=np.int32)

    sure_bg = cv2.dilate(opening, kernel, iterations=2)
    peaks = local_maxima_mask(
        opening,
        kernel_size=seed_kernel,
        min_dist_value=min_dist_value,
        open_iterations=1,
        min_peak_sep=min_peak_sep,
    )
    if cv2.countNonZero(peaks) == 0:
        _, peaks = cv2.threshold(
            dist_s, max(1.5, 0.25 * float(dist_s.max())), 255, cv2.THRESH_BINARY
        )
        peaks = np.uint8(peaks)
    # 极端情况下 peaks 仍可能为空 → 至少取 opening 的中心一点作种子，避免 markers 全 0
    if cv2.countNonZero(peaks) == 0 and cv2.countNonZero(opening) > 0:
        ys, xs = np.where(opening > 0)
        if len(xs) > 0:
            peaks = np.zeros_like(opening)
            peaks[ys[len(ys) // 2], xs[len(xs) // 2]] = 255

    unknown = cv2.subtract(sure_bg, peaks)
    _, markers = cv2.connectedComponents(peaks)
    markers = markers + 1
    markers[unknown == 255] = 0
    # 若 markers 无有效前景（全 0/1），直接返回零标签
    if int(markers.max()) <= 1:
        return np.zeros(binary.shape, dtype=np.int32)

    vis = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
    markers = cv2.watershed(vis, markers)
    labels = markers.astype(np.int32)
    labels[labels <= 1] = 0
    labels[labels == -1] = 0
    return labels


def _region_stats_fast(labels: np.ndarray) -> Dict[int, Dict[str, float]]:
    """用 bincount 一次算出各标签面积与质心。"""
    max_label = int(labels.max()) if labels.size else 0
    if max_label < 2:
        return {}
    flat = labels.ravel()
    areas = np.bincount(flat, minlength=max_label + 1)
    ys, xs = np.indices(labels.shape)
    sum_y = np.bincount(flat, weights=ys.ravel(), minlength=max_label + 1)
    sum_x = np.bincount(flat, weights=xs.ravel(), minlength=max_label + 1)
    out: Dict[int, Dict[str, float]] = {}
    for i in range(2, max_label + 1):
        a = float(areas[i])
        if a <= 0:
            continue
        out[i] = {"area": a, "cx": float(sum_x[i] / a), "cy": float(sum_y[i] / a)}
    return out


def count_from_labels(
    labels: np.ndarray,
    min_area: int = 20,
    max_area: int = 8000,
    min_circularity: float = 0.0,
    petri_circle: Optional[Tuple[int, int, int]] = None,
    min_distance_from_edge: int = 8,
    image_size: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """按分水岭标签区域过滤并计数。"""
    height, width = labels.shape[:2]
    if image_size is not None:
        width, height = image_size

    stats = _region_stats_fast(labels)
    details: List[Dict[str, Any]] = []
    count = 0

    for label_id, st in stats.items():
        area = st["area"]
        if area < min_area or area > max_area:
            continue
        cx, cy = int(st["cx"]), int(st["cy"])

        if petri_circle is not None:
            pcx, pcy, pr = petri_circle
            dx, dy = cx - pcx, cy - pcy
            if (dx * dx + dy * dy) ** 0.5 > pr * 0.92:
                continue
        else:
            region = labels == label_id
            ys, xs = np.where(region)
            if ys.size == 0:
                continue
            dist = int(min(xs.min(), ys.min(), width - 1 - xs.max(), height - 1 - ys.max()))
            if dist < min_distance_from_edge:
                continue

        circularity = None
        if min_circularity > 0:
            region_u8 = (labels == label_id).astype(np.uint8)
            contours, _ = cv2.findContours(region_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                cnt = max(contours, key=cv2.contourArea)
                perimeter = cv2.arcLength(cnt, True)
                if perimeter > 0:
                    circularity = float(4 * np.pi * cv2.contourArea(cnt) / (perimeter * perimeter))
                if circularity is not None and circularity < min_circularity:
                    continue

        count += 1
        details.append({
            "id": count,
            "x": int(cx),
            "y": int(cy),
            "area": int(area),
            "circularity": round(circularity, 4) if circularity is not None else None,
        })

    return {"count": count, "colony_details": details}


def count_from_peaks(
    binary: np.ndarray,
    seed_kernel: int = 11,
    min_area: int = 20,
    petri_circle: Optional[Tuple[int, int, int]] = None,
    min_distance_from_edge: int = 8,
    min_dist_value: float = 1.8,
) -> Dict[str, Any]:
    """距离变换局部极大点计数（极密菌落备选策略）。"""
    peaks = local_maxima_mask(
        binary, kernel_size=seed_kernel, min_dist_value=min_dist_value
    )
    n_labels, _, stats, centroids = cv2.connectedComponentsWithStats(peaks, connectivity=8)
    _, dist_s = distance_map(binary)
    height, width = binary.shape[:2]

    details: List[Dict[str, Any]] = []
    count = 0
    for i in range(1, n_labels):
        if int(stats[i, cv2.CC_STAT_AREA]) < 1:
            continue
        cx, cy = float(centroids[i][0]), float(centroids[i][1])
        ix, iy = int(round(cx)), int(round(cy))
        if not (0 <= iy < height and 0 <= ix < width):
            continue
        local_r = float(dist_s[iy, ix])
        if local_r < min_dist_value * 0.5:
            continue
        est_area = int(max(min_area, np.pi * max(local_r, 1.0) ** 2))

        if petri_circle is not None:
            pcx, pcy, pr = petri_circle
            if ((cx - pcx) ** 2 + (cy - pcy) ** 2) ** 0.5 > pr * 0.92:
                continue
        else:
            if min(ix, iy, width - 1 - ix, height - 1 - iy) < min_distance_from_edge:
                continue

        count += 1
        details.append({
            "id": count,
            "x": ix,
            "y": iy,
            "area": est_area,
            "circularity": None,
        })

    return {"count": count, "colony_details": details}


def draw_details_on_image(
    image: np.ndarray,
    details: List[Dict[str, Any]],
    petri_circle: Optional[Tuple[int, int, int]] = None,
) -> np.ndarray:
    """在图上画圆与编号，风格与 process_image 一致。"""
    out = image.copy()
    if petri_circle is not None:
        pcx, pcy, pr = petri_circle
        cv2.circle(out, (int(pcx), int(pcy)), int(pr), (255, 0, 0), 3)
    for d in details:
        cx, cy = int(d["x"]), int(d["y"])
        r = max(6, int((max(d["area"], 1) / np.pi) ** 0.5))
        cv2.circle(out, (cx, cy), r, (0, 255, 0), 2)
        cv2.putText(
            out, str(d["id"]), (cx - 10, cy + 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2,
        )
    return out
