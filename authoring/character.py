"""Lyra: skeleton-driven construction of the character on the integer grid.

Rigid identity parts (head, bows) are hand-authored pixel templates; limbs, torso and cloth
are rebuilt every frame from fixed-length bones, so volumes and lengths never drift.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from raster import (H, LIGHT, MATERIALS, W, XX, YY, Canvas, capsule, chain, despeckle, ellipse,
                    polygon, row_shade, tone_keys)

ART = Path(__file__).resolve().parent / "art"

# ---- fixed proportions (px) -------------------------------------------------------------
THIGH, SHIN = 27.0, 27.0
UPPER_ARM, FOREARM = 14.0, 15.5  # forearm measured to the hand centre
TORSO = 26.0  # hip-joint line -> neck base
NECK = 4.0
BOOT_TOP = 0.66  # fraction of thigh (from hip) where the boot shaft ends
BLADE = 35.0
GROUND = 140
ANKLE_Y = GROUND - 3.5  # ankle height of a planted, flat foot


def rad(a):
    return math.radians(a)


def vec(a, l=1.0):
    return (math.cos(rad(a)) * l, math.sin(rad(a)) * l)


def add(p, q):
    return (p[0] + q[0], p[1] + q[1])


def sub(p, q):
    return (p[0] - q[0], p[1] - q[1])


def mul(p, k):
    return (p[0] * k, p[1] * k)


def ang(p, q):
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))


def load_template(name):
    rows = [l.rstrip("\n") for l in (ART / name).read_text().splitlines() if l.strip()]
    w = max(len(r) for r in rows)
    return [r.ljust(w, ".") for r in rows]


HEADS = {}


def head_template(variant: str):
    if variant not in HEADS:
        base = load_template("head.txt")
        HEADS[variant] = apply_face_variant(base, variant)
    return HEADS[variant]


def apply_face_variant(rows, variant):
    g = [list(r) for r in rows]

    def put(x, y, k):
        g[y][x] = k
    if variant == "focus":  # determined: mouth set, lids lowered a touch
        put(14, 20, "K"); put(15, 20, "K")
        for x in (9, 10, 11):
            put(x, 14, "L") if x == 9 else None
    elif variant == "shout":  # impact kiai: open mouth
        put(14, 20, "K"); put(15, 20, "K")
        put(14, 21, "q"); put(15, 21, "K")
    elif variant == "calm":  # idle breathing frame: softer mouth
        put(14, 20, "k"); put(15, 20, "K")
    return ["".join(r) for r in g]


def ik(root, target, l1, l2, bend):
    """Two-bone IK with fixed lengths. bend=+1 bends the middle joint clockwise from root->target."""
    d = math.dist(root, target)
    d = max(min(d, l1 + l2 - 0.05), abs(l1 - l2) + 0.05)
    base = math.atan2(target[1] - root[1], target[0] - root[0])
    c = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)
    off = math.acos(max(-1.0, min(1.0, c)))
    a = base - off * bend
    mid = (root[0] + math.cos(a) * l1, root[1] + math.sin(a) * l1)
    b = math.atan2(target[1] - mid[1], target[0] - mid[0])
    end = (mid[0] + math.cos(b) * l2, mid[1] + math.sin(b) * l2)
    return mid, end


# ---- pose --------------------------------------------------------------------------------
@dataclass
class Pose:
    pelvis: tuple = (66.0, 82.0)
    lean: float = 2.0  # deg, + = forward (right)
    breath: float = 0.0  # px the chest/shoulders/head rise
    turn: float = 0.0  # shoulder rotation, + = near shoulder forward
    hip_turn: float = 0.0
    head: tuple = (0.0, 0.0)
    face: str = "neutral"
    near_foot: tuple = (59.0, ANKLE_Y, 0.0)  # ankle x, y, sole angle (+ = toe down)
    far_foot: tuple = (75.0, ANKLE_Y, 0.0)
    near_hand: tuple = (66.0, 88.0)
    near_bend: float = -1.0
    far_hand: tuple = (74.0, 80.0)
    far_bend: float = 1.0
    far_hand_shape: str = "fist"
    far_hand_dir: float = 90.0
    near_hand_dir: float = 90.0
    sword: float = 55.0  # direction hand -> tip (deg, 0 = right, 90 = down)
    sword_front: bool = True
    sword_glow: int = 0
    tails: tuple = ((0,) * 9, (0,) * 9)  # per-segment angle offsets (near, far)
    scarf: tuple = ((0,) * 7, (0,) * 7)
    skirt: tuple = (0.0, 0.0, 0.0)  # hem dx back, hem dx front, front lift
    fx: list = field(default_factory=list)


# ---- rest shapes for secondary chains -------------------------------------------------
TAIL_NEAR_REST = [168, 138, 112, 98, 92, 89, 87, 85, 82]
TAIL_FAR_REST = [5, 38, 70, 86, 92, 95, 97, 99, 101]
TAIL_SEG = [3.0, 5, 5, 5, 5, 5, 5, 4.5, 4]
TAIL_R = [1.8, 3.0, 4.0, 4.4, 4.4, 4.1, 3.6, 3.0, 2.2, 1.1]
SCARF_A_REST = [150, 118, 100, 94, 92, 92, 92]
SCARF_B_REST = [140, 110, 96, 90, 88, 88, 88]
SCARF_SEG = [3, 5, 5, 5, 5, 5, 4]


def chain_points(anchor, rest, offsets, segs):
    pts = [anchor]
    for a, o, l in zip(rest, offsets, segs):
        pts.append(add(pts[-1], vec(a + o, l)))
    return pts


class Rig:
    """Computes world-space joints for a pose."""

    def __init__(self, p: Pose):
        self.p = p
        P = p.pelvis
        la = rad(p.lean)
        self.up = (math.sin(la), -math.cos(la))
        self.right = (math.cos(la), math.sin(la))

        def L(x, y):  # torso local (x right, y up from hip line) -> world
            return (P[0] + x * self.right[0] + y * self.up[0], P[1] + x * self.right[1] + y * self.up[1])
        def Lb(x, y):  # like L, but the chest rises with breathing
            q = L(x, y)
            k = max(0.0, min(1.0, (y - 12.0) / (TORSO - 12.0)))
            return (q[0], q[1] - p.breath * k)
        self.L = Lb
        self.neck_base = add(L(0.5, TORSO), (0, -p.breath))
        self.neck_top = add(self.neck_base, (0.6 + p.head[0] * 0.3, -NECK))
        self.head_anchor = add(self.neck_top, p.head)
        t = p.turn
        self.sh_near = add(L(-6.0 + 2.2 * t, TORSO - 2.5 - 0.6 * t), (0, -p.breath))
        self.sh_far = add(L(6.0 + 1.2 * t, TORSO - 2.5 + 0.4 * t), (0, -p.breath))
        ht = p.hip_turn
        self.hip_near = L(-3.8 + 1.5 * ht, 0.5)
        self.hip_far = L(3.6 + 0.8 * ht, 0.0)
        nf, ff = p.near_foot, p.far_foot
        self.knee_near, self.ankle_near = ik(self.hip_near, nf[:2], THIGH, SHIN, +1)
        self.knee_far, self.ankle_far = ik(self.hip_far, ff[:2], THIGH, SHIN, +1)
        self.elbow_near, self.hand_near = ik(self.sh_near, p.near_hand, UPPER_ARM, FOREARM, p.near_bend)
        self.elbow_far, self.hand_far = ik(self.sh_far, p.far_hand, UPPER_ARM, FOREARM, p.far_bend)
        ho = self.head_origin()
        self.tail_anchor_near = (ho[0] + 2.0, ho[1] + 6.0)
        self.tail_anchor_far = (ho[0] + 20.5, ho[1] + 3.0)
        self.scarf_anchor = Lb(-3.5, TORSO - 1.0)

    def head_origin(self):
        a = self.head_anchor
        return (int(round(a[0] - 11.5)), int(round(a[1] - 21.0)))


# ---- drawing -----------------------------------------------------------------------------
def stamp_template(cv: Canvas, rows, origin, name, layer, material_of, lines=False):
    """Stamp a hand-authored template. material_of maps key -> material (for line ownership)."""
    ox, oy = origin
    groups: dict[str, np.ndarray] = {}
    keys = np.full((H, W), ".", dtype="<U1")
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            X, Y = ox + x, oy + y
            if 0 <= X < W and 0 <= Y < H:
                keys[Y, X] = ch
    mask = keys != "."
    cv.add(name, material_of, layer, mask, keys, lines=lines)


def shade_chain(material, v, hi=0.45, lo=-0.25, allow_light=True):
    return tone_keys(material, v + 0.12, hi, lo, allow_light)


def draw_tail(cv, pts, name, strands=True, dim=0.0):
    mask, u, s, v = chain(pts, TAIL_R)
    keys = shade_chain("hair", v - dim, hi=0.40, lo=-0.12)
    # angel-ring style highlight band near the top of the tail on the lit side
    ring = mask & (s > 0.18) & (s < 0.34) & (v > 0.05)
    keys = np.where(ring, "H", keys)
    ring2 = mask & (s > 0.22) & (s < 0.29) & (v > 0.35)
    keys = np.where(ring2, "W", keys)
    if strands:  # strand separation: a shadow groove along the tube
        groove = mask & (np.abs(u - 0.15) < 0.14) & (s > 0.36) & (s < 0.86)
        keys = np.where(groove & (keys != "g"), "g", keys)
    keys = despeckle(mask, keys)
    cv.add(name, "hair", "Back Hair", mask, keys)


def draw_scarf_end(cv, pts, width, name):
    radii = [width * (1.0 if i < len(pts) - 2 else 0.85) for i in range(len(pts))]
    radii[0] = width * 0.9
    mask, u, s, v = chain(pts, radii)
    keys = shade_chain("pink", v, hi=0.40, lo=-0.20)
    # fringe tip: last 8% lighter pink stripe
    tip = mask & (s > 0.9)
    keys = np.where(tip, "P", keys)
    band = mask & (s > 0.82) & (s <= 0.87)
    keys = np.where(band, "q", keys)
    keys = despeckle(mask, keys)
    cv.add(name, "pink", "Costume", mask, keys)


def draw_leg(cv, hip, knee, ankle, foot_angle, prefix, dim=0.0):
    # thigh skin (above boot)
    m, u, t = capsule(hip, knee, 4.3, 3.2)
    dx, dy = knee[0] - hip[0], knee[1] - hip[1]
    n = math.hypot(dx, dy) or 1
    px, py = -dy / n, dx / n
    v = u * (px * LIGHT[0] + py * LIGHT[1]) + 0.1 - dim
    skin = m & (t <= BOOT_TOP)
    keys = tone_keys("skin", v, 0.55, -0.25)
    cv.add(prefix + " thigh", "skin", "Body", skin, keys)
    # boot shaft + foot
    boot_pts = [add(hip, mul((dx, dy), BOOT_TOP - 0.02)), knee,
                add(knee, mul(sub(ankle, knee), 0.35)), ankle]
    radii = [3.8, 3.2, 3.4, 2.0]
    bm, bu, bs, bv = chain(boot_pts, radii)
    top = add(hip, mul((dx, dy), BOOT_TOP - 0.02))
    along = ((XX - top[0]) * dx + (YY - top[1]) * dy) / n
    bm &= along >= -0.2  # flat shaft top instead of a round cap
    foot = foot_poly(ankle, foot_angle)
    fm = polygon(foot)
    fv = row_shade(fm) * 0.6 + np.where(YY > ankle[1] + 2.2, -0.6, 0.15)
    mask = bm | fm
    v = np.where(bm, bv + 0.18, fv) - dim
    keys = tone_keys("leather", v, 0.30, -0.22)
    # knee cap sheen
    kc, _, _ = ellipse(add(knee, (0.8, -0.5)), 1.3, 1.8)
    keys = np.where(kc & bm & (v > -0.1), "B", keys)
    # cuff band (top 2 px of the shaft)
    cuff = bm & (along < 2.4)
    keys = np.where(cuff, np.where(v > -0.2, "B", "b"), keys)
    # sole
    ca, sa = math.cos(rad(foot_angle)), math.sin(rad(foot_angle))
    ly = -(XX - ankle[0]) * sa + (YY - ankle[1]) * ca
    sole = fm & (ly > 2.4)
    keys = np.where(sole, "d", keys)
    keys = despeckle(mask, keys)
    cv.add(prefix + " boot", "leather", "Costume", mask, keys)


def foot_poly(ankle, angle):
    local = [(-2.6, -2.5), (-3.2, 1.0), (-3.0, 3.55), (6.6, 3.55), (7.8, 2.6), (7.0, 1.0),
             (4.0, -0.6), (1.8, -2.4)]
    ca, sa = math.cos(rad(angle)), math.sin(rad(angle))
    return [(ankle[0] + x * ca - y * sa, ankle[1] + x * sa + y * ca) for x, y in local]


def draw_arm(cv, sh, elbow, hand, prefix, dim=0.0, cuff=True):
    pts = [sh, elbow, hand]
    radii = [3.4, 2.9, 2.3]
    m, u, s, v = chain(pts, radii)
    total = math.dist(sh, elbow) + math.dist(elbow, hand)
    sleeve_end = (UPPER_ARM + FOREARM - 3.2) / total
    sleeve = m & (s < sleeve_end)
    keys = tone_keys("navy", v + 0.34 - dim, 0.42, -0.2)
    keys = despeckle(sleeve, keys)
    cv.add(prefix + " sleeve", "navy", "Costume", sleeve, keys)
    if cuff:
        cf = m & (s >= sleeve_end - 0.07) & (s < sleeve_end + 0.02)
        ck = np.where(v > -0.1, "F", "f")
        cv.add(prefix + " cuff", "white", "Costume", cf, ck)


def draw_hand(cv, hand, direction, shape, prefix, dim=0.0):
    """Fingerless leather glove. direction = where the fingers/grip points."""
    if shape == "open":
        palm, _, _ = ellipse(hand, 2.6, 2.2, rad(direction))
        tip = add(hand, vec(direction, 3.2))
        fm, fu, ft = capsule(hand, tip, 1.6, 1.3)
        glove = palm & ~(fm & (ft > 0.45))
        fingers = fm & (ft > 0.45)
        gk = np.where(row_shade(palm) > 0.1 - dim, "B", "b")
        cv.add(prefix + " glove", "leather", "Costume", glove, gk)
        cv.add(prefix + " fingers", "skin", "Body", fingers, np.where(fu > 0.3, "k", "s"))
        return
    m, lx, ly = ellipse(hand, 2.7, 2.4, rad(direction))
    # fingers wrap the grip on the viewer-facing side (local -y after rotation)
    fingers = m & (ly > 0.35)
    glove = m & ~fingers
    gk = np.where(lx < -0.1, "d", np.where(ly < -0.45, "B", "b"))
    cv.add(prefix + " glove", "leather", "Costume", glove, gk)
    cv.add(prefix + " fingers", "skin", "Body", fingers, np.where(lx > 0.4, "k", "s"))


def draw_sword(cv, hand, a, glow=0, part="grip"):
    d = vec(a)
    pn = (-d[1], d[0])
    if part == "grip":
        pom = add(hand, vec(a, -4.3))
        m, _, _ = ellipse(pom, 1.5, 1.5)
        cv.add("pommel", "metal", "Weapon", m, np.where(row_shade(m) > 0, "X", "x"))
        g, _, t = capsule(add(hand, vec(a, -3.2)), add(hand, vec(a, 2.5)), 1.1, 1.1)
        cv.add("grip", "leather", "Weapon", g, "b")
        return
    # blade: from guard to tip, 2px -> 1px
    base = add(hand, vec(a, 4.2))
    tip = add(hand, vec(a, 4.2 + BLADE))
    bm, bu, bt = capsule(base, tip, 1.05, 0.5)
    # the side of the blade facing the light is bright, the other is the dark edge
    facing = (pn[0] * LIGHT[0] + pn[1] * LIGHT[1])
    lit = (bu * facing) >= 0
    bk = np.where(lit, "X", "y")
    bk = np.where(bm & (bt > 0.9), np.where(lit, "W", "x"), bk)
    bk = np.where(bm & (bt < 0.08), np.where(lit, "x", "Y"), bk)  # ricasso
    if glow:
        bk = np.where(lit, "C", "j")
        bk = np.where(bm & (bt > 0.9), "C", bk)
    cv.add("blade", "metal", "Weapon", bm, bk, lines=False)
    # guard: crossbar + cup + gem
    g0 = add(add(hand, vec(a, 3.0)), mul(pn, 3.6))
    g1 = add(add(hand, vec(a, 3.0)), mul(pn, -3.6))
    gm, gu, gt = capsule(g0, g1, 0.95, 0.95)
    cm, _, _ = ellipse(add(hand, vec(a, 3.2)), 2.0, 2.0)
    guard = gm | cm
    gk = np.where(row_shade(guard) > 0.1, "X", "x")
    gem, _, _ = ellipse(add(hand, vec(a, 3.3)), 0.8, 0.8)
    gk = np.where(gem, "j" if not glow else "C", gk)
    cv.add("guard", "metal", "Weapon", guard, gk)


def draw_torso(cv, rig: Rig, dim=0.0):
    L = rig.L
    t = rig.p.turn
    top = TORSO
    pts = [L(-2.5, top), L(-6.8 + 2.0 * t, top - 1.6), L(-8.2 + 1.4 * t, top - 5.5),
           L(-7.4, top - 10), L(-6.2, 11.5), L(-6.6, 8.2), L(-8.6, 4.2), L(-8.0, 2.8),
           L(-2.0, 3.8), L(4.0, 3.6), L(8.4, 3.0), L(8.2, 4.8), L(5.8, 8.6),
           L(5.6, 11.5), L(7.4, 14.2), L(8.8, 17.0), L(8.2 + 0.8 * t, top - 3.8),
           L(6.4 + 0.8 * t, top - 1.4), L(3.0, top + 0.2)]
    m = polygon(pts)
    v = row_shade(m) * 1.1 + 0.05 - dim
    keys = tone_keys("navy", v, 0.62, -0.42)
    # under-bust shadow band and front highlight
    lx = (XX - rig.p.pelvis[0])
    ly_world = YY
    bust_y = L(0, 13.0)[1]
    under = m & (np.abs(ly_world - bust_y) < 0.9) & (lx > 1.5)
    keys = np.where(under, "m", keys)
    # belt
    belt_top, belt_bot = L(0, 11.2)[1], L(0, 8.6)[1]
    belt = m & (YY >= belt_top) & (YY <= belt_bot)
    keys = np.where(belt, np.where(v > 0.35, "B", np.where(v > -0.4, "b", "d")), keys)
    bx, by = L(3.3, 9.9)
    buckle = m & (np.abs(XX - bx) <= 1.0) & (np.abs(YY - by) <= 0.6)
    keys = np.where(buckle, "X", keys)
    # white piping along the front opening (collar to belt)
    p0, p1 = L(2.6, top - 2.0), L(3.2, 11.6)
    pm, _, pt = capsule(p0, p1, 0.5, 0.5)
    keys = np.where(pm & m & ~belt, "F", keys)
    # peplum shadow below belt
    pep = m & (YY > belt_bot) & (v < 0.2)
    keys = np.where(pep, "m", keys)
    keys = despeckle(m, keys)
    cv.add("jacket", "navy", "Costume", m, keys)


def draw_skirt(cv, rig: Rig):
    L = rig.L
    back, front, lift = rig.p.skirt
    waist_y = 9.0
    hem_y = -9.8
    n_pleats = 7
    left_w, right_w = -6.8, 6.4
    hem_l, hem_r = -13.0 - back, 12.2 + front
    top = [L(left_w, waist_y), L(right_w, waist_y)]
    hem = []
    for i in range(n_pleats * 2 + 1):
        f = i / (n_pleats * 2)
        x = hem_r + (hem_l - hem_r) * f
        y = hem_y + (lift * (1 - f) ** 2) + (0.0 if i % 2 == 0 else 0.7)
        hem.append(L(x, y))
    pts = top + hem
    m = polygon(pts)
    # pleat coordinate: interpolate between left and right edge per row
    keys = np.full((H, W), "n", dtype="<U1")
    rows = np.nonzero(m.any(1))[0]
    for y in rows:
        xs = np.nonzero(m[y])[0]
        a, b = xs.min(), xs.max()
        span = max(b - a, 1)
        for x in xs:
            s = (x - a) / span
            k = s * n_pleats
            frac = k - math.floor(k)
            side = s * 2 - 1
            if frac < 0.28:
                key = "N" if side > -0.45 else "n"
            elif frac < 0.72:
                key = "n" if side > -0.55 else "m"
            else:
                key = "m"
            keys[y, x] = key
    # white frill peeking under the hem
    frill_pts = [L(hem_r - 0.5, hem_y + 1.5)] + [L(hem_r + (hem_l - hem_r) * (i / 12), hem_y - 1.6 +
                                                   (lift * (1 - i / 12) ** 2) - (0.6 if i % 2 else 0))
                                                 for i in range(13)] + [L(hem_l + 0.5, hem_y + 1.5)]
    fm = polygon(frill_pts)
    cv.add("frill", "white", "Costume", fm & ~m, np.where(row_shade(fm) > -0.3, "F", "f"))
    cv.add("skirt", "navy", "Costume", m, keys)


def draw_neck(cv, rig):
    m, u, t = capsule(rig.neck_base, add(rig.neck_top, (0, -1.5)), 2.5, 2.3)
    keys = np.where(u < -0.35, "s", "k")
    cv.add("neck", "skin", "Body", m, keys)


def draw_scarf_wrap(cv, rig):
    L = rig.L
    pts = [L(-5.2, TORSO + 1.2), L(-1.0, TORSO + 2.4), L(3.5, TORSO + 1.6), L(5.4, TORSO - 0.4),
           L(4.6, TORSO - 2.6), L(0.5, TORSO - 2.2), L(-4.6, TORSO - 1.6)]
    m = polygon(pts)
    v = row_shade(m)
    keys = tone_keys("pink", v, 0.45, -0.35)
    # fold line
    fy = L(0, TORSO - 0.2)[1]
    keys = np.where(m & (np.abs(YY - fy) < 0.5) & (v < 0.3), "q", keys)
    # knot on the near side, from which the ends fall
    km, _, _ = ellipse(L(-4.4, TORSO - 0.6), 2.0, 1.8)
    keys = np.where(km, np.where(row_shade(km) > 0, "p", "q"), keys)
    cv.add("scarf wrap", "pink", "Costume", m | km, np.where(km & ~m, "q", keys))


def bow_material(_):
    return "pink"


def build(p: Pose) -> Canvas:
    rig = Rig(p)
    cv = Canvas()
    ho = rig.head_origin()

    # far twin-tail + far bow (behind everything)
    far_pts = chain_points(rig.tail_anchor_far, TAIL_FAR_REST, p.tails[1], TAIL_SEG)
    draw_tail(cv, far_pts, "far tail", dim=0.18)
    stamp_template(cv, load_template("bow_far.txt"), (ho[0] + 18, ho[1] - 1), "far bow", "Back Hair",
                   "pink", lines=False)
    # scarf ends
    sa = chain_points(rig.scarf_anchor, SCARF_A_REST, p.scarf[0], SCARF_SEG)
    sb = chain_points(add(rig.scarf_anchor, (1.0, 0.5)), SCARF_B_REST, p.scarf[1],
                      [s * 0.86 for s in SCARF_SEG])
    draw_scarf_end(cv, sb, 1.5, "scarf end b")
    draw_scarf_end(cv, sa, 1.8, "scarf end a")
    # far arm
    draw_arm(cv, rig.sh_far, rig.elbow_far, rig.hand_far, "far arm", dim=0.2)
    draw_hand(cv, rig.hand_far, p.far_hand_dir, p.far_hand_shape, "far hand", dim=0.2)
    # near twin-tail
    near_pts = chain_points(rig.tail_anchor_near, TAIL_NEAR_REST, p.tails[0], TAIL_SEG)
    draw_tail(cv, near_pts, "near tail")
    # legs
    draw_leg(cv, rig.hip_far, rig.knee_far, rig.ankle_far, p.far_foot[2], "far", dim=0.18)
    draw_leg(cv, rig.hip_near, rig.knee_near, rig.ankle_near, p.near_foot[2], "near")
    # skirt, torso
    draw_skirt(cv, rig)
    if not p.sword_front:
        draw_sword(cv, rig.hand_near, p.sword, p.sword_glow, "grip")
        draw_sword(cv, rig.hand_near, p.sword, p.sword_glow, "blade")
    draw_torso(cv, rig)
    draw_neck(cv, rig)
    draw_scarf_wrap(cv, rig)
    # head
    stamp_template(cv, head_template(p.face), ho, "head", "Hair / Face", "hair")
    stamp_template(cv, load_template("bow_near.txt"), (ho[0] - 1, ho[1] + 3), "near bow", "Hair / Face",
                   "pink")
    # near arm + sword
    draw_arm(cv, rig.sh_near, rig.elbow_near, rig.hand_near, "near arm")
    if p.sword_front:
        draw_sword(cv, rig.hand_near, p.sword, p.sword_glow, "grip")
    draw_hand(cv, rig.hand_near, p.sword if p.sword_front or True else p.near_hand_dir, "fist", "near hand")
    if p.sword_front:
        draw_sword(cv, rig.hand_near, p.sword, p.sword_glow, "blade")
    for effect in p.fx:
        effect(cv, rig)
    return cv, rig


def blade_tip(p: Pose):
    r = Rig(p)
    return add(r.hand_near, vec(p.sword, 4.2 + BLADE))
