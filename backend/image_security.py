"""HTTP 层安全工具：上传校验、参数钳制、图像解码。"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np

# 上传与解码限制（局域网实验工具，够用即可）
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 15 * 1024 * 1024))
# 计算目标分辨率：超限自动等比降采样，而不是直接拒绝
MAX_IMAGE_PIXELS = int(os.environ.get("MAX_IMAGE_PIXELS", 25_000_000))  # ~25MP
MAX_IMAGE_SIDE = int(os.environ.get("MAX_IMAGE_SIDE", 8000))
# 绝对炸弹阈值：远超目标分辨率才拒绝，防止解压炸弹打爆内存
MAX_ABS_PIXELS = int(os.environ.get("MAX_ABS_PIXELS", 100_000_000))  # ~100MP
MAX_ABS_SIDE = int(os.environ.get("MAX_ABS_SIDE", 16000))
MAX_BATCH_IMAGES = 20
MAX_REF_PIXELS = 12_000_000

_ALLOWED_MAGIC = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"RIFF", "webp"),  # need WEBP at 8:12
)


def looks_like_image(file_bytes: bytes) -> bool:
    if not file_bytes or len(file_bytes) < 12:
        return False
    if file_bytes.startswith(b"\xff\xd8\xff"):
        return True
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if file_bytes[:2] == b"BM":
        return True
    if file_bytes[:4] in (b"II*\x00", b"MM\x00*"):
        return True
    if file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return True
    return False


def check_upload_size(raw: bytes, max_bytes: Optional[int] = None) -> None:
    limit = max_bytes if max_bytes is not None else MAX_UPLOAD_BYTES
    if len(raw) == 0:
        raise ValueError("空文件")
    if len(raw) > limit:
        raise ValueError(f"文件过大（上限 {limit // (1024 * 1024)}MB）")


def _probe_dimensions(file_bytes: bytes) -> Optional[Tuple[int, int]]:
    """在完整 imdecode 前从文件头探测宽高，降低解压炸弹峰值内存。"""
    try:
        if file_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(file_bytes) >= 24:
            w = int.from_bytes(file_bytes[16:20], "big")
            h = int.from_bytes(file_bytes[20:24], "big")
            return w, h
        if file_bytes.startswith(b"\xff\xd8\xff"):
            i = 2
            n = len(file_bytes)
            while i + 9 < n:
                if file_bytes[i] != 0xFF:
                    i += 1
                    continue
                marker = file_bytes[i + 1]
                if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                if i + 4 > n:
                    break
                seg_len = int.from_bytes(file_bytes[i + 2 : i + 4], "big")
                if marker in (0xC0, 0xC1, 0xC2, 0xC9, 0xCA) and i + 9 <= n:
                    h = int.from_bytes(file_bytes[i + 5 : i + 7], "big")
                    w = int.from_bytes(file_bytes[i + 7 : i + 9], "big")
                    return w, h
                i += 2 + seg_len
        if file_bytes[:2] == b"BM" and len(file_bytes) >= 26:
            w = int.from_bytes(file_bytes[18:22], "little", signed=True)
            h = int.from_bytes(file_bytes[22:26], "little", signed=True)
            return abs(w), abs(h)
    except Exception:
        return None
    return None


@dataclass
class DecodedImage:
    """解码结果：图像 + 从原图到工作分辨率的缩放元数据。"""

    image: np.ndarray
    scale: float  # 工作分辨率 / 原图分辨率；未缩放时为 1.0
    original_size: Tuple[int, int]  # (w, h)
    was_resized: bool
    warning: Optional[str] = None

    @property
    def scale2(self) -> float:
        return self.scale * self.scale


def _target_size(w: int, h: int, side_cap: int, pix_cap: int) -> Tuple[int, int, float]:
    """计算工作分辨率与缩放系数（scale = 工作/原图）。"""
    if w <= 0 or h <= 0:
        return max(w, 1), max(h, 1), 1.0
    scale = min(1.0, side_cap / float(max(w, h)))
    if w * h > 0:
        scale = min(scale, math.sqrt(pix_cap / float(w * h)))
    if scale >= 0.999:
        return w, h, 1.0
    tw = max(1, int(round(w * scale)))
    th = max(1, int(round(h * scale)))
    # 四舍五入后仍可能略超像素上限，再收一档
    while tw * th > pix_cap and (tw > 1 or th > 1):
        if tw >= th:
            tw = max(1, tw - 1)
        else:
            th = max(1, th - 1)
    return tw, th, tw / float(w)


def _resize_if_needed(image: np.ndarray, tw: int, th: int) -> np.ndarray:
    h, w = image.shape[:2]
    if w == tw and h == th:
        return image
    return cv2.resize(image, (tw, th), interpolation=cv2.INTER_AREA)


def _decode_jpeg_reduced(
    file_bytes: bytes, tw: int, th: int, ow: int, oh: int
) -> Optional[np.ndarray]:
    """JPEG 优先用 IMREAD_REDUCED_* 降低峰值内存，再精细缩放到目标尺寸。"""
    # OpenCV 从大到小尝试：8x → 4x → 2x，取仍 ≥ 目标尺寸的最大降幅
    for factor, flag in (
        (8, cv2.IMREAD_REDUCED_COLOR_8),
        (4, cv2.IMREAD_REDUCED_COLOR_4),
        (2, cv2.IMREAD_REDUCED_COLOR_2),
    ):
        if ow // factor < 1 or oh // factor < 1:
            continue
        if ow // factor >= tw and oh // factor >= th:
            nparr = np.frombuffer(file_bytes, np.uint8)
            image = cv2.imdecode(nparr, flag)
            if image is None:
                return None
            return _resize_if_needed(image, tw, th)
    return None


def decode_image_with_meta(
    file_bytes: bytes,
    max_side: Optional[int] = None,
    max_pixels: Optional[int] = None,
) -> DecodedImage:
    """校验魔数并解码。超目标分辨率时自动等比降采样；仅拒绝绝对炸弹尺寸。"""
    check_upload_size(file_bytes)
    if not looks_like_image(file_bytes):
        raise ValueError("不是受支持的图片格式（jpg/png/bmp/tiff/webp）")

    side_cap = max_side if max_side is not None else MAX_IMAGE_SIDE
    pix_cap = max_pixels if max_pixels is not None else MAX_IMAGE_PIXELS
    abs_side = max(side_cap * 2, MAX_ABS_SIDE)
    abs_pix = max(pix_cap * 4, MAX_ABS_PIXELS)

    probed = _probe_dimensions(file_bytes)
    if probed:
        pw, ph = probed
        if pw > 0 and ph > 0 and (pw > abs_side or ph > abs_side or pw * ph > abs_pix):
            raise ValueError(
                f"图片过大，超出可处理范围（最大边 {abs_side}px，最大像素 {abs_pix}）"
            )

    is_jpeg = file_bytes.startswith(b"\xff\xd8\xff")
    image: Optional[np.ndarray] = None
    orig_w, orig_h = 0, 0
    if probed:
        orig_w, orig_h = probed
        tw, th, _ = _target_size(orig_w, orig_h, side_cap, pix_cap)
        if tw != orig_w or th != orig_h:
            if is_jpeg:
                image = _decode_jpeg_reduced(file_bytes, tw, th, orig_w, orig_h)
            if image is None:
                nparr = np.frombuffer(file_bytes, np.uint8)
                full = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if full is None:
                    raise ValueError("图片解码失败")
                image = _resize_if_needed(full, tw, th)
        else:
            nparr = np.frombuffer(file_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        nparr = np.frombuffer(file_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("图片解码失败")
        h, w = image.shape[:2]
        if h <= 0 or w <= 0:
            raise ValueError("无效图片尺寸")
        if not probed:
            orig_w, orig_h = w, h
        if h > abs_side or w > abs_side or (h * w) > abs_pix:
            raise ValueError(
                f"图片过大，超出可处理范围（最大边 {abs_side}px，最大像素 {abs_pix}）"
            )
        tw, th, _ = _target_size(orig_w, orig_h, side_cap, pix_cap)
        image = _resize_if_needed(image, tw, th)

    h, w = image.shape[:2]
    if h <= 0 or w <= 0:
        raise ValueError("无效图片尺寸")
    if orig_w <= 0 or orig_h <= 0:
        orig_w, orig_h = w, h

    scale = w / float(orig_w)
    was_resized = abs(scale - 1.0) > 1e-3
    warning = None
    if was_resized:
        warning = (
            f"图片过大，已自动缩小至 {w}×{h}（原图 {orig_w}×{orig_h}，"
            f"约 {scale * 100:.0f}%）以完成计数"
        )

    return DecodedImage(
        image=image,
        scale=scale,
        original_size=(orig_w, orig_h),
        was_resized=was_resized,
        warning=warning,
    )


def decode_image_safe(
    file_bytes: bytes,
    max_side: Optional[int] = None,
    max_pixels: Optional[int] = None,
) -> np.ndarray:
    """兼容旧接口：只返回图像数组（超限时自动降采样）。"""
    return decode_image_with_meta(file_bytes, max_side=max_side, max_pixels=max_pixels).image


def scale_roi_for_image(roi: Optional[tuple], scale: float) -> Optional[tuple]:
    """把原图像素坐标系下的 ROI 缩放到工作分辨率。"""
    if roi is None or abs(scale - 1.0) < 1e-6:
        return roi
    if len(roi) == 3:  # circle: cx, cy, r
        cx, cy, r = roi
        return (int(round(cx * scale)), int(round(cy * scale)), max(1, int(round(r * scale))))
    if len(roi) == 4:  # rect: x, y, w, h
        x, y, w, h = roi
        return (
            int(round(x * scale)),
            int(round(y * scale)),
            max(1, int(round(w * scale))),
            max(1, int(round(h * scale))),
        )
    return roi


def scale_area_params(
    min_area: int, max_area: int, min_distance_from_edge: int, scale: float
) -> Tuple[int, int, int]:
    """面积按 scale²、线性距离按 scale 映射到工作分辨率。"""
    if abs(scale - 1.0) < 1e-6:
        return int(min_area), int(max_area), int(min_distance_from_edge)
    s2 = scale * scale
    amin = max(1, int(round(min_area * s2)))
    amax = max(amin + 1, int(round(max_area * s2)))
    edge = max(0, int(round(min_distance_from_edge * scale)))
    return amin, amax, edge


def clamp_odd(value: int, lo: int, hi: int) -> int:
    v = int(value)
    if v < lo:
        v = lo
    if v > hi:
        v = hi
    if v % 2 == 0:
        v += 1
        if v > hi:
            v -= 2
    return v


def clamp_count_params(
    blur_ksize: int,
    adaptive_block_size: int,
    thresh_val: int,
    min_area: int,
    max_area: int,
    min_circularity: float,
    min_distance_from_edge: int,
) -> Tuple[int, int, int, int, int, float, int]:
    blur = clamp_odd(blur_ksize, 1, 31)
    block = clamp_odd(adaptive_block_size, 3, 51)
    thr = max(0, min(255, int(thresh_val)))
    amin = max(1, int(min_area))
    amax = max(amin + 1, int(max_area))
    circ = max(0.0, min(1.0, float(min_circularity)))
    edge = max(0, min(1000, int(min_distance_from_edge)))
    return blur, block, thr, amin, amax, circ, edge


def parse_roi(roi_type: Optional[str], roi_data: Optional[str]) -> Optional[tuple]:
    """解析并校验 ROI；非法输入抛 ValueError。"""
    if not roi_type or not roi_data or roi_type == "none":
        return None
    try:
        parts = [float(x.strip()) for x in roi_data.split(",")]
        parts = [int(p) for p in parts]
    except Exception as e:
        raise ValueError(f"ROI 数据格式错误: {e}") from e
    if any(p < 0 for p in parts):
        raise ValueError("ROI 不能为负坐标")
    if roi_type == "circle" and len(parts) == 3:
        if parts[2] <= 0:
            raise ValueError("ROI 半径必须为正")
        return (parts[0], parts[1], parts[2])
    if roi_type == "rectangle" and len(parts) == 4:
        if parts[2] <= 0 or parts[3] <= 0:
            raise ValueError("ROI 宽高必须为正")
        return (parts[0], parts[1], parts[2], parts[3])
    raise ValueError("ROI 类型与数据不匹配")


def sanitize_filename(name: Optional[str], default: str = "image") -> str:
    if not name:
        return default
    # 去掉路径与危险字符
    base = name.replace("\\", "/").split("/")[-1]
    cleaned = "".join(c for c in base if c.isalnum() or c in "._- ()[]")
    cleaned = cleaned.strip().strip(".")
    return cleaned[:120] or default


def clamp_calibrate_budget(max_evals: int, time_limit_sec: float) -> Tuple[int, float]:
    me = max(1, min(60, int(max_evals)))
    tl = max(5.0, min(120.0, float(time_limit_sec)))
    return me, tl
