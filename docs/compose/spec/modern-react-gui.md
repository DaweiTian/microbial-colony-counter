---
feature: modern-react-gui
status: delivered
updated: 2026-09-13
branch: main
commits: (未提交，工作区变更)
---

# 现代化 React GUI（主界面重写 · 批次标定 · Tauri 桌面壳）

## Report

**What was built** — 以 Web 为主界面交付 Vite + React + TS + Tailwind 现代实验室工作台：单图计数（点击/拖拽/粘贴上传、参数滑条、防抖自动预览开关、ROI 矩形/圆+拖移+方向键微调、经典计数与一键智能、智能候选条形对比、结果/二值切换、详情表、历史、下载）与批次标定页（参考盘列表、PUT 同步 N/点、标定、批量计数、CSV/参数 JSON、应用到单图）。FastAPI 新增 `/api/v1/batch/*`（refs POST/PUT、calibrate、run，CPU 任务走线程池），`GET /` 服务 `frontend/dist`（同步至 `backend/static`，旧页备份为 `legacy-index.html.bak`）。`desktop/` 提供 Tauri 2 壳（`cargo check` 通过；`withGlobalTauri` + 前端 API_BASE 回退 `127.0.0.1:8000`）。Tkinter 主程序保留未删。

**Verification** — `cd frontend && npm run build:sync` PASS；`python backend/test_api_batch.py` PASS（health/root/refs/PUT/calibrate/plate keys=`predicted_count`/batch run/smart=95）；`python backend/test_algorithm.py` PASS（test1 petri=95、test2 petri=278）；`python backend/test_smart_count.py` 8 PASS；`cargo check`（desktop/src-tauri）PASS。独立审查 3 项 critical（事件循环阻塞、plate 字段名、缺 PUT）已修复并二次复查 PASS。

**Journey log** — create-tauri-app 在本机报「目录名称无效」，改为手写最小 Tauri 工程；crates.io 超时后改用 rsproxy sparse 镜像；`withGlobalTauri` 属于 `app` 而非 `app.security`；标定结果含 numpy 需 `_json_safe` 才能被 FastAPI 序列化；plate_results 真实字段是 `predicted_count/total_gt/fit_error` 而非猜测的 pred/gt/rel_error。

## [S1] Problem

现有前端有两套，体验与技术栈都过时：

1. **桌面 Tkinter**（`main.py` + `batch_workbench.py`）：功能全但视觉陈旧（多色 Material 按钮、灰底 Spinbox），布局拥挤，无法做出「科技感 / 实验室工具」品质；用户明确表示不够高级。
2. **Web 单文件**（`backend/static/index.html`，约 1288 行）：手机优先（`max-width: 600px`），桌面浏览器会挤成一长条；无拖拽上传、参数改动无即时预览、智能计数候选策略不可见、与桌面视觉语言不一致。
3. **批次标定仅 Tkinter**：无 HTTP API，手机/浏览器无法做批次标定与批量导出。

目标：以 **Web 为主界面**，用 **Vite + React + TypeScript + Tailwind** 重写单图计数与批次标定全流程，提供桌面双栏工作台布局与移动端适配；用 **Tauri** 包装为 Windows 客户端窗口。旧 `index.html` 被 React 构建产物取代。算法与既有 `/api/v1/count`、`/api/v1/count_smart` 语义不变。

## [S2] Design

### 2.1 产品范围（本期一次交付）

| 模块 | 内容 |
|------|------|
| 单图计数 | 拖拽/粘贴/点击上传、参数滑条、防抖预览、经典计数、一键智能、ROI、结果图/二值图、菌落数详情、历史、下载 |
| 批次标定 | 多参考盘（1–5）上传、人工 N、点选增强、标定、批量计数、CSV/参数 JSON 导出、参数回填单图 |
| 桌面壳 | Tauri 2 窗口加载构建后的前端；开发模式连本地 FastAPI |
| 入口替换 | FastAPI `/` 与 `/static` 服务 `frontend/dist`；旧 `backend/static/index.html` 改名为 `legacy-index.html.bak` 不再作为主入口 |

**明确不做（Out of Scope 见 S3）**：Flutter、YOLO 训练 UI、云同步、多用户、暗色主题完整双主题系统（仅图片舞台可用深色面板）、Tkinter 功能删除（保留可运行）。

### 2.2 架构分层

```
frontend/                     Vite + React + TS + Tailwind
  src/api/                    对 FastAPI 的 typed client
  src/features/count/         单图：上传 · 参数 · ROI · 结果
  src/features/batch/         批次：参考盘 · 标定 · 批量
  src/components/             通用：Button · Slider · Dropzone · Stage…
  src/styles/                 Tailwind token

backend/                      FastAPI（算法不动，补批次 HTTP API）
  static/                     挂载 frontend/dist（构建产物）
  api_batch.py 或 main 内扩展  标定/批量路由

desktop/                      Tauri 2 壳（仅窗口 + 前端资源 + 可选启动说明）
```

