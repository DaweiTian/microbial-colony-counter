"""image_security 单元测试"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.image_security import (
    clamp_count_params,
    clamp_odd,
    decode_image_safe,
    looks_like_image,
    parse_roi,
    sanitize_filename,
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


def test_decode_rejects_oversize(monkey=None):
    # 1x1 PNG
    png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
        b"\x00\x05\xfe\xd4\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    # 极大 side cap 应拒绝
    try:
        decode_image_safe(png, max_side=0)
        # max_side=0 会让任何正尺寸都超限
        raise AssertionError("should reject")
    except ValueError:
        pass


if __name__ == "__main__":
    test_magic_bytes()
    test_clamp_params()
    test_clamp_odd()
    test_parse_roi_ok()
    test_parse_roi_bad()
    test_sanitize_filename()
    test_decode_rejects_oversize()
    print("OK image_security")
