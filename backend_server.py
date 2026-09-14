"""Tauri sidecar 后端：只起 API，不弹浏览器；父进程退出后自杀。"""

from __future__ import annotations

import os
import sys
import threading


def _watch_parent_and_exit(parent_pid: int) -> None:
    """父进程（Tauri 主程序）消失时结束本进程，避免残留锁文件。"""
    if parent_pid <= 0 or parent_pid == os.getpid():
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(parent_pid))
        if not handle:
            return

        def _wait() -> None:
            # INFINITE
            kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            kernel32.CloseHandle(handle)
            os._exit(0)

        threading.Thread(target=_wait, daemon=True, name="parent-watch").start()
    except Exception:
        pass


def main() -> int:
    if getattr(sys, "frozen", False):
        # onefile: 资源在 _MEIPASS；onedir: 在 exe 目录
        meipass = getattr(sys, "_MEIPASS", None)
        base = meipass or os.path.dirname(sys.executable)
        os.chdir(os.path.dirname(sys.executable) or ".")
        if base and base not in sys.path:
            sys.path.insert(0, base)
        # static 与 backend 包在 _MEIPASS
        if meipass and meipass not in sys.path:
            sys.path.insert(0, meipass)

    os.environ.setdefault("COLONY_HOST", "127.0.0.1")
    os.environ.setdefault("COLONY_PORT", "18085")
    os.environ["COLONY_NO_BROWSER"] = "1"

    parent_raw = os.environ.get("COLONY_PARENT_PID", "")
    if parent_raw.isdigit():
        _watch_parent_and_exit(int(parent_raw))

    host = os.environ["COLONY_HOST"]
    port = int(os.environ["COLONY_PORT"])

    import uvicorn

    from backend.main import app

    print(f"[sidecar] starting {host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
