"""从根目录 icon.png 生成 Tauri 所需图标尺寸与 ico。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "icon.png"
OUT = ROOT / "desktop" / "src-tauri" / "icons"


def main() -> int:
    if not SRC.exists():
        print("缺少根目录 icon.png")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    img = Image.open(SRC).convert("RGBA")
    # 统一裁成正方形
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))

    for size in (32, 128, 256):
        img.resize((size, size), Image.Resampling.LANCZOS).save(OUT / f"{size}x{size}.png")
    img.resize((256, 256), Image.Resampling.LANCZOS).save(OUT / "icon.png")
    img.resize((128, 128), Image.Resampling.LANCZOS).save(OUT / "128x128@2x.png")
    # Windows ico
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.resize((256, 256), Image.Resampling.LANCZOS).save(
        OUT / "icon.ico", format="ICO", sizes=ico_sizes
    )
    print("icons written to", OUT)
    for p in sorted(OUT.iterdir()):
        print(f"  {p.name} {p.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
