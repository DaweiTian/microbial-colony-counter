# Tauri 桌面启动器

双击应用后自动拉起内置 Python 后端（sidecar），再在原生窗口中打开 React 界面。

## 一次性准备

```powershell
# 1) 前端
cd frontend
npm install
npm run build:sync
cd ..

# 2) 后端 sidecar（onedir，输出到 desktop/src-tauri/sidecar-backend/）
python build_sidecar.py
```

## 开发运行

```powershell
cd desktop
npm install
# 使用系统 Node（避免路径含空格的 node 解析问题）
# "C:\Program Files\nodejs\node.exe" node_modules\@tauri-apps\cli\tauri.js dev
npm run tauri:dev
```

- 开发模式 UI 走 Vite（5173）；sidecar 听 **18085**
- 若 18085 已有服务，会跳过再启动

## 发布安装包

```powershell
# 推荐：统一入口（构建 + 收集到仓库根 dist/）
python package_release.py --build

# 或只打 Tauri 包，再手动收集
cd desktop
npm run tauri:build -- --bundles nsis
cd ..
python package_release.py
```

**交付物固定在 `dist/installer/`**（例如 `微生物菌落计数器_0.1.5_x64-setup.exe`）。

各工具默认中间输出（勿当交付物）：

| 路径 | 内容 |
|------|------|
| `desktop/src-tauri/target/release/bundle/nsis/` | Tauri NSIS 原始输出 |
| `desktop/src-tauri/sidecar-backend/` | Python 后端 onedir |
| `frontend/dist/` | 前端构建中间目录 |
| `backend/static/` | 前端同步副本 |
| `dist/installer/` | **最终安装包** |

## 说明

| 项 | 值 |
|----|----|
| Sidecar | `sidecar-backend/colony-backend.exe`（onedir） |
| API | `http://127.0.0.1:18085` |
| 关窗 | 结束 sidecar（无托盘、无黑框） |
| 图标 | 根目录 `icon.png` → `desktop/src-tauri/icons/` |

Python 后端源码为 `backend_server.py`，由 `build_sidecar.py` 用 PyInstaller 打包（console + 父进程 `CREATE_NO_WINDOW`，避免 uvicorn 在 noconsole 下异常且不弹窗）。
