# 桌面端（Tauri）

Windows 客户端窗口，加载 React 前端并连接本机 FastAPI 后端。

## 前置

1. 后端已启动：仓库根目录 `uvicorn backend.main:app --host 127.0.0.1 --port 8000`
2. 已安装 Rust（`rustc --version`）与 Node 20+
3. 前端依赖已安装（`cd frontend && npm install`）

## 开发运行

```powershell
cd desktop
npm install
npm run tauri:dev
```

- `beforeDevCommand` 会启动 Vite（`http://127.0.0.1:5173`）
- 页面通过 `/api` 代理访问 `http://127.0.0.1:8000`；若直连打包页，前端会使用 `http://127.0.0.1:8000` 或环境变量 `VITE_API_BASE`

## 打包

```powershell
npm run tauri:build
```

会先构建前端再编译安装包。Python 后端仍需单独运行（本期不含 sidecar 离线打包）。
