---
feature: smart-colony-count-v2
status: delivered
updated: 2026-09-13
branch: main
commits: (未提交，工作区变更)
---

# 智能菌落计数 v2（评估 · 密菌落分离 · 一键智能 · DL 预留）

## Report

**What was built** — 在保留既有经典 OpenCV 计数、GUI、Web 与批次标定语义的前提下，交付了四块增量能力：(1) 可复现评估 CLI（`python -m backend.eval.run`），用例在 `backend/eval/cases/`，报告写入 `backend/eval/out/report.md`；(2) 密菌落分离：新增 `backend/core/blobcount.py`，`process_image` 支持 `segment_mode=labels|peaks|classic`，修复旧分水岭重建导致 test1 从 95 塌到 11 的缺陷，标签直计数 + 距离场 NMS 后 test1 labels=70，test2 labels=845（经典 petri 仅 278，目视粘连严重）；(3) 一键智能 `smart_count`：自动检皿、估参、多策略试跑与无真值选优，test1 选中 default_petri=95（与暂定真值一致），test2 选中 default_labels=845，结果图见 `backend/eval/out/test*_smart.jpg`；(4) 检测器抽象 `backend/core/detector.py`（OpenCV 默认 + `yolo-onnx` 占位回退），桌面「⚡ 一键智能」与 Web `POST /api/v1/count_smart` 已接入，旧 `POST /api/v1/count` 与「▶️ 处理」行为不变。

**Verification** — `python backend/test_smart_count.py` 8 PASS；`python backend/test_algorithm.py` 经典 test1=134/95、test2=691/278 与改前一致；`python backend/test_calibrator.py` OK（单盘相对误差约 8%）；`python -m backend.eval.run` 生成对比报告；FastAPI 路由含 `/api/v1/count` 与 `/api/v1/count_smart`。

**Journey log** — 旧 `_apply_watershed` 重建二值图会抹掉小菌落核，改为标签直计数是关键；局部极大若不做平滑+NMS 会把单菌落拆成上千碎片；估参过激进会劣化默认参数，因此 smart 以库存默认参数为主候选、估参仅作补充；无真值时选优对「过低计数」必须重罚，否则 Otsu 手动阈值会以 count=2 获胜；密菌落 smart 全策略约 30s，默认策略得分足够时会跳过估参变体。

## [S1] Problem

现有 OpenCV 流水线（`backend/core/algorithm.py` → `process_image`）已能完成「拍图 → 自动计数」，但在真实培养皿上仍有明显缺口：

1. **密菌落粘连**：test2 目视菌落数远多于算法输出（petri=278），大量相邻菌落被合成一个轮廓；全局分水岭对 test1 反而从 95 塌到 11，不可用。
2. **缺少可复现评估**：仓库无标注真值与评估脚本，无法量化改进；标定脚本把「默认 petri 计数」当作 test2 真值，存在循环论证。
3. **调参门槛高**：用户需手调模糊核、阈值、面积、分水岭、圆度；批次标定仍要先人工数参考盘。
4. **后续要上检测模型**，但当前算法与 UI 耦合，没有稳定的检测器抽象。

目标：在**不破坏**现有单图 API/GUI/批次标定语义的前提下，交付可复现评估、可用的密菌落分离、一键智能计数入口，并为本地深度学习检测预留接口。

## [S2] Design

### 2.1 架构分层

```
UI (桌面 / Web)
    │  count_smart / count(legacy)
    ▼
backend/core/smart.py          一键：估参 + 多策略试跑 + 选优
    │
    ├── backend/core/algorithm.py   既有 process_image（只修 bug / 增强，不改签名默认语义）
    ├── backend/core/blobcount.py   密菌落：距离变换局部极大 + 分水岭标签计数（新）
    └── backend/core/detector.py    ColonyDetector 协议 + OpenCV 实现 + DL 占位

backend/core/evaluate.py       离线评估：跑配置矩阵、对比 GT、出报告
backend/eval/cases/            评估用例：图 + GT JSON
```

### 2.2 算法增强（密菌落）

**问题根因**：`_apply_watershed` 把 watershed 标签重建为二值前景时，小菌落核被 `morphologyEx(OPEN)` 与全局 `dist_transform` 阈值抹掉，导致欠分割/漏检。

**方案 A — 标签直计数（默认新路径 `segment_mode="labels"`）**：

1. 二值化后做形态学开运算（核大小可配，默认 3）。
2. 距离变换 → `cv2.dilate` 取局部极大作为 sure foreground 种子（比固定 0.4×max 更稳）。
3. `connectedComponents` 种子 → 标记未知区 → `cv2.watershed`。
4. **直接遍历 labels≥2 的连通域**做面积/圆度/边缘过滤，不再重建二值图。

**方案 B — 仅局部极大计数（`segment_mode="peaks"`）**：对极密、几乎连成片的盘，用距离变换局部极大点数作为菌落数，面积用邻域估计；作 smart 试跑的候选之一。

**兼容**：

- `use_watershed=True` 且未指定 `segment_mode` 时走修复后的标签路径（行为从「错误地塌缩」变为「可用」，属 bugfix）。
- `use_watershed=False` 保持原轮廓路径。
- Web/桌面参数透传新增 `segment_mode`（可选，默认 `auto`=有分水岭时 labels）。

### 2.3 一键智能计数 `smart.py`

```python
def smart_count(image, overrides=None) -> dict
# 返回与 process_image 兼容的超集：
# {count, processed_image, binary_image, colony_details, petri_circle,
#  strategy, params, candidates: [{strategy, count, score}], ...}
```

