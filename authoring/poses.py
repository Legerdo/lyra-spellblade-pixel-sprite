"""Pose-to-pose key data for every frame (joint targets in canvas pixels).

Secondary motion (twin-tails, scarf, skirt) is not keyed by hand per frame: each chain
follows a drive signal with a per-segment delay, so the root reacts first and the tip
follows later (follow-through / overlapping action). Loops sample the drive cyclically.
"""
from __future__ import annotations

import math
from dataclasses import replace

from character import ANKLE_Y, Pose

GY = ANKLE_Y


def sample(sig, f, cyclic):
    """Linear sample of a per-frame signal at fractional frame f."""
    n = len(sig)
    if cyclic:
        f %= n
        i = int(math.floor(f))
        a = f - i
        return sig[i] * (1 - a) + sig[(i + 1) % n] * a
    f = max(0.0, min(n - 1.0, f))
    i = int(math.floor(f))
    a = f - i
    return sig[i] * (1 - a) + sig[min(i + 1, n - 1)] * a


def lagged(sig, f, n_seg, lag, gains, cyclic, pre=None):
    """Per-segment offsets: segment i sees the drive i*lag frames late."""
    out = []
    for i in range(n_seg):
        t = f - i * lag
        if not cyclic and t < 0 and pre is not None:
            v = pre
        else:
            v = sample(sig, t, cyclic)
        out.append(v * gains[i])
    return tuple(out)


TAIL_GAIN = [0.25, 0.55, 0.8, 1, 1, 1.05, 1.1, 1.15, 1.2]
SCARF_GAIN = [0.35, 0.7, 0.95, 1, 1.05, 1.1, 1.15]


def secondary(poses_, tail_sig, scarf_sig, cyclic, tail_lag=0.45, scarf_lag=0.6, far_scale=0.85,
              pre_tail=0.0, pre_scarf=0.0, tail_gain=None, far_sig=None, far_gain=None):
    out = []
    tg = tail_gain or TAIL_GAIN
    fg = far_gain or [g * far_scale for g in tg]
    fs = far_sig or tail_sig
    for f, p in enumerate(poses_):
        tn = lagged(tail_sig, f, 9, tail_lag, tg, cyclic, pre_tail)
        tf = lagged(fs, f - 0.3, 9, tail_lag, fg, cyclic, pre_tail)
        sa = lagged(scarf_sig, f, 7, scarf_lag, SCARF_GAIN, cyclic, pre_scarf)
        sb = lagged(scarf_sig, f - 0.4, 7, scarf_lag, [g * 0.9 for g in SCARF_GAIN], cyclic, pre_scarf)
        out.append(replace(p, tails=(tn, tf), scarf=(sa, sb)))
    return out


# ------------------------------------------------------------------ IDLE (model sheet)
IDLE0 = Pose(
    pelvis=(66.0, 83.5), lean=2.0, turn=0.0,
    near_foot=(58.0, GY, 0.0), far_foot=(78.0, GY, 0.0),
    near_hand=(76.0, 86.0), near_bend=-1, sword=62.0,
    far_hand=(75.0, 81.0), far_bend=1, far_hand_dir=200.0,
    skirt=(0.0, 0.0, 0.0),
)
IDLE1 = replace(IDLE0, breath=1.0, head=(0.0, -1.0), face="calm", near_hand=(76.0, 85.5),
                far_hand=(75.0, 80.5), skirt=(0.6, -0.4, 0.0))
idle = secondary([IDLE0, IDLE1], tail_sig=[0.0, -5.0], scarf_sig=[0.0, -7.0], cyclic=True,
                 tail_lag=0.5, scarf_lag=0.5)

# ------------------------------------------------------------------ RUN (6f loop, 90 ms)
RX = 66.0
# near foot: ankle (dx from pelvis, height above ground, sole angle) ??far foot is 3 frames later
NEAR_FOOT = [(13, 0, -12), (2, 0, 0), (-10, 2.0, 25), (-17, 12.5, 58), (-5, 18.5, 42), (10, 8, 4)]
PELVIS_Y = [85.3, 87.6, 83.4, 85.3, 87.6, 83.4]
TURN = [-0.8, -0.4, 0.4, 0.8, 0.4, -0.4]
NEAR_HAND = [(51, 77), (55, 81), (65, 80), (76, 70), (72, 75), (61, 81)]
SWORD = [158, 150, 138, 124, 128, 146]
FAR_HAND = [(86, 69), (83, 74), (76, 79), (67, 79), (70, 78), (80, 75)]
SKIRT = [(2.5, 0.5, 1.0), (2.8, 0.0, 2.4), (3.2, 0.5, 1.2), (2.5, 0.5, 1.0), (2.8, 0.0, 2.4),
         (3.2, 0.5, 1.2)]


