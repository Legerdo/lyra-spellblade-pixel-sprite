"""Magic FX on the FX layer: hard-edged pixel shapes with a few stepped alpha levels (no blur)."""
from __future__ import annotations

import math

import numpy as np

from raster import H, W, XX, YY, ellipse, polygon

ALPHA_STEPS = (255, 200, 140)


def _add(cv, name, mask, keys, alpha):
    if mask.any():
        cv.add(name, "fx", "FX", mask, keys, alpha=np.where(mask, alpha, 0))


def arc_trail(cv, center, tip0, tip1, width=9.0, pink=True, name="trail", fade=1.0):
    """Crescent smear following the blade tip from tip0 (older) to tip1 (current).

    The outer edge follows the tip path (radius interpolated so both tip positions lie on it);
    the band thickens toward the current blade and tapers to a point at the old end.
    """
    cx, cy = center
    a0 = math.atan2(tip0[1] - cy, tip0[0] - cx)
    a1 = math.atan2(tip1[1] - cy, tip1[0] - cx)
    d = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi  # shortest signed sweep
    r0, r1 = math.dist(center, tip0), math.dist(center, tip1)
    ang = np.arctan2(YY - cy, XX - cx)
    rel = (ang - a0) % (2 * math.pi) if d > 0 else (a0 - ang) % (2 * math.pi)
    s = rel / abs(d)  # 0 at old tip, 1 at current tip
    inside_sweep = (s >= 0) & (s <= 1.0)
    s = np.clip(s, 0, 1)
    rr = np.hypot(XX - cx, YY - cy)
    r_out = r0 + (r1 - r0) * s + 0.5
    thick = 1.0 + (width - 1.0) * (s ** 0.8)
    r_in = r_out - thick
    m = inside_sweep & (rr <= r_out) & (rr >= r_in)
    depth = (r_out - rr) / np.maximum(thick, 1e-6)  # 0 at outer edge -> 1 inner edge
    keys = np.full((H, W), "j", dtype="<U1")
    keys = np.where(depth < 0.22, "C", keys)
    keys = np.where((depth >= 0.22) & (depth < 0.5), "c", keys)
    if pink:
        keys = np.where(depth > 0.8, "z", keys)
    alpha = np.where(s > 0.62, ALPHA_STEPS[0], np.where(s > 0.3, ALPHA_STEPS[1], ALPHA_STEPS[2]))
    if fade < 1.0:
        alpha = np.where(alpha == 255, 200, 140)
        keys = np.where(keys == "C", "c", keys)
    _add(cv, name, m, keys, alpha)


def star(cv, c, size=4, name="flash", alpha=255):
    """4-point impact star with a solid core."""
    x, y = c
    ax = np.abs(XX - x)
    ay = np.abs(YY - y)
    arms = ((ax <= 0.6) & (ay <= size)) | ((ay <= 0.6) & (ax <= size))
    core = (ax + ay) <= max(1.6, size * 0.45)
    diag = (np.abs(ax - ay) <= 0.6) & (ax <= size * 0.45) & (ax >= 1)
    m = arms | core | diag
    keys = np.where(core, "C", np.where(arms & ((ax > size * 0.6) | (ay > size * 0.6)), "z", "c"))
    keys = np.where(diag & ~core, "c", keys)
    _add(cv, name, m, keys, np.where(core | arms, alpha, min(alpha, 200)))


def sparkle(cv, c, kind="plus", key="c", name="sparkle", alpha=255):
    """Tiny deliberate clusters: 3x3 plus or 2x2 diamond-ish block, never lone pixels."""
    x, y = int(round(c[0])), int(round(c[1]))
    pts = [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)] if kind == "plus" else [(0, 0), (1, 0), (0, 1), (1, 1)]
    m = np.zeros((H, W), bool)
    keys = np.full((H, W), key, dtype="<U1")
    for dx, dy in pts:
        if 0 <= x + dx < W and 0 <= y + dy < H:
            m[y + dy, x + dx] = True
    if kind == "plus" and 0 <= x < W and 0 <= y < H:
        keys[y, x] = "C"
    _add(cv, name, m, keys, alpha)


def sigil(cv, c, rx=7.0, ry=3.0, name="sigil", alpha=200, spin=0):
    """Flat magic circle (ellipse ring + 4 rune ticks)."""
    outer, lx, ly = ellipse(c, rx + 0.5, ry + 0.5)
    inner, _, _ = ellipse(c, rx - 0.6, ry - 0.6)
    ring = outer & ~inner
    ang = np.arctan2(ly, lx)
    ticks = np.zeros((H, W), bool)
    for k in range(4):
        a = spin * 0.4 + k * math.pi / 2
        tx, ty = c[0] + math.cos(a) * (rx + 1.6), c[1] + math.sin(a) * (ry + 1.2)
        tm, _, _ = ellipse((tx, ty), 0.9, 0.9)
        ticks |= tm
    keys = np.where(np.sin(ang * 2 + spin) > 0, "z", "c")
    _add(cv, name, ring, keys, alpha)
    _add(cv, name + " ticks", ticks & ~ring, "C", alpha)


def blade_glow(cv, hand, direction, blade, name="glow", alpha=140, reach=1.6):
    """Hard-edged aura hugging the blade (one ring of pixels, stepped alpha)."""
    dx, dy = math.cos(math.radians(direction)), math.sin(math.radians(direction))
    p0 = (hand[0] + dx * 4.5, hand[1] + dy * 4.5)
    p1 = (hand[0] + dx * (4.2 + blade + 1.5), hand[1] + dy * (4.2 + blade + 1.5))
    t = np.clip(((XX - p0[0]) * dx + (YY - p0[1]) * dy) / (blade + 1.2), 0, 1)
    cxp, cyp = p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1])
    dist = np.hypot(XX - cxp, YY - cyp)
    m = (dist <= 1.4 + reach) & (dist > 1.4)
    keys = np.where(t > 0.55, "c", "z")
    _add(cv, name, m, keys, alpha)


def crescent_wave(cv, c, radius, thickness, height_scale=1.0, name="wave", alpha_scale=1.0, pink=True):
    """Vertical crescent facing right (convex side forward)."""
    cx, cy = c
    ox, oy = XX - cx, (YY - cy) / height_scale
    r = np.hypot(ox, oy)
    ix = XX - (cx - thickness)
    ri = np.hypot(ix, oy)
    m = (r <= radius) & (ri > radius) & (ox > -radius * 0.2)
    depth = np.clip((radius - r) / max(thickness, 1e-6), 0, 1)
    keys = np.where(depth < 0.2, "C", np.where(depth < 0.45, "c", "j"))
    if pink:
        keys = np.where(depth > 0.78, "z", keys)
    # tips of the crescent fade
    vert = np.abs(oy) / radius
    alpha = np.where(vert < 0.6, 255, np.where(vert < 0.82, 200, 140))
    if alpha_scale < 1:
        alpha = np.where(alpha == 255, 200, 140)
    _add(cv, name, m, keys, alpha)
