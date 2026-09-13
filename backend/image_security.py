"""HTTP 层安全工具：上传校验、参数钳制、图像解码。"""

from __future__ import annotations

import os
from typing import Optional, Tuple

import cv2
import numpy as np

# 上传与解码限制（局域网实验工具，够用即可）
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
MAX_IMAGE_PIXELS = int(os.environ.get("MAX_IMAGE_PIXELS", 25_000_000))  # ~25MP
MAX_IMAGE_SIDE = int(os.environ.get("MAX_IMAGE_SIDE", 8000))
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


def decode_image_safe(
    file_bytes: bytes,
    max_side: Optional[int] = None,
    max_pixels: Optional[int] = None,
) -> np.ndarray:
    """校验魔数并解码，限制边长与像素总量，降低解压炸弹风险。"""
    check_upload_size(file_bytes)
    if not looks_like_image(file_bytes):
        raise ValueError("不是受支持的图片格式（jpg/png/bmp/tiff/webp）")

    side_cap = max_side if max_side is not None else MAX_IMAGE_SIDE
    pix_cap = max_pixels if max_pixels is not None else MAX_IMAGE_PIXELS

    probed = _probe_dimensions(file_bytes)
    if probed:
        pw, ph = probed
        if pw > 0 and ph > 0 and (pw > side_cap or ph > side_cap or pw * ph > pix_cap):
            raise ValueError(
                f"图片尺寸过大（最大边 {side_cap}px，最大像素 {pix_cap}）"
            )

    nparr = np.frombuffer(file_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("图片解码失败")

    h, w = image.shape[:2]
    if h <= 0 or w <= 0:
        raise ValueError("无效图片尺寸")
    if h > side_cap or w > side_cap or (h * w) > pix_cap:
        image = None
        raise ValueError(
            f"图片尺寸过大（最大边 {side_cap}px，最大像素 {pix_cap}）"
        )
    return image


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
    me = max(1, min(40, int(max_evals)))
    tl = max(5.0, min(60.0, float(time_limit_sec)))
    return me, tl