NEAR_CONTACT_DY = 3.2


def run_pose(f):
    nf = NEAR_FOOT[f]
    if f == 0:  # near hip sits higher in this frame: extend to a true heel contact
        nf = (nf[0], nf[1] - NEAR_CONTACT_DY, nf[2])
    ff = NEAR_FOOT[(f + 3) % 6]
    return Pose(
        pelvis=(RX, PELVIS_Y[f]), lean=10.0, turn=TURN[f], hip_turn=-TURN[f] * 0.6,
        head=(1.0, 0.0), face="neutral",
        near_foot=(RX + nf[0], GY - nf[1], nf[2]), far_foot=(RX + ff[0], GY - ff[1], ff[2]),
        near_hand=NEAR_HAND[f], near_bend=-1, sword=SWORD[f],
        far_hand=FAR_HAND[f], far_bend=-1, far_hand_dir=20.0,
        skirt=SKIRT[f],
    )


# tails/scarf stream behind; vertical bob makes them flap twice per cycle
RUN_TAIL = [40 + 15 * math.sin(2 * math.pi * (f / 3.0) + 0.6) for f in range(6)]
RUN_TAIL_FAR = [52 + 13 * math.sin(2 * math.pi * (f / 3.0) + 0.2) for f in range(6)]
RUN_SCARF = [62 + 12 * math.sin(2 * math.pi * (f / 3.0) + 1.1) for f in range(6)]
# gravity droop: the trailing push weakens toward the tip, so the tails arc downward
RUN_GAIN = [0.3, 0.75, 0.95, 1.0, 0.92, 0.84, 0.76, 0.68, 0.6]
RUN_GAIN_FAR = [0.35, 0.8, 1.0, 1.05, 1.0, 0.95, 0.88, 0.8, 0.72]
run = secondary([run_pose(f) for f in range(6)], RUN_TAIL, RUN_SCARF, cyclic=True, tail_lag=0.32,
                tail_gain=RUN_GAIN, far_sig=RUN_TAIL_FAR, far_gain=RUN_GAIN_FAR)

# ------------------------------------------------------------------ ATTACK A: rising slash
def P(**kw):
    base = dict(far_hand_shape="open", far_bend=-1, near_bend=-1, face="focus")
    base.update(kw)
    return Pose(**base)


A = [
    # 0 anticipation: sink, pull the blade back low, free hand forward for balance
    P(pelvis=(64, 86.2), lean=-3, turn=-0.8, near_foot=(57, GY, 0), far_foot=(79, GY, 0),
      near_hand=(53, 88), sword=165, far_hand=(85, 73), far_hand_dir=-5),
    # 1 loading: deepest coil, weight on the front (far) foot, near foot unloads to step
    P(pelvis=(61, 88.3), lean=-6, turn=-1.0, hip_turn=-0.6, near_foot=(62, GY - 2.5, 14),
      far_foot=(78, GY, 0), near_hand=(46, 92), sword=172, far_hand=(88, 69), far_hand_dir=-15),
    # 2 acceleration: step lands, blade sweeps under and forward
    P(pelvis=(71, 86.3), lean=8, turn=0.2, hip_turn=0.5, near_foot=(88, GY, 0),
      far_foot=(64, GY - 2.2, 22), near_hand=(77, 89), sword=38, far_hand=(76, 77),
      far_hand_dir=190),
    # 3 impact: full rising extension on the planted front foot
    P(pelvis=(75, 84.3), lean=10, turn=1.0, hip_turn=0.8, face="shout", near_foot=(90, GY, 0),
      far_foot=(58, GY - 2.2, 32), near_hand=(102, 56), sword=-40, far_hand=(68, 75),
      far_hand_dir=200),
    # 4 overshoot: blade carries past vertical, body stretches, back heel up
    P(pelvis=(76, 83.3), lean=6, turn=0.9, hip_turn=0.7, face="shout", near_foot=(90, GY, 0),
      far_foot=(61, GY - 3.0, 36), near_hand=(88, 44), sword=-94, far_hand=(71, 72),
      far_hand_dir=200),
    # 5 recovery: settle into guard, blade lowered forward
    P(pelvis=(72, 85.0), lean=3, turn=0.3, hip_turn=0.3, near_foot=(86, GY, 0),
      far_foot=(62, GY, 4), near_hand=(83, 84), sword=46, far_hand=(75, 80), far_hand_dir=200,
      far_hand_shape="fist"),
]


