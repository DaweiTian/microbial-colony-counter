"""构建 Tauri sidecar 后端（onedir，启动快、无解压等待）。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = "colony-backend"
# onedir 输出目录：作为 Tauri resource 整夹打包
OUT_DIR = ROOT / "desktop" / "src-tauri" / "sidecar-backend"


def main() -> int:
    static = ROOT / "backend" / "static"
    if not (static / "index.html").exists():
        print("缺少 backend/static/index.html，先 npm run build:sync")
        return 1

    work = ROOT / "build_sidecar"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        # 必须 console：noconsole 会让 uvicorn 启动异常。
        # 黑框由父进程 CREATE_NO_WINDOW 抑制。
        "--console",
        "--name",
        APP,
        "--paths",
        str(ROOT),
        "--distpath",
        str(work / "dist"),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(work),
        "--add-data",
        f"{ROOT / 'backend' / 'static'}{sep}backend/static",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.loops.asyncio",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.protocols.http.h11_impl",
        "--hidden-import",
        "uvicorn.protocols.websockets.auto",
        "--hidden-import",
        "uvicorn.lifespan.on",
        "--hidden-import",
        "backend.main",
        "--hidden-import",
        "backend.api_batch",
        "--hidden-import",
        "backend.image_security",
        "--collect-all",
        "cv2",
        "--collect-all",
        "uvicorn",
        "--exclude-module",
        "onnxruntime",
        "--exclude-module",
        "tensorflow",
        str(ROOT / "backend_server.py"),
    ]
    print("构建 sidecar (onedir, console+CREATE_NO_WINDOW)…")
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        return rc

    src = work / "dist" / APP
    if not (src / f"{APP}.exe").exists():
        print("未找到 sidecar 目录:", src)
        return 1
    # 拷贝整个 onedir
    shutil.copytree(src, OUT_DIR, dirs_exist_ok=True)
    exe = OUT_DIR / f"{APP}.exe"
    mb = sum(f.stat().st_size for f in OUT_DIR.rglob("*") if f.is_file()) / (1024 * 1024)
    print(f"✅ {exe}")
    print(f"   总大小约 {mb:.1f} MB（onedir，启动快）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
