"""Render Lyra frames to per-layer RGBA images + composite, and review sheets."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from character import build
from palette import PALETTE, rgba
from raster import H, LAYERS, W

HERE = Path(__file__).resolve().parent

LUT = {k: rgba(k) for k in PALETTE}


def render(pose):
    cv, rig = build(pose)
    key, owner, alpha, fx_key, fx_alpha = cv.finalize()
    layers = {name: np.zeros((H, W, 4), np.uint8) for name in LAYERS}
    part_layer = [p.layer for p in cv.parts]
    ys, xs = np.nonzero(key != ".")
    for y, x in zip(ys, xs):
        layer = part_layer[owner[y, x]]
        layers[layer][y, x] = LUT[key[y, x]]
    ys, xs = np.nonzero(fx_key != ".")
    for y, x in zip(ys, xs):
        c = LUT[fx_key[y, x]]
        layers["FX"][y, x] = (c[0], c[1], c[2], int(fx_alpha[y, x]))
    # cleanup pass: drop detached single pixels (no opaque 8-neighbour in the whole body)
    body = np.zeros((H, W), bool)
    for name in LAYERS[:-1]:
        body |= layers[name][..., 3] > 0
    pad = np.pad(body, 1)
    nb = sum(np.roll(np.roll(pad, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
             if (dx, dy) != (0, 0))[1:-1, 1:-1]
    lonely = body & (nb == 0)
    for name in LAYERS[:-1]:
        layers[name][lonely] = 0
    render.last_removed = int(lonely.sum())
    # pinholes: a transparent pixel enclosed on 4 sides takes its upper/left neighbour's colour
    body &= ~lonely
    for _ in range(2):
        pad = np.pad(body, 1)
        holes = (~body) & pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:]
        for y, x in zip(*np.nonzero(holes)):
            for name in LAYERS[:-1]:
                if layers[name][y - 1, x, 3]:
                    layers[name][y, x] = layers[name][y - 1, x]
                    break
                if layers[name][y, x - 1, 3]:
                    layers[name][y, x] = layers[name][y, x - 1]
                    break
            body[y, x] = True
    comp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for name in LAYERS:
        comp.alpha_composite(Image.fromarray(layers[name], "RGBA"))
    return comp, {n: Image.fromarray(a, "RGBA") for n, a in layers.items()}, rig


def checker(size, cell=8, a=(58, 62, 74), b=(70, 75, 88)):
    img = Image.new("RGBA", size, a + (255,))
    px = np.array(img)
    yy, xx = np.mgrid[0:size[1], 0:size[0]]
    px[((xx // cell + yy // cell) % 2) == 1] = b + (255,)
    return Image.fromarray(px, "RGBA")


def sheet(frames, zoom=3, cols=None, label_h=0, guides=True):
    cols = cols or len(frames)
    rows = (len(frames) + cols - 1) // cols
    fw, fh = W * zoom, H * zoom
    out = checker((cols * fw + (cols + 1) * 4, rows * fh + (rows + 1) * 4), cell=4 * zoom)
    for i, f in enumerate(frames):
        big = f.resize((fw, fh), Image.Resampling.NEAREST)
        x = 4 + (i % cols) * (fw + 4)
        y = 4 + (i // cols) * (fh + 4)
        if guides:
            g = np.array(out)
            gy = y + 140 * zoom
            g[gy:gy + 1, x:x + fw] = (255, 90, 90, 255)
            out = Image.fromarray(g, "RGBA")
        out.alpha_composite(big, (x, y))
    return out


if __name__ == "__main__":
    import poses
    names = sys.argv[1:] or ["idle"]
    frames = []
    for name in names:
        for pose in poses.ANIMS[name]:
            comp, _, _ = render(pose)
            frames.append(comp)
    zoom = 3
    sheet(frames, zoom, cols=min(6, len(frames))).save(HERE / "_review.png")
    sheet(frames, 1, guides=False).save(HERE / "_review_1x.png")
    print(len(frames), "frames")
