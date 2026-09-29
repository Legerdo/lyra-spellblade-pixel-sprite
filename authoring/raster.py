"""Integer-grid rasterization helpers and the part compositor with selective outlines.

Every part is a boolean mask + per-pixel palette keys. Parts are stamped back-to-front.
`finalize()` draws lines only where they separate a part from transparency (material
outline) or from a part *behind* it (inner line). Edges touching a part in front are left
to that front part, so lines never double up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from palette import KEYS

W, H = 140, 168
KEY_INDEX = {k: i + 1 for i, k in enumerate(KEYS)}  # 0 = transparent
INDEX_KEY = {v: k for k, v in KEY_INDEX.items()}

YY, XX = np.mgrid[0:H, 0:W].astype(np.float64)

MATERIALS = {
    #          light mid  shadow line  inner
    "skin":    ("S", "s", "k", "K", "K"),
    "hair":    ("H", "h", "g", "G", "G"),
    "navy":    ("N", "n", "m", "M", "M"),
    "pink":    ("P", "p", "q", "Q", "Q"),
    "white":   ("F", "F", "f", "G", "f"),
    "leather": ("B", "b", "d", "D", "D"),
    "metal":   ("X", "x", "y", "Y", "Y"),
    "fx":      ("C", "c", "j", "J", "J"),
}

LAYERS = ["Back Hair", "Body", "Costume", "Hair / Face", "Weapon", "FX"]


def tone_keys(material: str, value: np.ndarray, hi: float, lo: float, allow_light: bool = True) -> np.ndarray:
    light, mid, shadow, *_ = MATERIALS[material]
    out = np.full(value.shape, mid, dtype="<U1")
    out[value < lo] = shadow
    if allow_light:
        out[value > hi] = light
    return out


# ------------------------------------------------------------------ shapes
def capsule(p0, p1, r0, r1):
    """Tapered capsule. Returns (mask, u) where u is signed cross-axis coordinate in [-1, 1]."""
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    ll = dx * dx + dy * dy
    if ll < 1e-9:
        t = np.zeros_like(XX)
    else:
        t = np.clip(((XX - x0) * dx + (YY - y0) * dy) / ll, 0.0, 1.0)
    cx, cy = x0 + t * dx, y0 + t * dy
    ox, oy = XX - cx, YY - cy
    dist = np.hypot(ox, oy)
    r = r0 + (r1 - r0) * t
    mask = dist <= r
    n = math.hypot(dx, dy) or 1.0
    px, py = -dy / n, dx / n  # left-hand perpendicular
    u = (ox * px + oy * py) / np.maximum(r, 1e-6)
    return mask, np.clip(u, -1, 1), t


LIGHT = (0.6, -0.8)  # toward the light: upper right (the direction Lyra faces)


def chain(points, radii, light=LIGHT):
    """Union of capsules along a polyline.

    Returns (mask, u, s, v): u = cross-axis coordinate, s = arc parameter 0..1,
    v = 2D lambert-ish light value using the segment's perpendicular.
    """
    mask = np.zeros((H, W), bool)
    u = np.zeros((H, W))
    s = np.zeros((H, W))
    v = np.zeros((H, W))
    best = np.full((H, W), np.inf)
    lens = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    total = sum(lens) or 1.0
    acc = 0.0
    for i in range(len(points) - 1):
        m, uu, t = capsule(points[i], points[i + 1], radii[i], radii[i + 1])
        dx, dy = points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]
        n = math.hypot(dx, dy) or 1.0
        px, py = -dy / n, dx / n
        vv = uu * (px * light[0] + py * light[1])
        score = np.abs(uu) + (~m) * 10
        take = m & (score < best)
        best = np.where(take, score, best)
        u = np.where(take, uu, u)
        v = np.where(take, vv, v)
        s = np.where(take, (acc + t * lens[i]) / total, s)
        mask |= m
        acc += lens[i]
    return mask, u, s, v


def row_shade(mask: np.ndarray, light=LIGHT) -> np.ndarray:
    """Cheap cross-section shading for flat-ish shapes: per row, x normalized to [-1, 1]."""
    v = np.zeros((H, W))
    rows = np.nonzero(mask.any(1))[0]
    for y in rows:
        xs = np.nonzero(mask[y])[0]
        a, b = xs.min(), xs.max()
        if b == a:
            continue
        v[y, a:b + 1] = ((np.arange(a, b + 1) - a) / (b - a) * 2 - 1) * light[0]
    return v


def polygon(points) -> np.ndarray:
    """Even-odd point-in-polygon on pixel centers."""
    pts = np.asarray(points, dtype=np.float64)
    inside = np.zeros((H, W), bool)
    n = len(pts)
    x_min, y_min = np.floor(pts.min(0)).astype(int) - 1
    x_max, y_max = np.ceil(pts.max(0)).astype(int) + 1
    x_min, y_min = max(x_min, 0), max(y_min, 0)
    x_max, y_max = min(x_max, W - 1), min(y_max, H - 1)
    if x_max < x_min or y_max < y_min:
        return inside
    X = XX[y_min:y_max + 1, x_min:x_max + 1]
    Y = YY[y_min:y_max + 1, x_min:x_max + 1]
    sub = np.zeros(X.shape, bool)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        cond = (yi > Y) != (yj > Y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (xj - xi) * (Y - yi) / (yj - yi) + xi
        sub ^= cond & (X < xint)
        j = i
    inside[y_min:y_max + 1, x_min:x_max + 1] = sub
    return inside


def ellipse(c, rx, ry, angle=0.0):
    ca, sa = math.cos(angle), math.sin(angle)
    ox, oy = XX - c[0], YY - c[1]
    lx = (ox * ca + oy * sa) / rx
    ly = (-ox * sa + oy * ca) / ry
    d = lx * lx + ly * ly
    return d <= 1.0, lx, ly


def line_pixels(p0, p1):
    """Bresenham integer line."""
    x0, y0 = int(round(p0[0])), int(round(p0[1]))
    x1, y1 = int(round(p1[0])), int(round(p1[1]))
    pts = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return pts


def shift(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """out[y, x] = mask[y+dy, x+dx] (False outside)."""
    out = np.zeros_like(mask)
    ys = slice(max(0, -dy), H - max(0, dy))
    xs = slice(max(0, -dx), W - max(0, dx))
    yd = slice(max(0, dy), H - max(0, -dy))
    xd = slice(max(0, dx), W - max(0, -dx))
    out[ys, xs] = mask[yd, xd]
    return out


def erode4(mask):
    return mask & shift(mask, 1, 0) & shift(mask, -1, 0) & shift(mask, 0, 1) & shift(mask, 0, -1)


def despeckle(mask: np.ndarray, keys: np.ndarray) -> np.ndarray:
    """Replace single tone pixels whose 4 in-part neighbours all agree on another tone."""
    out = keys.copy()
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys, xs):
        nb = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            xx, yy = x + dx, y + dy
            if 0 <= xx < W and 0 <= yy < H and mask[yy, xx]:
                nb.append(keys[yy, xx])
        if len(nb) >= 3 and all(n == nb[0] for n in nb) and nb[0] != keys[y, x]:
            out[y, x] = nb[0]
    return out


# ------------------------------------------------------------------ compositor
@dataclass
class Part:
    name: str
    material: str
    layer: str
    mask: np.ndarray
    keys: np.ndarray  # full-frame array of palette keys ("." outside)
    lines: bool = True
    line_key: str | None = None  # override outline color
    inner_key: str | None = None
    alpha: np.ndarray | None = None  # only for FX


@dataclass
class Canvas:
    parts: list[Part] = field(default_factory=list)

    def add(self, name, material, layer, mask, keys, **kw):
        if isinstance(keys, str):
            keys = np.where(mask, keys, ".")
        else:
            keys = np.where(mask, keys, ".")
        self.parts.append(Part(name, material, layer, mask, keys, **kw))

    def finalize(self):
        """Returns (key[H,W], owner[H,W] part index, alpha[H,W])."""
        key = np.full((H, W), ".", dtype="<U1")
        owner = np.full((H, W), -1, dtype=np.int32)
        alpha = np.zeros((H, W), dtype=np.int32)
        for i, p in enumerate(self.parts):
            if p.alpha is None:
                key = np.where(p.mask, p.keys, key)
                owner = np.where(p.mask, i, owner)
                alpha = np.where(p.mask, 255, alpha)
        # lines
        line = key.copy()
        for i, p in enumerate(self.parts):
            if p.alpha is not None or not p.lines:
                continue
            _, _, _, outline, inner = MATERIALS[p.material]
            outline = p.line_key or outline
            inner = p.inner_key or inner
            visible = owner == i
            edge = p.mask & ~erode4(p.mask) & visible
            if not edge.any():
                continue
            to_outline = np.zeros((H, W), bool)
            to_inner = np.zeros((H, W), bool)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nb_in = shift(p.mask, dx, dy)
                nb_owner = np.full((H, W), -2, dtype=np.int32)  # -2 = off-canvas
                ys = slice(max(0, -dy), H - max(0, dy))
                xs = slice(max(0, -dx), W - max(0, dx))
                yd = slice(max(0, dy), H - max(0, -dy))
                xd = slice(max(0, dx), W - max(0, -dx))
                nb_owner[ys, xs] = owner[yd, xd]
                outside = ~nb_in
                to_outline |= edge & outside & (nb_owner < 0)
                to_inner |= edge & outside & (nb_owner >= 0) & (nb_owner < i)
            line = np.where(to_inner, inner, line)
            line = np.where(to_outline, outline, line)
        key = line
        # FX parts last (alpha)
        fx_key = np.full((H, W), ".", dtype="<U1")
        fx_alpha = np.zeros((H, W), dtype=np.int32)
        for i, p in enumerate(self.parts):
            if p.alpha is not None:
                fx_key = np.where(p.mask, p.keys, fx_key)
                fx_alpha = np.where(p.mask, p.alpha, fx_alpha)
                owner = np.where(p.mask & (owner < 0), i, owner)
        return key, owner, alpha, fx_key, fx_alpha