流程：

1. **培养皿**：`detect_petri_dish_circle`；失败则全图 + 边缘距离。
2. **图像统计**：灰度均值/方差、Otsu 候选阈值、菌落像素占比 → 估计 `min_area/max_area`（以皿半径归一）、`blur_ksize`、`adaptive_c`。
3. **候选策略**（并行评估，取分最高）：
   - `contour`：经典轮廓 + 自适应阈值
   - `labels`：分水岭标签
   - `peaks`：距离变换极大
   - 可选 `contour_manual_otsu`
4. **选优启发式**（无 GT 时）**：
   - 中位圆度落在 [0.35, 0.95]
   - 面积 IQR 不爆炸（排除碎片噪声）
   - 菌落中心不贴皿边（rim 抑制）
   - 计数落在合理区间（与皿面积相关的上下界）
   - 综合 `score = w1*shape + w2*area_sanity + w3*rim + w4*density_bonus`
5. 返回最优结果 + 候选列表（便于 UI 展示「为何选它」）。

**接口**：

- 桌面：工具栏「⚡ 一键智能计数」
- Web：`POST /api/v1/count_smart`；旧 `POST /api/v1/count` 不动

### 2.4 检测器抽象（DL 预留）

```python
# backend/core/detector.py
class ColonyDetector(Protocol):
    name: str
    def detect(self, image: np.ndarray, **kwargs) -> DetectionResult: ...

class OpenCVDetector:  # 包装 smart_count / process_image
class DetectorRegistry:
    # "opencv" | "opencv-classic" | 未来 "yolo-onnx"
    def get(name: str) -> ColonyDetector
```

`DetectionResult`：`count`, `details`, `image`, `meta`。

DL 落地约定（本阶段不实现训练）：

- 推理格式：ONNX（YOLO 系检测头，单类 colony）。
- 权重路径：`models/colony_yolo.onnx`（可选安装）；缺失时 registry 回退 OpenCV。
- 训练数据：后续用桌面「点选校正」导出的点+框标注；本阶段评估图不上传云端。

### 2.5 评估

**GT 格式** `backend/eval/cases/<id>.json`：

```json
{
  "image": "test1.jpg",
  "count": 95,
  "confidence": "approximate",
  "notes": "目视估计；密菌落待人工复核"
}
```

**CLI**：

```bash
python -m backend.eval.run              # 全部用例
python -m backend.eval.run --case test1
```

输出：每用例各策略 `count / |err| / rel_err / time`，以及汇总表；写 `backend/eval/out/report.md`。

**基线与改进后（2026-09-13，本机）**：

| 图 | 策略 | 改前 | 改后 | 备注 |
|----|------|-----:|-----:|------|
| test1 | classic petri | 95 | 95 | 与暂定 GT=95 对齐 |
| test1 | petri+watershed | 11 | labels=70 | 修复塌缩 |
| test1 | smart | — | 95 (default_petri) | 选优正确 |
| test2 | classic petri | 278 | 278 | 目视严重粘连合并 |
| test2 | petri+watershed | 287 | labels=845 | 粘连分离有效 |
| test2 | smart | — | 845 (default_labels) | 密菌落选用 labels |

### 2.6 错误与边界

- 图像读失败 / 空图：返回 `error` 字段，不抛到 UI。
- 培养皿检测失败：smart 回退全图；在 `meta` 标记 `petri_detected=false`。
- 超大图：沿用现有 max_dimension=1200 缩放及面积缩放。
- 旧 API 字段只增不减；`segment_mode` 缺省时经典路径行为与 v1.1.2 一致（除 watershed bugfix）。

## [S3] Out of Scope

- 深度学习模型训练、权重分发、GPU 推理（只留接口与文档约定）。
- 手机 App / Flutter 端改造。
- 批次标定算法重写（继续复用 `process_image`；smart 可作为其默认底座后续再接）。
- 云端标注平台、账号体系。
- 删除或重命名既有桌面/Web 功能入口。

## Tasks

- [x] T1: 评估用例与 CLI — acceptance: `python -m backend.eval.run` 在 test1/test2 上输出各策略 count/误差/耗时，并生成 `backend/eval/out/report.md`（covers: S2.5）
- [x] T2: 修复分水岭并实现 blobcount 标签/峰值模式 — acceptance: test1 开分水岭后 count 与 classic 同量级（不再≈11）；test2 labels/peaks 不低于 classic 粘连结果且不崩溃；单元测试覆盖 `segment_mode` 三种取值（covers: S2.2; depends: T1）
- [x] T3: smart_count 一键估参选优 — acceptance: 对 test1/test2 无手工参数时返回结果含 strategy 与 params；test1 不明显差于 classic petri；实现有测试（covers: S2.3; depends: T2）
- [x] T4: ColonyDetector 抽象与注册表 — acceptance: `DetectorRegistry.get("opencv")` 可调用并返回 DetectionResult；未知名回退 opencv；测试通过（covers: S2.4; depends: T3）
- [x] T5: 桌面与 Web 接入一键入口 — acceptance: GUI 工具栏可触发 smart；Web `POST /api/v1/count_smart` 返回与旧 count 兼容的 JSON 超集；旧 `/api/v1/count` 行为不变（covers: S2.3; depends: T3）
- [x] T6: 复跑评估并更新本文件 Report — acceptance: report.md 含改进前后对比；本文件 status=delivered（covers: S2.5; depends: T1 T2 T3 T5）
