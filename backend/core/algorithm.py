
import cv2
import numpy as np
from typing import Tuple, Optional, Dict, Any, List

from backend.core.blobcount import (
    count_from_labels,
    count_from_peaks,
    draw_details_on_image,
    watershed_labels,
)


def detect_petri_dish_circle(image: np.ndarray) -> Optional[Tuple[int, int, int]]:
    """
    增强版培养皿圆形区域检测
    使用多组参数尝试，选取最佳圆（最接近图像中心且半径合理的）
    :param image: 输入图像 (BGR)
    :return: (x, y, r) 或 None
    """
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (9, 9), 2)

        height, width = image.shape[:2]
        min_dim = min(height, width)
        img_center_x = width / 2.0
        img_center_y = height / 2.0

        all_circles = []

        # 多组参数尝试，从严格到宽松
        param_sets = [
            {"dp": 1, "param1": 80, "param2": 40},   # 严格
            {"dp": 1, "param1": 60, "param2": 35},   # 中等
            {"dp": 1, "param1": 50, "param2": 30},   # 标准
            {"dp": 1.2, "param1": 40, "param2": 25},  # 宽松
        ]

        min_radius = int(min_dim * 0.15)
        max_radius = int(min_dim * 0.48)

        for params in param_sets:
            circles = cv2.HoughCircles(
                blurred,
                cv2.HOUGH_GRADIENT,
                dp=params["dp"],
                minDist=min_dim // 2,
                param1=params["param1"],
                param2=params["param2"],
                minRadius=min_radius,
                maxRadius=max_radius
            )
            if circles is not None:
                circles = np.uint16(np.around(circles))
                for c in circles[0]:
                    all_circles.append(c)

        if not all_circles:
            return None

        # 选择最佳圆：综合评分 = 靠近图像中心 + 半径合理性
        best_circle = None
        best_score = float('inf')

        for circle in all_circles:
            x, y, r = circle
            # 检查半径合理性
            if r < min_radius or r > max_radius:
                continue
            # 计算圆心到图像中心的距离
            dx = float(x) - img_center_x
            dy = float(y) - img_center_y
            distance_to_center = np.sqrt(dx * dx + dy * dy)
            # 评分：越小越好（优先靠近中心、半径适中的圆）
            radius_ratio = r / (min_dim * 0.35)
            radius_penalty = abs(radius_ratio - 1.0) * 100
            score = distance_to_center + radius_penalty
            if score < best_score:
                best_score = score
                best_circle = circle

        if best_circle is not None:
            return (int(best_circle[0]), int(best_circle[1]), int(best_circle[2]))

        return None

    except Exception as e:
        print(f"培养皿检测失败: {e}")
        return None


