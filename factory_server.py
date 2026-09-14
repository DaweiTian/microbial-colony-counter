"""工厂测试用 Web 服务入口（PyInstaller 打包）。"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser


def _lan_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return None


def main() -> int:
    # PyInstaller onedir：资源在 _MEIPASS 或可执行旁
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        os.chdir(base)
        # 确保能 import backend
        if base not in sys.path:
            sys.path.insert(0, base)

    host = os.environ.get("COLONY_HOST", "127.0.0.1")
    port = int(os.environ.get("COLONY_PORT", "18085"))

    import uvicorn

    from backend.main import app

    url_local = f"http://127.0.0.1:{port}/"
    print("=" * 50)
    print("微生物菌落计数器 · 工厂测试版")
    print(f"本机访问: {url_local}")
    lan = _lan_ip()
    if lan and host in ("0.0.0.0", "::"):
        print(f"局域网:   http://{lan}:{port}/")
    elif lan and host == "127.0.0.1":
        print("提示: 如需手机/局域网访问，请设置 COLONY_HOST=0.0.0.0 后重启")
    print("关闭本窗口或按 Ctrl+C 可停止服务")
    print("=" * 50)

    def _open():
        time.sleep(1.2)
        try:
            if os.environ.get("COLONY_NO_BROWSER") == "1":
                return
            webbrowser.open(url_local)
        except Exception:
            pass

    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
