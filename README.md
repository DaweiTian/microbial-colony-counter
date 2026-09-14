# 微生物菌落计数器

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.x-green.svg)](https://opencv.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/badge/Release-v0.2.0-orange.svg)](https://github.com/DaweiTian/microbial-colony-counter/releases/tag/v0.2.0)

培养皿菌落自动计数工具：现代 Web 工作台 + 本地 Python 后端，可选 Tauri 桌面安装包。支持一键智能计数、皿内圆形裁切、参数调节、ROI、批次标定、历史回放与导出。

**仓库**: [https://github.com/DaweiTian/microbial-colony-counter](https://github.com/DaweiTian/microbial-colony-counter)

**当前版本**: **v0.2.0**

---

## 功能概览

### 单图计数

- 上传 / 拖拽 / Ctrl+V 粘贴图片（JPG、PNG、BMP、TIFF、WebP）
- **一键智能计数**：自动估参 + 多策略选优
- **按参数手动计数**：二值化、模糊、面积、边缘距离、圆度、分水岭等
- **ROI**：全图 / 矩形 / 圆形，可缩放、键盘微调
- **皿内圆形裁切**：按原图分辨率裁出培养皿并遮罩圆外背景，减少整图压缩导致的模糊
- 超大图自动等比缩小后再计数，并提示缩放比例
- 原图 / 结果 / 二值切换；结果卡含菌落数、策略、警告、候选对比、详情表
- 导出菌落详情 CSV、下载结果图（系统「另存为」）

### 批次标定

- 上传 1～5 块参考盘，填写人工计数 N，可选点选典型菌落
- 图片默认适配窗口，支持缩放 / 平移；点选在任意缩放下可用
- 联合搜索本批次参数，批量计数其余平板，导出 CSV

### 界面与桌面

- 浅色 / 深色主题切换（跟随系统或手动）
- 布局：左侧选图 + 历史，右侧舞台；参数悬浮面板；智能计数固定底部
- 历史本地保存、回放、重命名、单删 / 批删、批量导出 CSV
- Tauri 桌面壳：无系统标题栏、自绘顶栏、版本徽章、默认最大化
- 安装包带本地 sidecar 后端，双击即可用

### 算法能力

- OpenCV 经典轮廓 / 分水岭标签 / 距离场峰值等多策略
- 培养皿圆形检测（大图先降到约 1000px 再 Hough，避免卡死）
- 可选 YOLO ONNX 检测器骨架（无权重时自动回退 OpenCV）

---

## 快速开始

### 方式一：安装包（推荐）

从 [Releases](https://github.com/DaweiTian/microbial-colony-counter/releases) 下载  
`微生物菌落计数器_0.2.0_x64-setup.exe`，安装后双击运行。

应用会自动拉起本地后端（默认 `http://127.0.0.1:18085`），无需单独启动 Python。

### 方式二：源码运行 Web 界面

```bash
# 1) Python 依赖
pip install -r requirements.txt

# 2) 构建前端并同步到 backend/static
cd frontend
npm install
npm run build:sync
cd ..

# 3) 启动后端（默认端口 18085）
uvicorn backend.main:app --host 127.0.0.1 --port 18085
# 浏览器打开 http://127.0.0.1:18085
```

开发热更新：

```bash
# 终端 1：后端
uvicorn backend.main:app --port 18085

# 终端 2：前端（/api 代理到 18085）
cd frontend && npm run dev
# 打开 http://127.0.0.1:5173
```

Windows 也可用 `start_web_app.ps1` / `python web_launcher.py`。

### 方式三：Tauri 桌面开发

```powershell
# 前端已 build:sync 后
cd desktop
npm install
npm run tauri:dev
```

详见 [`desktop/README.md`](desktop/README.md)。

### 方式四：打包安装包

```powershell
python package_release.py --build
# 交付物：dist/installer/微生物菌落计数器_0.2.0_x64-setup.exe
```

脚本会依次构建前端、PyInstaller sidecar、Tauri NSIS，并把安装包收集到 `dist/installer/`。

---

## 使用提示

### 皿内裁切（推荐大图）

1. 底栏点「皿内裁切」进入圆形 ROI  
2. 拖拽 / 缩放圆，尽量贴合培养皿边缘  
3. 点「裁切皿内·智能」或「裁切·按参数」  

裁切在**原图分辨率**上进行，圆外涂为皿缘均色，有利于阈值分割。

### 大图说明

- 后端默认将最长边限制在约 8000px、约 25MP，超出会自动缩小并在结果中提示  
- 舞台图片按容器自适应显示，不会撑出滚动条  

### 历史与导出

- 记录保存在**本机浏览器 localStorage**，不会上传  
- 导出走系统「另存为」，可自定义路径与文件名  
- 可用环境变量 `COLONY_EXPORT_DIR` 指定「直接写入」模式的目录（默认尝试「下载」）  

### 批次标定要点

- 换菌种、培养基或拍摄条件后应重新标定  
- 建议 2～5 块参考盘联合学习，密菌落可对难盘做点选增强  

设计说明见 [`开发计划-批次标定.md`](开发计划-批次标定.md)。

---

## API（摘要）

默认监听 `http://127.0.0.1:18085`。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/count` | 按参数计数（可带 ROI） |
| POST | `/api/v1/count_smart` | 一键智能计数 |
| POST | `/api/v1/export` | 保存导出文件到本机 |
| POST | `/api/v1/batch/*` | 参考盘 / 标定 / 批量 |
| GET | `/health` | 健康检查 |

```bash
curl -F "image=@test1.jpg" http://127.0.0.1:18085/api/v1/count_smart
```

交互式文档：启动后访问 `http://127.0.0.1:18085/docs`（可用 `COLONY_ENABLE_DOCS=0` 关闭）。

---

## 离线评估（可选）

```bash
python -m backend.eval.run
python -m backend.eval.run --case test1
```

用例与真值：`backend/eval/cases/*.json`；报告：`backend/eval/out/report.md`。请用人工计数作为真值。

---

## YOLO 数据与训练（可选）

核心计数以 OpenCV 为主，YOLO 为可选增强：

```bash
python -m backend.yolo.export_dataset --image-dir /path/to/photos --out datasets/colony
pip install -r requirements-ml.txt
python -m backend.yolo.train --data datasets/colony/dataset.yaml --epochs 50
python -m backend.yolo.to_onnx --weights runs/detect/colony/weights/best.pt --out models/colony_yolo.onnx
```

无权重时 `detector=yolo-onnx` 会自动回退 OpenCV。

---

## 环境要求

- **Python** 3.10+（开发验证环境为 3.13）
- **Node.js** 18+（构建前端 / Tauri）
- **系统**：Windows 10/11（安装包）；Linux/macOS 可源码运行 Web 版

```text
opencv-python>=4.5.0,<5
numpy>=1.19.0,<3
Pillow>=8.0.0,<12
fastapi>=0.100.0,<1
uvicorn[standard]>=0.23.0,<1
python-multipart>=0.0.6,<1
```

```bash
git clone https://github.com/DaweiTian/microbial-colony-counter.git
cd microbial-colony-counter
pip install -r requirements.txt
```

---

## 项目结构

```text
microbial-colony-counter/
├── backend/
│   ├── core/
│   │   ├── algorithm.py       # 计数主流程（含大图内部缩放）
│   │   ├── blobcount.py       # 标签 / 峰值 / 分水岭
│   │   ├── smart.py           # 智能估参与多策略选优
│   │   ├── detector.py        # opencv / yolo-onnx
│   │   ├── calibrator.py      # 批次参数学习
│   │   ├── batch.py           # 批量计数
│   │   └── ...
│   ├── image_security.py      # 上传校验、自动降采样、导出路径
│   ├── main.py                # FastAPI 入口
│   ├── api_batch.py           # 批次 HTTP API
│   └── static/                # 前端构建产物（sidecar 打包用）
├── frontend/                  # Vite + React + TS + Tailwind
│   └── src/
│       ├── features/count/    # 单图计数页
│       ├── features/batch/    # 批次标定页
│       └── components/        # 主题、标题栏、通用 UI
├── desktop/                   # Tauri 2 桌面壳
│   └── src-tauri/
├── package_release.py         # 一键构建并收集安装包到 dist/installer/
├── build_sidecar.py           # PyInstaller onedir 后端
└── README.md
```

旧版 Tkinter 主程序（`main.py`）仍保留，日常请优先使用 Web / 桌面安装包。

---

## 更新日志

### v0.2.0（发布）

- 浅色 / 深色主题；标题栏版本徽章  
- 单图页新布局：左栏 + 舞台、悬浮参数、底部智能计数  
- 皿内圆形裁切（原分辨率 + 圆外掩膜）  
- 大图自动降采样；舞台自适应不溢出  
- 历史回放 / 重命名 / 删除 / 批量导出；导出「另存为」  
- 批次图缩放与点选；点位随缩放变化  
- 桌面：自绘标题栏、默认最大化、关窗清理 sidecar、安装前结束占用进程  
- 统一打包脚本 `package_release.py`  

### 历史版本

- **v1.2.x 系列**：一键智能、密菌落分离、评估 CLI、YOLO 准备（旧版本号体系）  
- **v1.1.2**：多参考盘联合标定  
- **v1.1.1**：批次标定工作台  

---

## 贡献

欢迎 Issue 与 Pull Request。

## 许可证

[MIT License](LICENSE)

## 联系方式

- 维护者：Vincent Tian  
- 邮箱：tianwenx@wo.cn  

---

**Enjoy counting!**
