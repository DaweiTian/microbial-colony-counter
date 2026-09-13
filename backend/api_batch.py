"""批次标定 HTTP API（供 React 前端使用）。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.core.batch import batch_count_images
from backend.core.calibrator import calibrate_multi
from backend.image_security import (
    MAX_BATCH_IMAGES,
    MAX_REF_PIXELS,
    MAX_UPLOAD_BYTES,
    clamp_calibrate_budget,
    decode_image_safe,
    sanitize_filename,
)

logger = logging.getLogger("colony.batch")

router = APIRouter(prefix="/api/v1/batch", tags=["batch"])

# 服务端会话缓存：ref_id -> 状态。主线程加锁保护。
_REF_STORE: Dict[str, Dict[str, Any]] = {}
_REF_LOCK = threading.Lock()
_MAX_REFS = 20
_REF_TTL_SEC = 3600
# 与 main.py 共享，避免双池过度订阅 CPU
_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def _thumb_base64(image: np.ndarray, max_dim: int = 480, quality: int = 70) -> str:
    h, w = image.shape[:2]
    if max(h, w) > max_dim:
        ratio = max_dim / max(h, w)
        image = cv2.resize(image, (int(w * ratio), int(h * ratio)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("thumbnail encode failed")
    import base64

    return base64.b64encode(buf).decode("utf-8")


def _json_safe(obj: Any) -> Any:
    """Convert numpy / nested structures to JSON-serializable Python types."""
    if obj is None or isinstance(obj, (str, bool, int, float)):
        return obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        # 防御：大数组不进 JSON（正常路径已剥离）
        if obj.size > 10_000:
            return f"<ndarray {obj.shape}>"
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    return str(obj)

_IMAGE_KEYS = (
    "processed_image",
    "binary_image",
    "image",
    "original_image",
)


def _strip_images(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _strip_images(v)
            for k, v in obj.items()
            if k not in _IMAGE_KEYS
        }
    if isinstance(obj, (list, tuple)):
        return [_strip_images(v) for v in obj]
    return obj


def _slim_plates(result: Dict[str, Any]) -> Dict[str, Any]:
    """精简 plate_results 与顶层 result：去掉大图，保留可读字段。"""
    result = dict(result)
    plates = result.get("plate_results") or []
    slim = []
    for p in plates:
        if not isinstance(p, dict):
            continue
        slim.append(
            {
                k: p.get(k)
                for k in (
                    "name",
                    "total_gt",
                    "strategy",
                    "n_points",
                    "predicted_count",
                    "fit_error",
                    "match_score",
                    "error",
                )
                if k in p
            }
        )
    if slim:
        result["plate_results"] = slim
    # 剥离任何残留图像字段
    for k in list(result.keys()):
        if k in _IMAGE_KEYS:
            result.pop(k, None)
    if "best_result" in result and isinstance(result["best_result"], dict):
        result["best_result"] = _strip_images(result["best_result"])
    if "result" in result:
        if isinstance(result["result"], dict):
            result["result"] = _strip_images(result["result"])
        else:
            result.pop("result", None)
    return result


def _purge_expired_locked() -> None:
    now = time.time()
    expired = [
        rid
        for rid, st in _REF_STORE.items()
        if now - st.get("ts", now) > _REF_TTL_SEC
    ]
    for rid in expired:
        _REF_STORE.pop(rid, None)


class RefPoint(BaseModel):
    x: float
    y: float


class RefUpdate(BaseModel):
    total_gt: Optional[int] = None
    points: Optional[List[RefPoint]] = None


class CalibrateRef(BaseModel):
    id: str
    total_gt: Optional[int] = None
    points: List[RefPoint] = Field(default_factory=list)


class CalibrateRequest(BaseModel):
    refs: List[CalibrateRef] = Field(default_factory=list)
    max_evals: int = Field(40, ge=1, le=40)
    time_limit_sec: float = Field(60.0, ge=5.0, le=60.0)


@router.post("/refs")
async def add_refs(images: List[UploadFile] = File(...)) -> Dict[str, Any]:
    if not images:
        raise HTTPException(status_code=400, detail="请至少上传一张参考盘图片")
    if len(images) > 5:
        raise HTTPException(status_code=400, detail="单次最多 5 张")

    def _load(raw: bytes, name: str) -> Dict[str, Any]:
        image = decode_image_safe(raw, max_pixels=MAX_REF_PIXELS)
        h, w = image.shape[:2]
        # 存前缩到工作分辨率，降低内存占用
        if max(h, w) > 1600:
            ratio = 1600 / max(h, w)
            image = cv2.resize(
                image,
                (int(w * ratio), int(h * ratio)),
                interpolation=cv2.INTER_AREA,
            )
        return {
            "image": image,
            "name": sanitize_filename(name),
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
            "thumb_base64": _thumb_base64(image),
        }

    loop = asyncio.get_running_loop()
    refs_out = []
    for uf in images:
        raw = await uf.read()
        try:
            loaded = await loop.run_in_executor(_EXECUTOR, _load, raw, uf.filename or "ref")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception:
            logger.exception("ref decode failed")
            raise HTTPException(status_code=400, detail="参考盘图片解码失败")

        ref_id = uuid.uuid4().hex
        with _REF_LOCK:
            _purge_expired_locked()
            if len(_REF_STORE) >= _MAX_REFS:
                # 淘汰最旧
                oldest = min(_REF_STORE.items(), key=lambda kv: kv[1].get("ts", 0))[0]
                _REF_STORE.pop(oldest, None)
            _REF_STORE[ref_id] = {
                **loaded,
                "total_gt": None,
                "points": [],
                "ts": time.time(),
            }
        refs_out.append(
            {
                "id": ref_id,
                "name": loaded["name"],
                "width": loaded["width"],
                "height": loaded["height"],
                "thumb_base64": loaded["thumb_base64"],
            }
        )
    return {"refs": refs_out}


@router.put("/refs/{ref_id}")
async def update_ref(ref_id: str, body: RefUpdate) -> Dict[str, Any]:
    with _REF_LOCK:
        stored = _REF_STORE.get(ref_id)
        if not stored:
            raise HTTPException(status_code=404, detail="参考盘不存在或已过期")
        if body.total_gt is not None:
            if body.total_gt < 0 or body.total_gt > 1_000_000:
                raise HTTPException(status_code=400, detail="total_gt 超出范围")
            stored["total_gt"] = int(body.total_gt)
        if body.points is not None:
            if len(body.points) > 5000:
                raise HTTPException(status_code=400, detail="点选过多")
            stored["points"] = [{"x": float(p.x), "y": float(p.y)} for p in body.points]
        stored["ts"] = time.time()
        return {
            "id": ref_id,
            "name": stored["name"],
            "total_gt": stored.get("total_gt"),
            "points": stored.get("points") or [],
        }


@router.post("/calibrate")
async def calibrate(req: CalibrateRequest) -> Dict[str, Any]:
    if not req.refs:
        raise HTTPException(status_code=400, detail="请提供参考盘")
    if len(req.refs) > 5:
        raise HTTPException(status_code=400, detail="参考盘最多 5 块")

    max_evals, time_limit = clamp_calibrate_budget(req.max_evals, req.time_limit_sec)

    references: List[Dict[str, Any]] = []
    for item in req.refs:
        with _REF_LOCK:
            stored = _REF_STORE.get(item.id)
        if not stored:
            raise HTTPException(status_code=404, detail="参考盘不存在或已过期")
        total_gt = item.total_gt if item.total_gt is not None else stored.get("total_gt")
        points = (
            [{"x": p.x, "y": p.y} for p in item.points]
            if item.points
            else list(stored.get("points") or [])
        )
        references.append(
            {
                "name": stored["name"],
                "image": stored["image"],
                "total_gt": total_gt,
                "points": points,
            }
        )

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _EXECUTOR,
        lambda: calibrate_multi(
            references,
            max_evals=max_evals,
            time_limit_sec=time_limit,
        ),
    )
    return _json_safe(_slim_plates(result))


@router.post("/run")
async def batch_run(
    images: List[UploadFile] = File(...),
    params: str = Form(...),
) -> Dict[str, Any]:
    import json

    if not images:
        raise HTTPException(status_code=400, detail="请提供批量图片")
    if len(images) > MAX_BATCH_IMAGES:
        raise HTTPException(status_code=400, detail=f"单次批量最多 {MAX_BATCH_IMAGES} 张")
    try:
        param_dict = json.loads(params)
        if not isinstance(param_dict, dict):
            raise ValueError("params must be object")
    except Exception:
        raise HTTPException(status_code=400, detail="params JSON 无效")

    payloads: List[tuple[str, bytes]] = []
    errors: List[Dict[str, Any]] = []
    for uf in images:
        raw = await uf.read()
        payloads.append((sanitize_filename(uf.filename), raw))

    def _process_all(items: List[tuple[str, bytes]]):
        out: List[Dict[str, Any]] = []
        arrays: List[np.ndarray] = []
        names: List[str] = []
        for name, raw in items:
            try:
                arrays.append(decode_image_safe(raw))
                names.append(name)
            except ValueError as e:
                out.append(
                    {
                        "name": name,
                        "count": 0,
                        "error": str(e),
                        "processed_image_base64": None,
                    }
                )
            except Exception:
                out.append(
                    {
                        "name": name,
                        "count": 0,
                        "error": "解码失败",
                        "processed_image_base64": None,
                    }
                )
        if arrays:
            results = batch_count_images(arrays, param_dict, names=names)
            for r in results:
                thumb = None
                if r.get("processed_image") is not None:
                    try:
                        thumb = _thumb_base64(r["processed_image"], max_dim=640, quality=55)
                    except Exception:
                        thumb = None
                out.append(
                    {
                        "name": r.get("name"),
                        "count": r.get("count", 0),
                        "error": r.get("error"),
                        "processed_image_base64": thumb,
                    }
                )
        return out

    t0 = time.time()
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(_EXECUTOR, _process_all, payloads)
    items.extend(errors)
    return {"items": items, "elapsed_ms": (time.time() - t0) * 1000}
