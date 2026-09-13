
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from typing import Optional
import cv2
import numpy as np
import base64
import time
import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from backend.image_security import (
    clamp_count_params,
    decode_image_safe,
    parse_roi,
)

# Import core algorithm and schemas
from backend.core.algorithm import process_image
from backend.core.smart import smart_count
from backend.schemas import CountResponse
from backend.api_batch import router as batch_router, _EXECUTOR as BATCH_EXECUTOR

logger = logging.getLogger("colony.counter")

# 共享线程池：避免 main/api_batch 各起一套过度订阅 CPU
_executor = BATCH_EXECUTOR
if _executor is None:  # pragma: no cover
    _executor = ThreadPoolExecutor(max_workers=2)

# CORS：局域网工具默认允许常见本机来源；可用 COLONY_CORS_ORIGINS 覆盖（逗号分隔）
_cors_env = os.environ.get("COLONY_CORS_ORIGINS", "").strip()
if _cors_env:
    _origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _origins = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8001",
    ]

app = FastAPI(
    title="Microbial Colony Counter API",
    description="Backend API for Colony Counter Mobile App",
    version="0.1.0",
    docs_url=os.environ.get("COLONY_ENABLE_DOCS", "1") == "1" and "/docs" or None,
    redoc_url=os.environ.get("COLONY_ENABLE_DOCS", "1") == "1" and "/redoc" or None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(batch_router)

# React 构建产物（frontend/dist），未构建时回退 legacy
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_LEGACY_HTML = os.path.join(_STATIC_DIR, "legacy-index.html.bak")
_REACT_INDEX = os.path.join(_STATIC_DIR, "index.html")
_ASSETS_DIR = os.path.join(_STATIC_DIR, "assets")

if os.path.isdir(_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")

def image_to_base64(image: np.ndarray, quality: int = 55) -> str:
    """Convert OpenCV image to compressed base64 string"""
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    _, buffer = cv2.imencode('.jpg', image, encode_params)
    return base64.b64encode(buffer).decode('utf-8')

def make_thumbnail(image: np.ndarray, max_dim: int = 800) -> np.ndarray:
    """生成缩略图用于前端显示，减小传输体积"""
    h, w = image.shape[:2]
    if max(h, w) <= max_dim:
        return image
    ratio = max_dim / max(h, w)
    new_w, new_h = int(w * ratio), int(h * ratio)
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

def decode_image(file_bytes: bytes) -> np.ndarray:
    """Decode image bytes to OpenCV format with size/content guards."""
    return decode_image_safe(file_bytes)


def _encode_result_images(result: dict) -> tuple[str | None, str | None]:
    """在工作线程内做缩略图+JPEG，避免阻塞事件循环。"""
    binary_b64 = None
    processed_b64 = None
    if result.get("binary_image") is not None:
        thumb = make_thumbnail(result["binary_image"], max_dim=800)
        binary_b64 = image_to_base64(thumb, quality=50)
    if result.get("processed_image") is not None:
        thumb = make_thumbnail(result["processed_image"], max_dim=800)
        processed_b64 = image_to_base64(thumb, quality=55)
    return binary_b64, processed_b64


@app.post("/api/v1/count", response_model=CountResponse)
async def count_colonies(
    image: UploadFile = File(...),
    thresh_method: str = Form("adaptive", description="二值化方法: 'manual' 或 'adaptive'"),
    thresh_val: int = Form(100, description="手动阈值 (0-255)"),
    adaptive_block_size: int = Form(11, description="自适应阈值块大小 (奇数)"),
    adaptive_c: int = Form(2, description="自适应阈值常数C"),
    blur_ksize: int = Form(7, description="高斯模糊核大小 (奇数)"),
    min_area: int = Form(50, description="最小菌落面积"),
    max_area: int = Form(5000, description="最大菌落面积"),
    min_distance_from_edge: int = Form(20, description="最小边缘距离"),
    detect_petri_dish: bool = Form(False, description="是否自动检测培养皿"),
    use_watershed: bool = Form(False, description="是否使用分水岭算法分离粘连菌落"),
    min_circularity: float = Form(0.0, description="最小圆度 (0-1, 0=不过滤)"),
    roi_type: Optional[str] = Form(None, description="ROI类型: 'circle' 或 'rectangle'"),
    roi_data: Optional[str] = Form(None, description="ROI数据 (逗号分隔): x,y,w,h 或 cx,cy,r")
):
    start_time = time.time()
    adaptive_c = max(-25, min(25, int(adaptive_c)))

    try:
        contents = await image.read()
        cv_image = decode_image(contents)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("count upload decode failed")
        raise HTTPException(status_code=400, detail="Invalid image file")

    try:
        manual_roi = parse_roi(roi_type, roi_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    (
        blur_ksize,
        adaptive_block_size,
        thresh_val,
        min_area,
        max_area,
        min_circularity,
        min_distance_from_edge,
    ) = clamp_count_params(
        blur_ksize,
        adaptive_block_size,
        thresh_val,
        min_area,
        max_area,
        min_circularity,
        min_distance_from_edge,
    )

    def _job():
        result = process_image(
            image=cv_image,
            blur_ksize=blur_ksize,
            thresh_method=thresh_method,
            thresh_val=thresh_val,
            adaptive_block_size=adaptive_block_size,
            adaptive_c=adaptive_c,
            min_area=min_area,
            max_area=max_area,
            min_distance_from_edge=min_distance_from_edge,
            detect_petri_dish=detect_petri_dish,
            manual_roi=manual_roi,
            use_watershed=use_watershed,
            min_circularity=min_circularity,
        )
        binary_b64, processed_b64 = _encode_result_images(result)
        return result, binary_b64, processed_b64

    loop = asyncio.get_running_loop()
    result, binary_b64, processed_b64 = await loop.run_in_executor(_executor, _job)

    if result.get("error"):
        logger.warning("algorithm error: %s", result["error"])
        raise HTTPException(status_code=500, detail="算法处理失败")

    processing_ms = (time.time() - start_time) * 1000
    response = CountResponse(
        count=result["count"],
        quality_score=None,
        warnings=[],
        petri_circle=result.get("petri_circle"),
        processing_ms=processing_ms,
        colony_details=result.get("colony_details", [])
    )
    response.binary_image_base64 = binary_b64
    response.processed_image_base64 = processed_b64
    return response


def _build_count_response(
    result: dict,
    processing_ms: float,
    binary_b64: str | None,
    processed_b64: str | None,
) -> CountResponse:
    """把 process_image / smart_count 结果转成 API 响应。"""
    cand = result.get("candidates")
    if cand is not None:
        cand = [
            {k: c.get(k) for k in ("strategy", "count", "score", "error") if k in c}
            for c in cand
        ]
    warnings = list(result.get("warnings") or [])
    if result.get("detector_fallback"):
        warnings.append("检测器不可用，已回退 OpenCV")
    response = CountResponse(
        count=result["count"],
        quality_score=None,
        warnings=warnings,
        petri_circle=result.get("petri_circle"),
        processing_ms=processing_ms,
        colony_details=result.get("colony_details", []),
        strategy=result.get("strategy"),
        detector=result.get("detector", "opencv"),
        smart=result.get("smart"),
        petri_detected=result.get("petri_detected"),
        candidates=cand,
    )
    response.binary_image_base64 = binary_b64
    response.processed_image_base64 = processed_b64
    return response


@app.post("/api/v1/count_smart", response_model=CountResponse)
async def count_colonies_smart(
    image: UploadFile = File(...),
    detector: str = Form("opencv", description="检测器: opencv | yolo-onnx（无权重时回退 opencv）"),
):
    """一键智能计数：默认 OpenCV smart；可选 yolo-onnx。"""
    start_time = time.time()
    try:
        contents = await image.read()
        cv_image = decode_image(contents)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("smart upload decode failed")
        raise HTTPException(status_code=400, detail="Invalid image file")

    from backend.core.detector import detect_colonies

    loop = asyncio.get_running_loop()

    def _job():
        if detector and detector != "opencv":
            det = detect_colonies(cv_image, detector=detector)
            result = det.to_dict()
            result.setdefault("error", det.meta.get("error"))
            if det.meta.get("fallback"):
                result["detector_fallback"] = True
        else:
            result = smart_count(cv_image)
        binary_b64, processed_b64 = _encode_result_images(result)
        return result, binary_b64, processed_b64

    result, binary_b64, processed_b64 = await loop.run_in_executor(_executor, _job)
    if result.get("error"):
        logger.warning("smart error: %s", result["error"])
        raise HTTPException(status_code=500, detail="算法处理失败")
    result.setdefault("detector", detector or "opencv")
    result.setdefault("smart", True)
    return _build_count_response(
        result, (time.time() - start_time) * 1000, binary_b64, processed_b64
    )


@app.get("/", response_class=HTMLResponse)
async def read_root():
    path = _REACT_INDEX if os.path.isfile(_REACT_INDEX) else None
    if path is None and os.path.isfile(_LEGACY_HTML):
        path = _LEGACY_HTML
    if path is None:
        return HTMLResponse(
            content=(
                "<html><body style='font-family:sans-serif;padding:2rem'>"
                "<h2>前端未构建</h2>"
                "<p>请先运行 <code>cd frontend && npm install && npm run build</code>，"
                "再把 <code>frontend/dist</code> 同步到 <code>backend/static/</code>，"
                "或直接访问 Vite 开发服务器。</p>"
                "</body></html>"
            ),
            status_code=200,
        )
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(
            content=f.read(),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Microbial Colony Counter API is running"}

if __name__ == "__main__":
    import uvicorn
    # 默认仅监听本机；局域网访问用 COLONY_HOST=0.0.0.0
    host = os.environ.get("COLONY_HOST", "127.0.0.1")
    port = int(os.environ.get("COLONY_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
