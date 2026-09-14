"""收集桌面安装包等发布产物到统一的 dist/ 目录。

Tauri/PyInstaller 默认输出路径分散，本脚本只做「归位」：
  dist/installer/  ← NSIS 安装包（主交付物）
  dist/RELEASE.txt ← 产物说明

用法:
  python package_release.py           # 仅收集已有产物
  python package_release.py --build   # 先前端+sidecar+tauri 再收集
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
INSTALLER_DIR = DIST / "installer"
NSIS_DIR = ROOT / "desktop" / "src-tauri" / "target" / "release" / "bundle" / "nsis"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"\n$ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=str(cwd or ROOT))


def build_all() -> None:
    # 1) 前端并同步到 backend/static（sidecar 会打包这份静态资源）
    npm = shutil.which("npm") or "npm"
    run([npm, "run", "build:sync"], cwd=ROOT / "frontend")
    # 2) sidecar onedir
    run([sys.executable, "build_sidecar.py"])
    # 3) Tauri NSIS
    run([npm, "run", "tauri:build", "--", "--bundles", "nsis"], cwd=ROOT / "desktop")


def collect() -> Path | None:
    DIST.mkdir(exist_ok=True)
    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)

    # 清掉 installer 里旧的 setup，避免版本堆积
    for old in INSTALLER_DIR.glob("*-setup.exe"):
        old.unlink()

    if not NSIS_DIR.is_dir():
        print(f"未找到 NSIS 产物目录: {NSIS_DIR}")
        print("请先执行: npm run tauri:build -- --bundles nsis  （或 python package_release.py --build）")
        return None

    setups = sorted(NSIS_DIR.glob("*-setup.exe"), key=lambda p: p.stat().st_mtime)
    if not setups:
        print(f"NSIS 目录中没有 *-setup.exe: {NSIS_DIR}")
        return None

    src = setups[-1]
    dest = INSTALLER_DIR / src.name
    shutil.copy2(src, dest)
    print(f"已复制安装包 → {dest}")

    # 主程序 exe（免安装调试用）
    app_exe = ROOT / "desktop" / "src-tauri" / "target" / "release" / "colony-counter-desktop.exe"
    if app_exe.is_file():
        shutil.copy2(app_exe, DIST / app_exe.name)
        print(f"已复制主程序 → {DIST / app_exe.name}")

    notes = f"""微生物菌落计数器 · 发布产物
==============================

安装包（推荐分发）
  installer/{dest.name}

主程序（与 sidecar-backend 同目录才可独立运行，一般不必单独发）
  colony-counter-desktop.exe

构建源路径（中间产物，勿当交付物）
  desktop/src-tauri/target/release/bundle/nsis/   Tauri NSIS 默认输出
  desktop/src-tauri/sidecar-backend/              Python 后端 onedir
  frontend/dist/                                  前端构建中间目录
  backend/static/                                 前端同步副本（sidecar 打包用）

重新打包
  python package_release.py --build
"""
    (DIST / "RELEASE.txt").write_text(notes, encoding="utf-8")
    print(f"说明已写入 {DIST / 'RELEASE.txt'}")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="收集/构建发布产物到 dist/")
    ap.add_argument("--build", action="store_true", help="先完整构建再收集")
    args = ap.parse_args()
    if args.build:
        build_all()
    dest = collect()
    return 0 if dest else 1


if __name__ == "__main__":
    raise SystemExit(main())