- **开发**：`npm run dev`（Vite，proxy `/api` → `http://127.0.0.1:8000`）+ `uvicorn backend.main:app`。
- **生产/分享**：`npm run build` → `frontend/dist`，FastAPI 直接服务；浏览器访问即可。
- **Tauri**：`desktop/` 指向已 build 的前端；`beforeDevCommand` 可起 Vite；连接本地已运行的后端（默认 `http://127.0.0.1:8000`）。Python sidecar 全量离线打包列为后续，不阻塞本期「可双击开窗连本机后端」。

### 2.3 视觉系统（现代实验室工具风）

风格锚点：Linear / 现代科学 SaaS 工作台——浅色、高对比层级、少装饰、数据与图像优先。

| Token | 值 | 用途 |
|-------|-----|------|
| bg | `#F4F6F8` | 页面底 |
| surface | `#FFFFFF` | 卡片/面板 |
| ink | `#0F172A` | 主文字 |
| muted | `#64748B` | 次级文字 |
| line | `#E2E8F0` | 分割线/描边 |
| primary | `#2563EB` | 主操作、选中 |
| accent | `#0D9488` | 智能/成功 |
| warn | `#D97706` | 警告（分水岭过分割等） |
| danger | `#DC2626` | 清空/失败 |
| stage | `#0B1220` | 图像舞台深色底（突出菌落标注） |

- 字体：`Inter, "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui`；数字与策略名可用 `ui-monospace, "JetBrains Mono", Consolas`。
- 圆角：卡片 `12px`，控件 `8px`；阴影极轻（`0 1px 2px rgb(15 23 42 / 0.06)`）。
- 间距节奏：4/8/12/16/24/32。
- 图标：lucide-react 线性图标，不用 emoji 作主按钮图标。

**布局**

- **≥1280px**：三栏工作台——左栏 260px（品牌/模式切换/上传/历史），中栏弹性（图像舞台，可切换 原图|二值|结果），右栏 320px（参数 + 结果摘要 + 智能候选）。
- **768–1279px**：两栏（中+右参数抽屉），左栏收成顶栏。
- **&lt;768px**：单列纵向（上传 → 预览/ROI → 参数折叠 → 操作 → 结果），触控目标 ≥44px。

**签名时刻**

1. 计数完成：结果卡数字滚动/强调动画 + 结果图上菌落标注淡入。
2. 智能计数：候选策略条形对比（strategy / count / score），高亮选中项。

### 2.4 交互契约（单图）

| 行为 | 约定 |
|------|------|
| 上传 | 点击、拖拽、粘贴（Ctrl+V）；支持 jpg/png/bmp/tiff/webp；换图清空结果与 ROI |
| 参数 | 滑条即时显示数值；`onParamsChanged` 标记 dirty；**防抖 400ms** 后可选「自动预览」（默认关，用户开关）；手动「开始计数」/「一键智能」始终可用 |
| 一键智能 | `POST /api/v1/count_smart`；展示 count、耗时、strategy、candidates；失败 toast |
| 经典计数 | `POST /api/v1/count`（含 ROI、全部参数） |
| ROI | 画布叠加；矩形/圆形；拖移、角点缩放、方向键微调；与「自动检测培养皿」互斥提示 |
| 结果 | 大图点击放大；二值图并排/切换；详情表可折叠；行 hover 高亮对应标注（若仅有中心点则高亮点） |
| 历史 | localStorage 最多 20 条（缩略 dataURL + count + 时间）；点击仅恢复元数据，不恢复原图字节（标注：需重传） |
| 下载 | 处理结果图 PNG 下载 |

### 2.5 交互契约（批次标定）

对齐 `batch_workbench.py` 语义，改为 HTTP：

| 能力 | API（新增） | 说明 |
|------|-------------|------|
| 添加参考盘 | `POST /api/v1/batch/refs` multipart 多文件 | 返回 ref_id、缩略图 base64 |
| 更新 N / 点选 | `PUT /api/v1/batch/refs/{id}` JSON `{total_gt, points:[{x,y}]}` | 点选坐标为图像像素 |
| 标定 | `POST /api/v1/batch/calibrate` `{ref_ids, max_evals?, time_limit_sec?}` | 调 `calibrate_multi`；耗时长，后端线程池执行 |
| 批量计数 | `POST /api/v1/batch/run` multipart 图片 + `params` JSON | 调 `batch_count_images`；返回各图 count + 可选缩略结果图 |
| 导出 | 前端生成 CSV；`params` JSON 下载 | 与 `results_to_csv_rows` 字段对齐（name,count,error） |

