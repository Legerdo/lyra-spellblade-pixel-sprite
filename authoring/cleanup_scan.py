"""Cleanup-pass scan: stray pixels, pinholes, off-palette colours, baseline per frame."""
import numpy as np

import poses
from build import render
from palette import RGB_TO_KEY

total_removed = 0
for anim in poses.ORDER:
    for i, p in enumerate(poses.ANIMS[anim]):
        comp, layers, _ = render(p)
        total_removed += render.last_removed
        a = np.array(comp)
        op = a[..., 3] > 0
        # pinholes: transparent pixel fully enclosed by 4 opaque neighbours
        pad = np.pad(op, 1)
        enclosed = (~op) & pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:]
        body = np.array(layers["Back Hair"])[..., 3] > 0
        for n in ("Body", "Costume", "Hair / Face", "Weapon"):
            body |= np.array(layers[n])[..., 3] > 0
        rgb = {tuple(c) for c in a[body][:, :3]}
        off = [c for c in rgb if c not in RGB_TO_KEY]
        partial = int(((a[..., 3] > 0) & (a[..., 3] < 255) & body).sum())
        ys = np.nonzero(body.any(1))[0]
        print(f"{anim}:{i} removed={render.last_removed} pinholes={int(enclosed.sum())} "
              f"offpal={len(off)} semi_alpha_body={partial} bbox_y=({ys.min()},{ys.max()}) colors={len(rgb)}")
print("total stray removed", total_removed)
