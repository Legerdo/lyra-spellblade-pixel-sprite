"""End-to-end: render cels -> Pixelorama (stable) .pxo -> reopen/inspect -> Pixelorama CLI exports.

Usage: python pipeline.py [render|create|inspect|export|all]
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import poses
import px
from build import render
from palette import PALETTE
from raster import H, LAYERS, W

OUT = px.OUT
SRC = OUT / "source"
PXO = OUT / "character_action.pxo"
EXPORTS = OUT / "exports"
FRAMES_DIR = EXPORTS / "frames"
SHEET = EXPORTS / "character_action.png"
SHEET_COLUMNS = 5
TAG_COLORS = {"idle": "#8fd3ff", "run": "#ffb8d2", "attack-a": "#86f2ff", "attack-b": "#ff5cb6"}


def frame_table():
    rows = []
    for anim in poses.ORDER:
        for i, p in enumerate(poses.ANIMS[anim]):
            rows.append((anim, i, p))
    return rows


def stage_render():
    if SRC.exists():
        shutil.rmtree(SRC)
    (SRC / "cels").mkdir(parents=True)
    (SRC / "reference").mkdir(parents=True)
    frames, tags = [], []
    idx = 0
    for anim in poses.ORDER:
        start = idx
        for i, p in enumerate(poses.ANIMS[anim]):
            comp, layers, _ = render(p)
            cels = []
            for li, name in enumerate(LAYERS):
                rel = f"cels/f{idx:02d}_l{li}.png"
                layers[name].save(SRC / rel)
                cels.append(rel)
            comp.save(SRC / "reference" / f"f{idx:02d}_{anim}_{i}.png")
            frames.append({"id": f"{anim}:{i}", "duration_ms": poses.DURATION_MS[anim], "cels": cels})
            idx += 1
        tags.append({"name": anim, "from": start + 1, "to": idx, "color": TAG_COLORS[anim]})
    manifest = {
        "name": "character_action", "width": W, "height": H, "fps": 10.0, "layers": LAYERS,
        "frames": frames, "tags": tags, "sheet_columns": SHEET_COLUMNS,
        "palette_name": "Lyra Spellblade", "palette": ["#" + PALETTE[k][0] for k in PALETTE],
        "user_data": {"character": "Lyra, silver twin-tail spellblade", "pivot_feet": [70, 140],
                      "design_area": [30, 28, 80, 112], "ground_y": 140,
                      "authoring": "skeleton-driven integer-grid construction + hand-authored head/bow templates",
                      "image_generation_service": False},
    }
    (SRC / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("rendered", idx, "frames")
    return manifest


def stage_create():
    if PXO.exists():
        PXO.unlink()
    res = px.run("create", [], extra_env={"LYRA_MANIFEST": str(SRC / "manifest.json"), "LYRA_SRC": str(SRC),
                                          "LYRA_PXO": str(PXO), "LYRA_REPORT": str(OUT / "logs" / "create.json")})
    rep = json.loads((OUT / "logs" / "create.json").read_text(encoding="utf-8"))
    print("create", res.returncode, rep)
    assert res.returncode == 0 and rep["ok"] and PXO.is_file(), "create failed"


def stage_inspect(tag="inspect"):
    dump = OUT / "logs" / f"{tag}-cels"
    if dump.exists():
        shutil.rmtree(dump)
    res = px.run("inspect", [], log_name=tag,
                 extra_env={"LYRA_PXO": str(PXO), "LYRA_DUMP": str(dump),
                            "LYRA_REPORT": str(OUT / "logs" / f"{tag}.json")})
    rep = json.loads((OUT / "logs" / f"{tag}.json").read_text(encoding="utf-8"))
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    mismatches = []
    for i, fd in enumerate(manifest["frames"]):
        for j, rel in enumerate(fd["cels"]):
            a = np.array(Image.open(SRC / rel).convert("RGBA"))
            b = np.array(Image.open(dump / f"f{i:02d}_l{j}.png").convert("RGBA"))
            a[a[..., 3] == 0] = 0
            b[b[..., 3] == 0] = 0
            if a.shape != b.shape or not np.array_equal(a, b):
                mismatches.append(rel)
    rep["cel_mismatches"] = mismatches
    rep["cels_compared"] = sum(len(f["cels"]) for f in manifest["frames"])
    (OUT / "logs" / f"{tag}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(tag, res.returncode, {k: rep[k] for k in ("frames", "size", "durations_ms", "tags")},
          "mismatches", len(mismatches))
    return rep


def _cli(label, args):
    res = px.run("", ["--quit", "--", str(PXO), *args], log_name=label)
    if res.returncode != 0:
        raise RuntimeError(f"{label} failed, see logs/{label}.log")
    return res


def stage_export():
    if EXPORTS.exists():
        shutil.rmtree(EXPORTS)
    FRAMES_DIR.mkdir(parents=True)
    _cli("cli-info", ["--size", "--framecount"])
    _cli("cli-sheet", ["--export", "--spritesheet", "--json", "--output", str(SHEET)])
    _cli("cli-frames", ["--export", "--output", str(FRAMES_DIR / "character_action.png")])
    tmp = OUT / "logs" / "repeat"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    _cli("cli-sheet-repeat", ["--export", "--spritesheet", "--output", str(tmp / "character_action.png")])
    print(sorted(p.name for p in EXPORTS.rglob("*") if p.is_file())[:30])


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("render", "all"):
        stage_render()
    if what in ("create", "all"):
        stage_create()
    if what in ("inspect", "all"):
        stage_inspect()
    if what in ("export", "all"):
        stage_export()


def stage_gui():
    shots = OUT / "qa" / "pixelorama-gui"
    if shots.exists():
        shutil.rmtree(shots)
    res = px.run("gui", [], headless=False, timeout=240, log_name="gui",
                 extra_env={"LYRA_PXO": str(PXO), "LYRA_SHOTS": str(shots),
                            "LYRA_REPORT": str(OUT / "logs" / "gui.json")})
    rep = json.loads((OUT / "logs" / "gui.json").read_text(encoding="utf-8"))
    print("gui", res.returncode, rep)
    return rep


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "gui":
    stage_gui()