会话状态：参考盘与批量图列表存 **前端内存**（刷新丢失可接受）。图片字节存后端内存 `_REF_STORE`（上限 20，无 TTL，进程退出即清）；`PUT /refs/{id}` 同步 N/点；标定请求体仍可覆盖当前 N/点。

UI 流程：上传参考盘列表 → 逐盘填 N → 可选点选画布 → 「开始标定」进度 → 显示 fit_error 与最优 params → 「批量上传」→ 「应用标定参数批量计数」→ 表格 + 导出 CSV → 「应用到单图」。

### 2.6 后端增量（不改算法）

- 保持 `process_image` / `smart_count` / `calibrate_multi` / `batch_count_images` 不动。
- 新增批次路由时复用现有 `_executor` 与缩略图工具。
- CORS 已全开，开发 Vite proxy 亦可。
- `GET /` 改为读取 `backend/static/index.html`（构建产物）；若 dist 未构建则返回简短提示页（开发友好）。
- `backend/requirements.txt` 或根 `requirements.txt` 补 `fastapi`、`uvicorn`、`python-multipart`（若缺失）。

### 2.7 Tauri 壳

- 目录 `desktop/`（`create-tauri-app` 风格，identifier `com.microbial.colony-counter`）。
- `frontendDist` = `../frontend/dist`；窗口标题「微生物菌落计数器」；默认 1280×860，最小 960×640。
- 开发：文档说明先起 uvicorn + 可选 Vite；Tauri `devUrl` 可用 Vite 或直接 dist。
- 本期验收：`npm run tauri:dev`（或 `cargo tauri dev`）能打开窗口加载 UI 并调用已运行的 API；不要求安装包 `tauri build` 在 CI 全绿（本机尝试 build，失败则记录 blocker 不阻塞 Web 交付）。

### 2.8 工作区决策（覆盖默认）

- 用户明确：**不使用独立 worktree**，直接在 `D:\Mimo-workspace\microbial-colony-counter` 的 main 工作树修改。
- 旧 Web 页：**React 取代**，非并行 `/v2`。

## [S3] Out of Scope

- 删除或重写 Tkinter 主程序/批次工作台代码（保留现状，文档引导 Web）
- Flutter `mobile/` 完善
- Python 完全离线 sidecar / 安装包一键分发
- YOLO 训练与权重管理界面
- 多用户/权限/云端
- 改动 `process_image`、`smart_count` 核心算法行为
- 完整双主题（浅色为主；仅图像舞台深色）

## Tasks

- [x] T1: Scaffold frontend（Vite+React+TS+Tailwind+lucide）与设计 token/基础组件 — acceptance: `npm run build` 成功；有 Button/Card/Slider/Dropzone 与全局布局壳 (covers: S2.2, S2.3)
- [x] T2: API client 与类型 — acceptance: 对 `/api/v1/count`、`/api/v1/count_smart`、`/health` 有 typed 封装与错误处理 (covers: S2.2, S2.4)
- [x] T3: 单图上传与图像舞台 — acceptance: 点击/拖拽/粘贴选图，桌面三栏与移动单列自适应，ROI 画布可画矩形/圆并移动 (covers: S2.3, S2.4)
- [x] T4: 参数面板与经典计数 — acceptance: 滑条/开关齐全，POST count 显示结果图/二值/耗时/详情表，可下载结果图 (covers: S2.4)
- [x] T5: 一键智能与候选展示 — acceptance: count_smart 成功后展示 strategy/candidates 对比与签名动效 (covers: S2.4)
- [x] T6: 历史与空状态/错误提示 — acceptance: localStorage 历史列表，失败 toast，换图重置状态 (covers: S2.4)
- [x] T7: 批次 HTTP API — acceptance: refs 增改、calibrate、batch run 可用；`calibrate_multi`/`batch_count_images` 被调用且返回字段完整；有最小 API 测试或可复现 curl (covers: S2.5, S2.6)
- [x] T8: 批次标定 UI — acceptance: 参考盘列表、N、点选、标定进度、结果参数、批量表格、CSV 导出、应用到单图 (covers: S2.5)
- [x] T9: FastAPI 服务 dist 与旧页替换 — acceptance: `npm run build` 后 `GET /` 返回 React 应用；旧 index.html 不再作为 `/` 源 (covers: S2.2, S2.6)
- [x] T10: Tauri 桌面壳 — acceptance: `desktop/` 可开发运行并加载前端；README 启动步骤可复现 (covers: S2.7)
- [x] T11: 端到端验证与文档 — acceptance: 启动后端+前端，用 test1.jpg 走通智能计数与标定路径；更新 README/使用说明中的入口说明 (covers: S2.1, S2.7)
- [x] T12: 代码审查修复 — acceptance: Reviewer critical 项清零或有证据驳回 (covers: S2)