def _split_large_blob(cnt: np.ndarray, min_area: int, morph_kernel_size: int) -> list:
    """
    对超大面积的融合菌落区域进行局部分水岭拆分
    :param cnt: 轮廓
    :param min_area: 最小菌落面积
    :param morph_kernel_size: 形态学核大小
    :return: 拆分后的子轮廓列表
    """
    kernel = np.ones((morph_kernel_size, morph_kernel_size), np.uint8)

    # 创建仅包含此轮廓的二值图像
    x, y, w, h = cv2.boundingRect(cnt)
    margin = 5
    roi_x = max(0, x - margin)
    roi_y = max(0, y - margin)
    roi_w = w + 2 * margin
    roi_h = h + 2 * margin

    local_mask = np.zeros((roi_h, roi_w), dtype=np.uint8)
    shifted_cnt = cnt.copy()
    shifted_cnt[:, :, 0] -= roi_x
    shifted_cnt[:, :, 1] -= roi_y
    cv2.drawContours(local_mask, [shifted_cnt], -1, 255, -1)

    # 形态学开运算去除小噪点
    opening = cv2.morphologyEx(local_mask, cv2.MORPH_OPEN, kernel, iterations=2)
    if cv2.countNonZero(opening) == 0:
        return []

    # 确定背景
    sure_bg = cv2.dilate(opening, kernel, iterations=3)

    # 距离变换 → 确定前景（菌落中心）
    dist_transform = cv2.distanceTransform(opening, cv2.DIST_L2, 5)
    # 阈值比例较低（0.2），以保留更多小菌落中心
    ret, sure_fg = cv2.threshold(dist_transform, 0.2 * dist_transform.max(), 255, 0)
    sure_fg = np.uint8(sure_fg)

    unknown = cv2.subtract(sure_bg, sure_fg)
    ret, markers = cv2.connectedComponents(sure_fg)
    markers = markers + 1
    markers[unknown == 255] = 0

    local_3ch = cv2.cvtColor(local_mask, cv2.COLOR_GRAY2BGR)
    markers = cv2.watershed(local_3ch, markers)

    # 提取各子区域轮廓
    sub_contours = []
    labels = markers.copy()
    labels[labels == -1] = 0
    labels[labels == 1] = 0

    for label_id in range(2, labels.max() + 1):
        region = (labels == label_id).astype(np.uint8) * 255
        cnts, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            sub_area = cv2.contourArea(c)
            if sub_area >= min_area:
                # 还原到原始图像坐标系
                c[:, :, 0] += roi_x
                c[:, :, 1] += roi_y
                sub_contours.append(c)

    return sub_contours


