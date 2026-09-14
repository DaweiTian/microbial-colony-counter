"""image_security 单元测试"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.image_security import (
    clamp_count_params,
    clamp_odd,
    decode_image_safe,
    decode_image_with_meta,
    looks_like_image,
    parse_roi,
    sanitize_filename,
    scale_area_params,
    scale_roi_for_image,
)


def test_magic_bytes():
    assert looks_like_image(b"\xff\xd8\xff" + b"\x00" * 20)
    assert looks_like_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    assert not looks_like_image(b"<?php evil();")
    assert not looks_like_image(b"")


def test_clamp_params():
    blur, block, thr, amin, amax, circ, edge = clamp_count_params(
        -5, 1, 999, 0, -1, 5.0, -10
    )
    assert blur >= 1 and blur % 2 == 1
    assert block >= 3 and block % 2 == 1
    assert thr == 255
    assert amin >= 1
    assert amax > amin
    assert circ == 1.0
    assert edge == 0


def test_clamp_odd():
    assert clamp_odd(4, 3, 31) == 5
    assert clamp_odd(2, 3, 31) == 3
    assert clamp_odd(31, 3, 31) == 31


def test_parse_roi_ok():
    assert parse_roi("circle", "10,20,5") == (10, 20, 5)
    assert parse_roi("rectangle", "1,2,30,40") == (1, 2, 30, 40)
    assert parse_roi(None, None) is None
    assert parse_roi("none", "1,2,3") is None


def test_parse_roi_bad():
    for args in [
        ("circle", "abc"),
        ("circle", "-1,2,3"),
        ("circle", "1,2,0"),
        ("rectangle", "1,2,0,5"),
        ("rectangle", "1,2"),
    ]:
        try:
            parse_roi(*args)
            raise AssertionError(f"should reject {args}")
        except ValueError:
            pass


def test_sanitize_filename():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("a/b/c.jpg") == "c.jpg"
    assert sanitize_filename(None) == "image"
    assert ".." not in sanitize_filename("..\\..\\x.jpg")


def test_reject_absolute_bomb():
    import struct
    import zlib

    # 仅构造合法 PNG 头（声明 20000×20000），应在解码前被绝对阈值拒绝
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0))
    try:
        decode_image_with_meta(raw)
        raise AssertionError("should reject bomb")
    except ValueError as e:
        assert "过大" in str(e) or "范围" in str(e)


def test_downscale_synthetic():
    import cv2
    import numpy as np

    # 构造 2000x1500 JPEG，目标限制 400px → 应自动缩小
    img = np.zeros((1500, 2000, 3), dtype=np.uint8)
    img[:] = (40, 80, 120)
    cv2.circle(img, (1000, 750), 200, (200, 180, 60), -1)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    raw = buf.tobytes()

    meta = decode_image_with_meta(raw, max_side=400, max_pixels=400 * 400)
    h, w = meta.image.shape[:2]
    assert max(h, w) <= 400
    assert meta.was_resized is True
    assert abs(meta.scale - w / 2000) < 1e-6
    assert meta.warning and "缩小" in meta.warning
    # 旧接口仍返回 ndarray
    arr = decode_image_safe(raw, max_side=400, max_pixels=400 * 400)
    assert arr.shape[:2] == (h, w)


def test_scale_helpers():
    roi = scale_roi_for_image((100, 200, 30), 0.5)
    assert roi == (50, 100, 15)
    rect = scale_roi_for_image((10, 20, 40, 80), 0.5)
    assert rect == (5, 10, 20, 40)
    assert scale_roi_for_image(None, 0.5) is None
    amin, amax, edge = scale_area_params(100, 400, 20, 0.5)
    assert amin == 25 and amax == 100 and edge == 10
    # scale=1 时原样返回
    assert scale_area_params(100, 400, 20, 1.0) == (100, 400, 20)


if __name__ == "__main__":
    test_magic_bytes()
    test_clamp_params()
    test_clamp_odd()
    test_parse_roi_ok()
    test_parse_roi_bad()
    test_sanitize_filename()
    test_reject_absolute_bomb()
    test_downscale_synthetic()
    test_scale_helpers()
    print("OK image_security")
