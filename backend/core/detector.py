"""菌落检测器抽象：OpenCV 实现 + 本地 ONNX YOLO。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

import cv2
import numpy as np

from backend.core.algorithm import process_image
from backend.core.smart import smart_count


@dataclass
class DetectionResult:
    count: int
    details: List[Dict[str, Any]] = field(default_factory=list)
    image: Optional[np.ndarray] = None
    binary_image: Optional[np.ndarray] = None
    petri_circle: Optional[tuple] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "colony_details": self.details,
            "processed_image": self.image,
            "binary_image": self.binary_image,
            "petri_circle": self.petri_circle,
            **self.meta,
        }


@runtime_checkable
class ColonyDetector(Protocol):
    name: str

    def detect(self, image: np.ndarray, **kwargs: Any) -> DetectionResult:
        ...


def _wrap_process(result: Dict[str, Any], name: str, strategy: Optional[str] = None) -> DetectionResult:
    meta = {
        "error": result.get("error"),
        "detector": name,
        "scale_ratio": result.get("scale_ratio"),
        "original_size": result.get("original_size"),
    }
    if strategy is not None:
        meta["strategy"] = strategy
    for key in ("strategy", "params", "candidates", "smart", "petri_detected", "segment_mode"):
        if key in result:
            meta[key] = result[key]
    return DetectionResult(
        count=int(result.get("count") or 0),
        details=list(result.get("colony_details") or []),
        image=result.get("processed_image"),
        binary_image=result.get("binary_image"),
        petri_circle=result.get("petri_circle"),
        meta=meta,
    )


class OpenCVSmartDetector:
    """默认检测器：一键智能（估参 + 多策略）。"""

    name = "opencv"

    def detect(self, image: np.ndarray, **kwargs: Any) -> DetectionResult:
        return _wrap_process(smart_count(image, overrides=kwargs or None), self.name, strategy="smart")


class OpenCVClassicDetector:
    """经典手动参数路径（与旧 process_image 一致）。"""

    name = "opencv-classic"

    def detect(self, image: np.ndarray, **kwargs: Any) -> DetectionResult:
        return _wrap_process(process_image(image, **kwargs), self.name, strategy="classic")


def _letterbox(image: np.ndarray, new_h: int, new_w: int) -> Tuple[np.ndarray, float, float, float]:
    """保持长边比例填充到 (new_h, new_w)，返回 img, scale, pad_x, pad_y。"""
    h, w = image.shape[:2]
    scale = min(new_w / w, new_h / h)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((new_h, new_w, 3), 114, dtype=np.uint8)
    pad_x = (new_w - nw) / 2.0
    pad_y = (new_h - nh) / 2.0
    left, top = int(round(pad_x)), int(round(pad_y))
    canvas[top : top + nh, left : left + nw] = resized
    return canvas, scale, pad_x, pad_y


def _nms_boxes(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> List[int]:
    """简易 NMS，boxes 为 xyxy。"""
    if boxes.size == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[i] + areas[rest] - inter + 1e-6
        iou = inter / union
        order = rest[iou <= iou_thres]
    return keep


def _decode_yolo_output(
    raw: np.ndarray,
    conf_thres: float,
    img_w: int,
    img_h: int,
    scale: float,
    pad_x: float,
    pad_y: float,
) -> np.ndarray:
    """
    兼容常见 YOLOv8/v11 ONNX 输出：
      - (1, 4+nc, N)  → 转置为 (N, 4+nc)，无独立 obj
      - (1, N, 4+nc)
      - (1, N, 5+nc)  → 含 obj
    返回 xyxy + score 的数组 (M, 5)，坐标已映射回原图。
    """
    arr = np.asarray(raw)
    if arr.ndim == 3:
        arr = arr[0]
    # 常见 ultralytics 导出: (4+nc, N) → 转为 (N, 4+nc)
    # N 通常很大(8400)；小 N 时若 dim0 为通道数(5..84)也转置
    if arr.ndim == 2:
        c_lim = 84
        if arr.shape[0] <= c_lim and arr.shape[0] < arr.shape[1]:
            arr = arr.T
        elif arr.shape[0] <= c_lim and arr.shape[1] <= 32 and arr.shape[0] >= 5:
            arr = arr.T

    if arr.shape[1] < 5:
        return np.zeros((0, 5), dtype=np.float32)

    # 判断是否含 objectness：列数 = 5 + nc
    # 单类时 4+nc=5，与 5+nc（nc=0）歧义；按列数启发式：
    # 5 列 → cx,cy,w,h,score；6+ 列且第5列像 obj 时用 obj*cls
    boxes_cxcywh = arr[:, :4]
    if arr.shape[1] == 5:
        scores = arr[:, 4]
    else:
        # YOLOv8: 4 + nc，无 obj；取类别最大分
        scores = arr[:, 4:].max(axis=1)

    mask = scores >= conf_thres
    if not np.any(mask):
        return np.zeros((0, 5), dtype=np.float32)

    boxes_cxcywh = boxes_cxcywh[mask]
    scores = scores[mask]
    cx, cy, bw, bh = boxes_cxcywh.T
    x1 = cx - bw / 2
    y1 = cy - bh / 2
    x2 = cx + bw / 2
    y2 = cy + bh / 2

    # letterbox 逆变换 → 原图
    x1 = (x1 - pad_x) / scale
    x2 = (x2 - pad_x) / scale
    y1 = (y1 - pad_y) / scale
    y2 = (y2 - pad_y) / scale

    x1 = np.clip(x1, 0, img_w)
    x2 = np.clip(x2, 0, img_w)
    y1 = np.clip(y1, 0, img_h)
    y2 = np.clip(y2, 0, img_h)

    return np.stack([x1, y1, x2, y2, scores], axis=1).astype(np.float32)


class OnnxYoloDetector:
    """
    本地 ONNX YOLO 检测器。
    默认权重 models/colony_yolo.onnx；registry 在加载失败时回退 OpenCV。
    """

    name = "yolo-onnx"

    def __init__(self, model_path: str = "models/colony_yolo.onnx"):
        self.model_path = model_path
        self._session = None

    def _load(self):
        if self._session is not None:
            return self._session
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError as e:
            raise RuntimeError("onnxruntime 未安装，无法使用 yolo-onnx 检测器") from e
        import os
        if not os.path.exists(self.model_path):
            raise RuntimeError(f"ONNX 权重不存在: {self.model_path}")
        self._session = ort.InferenceSession(
            self.model_path, providers=["CPUExecutionProvider"]
        )
        return self._session

    def _input_size(self, session) -> Tuple[int, int]:
        inp = session.get_inputs()[0]
        shape = []
        for d in inp.shape:
            shape.append(d if isinstance(d, int) else 640)
        # NCHW
        if len(shape) == 4:
            return int(shape[2]), int(shape[3])  # h, w
        return 640, 640

    def detect(self, image: np.ndarray, **kwargs: Any) -> DetectionResult:
        session = self._load()
        conf = float(kwargs.get("conf", 0.25))
        iou_thres = float(kwargs.get("iou", 0.45))

        img_h, img_w = image.shape[:2]
        ih, iw = self._input_size(session)
        boxed, scale, pad_x, pad_y = _letterbox(image, ih, iw)
        blob = boxed.astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1)[None]

        inp_name = session.get_inputs()[0].name
        outputs = session.run(None, {inp_name: blob})
        raw = outputs[0]
        dets = _decode_yolo_output(raw, conf, img_w, img_h, scale, pad_x, pad_y)

        if dets.shape[0] > 0:
            boxes = dets[:, :4]
            scores = dets[:, 4]
            keep = _nms_boxes(boxes, scores, iou_thres)
            dets = dets[keep]

        vis = image.copy()
        details: List[Dict[str, Any]] = []
        count = 0
        for x1, y1, x2, y2, score in dets:
            count += 1
            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)
            area = int(max(1, (x2 - x1) * (y2 - y1)))
            details.append({
                "id": count,
                "x": cx,
                "y": cy,
                "area": area,
                "circularity": None,
                "score": round(float(score), 4),
            })
            cv2.rectangle(vis, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
            cv2.putText(
                vis, str(count), (cx - 8, cy + 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1,
            )

        return DetectionResult(
            count=count,
            details=details,
            image=vis,
            meta={
                "detector": self.name,
                "model_path": self.model_path,
                "error": None,
                "conf": conf,
                "iou": iou_thres,
            },
        )


class DetectorRegistry:
    def __init__(self) -> None:
        self._detectors: Dict[str, ColonyDetector] = {
            "opencv": OpenCVSmartDetector(),
            "opencv-classic": OpenCVClassicDetector(),
            "yolo-onnx": OnnxYoloDetector(),
        }
        self._fallback = "opencv"

    def register(self, detector: ColonyDetector, name: Optional[str] = None) -> None:
        self._detectors[name or detector.name] = detector

    def available(self) -> List[str]:
        return list(self._detectors.keys())

    def get(self, name: str) -> ColonyDetector:
        det = self._detectors.get(name)
        if det is None:
            return self._detectors[self._fallback]
        if name == "yolo-onnx":
            try:
                det._load()  # type: ignore[attr-defined]
            except Exception:
                return self._detectors[self._fallback]
        return det


registry = DetectorRegistry()


def detect_colonies(image: np.ndarray, detector: str = "opencv", **kwargs: Any) -> DetectionResult:
    requested = detector
    det = registry.get(detector)
    result = det.detect(image, **kwargs)
    if requested and requested != "opencv" and det.name == "opencv":
        result.meta = dict(result.meta or {})
        result.meta["fallback"] = True
        result.meta["requested_detector"] = requested
    return result