def process_image(
    image: np.ndarray,
    blur_ksize: int = 7,
    thresh_method: str = "adaptive",  # "manual" or "adaptive"
    thresh_val: int = 100,
    adaptive_block_size: int = 11,
    adaptive_c: int = 2,
    min_area: int = 50,
    max_area: int = 5000,
    min_distance_from_edge: int = 20,
    detect_petri_dish: bool = False,
    manual_roi: Optional[Tuple] = None,  # (x, y, w, h) rect or (cx, cy, r) circle
    use_watershed: bool = False,
    min_circularity: float = 0.0,
    segment_mode: Optional[str] = None,  # None/auto | classic | labels | peaks
    seed_kernel: int = 11,
    min_dist_value: float = 1.8,
) -> Dict[str, Any]:
    """
    核心图像处理函数

    :param image: 输入图像 (BGR)
    :param blur_ksize: 高斯模糊核大小 (奇数)
    :param thresh_method: 二值化方法 "manual" 或 "adaptive"
    :param thresh_val: 手动阈值 (0-255)
    :param adaptive_block_size: 自适应阈值块大小 (奇数)
    :param adaptive_c: 自适应阈值常数C
    :param min_area: 最小菌落面积 (像素)
    :param max_area: 最大菌落面积 (像素)
    :param min_distance_from_edge: 最小边缘距离 (像素)
    :param detect_petri_dish: 是否自动检测培养皿
    :param manual_roi: 手动选择区域
    :param use_watershed: 是否使用分水岭算法分离粘连菌落
    :param min_circularity: 最小圆度 (0-1, 0=不过滤, 越接近1越圆)
    :param segment_mode: 分割模式 classic/labels/peaks；None 或 auto 时由 use_watershed 决定
    :param seed_kernel: 分水岭/峰值种子邻域核（奇数）
    :return: 结果字典
    """
    try:
        # ── 大图自动缩放 ──
        original_height, original_width = image.shape[:2]
        scale_ratio = 1.0
        max_dimension = 1200

        if max(original_height, original_width) > max_dimension:
            scale_ratio = max_dimension / max(original_height, original_width)
            new_width = int(original_width * scale_ratio)
            new_height = int(original_height * scale_ratio)
            image = cv2.resize(image, (new_width, new_height))

        height, width = image.shape[:2]
        output_image = image.copy()

        result = {
            "count": 0,
            "binary_image": None,
            "processed_image": None,
            "petri_circle": None,
            "error": None,
            "scale_ratio": scale_ratio,
            "original_size": (original_width, original_height),
            "colony_details": [],
            "segment_mode": None,
        }

        # ── 缩放自适应参数 ──
        if scale_ratio != 1.0:
            sr2 = scale_ratio * scale_ratio
            min_area = max(1, int(min_area * sr2))
            max_area = max(min_area + 1, int(max_area * sr2))
            min_distance_from_edge = max(0, int(min_distance_from_edge * scale_ratio))
            if manual_roi is not None and len(manual_roi) >= 3:
                manual_roi = tuple(int(v * scale_ratio) for v in manual_roi)

        # ── 形态学核大小（随缩放调整）──
        morph_kernel_size = max(2, int(3 * scale_ratio)) if scale_ratio != 1.0 else 3

        # ── 培养皿检测 ──
        petri_mask = None
        if detect_petri_dish:
            petri_mask = detect_petri_dish_circle(image)
            if petri_mask is not None:
                result["petri_circle"] = petri_mask
                cv2.circle(output_image, (int(petri_mask[0]), int(petri_mask[1])),
                           int(petri_mask[2]), (255, 0, 0), 3)

        # ── 1. 灰度化 ──
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # ── 手动 ROI 掩码 ──
        roi_mask = None
        if manual_roi is not None:
            if len(manual_roi) == 3:  # 圆形 (cx, cy, r)
                cx, cy, r = manual_roi
                roi_mask = np.zeros_like(gray)
                cv2.circle(roi_mask, (int(cx), int(cy)), int(r), 255, -1)
                cv2.circle(output_image, (int(cx), int(cy)), int(r), (0, 255, 255), 3)
            elif len(manual_roi) == 4:  # 矩形 (x, y, w, h)
                rx, ry, rw, rh = manual_roi
                roi_mask = np.zeros_like(gray)
                cv2.rectangle(roi_mask, (rx, ry), (rx + rw, ry + rh), 255, -1)
                cv2.rectangle(output_image, (rx, ry), (rx + rw, ry + rh), (0, 255, 255), 3)

        # ── 应用掩码到灰度图 ──
        if petri_mask is not None:
            pcx, pcy, pr = petri_mask
            mask = np.zeros_like(gray)
            cv2.circle(mask, (int(pcx), int(pcy)), int(pr), 255, -1)
            gray = cv2.bitwise_and(gray, gray, mask=mask)
        elif roi_mask is not None:
            gray = cv2.bitwise_and(gray, roi_mask)

        # ── 2. 高斯模糊去噪 ──
        if blur_ksize % 2 == 0:
            blur_ksize += 1
        blurred = cv2.GaussianBlur(gray, (blur_ksize, blur_ksize), 0)

        # ── 3. 二值化 ──
        if thresh_method == "manual":
            _, thresh = cv2.threshold(blurred, thresh_val, 255, cv2.THRESH_BINARY_INV)
        else:  # adaptive
            if adaptive_block_size % 2 == 0:
                adaptive_block_size += 1
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY_INV, adaptive_block_size, adaptive_c
            )

        # ── 应用掩码到二值图 ──
        if petri_mask is not None:
            pcx, pcy, pr = petri_mask
            mask = np.zeros_like(thresh)
            cv2.circle(mask, (int(pcx), int(pcy)), int(pr), 255, -1)
            thresh = cv2.bitwise_and(thresh, mask)
        elif roi_mask is not None:
            thresh = cv2.bitwise_and(thresh, roi_mask)

        result["binary_image"] = thresh.copy()

        # ── 分割模式解析 ──
        mode = (segment_mode or "auto").lower()
        if mode == "auto":
            mode = "labels" if use_watershed else "classic"
        result["segment_mode"] = mode

        # ── peaks：距离变换局部极大计数 ──
        if mode == "peaks":
            peak_res = count_from_peaks(
                thresh,
                seed_kernel=seed_kernel,
                min_area=min_area,
                petri_circle=petri_mask,
                min_distance_from_edge=min_distance_from_edge,
                min_dist_value=min_dist_value,
            )
            result["count"] = peak_res["count"]
            result["colony_details"] = peak_res["colony_details"]
            result["processed_image"] = draw_details_on_image(
                output_image, peak_res["colony_details"], petri_mask
            )
            return result

        # ── labels：分水岭标签直计数（修复旧重建路径丢小菌落问题）──
        if mode == "labels":
            sk = seed_kernel if scale_ratio == 1.0 else max(5, int(seed_kernel * scale_ratio))
            if sk % 2 == 0:
                sk += 1
            mdv = min_dist_value if scale_ratio == 1.0 else max(1.0, min_dist_value * scale_ratio)
            labels = watershed_labels(
                thresh, seed_kernel=sk, min_dist_value=mdv, open_iterations=1
            )
            result["binary_image"] = (labels > 0).astype(np.uint8) * 255
            label_res = count_from_labels(
                labels,
                min_area=min_area,
                max_area=max_area,
                min_circularity=min_circularity,
                petri_circle=petri_mask,
                min_distance_from_edge=min_distance_from_edge,
                image_size=(width, height),
            )
            result["count"] = label_res["count"]
            result["colony_details"] = label_res["colony_details"]
            result["processed_image"] = draw_details_on_image(
                output_image, label_res["colony_details"], petri_mask
            )
            return result

        # ── classic：原有轮廓路径 ──
        # ── 5. 轮廓检测 ──
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # ── 6. 过滤和计数（含大面积融合区域自动拆分）──
        colony_count = 0
        colony_details = []

        for cnt in contours:
            area = cv2.contourArea(cnt)

            # 面积过小直接跳过
            if area < min_area:
                continue

            # 构建待处理轮廓列表
            # 面积在范围内 → 直接处理
            # 面积超过 max_area → 尝试分水岭拆分为多个独立菌落
            if area <= max_area:
                candidates = [cnt]
            else:
                candidates = _split_large_blob(cnt, min_area, morph_kernel_size)

            for candidate in candidates:
                c_area = cv2.contourArea(candidate)
                if c_area < min_area or c_area > max_area:
                    continue

                cx, cy, cw, ch = cv2.boundingRect(candidate)

                # ── 位置检查 ──
                if petri_mask is not None:
                    pcx, pcy, pr = petri_mask
                    M = cv2.moments(candidate)
                    if M["m00"] != 0:
                        mX = int(M["m10"] / M["m00"])
                        mY = int(M["m01"] / M["m00"])
                        dx = float(mX - pcx)
                        dy = float(mY - pcy)
                        in_region = np.sqrt(dx * dx + dy * dy) <= pr * 0.9
                    else:
                        in_region = False
                else:
                    dist = min(cx, cy, width - (cx + cw), height - (cy + ch))
                    in_region = dist >= min_distance_from_edge

                if not in_region:
                    continue

                # ── 圆度过滤 ──
                circularity = 0.0
                perimeter = cv2.arcLength(candidate, True)
                if perimeter > 0:
                    circularity = 4 * np.pi * c_area / (perimeter * perimeter)
                if min_circularity > 0 and circularity < min_circularity:
                    continue

                # ── 通过所有过滤，计入结果 ──
                colony_count += 1

                cv2.drawContours(output_image, [candidate], -1, (0, 255, 0), 2)

                M = cv2.moments(candidate)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    cv2.putText(output_image, str(colony_count), (cX - 10, cY + 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                    colony_details.append({
                        "id": colony_count,
                        "x": int(cX),
                        "y": int(cY),
                        "area": int(c_area),
                        "circularity": round(float(circularity), 4)
                    })

        result["processed_image"] = output_image
        result["count"] = colony_count
        result["colony_details"] = colony_details
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "count": 0,
            "binary_image": None,
            "processed_image": None,
            "petri_circle": None,
            "error": str(e),
            "scale_ratio": 1.0,
            "original_size": (image.shape[1], image.shape[0]),
            "colony_details": [],
            "segment_mode": segment_mode,
        }
