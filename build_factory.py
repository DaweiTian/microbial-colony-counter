"""构建工厂测试包（onedir，便于拷贝与杀软友好）。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist_factory"
APP_NAME = "ColonyCounterFactory"


def main() -> int:
    static = ROOT / "backend" / "static"
    if not (static / "index.html").exists():
        print("❌ 缺少 backend/static/index.html，请先: cd frontend && npm run build:sync")
        return 1

    if DIST.exists():
        shutil.rmtree(DIST)
    build_dir = ROOT / "build_factory"
    if build_dir.exists():
        shutil.rmtree(build_dir)

    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        APP_NAME,
        "--paths",
        str(ROOT),
        "--distpath",
        str(DIST),
        "--workpath",
        str(build_dir),
        "--specpath",
        str(build_dir),
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
        "--hidden-import",
        "backend.core.algorithm",
        "--hidden-import",
        "backend.core.smart",
        "--hidden-import",
        "backend.core.blobcount",
        "--hidden-import",
        "backend.core.calibrator",
        "--hidden-import",
        "backend.core.batch",
        "--hidden-import",
        "backend.core.detector",
        "--collect-all",
        "cv2",
        "--collect-all",
        "uvicorn",
        str(ROOT / "factory_server.py"),
    ]

    print("🔨 开始打包工厂测试版…")
    rc = subprocess.call(cmd, cwd=str(ROOT))
    if rc != 0:
        print("❌ PyInstaller 失败")
        return rc

    out = DIST / APP_NAME
    exe = out / f"{APP_NAME}.exe"
    if not exe.exists():
        print("❌ 未找到生成的 exe:", exe)
        return 1

    readme = out / "使用说明.txt"
    readme.write_text(
        "微生物菌落计数器 · 工厂测试版\n"
        "================================\n"
        "1. 双击 ColonyCounterFactory.exe 启动\n"
        "2. 浏览器会自动打开 http://127.0.0.1:8000/\n"
        "3. 上传培养皿照片 → 点「一键智能」或「开始计数」\n"
        "4. 批次标定在顶部「批次标定」页签\n\n"
        "局域网/手机访问（可选）:\n"
        "  新建 start_lan.bat，内容：\n"
        "    set COLONY_HOST=0.0.0.0\n"
        "    ColonyCounterFactory.exe\n"
        "  然后用本机 IP 访问 http://<本机IP>:8000/\n\n"
        "默认仅监听 127.0.0.1，避免未授权访问。\n"
        "如杀毒软件拦截，请选择信任/允许。\n",
        encoding="utf-8",
    )

    zip_base = DIST / "ColonyCounterFactory-win64"
    zip_path = shutil.make_archive(
        str(zip_base), "zip", root_dir=str(out.parent), base_dir=out.name
    )
    size_mb = os.path.getsize(exe) / (1024 * 1024)
    zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print("✅ 工厂测试包已生成")
    print(f"   目录: {out}")
    print(f"   EXE:  {exe} ({size_mb:.1f} MB)")
    print(f"   ZIP:  {zip_path} ({zip_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
