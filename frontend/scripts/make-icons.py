from pathlib import Path

from PIL import Image, ImageDraw

out = Path("desktop/src-tauri/icons")
out.mkdir(parents=True, exist_ok=True)


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, size // 16)
    d.rounded_rectangle([m, m, size - m, size - m], radius=size // 5, fill=(37, 99, 235, 255))
    cx, cy = size // 2, size // 2
    r = size // 4
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 255), width=max(2, size // 32))
    d.ellipse([cx - r // 3, cy - r // 3, cx + r // 3, cy + r // 3], fill=(255, 255, 255, 230))
    return img


for s in (32, 128, 256):
    make(s).save(out / f"{s}x{s}.png")
make(256).save(out / "icon.png")
make(256).save(out / "128x128@2x.png")
# ico
imgs = [make(s) for s in (16, 32, 64, 128, 256)]
imgs[-1].save(out / "icon.ico", format="ICO", sizes=[(16, 16), (32, 32), (64, 64), (128, 128)])
print("ok", sorted(p.name for p in out.iterdir()))