def with_fx(poses_, builders):
    out = []
    for i, p in enumerate(poses_):
        out.append(replace(p, fx=[b for b in builders.get(i, [])]))
    return out


def _attack_a_fx():
    import fx
    from character import Rig
    tips = [blade_tip(p) for p in A]
    sh = [Rig(p).sh_near for p in A]
    return {
        2: [lambda cv, r: fx.arc_trail(cv, sh[2], tips[1], tips[2], width=7, name="trail A2")],
        3: [lambda cv, r: fx.arc_trail(cv, sh[3], tips[2], tips[3], width=11, name="trail A3"),
            lambda cv, r: fx.star(cv, (tips[3][0] - 1, tips[3][1] + 1), size=5, name="impact")],
        4: [lambda cv, r: fx.arc_trail(cv, sh[4], tips[3], tips[4], width=7, fade=0.5, name="trail A4"),
            lambda cv, r: fx.sparkle(cv, (tips[3][0] - 3, tips[3][1] + 8), "plus", "c"),
            lambda cv, r: fx.sparkle(cv, (tips[3][0] + 2, tips[3][1] - 6), "block", "z", alpha=200)],
        5: [lambda cv, r: fx.sparkle(cv, (tips[4][0] + 12, tips[4][1] + 14), "block", "c", alpha=200),
            lambda cv, r: fx.sparkle(cv, (tips[3][0] - 4, tips[3][1] + 3), "plus", "z", alpha=140)],
    }


from character import blade_tip  # noqa: E402

A_TAIL = [-8, -16, 28, 46, 34, 12]
A_TAIL_FAR = [-6, -12, 24, 40, 30, 10]
A_SCARF = [-10, -22, 38, 60, 44, 18]
attack_a = secondary(with_fx(A, _attack_a_fx()), A_TAIL, A_SCARF, cyclic=False, tail_lag=0.45,
                     scarf_lag=0.55, far_sig=A_TAIL_FAR)

# ------------------------------------------------------------------ ATTACK B: magic sword wave
B = [
    # 0 preparation: free hand opens a sigil, blade lowered at the side
    P(pelvis=(64, 85.2), lean=0, turn=-0.3, near_foot=(56, GY, 0), far_foot=(81, GY, 0),
      near_hand=(60, 90), sword=108, far_hand=(84, 62), far_hand_dir=-35),
    # 1 raising: blade lifted vertically behind the head line, face stays clear
    P(pelvis=(65, 84.6), lean=-2, turn=-0.6, near_foot=(56, GY, 0), far_foot=(81, GY, 0),
      near_hand=(55, 44), near_bend=1, sword=-100, far_hand=(88, 60), far_hand_dir=-40),
    # 2 charge: crouch 2 px, blade ignites, ground circle
    P(pelvis=(65, 86.6), lean=-3, turn=-0.7, near_foot=(55, GY, 0), far_foot=(82, GY, 0),
      near_hand=(55, 45), near_bend=1, sword=-100, sword_glow=1, far_hand=(87, 61), far_hand_dir=-60),
    # 3 release: big forward cut, weight drives onto the front foot
    P(pelvis=(72, 86.2), lean=9, turn=0.9, hip_turn=0.6, face="shout", near_foot=(58, GY - 1.0, 18),
      far_foot=(84, GY, 0), near_hand=(94, 72), sword=12, sword_glow=1, far_hand=(70, 76),
      far_hand_dir=200),
    # 4 wave: crescent detaches and travels, blade follows through low
    P(pelvis=(73, 87.2), lean=10, turn=0.8, hip_turn=0.6, face="shout", near_foot=(59, GY - 1.5, 22),
      far_foot=(84, GY, 0), near_hand=(95, 77), sword=24, far_hand=(70, 77), far_hand_dir=200),
    # 5 recovery
    P(pelvis=(70, 85.4), lean=4, turn=0.3, hip_turn=0.3, face="calm", near_foot=(59, GY, 4),
      far_foot=(84, GY, 0), near_hand=(84, 86), sword=50, far_hand=(75, 80), far_hand_dir=200,
      far_hand_shape="fist"),
]


