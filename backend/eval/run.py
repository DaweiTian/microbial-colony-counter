"""评估 CLI：python -m backend.eval.run [--case test1]"""

from __future__ import annotations

import argparse
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="菌落计数离线评估")
    parser.add_argument("--case", default=None, help="仅评估指定用例 id（不含扩展名）")
    parser.add_argument("--no-save", action="store_true", help="不写 out/report.md")
    args = parser.parse_args(argv)

    # 保证可从仓库根目录导入 backend
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from backend.core.evaluate import run_eval

    payload = run_eval(case_id=args.case, save=not args.no_save)
    print(payload["report"])
    if not args.no_save:
        from backend.core.evaluate import OUT_DIR
        print(f"\n已写入: {OUT_DIR / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
