"""Quick look: render an ASCII part or a PNG at 1x and zoomed with a checkerboard, for visual review."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

from palette import PALETTE, rgba

HERE = Path(__file__).resolve().parent


def ascii_to_image(rows: list[str]) -> Image.Image:
    w = max(len(r) for r in rows)
    img = Image.new("RGBA", (w, len(rows)), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                if ch not in PALETTE:
                    raise ValueError(f"unknown key {ch!r} at {x},{y}")
                img.putpixel((x, y), rgba(ch))
    return img


def checker(size: tuple[int, int], cell: int = 8) -> Image.Image:
    bg = Image.new("RGBA", size, (58, 62, 74, 255))
    px = bg.load()
    for y in range(size[1]):
        for x in range(size[0]):
            if (x // cell + y // cell) % 2:
                px[x, y] = (72, 77, 90, 255)
    return bg


def review(img: Image.Image, zoom: int, out: Path, native_copies: int = 1) -> None:
    """Left: native 1x (and 2x) on checker; right: zoomed nearest."""
    big = img.resize((img.width * zoom, img.height * zoom), Image.Resampling.NEAREST)
    x2 = img.resize((img.width * 2, img.height * 2), Image.Resampling.NEAREST)
    W = img.width + 8 + x2.width + 8 + big.width + 16
    H = max(big.height, x2.height) + 16
    canvas = checker((W, H))
    canvas.alpha_composite(img, (8, 8))
    canvas.alpha_composite(x2, (16 + img.width, 8))
    canvas.alpha_composite(big, (24 + img.width + x2.width, 8))
    canvas.save(out)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    zoom = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else HERE / "_peek.png"
    if src.suffix == ".txt":
        img = ascii_to_image([l.rstrip("\n") for l in src.read_text().splitlines() if l.strip()])
    else:
        img = Image.open(src).convert("RGBA")
    review(img, zoom, out)
    print(out, img.size)