def _attack_b_fx():
    import fx
    from character import BLADE, Rig
    tips = [blade_tip(p) for p in B]
    rigs = [Rig(p) for p in B]
    sh = [r.sh_near for r in rigs]
    fh = [r.hand_far for r in rigs]
    return {
        0: [lambda cv, r: fx.sigil(cv, (fh[0][0] + 5, fh[0][1] - 2), rx=2.2, ry=5.5, alpha=200, spin=0),
            lambda cv, r: fx.sparkle(cv, (fh[0][0] + 9, fh[0][1] - 9), "plus", "z", alpha=200)],
        1: [lambda cv, r: fx.sigil(cv, (fh[1][0] + 5, fh[1][1] - 2), rx=2.8, ry=7.0, alpha=255, spin=1),
            lambda cv, r: fx.blade_glow(cv, rigs[1].hand_near, B[1].sword, BLADE, alpha=140),
            lambda cv, r: fx.sparkle(cv, (tips[1][0] + 6, tips[1][1] + 10), "plus", "c", alpha=200)],
        2: [lambda cv, r: fx.blade_glow(cv, rigs[2].hand_near, B[2].sword, BLADE, alpha=200, reach=2.2),
            lambda cv, r: fx.star(cv, tips[2], size=5, name="charge"),
            lambda cv, r: fx.sigil(cv, (68, 139), rx=24, ry=3.2, alpha=200, spin=2, name="ground sigil"),
            lambda cv, r: fx.sparkle(cv, (tips[2][0] + 9, tips[2][1] + 14), "plus", "z"),
            lambda cv, r: fx.sparkle(cv, (tips[2][0] - 8, tips[2][1] + 20), "plus", "c"),
            lambda cv, r: fx.sparkle(cv, (fh[2][0] + 4, fh[2][1] - 6), "block", "c", alpha=200)],
        3: [lambda cv, r: fx.arc_trail(cv, sh[3], tips[2], tips[3], width=12, name="release arc"),
            lambda cv, r: fx.blade_glow(cv, rigs[3].hand_near, B[3].sword, BLADE, alpha=200, reach=2.0),
            lambda cv, r: fx.crescent_wave(cv, (tips[3][0] - 12, tips[3][1] - 1), 13, 4.5,
                                           height_scale=1.7, name="wave forming")],
        4: [lambda cv, r: fx.crescent_wave(cv, (117, tips[3][1]), 20, 7.5, height_scale=1.75, name="wave"),
            lambda cv, r: fx.sparkle(cv, (104, tips[3][1] - 26), "plus", "c"),
            lambda cv, r: fx.sparkle(cv, (101, tips[3][1] + 24), "plus", "z", alpha=200)],
        5: [lambda cv, r: fx.crescent_wave(cv, (125, tips[3][1]), 13, 2.6, height_scale=1.9, name="wave fade",
                                           alpha_scale=0.5),
            lambda cv, r: fx.sparkle(cv, (113, tips[3][1] - 18), "block", "c", alpha=140),
            lambda cv, r: fx.sparkle(cv, (110, tips[3][1] + 20), "block", "z", alpha=140)],
    }


B_TAIL = [-2, 6, 18, 36, 42, 16]
B_TAIL_FAR = [-4, -12, -22, 30, 38, 14]  # charge updraft spreads the far tail outward (right)
B_SCARF = [-4, 8, 22, 50, 58, 24]
attack_b = secondary(with_fx(B, _attack_b_fx()), B_TAIL, B_SCARF, cyclic=False, tail_lag=0.45,
                     scarf_lag=0.55, far_sig=B_TAIL_FAR)

ANIMS = {
    "idle": idle,
    "run": run,
    "attack-a": attack_a,
    "attack-b": attack_b,
}
ORDER = ["idle", "run", "attack-a", "attack-b"]
DURATION_MS = {"idle": 500, "run": 90, "attack-a": 100, "attack-b": 100}
