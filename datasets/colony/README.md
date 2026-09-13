# 菌落 YOLO 数据集

本目录默认由伪标签导出生成，**请按批次补充人工校正后再训练**。

## 目录结构

```text
datasets/colony/
  images/train/   images/val/
  labels/train/   labels/val/
  dataset.yaml
  export_meta.json
```

## 标注格式（YOLO txt）

每行：`class cx cy w h`（归一化 0–1），单类 `0 = colony`。

由中心点生成方框：边长 ≈ 2 × 菌落半径（由 area 估计）。

## 推荐流程

1. 伪标签导出：
   ```bash
   python -m backend.yolo.export_dataset --image-dir /path/to/photos --out datasets/colony --val-ratio 0.2
   ```
2. **人工抽检/改错**（LabelImg / CVAT / Roboflow 均可），重点：密菌落漏检、笔迹误检。
3. 训练：
   ```bash
   pip install -r requirements-ml.txt
   python -m backend.yolo.train --data datasets/colony/dataset.yaml --epochs 50 --imgsz 640
   ```
4. 导出 ONNX 到推理路径：
   ```bash
   python -m backend.yolo.to_onnx --weights runs/detect/colony/weights/best.pt --out models/colony_yolo.onnx
   ```
5. 应用：`DetectorRegistry` / API 使用 `yolo-onnx`；无权重时自动回退 OpenCV。

## 建议数据量

| 阶段 | 图片数 | 说明 |
|------|--------|------|
| 冒烟 | 5～20 | 只验证管线 |
| 可用 | 80～150 | 覆盖稀疏/密菌落、光照、笔迹、反光 |
| 较稳 | 300+ | 多设备/多菌种 |

评估主指标用 `backend/eval` 的计数相对误差，mAP 仅作参考。
