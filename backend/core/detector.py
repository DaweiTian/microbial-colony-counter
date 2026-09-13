"""菌落检测器抽象：OpenCV 实现 + 深度学习占位。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

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


class OnnxYoloDetector:
    """
    本地 ONNX YOLO 检测占位。
    权重路径默认 models/colony_yolo.onnx；未安装时 raise，由 registry 回退 OpenCV。
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
        self._session = ort.InferenceSession(self.model_path, providers=["CPUExecutionProvider"])
        return self._session

    def detect(self, image: np.ndarray, **kwargs: Any) -> DetectionResult:
        session = self._load()
        # 推理契约：输入 NCHW float32 0-1，输出 (1, N, 6) = x1,y1,x2,y2,score,cls
        # 具体预处理随训练配置在后续阶段落地；此处保证接口可调用。
        h, w = image.shape[:2]
        inp = session.get_inputs()[0]
        _, _, ih, iw = [d if isinstance(d, int) else 512 for d in inp.shape]
        resized = cv2_resize(image, iw, ih)
        blob = resized.astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1)[None]
        outputs = session.run(None, {inp.name: blob})
        det = outputs[0]
        details: List[Dict[str, Any]] = []
        count = 0
        sx, sy = w / float(iw), h / float(ih)
        for row in det[0]:
            x1, y1, x2, y2, score, _cls = [float(v) for v in row[:6]]
            if score < float(kwargs.get("conf", 0.25)):
                continue
            count += 1
            details.append({
                "id": count,
                "x": int((x1 + x2) / 2 * sx),
                "y": int((y1 + y2) / 2 * sy),
                "area": int(max(1, (x2 - x1) * sx * (y2 - y1) * sy)),
                "circularity": None,
                "score": round(score, 4),
            })
        return DetectionResult(
            count=count,
            details=details,
            image=image,
            meta={"detector": self.name, "model_path": self.model_path, "error": None},
        )


def cv2_resize(image: np.ndarray, w: int, h: int) -> np.ndarray:
    import cv2
    return cv2.resize(image, (w, h))


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
            # 探测可用性，不可用则回退
            try:
                det._load()  # type: ignore[attr-defined]
            except Exception:
                return self._detectors[self._fallback]
        return det


registry = DetectorRegistry()


def detect_colonies(image: np.ndarray, detector: str = "opencv", **kwargs: Any) -> DetectionResult:
    return registry.get(detector).detect(image, **kwargs)
