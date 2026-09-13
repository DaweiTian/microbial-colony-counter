"""批次标定 HTTP API（供 React 前端使用）。"""

from __future__ import annotations

import asyncio
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

router = APIRouter(prefix="/api/v1/batch", tags=["batch"])

# 服务端会话缓存：ref_id -> ndarray。前端无状态，标定时按 id 引用。
_REF_STORE: Dict[str, Dict[str, Any]] = {}
_MAX_REFS = 20
_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def _decode(file_bytes: bytes) -> np.ndarray:
    nparr = np.frombuffer(file_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Failed to decode image")
    return image


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
        return obj.tolist()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    return str(obj)


def _slim_plates(result: Dict[str, Any]) -> Dict[str, Any]:
    """精简 plate_results：去掉大图，保留可读字段。"""
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
        result = dict(result)
        result["plate_results"] = slim
    return result


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
    refs: List[CalibrateRef]
    max_evals: int = 40
    time_limit_sec: float = 60.0


@router.post("/refs")
async def add_refs(images: List[UploadFile] = File(...)) -> Dict[str, Any]:
    if not images:
        raise HTTPException(status_code=400, detail="请至少上传一张参考盘图片")
    if len(images) > 5:
        raise HTTPException(status_code=400, detail="单次最多 5 张")
    refs_out = []
    for uf in images:
        raw = await uf.read()
        try:
            image = _decode(raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"图片解码失败 {uf.filename}: {e}")
        ref_id = uuid.uuid4().hex
        if len(_REF_STORE) >= _MAX_REFS:
            oldest = next(iter(_REF_STORE))
            _REF_STORE.pop(oldest, None)
        _REF_STORE[ref_id] = {
            "image": image,
            "name": uf.filename or ref_id,
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
            "total_gt": None,
            "points": [],
        }
        refs_out.append(
            {
                "id": ref_id,
                "name": uf.filename or ref_id,
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
                "thumb_base64": _thumb_base64(image),
            }
        )
    return {"refs": refs_out}


@router.put("/refs/{ref_id}")
async def update_ref(ref_id: str, body: RefUpdate) -> Dict[str, Any]:
    stored = _REF_STORE.get(ref_id)
    if not stored:
        raise HTTPException(status_code=404, detail=f"参考盘不存在或已过期: {ref_id}")
    if body.total_gt is not None:
        if body.total_gt < 0:
            raise HTTPException(status_code=400, detail="total_gt 不能为负")
        stored["total_gt"] = int(body.total_gt)
    if body.points is not None:
        stored["points"] = [{"x": float(p.x), "y": float(p.y)} for p in body.points]
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

    references: List[Dict[str, Any]] = []
    for item in req.refs:
        stored = _REF_STORE.get(item.id)
        if not stored:
            raise HTTPException(status_code=404, detail=f"参考盘不存在或已过期: {item.id}")
        # 优先用请求体中的 N/点；若请求体缺省则回退到 PUT 存的状态
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
            max_evals=req.max_evals,
            time_limit_sec=req.time_limit_sec,
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
    if len(images) > 50:
        raise HTTPException(status_code=400, detail="单次批量最多 50 张")
    try:
        param_dict = json.loads(params)
        if not isinstance(param_dict, dict):
            raise ValueError("params must be object")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"params JSON 无效: {e}")

    arrays: List[np.ndarray] = []
    names: List[str] = []
    errors: List[Dict[str, Any]] = []
    for uf in images:
        raw = await uf.read()
        try:
            arrays.append(_decode(raw))
            names.append(uf.filename or "image")
        except Exception as e:
            errors.append(
                {
                    "name": uf.filename or "image",
                    "count": 0,
                    "error": str(e),
                    "processed_image_base64": None,
                }
            )

    t0 = time.time()
    items: List[Dict[str, Any]] = []
    if arrays:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            _EXECUTOR,
            lambda: batch_count_images(arrays, param_dict, names=names),
        )
        for r in results:
            thumb = None
            if r.get("processed_image") is not None:
                try:
                    thumb = _thumb_base64(r["processed_image"], max_dim=640, quality=55)
                except Exception:
                    thumb = None
            items.append(
                {
                    "name": r.get("name"),
                    "count": r.get("count", 0),
                    "error": r.get("error"),
                    "processed_image_base64": thumb,
                }
            )
    items.extend(errors)
    return {"items": items, "elapsed_ms": (time.time() - t0) * 1000}
