"""Contact sheet of all 20 frames (5 columns) at integer zoom with baseline guide."""
import sys
from pathlib import Path

import poses
from build import render, sheet

zoom = int(sys.argv[1]) if len(sys.argv) > 1 else 2
out = Path(__file__).resolve().parent / "_qa" / (sys.argv[2] if len(sys.argv) > 2 else "contact.png")
frames = [render(p)[0] for a in poses.ORDER for p in poses.ANIMS[a]]
sheet(frames, zoom, cols=5).save(out)
print(out)
