"""Zoomed crop of one rendered frame: python crop.py <anim> <index> x0 y0 x1 y1 [zoom]"""
import sys
from pathlib import Path

from PIL import Image

import poses
from build import checker, render

anim, idx = sys.argv[1], int(sys.argv[2])
x0, y0, x1, y1 = map(int, sys.argv[3:7])
zoom = int(sys.argv[7]) if len(sys.argv) > 7 else 8
comp, _, _ = render(poses.ANIMS[anim][idx])
c = comp.crop((x0, y0, x1, y1))
big = c.resize((c.width * zoom, c.height * zoom), Image.Resampling.NEAREST)
out = checker(big.size, cell=zoom * 2)
out.alpha_composite(big)
out.save(Path(__file__).resolve().parent / (sys.argv[8] if len(sys.argv) > 8 else "_crop.png"))
print(out.size)
