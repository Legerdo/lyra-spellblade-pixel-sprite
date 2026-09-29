"""Structural validation of the Pixelorama exports + project, and browser verification of index.html."""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
import zipfile

import numpy as np
from PIL import Image

import poses
import px
from palette import RGB_TO_KEY

OUT = px.OUT
EXP = OUT / "exports"
QA = OUT / "qa"
QA.mkdir(exist_ok=True)
checks: dict[str, bool] = {}
info: dict = {}


def rgba(p):
    return np.array(Image.open(p).convert("RGBA"))


# ---------------- exports
frame_files = sorted((EXP / "frames").glob("character_action_*.png"))
checks["frame_count_20"] = len(frame_files) == 20
frames = []
for f in frame_files:
    im = Image.open(f)
    frames.append(np.array(im.convert("RGBA")))
    checks.setdefault("frames_140x168", True)
    checks["frames_140x168"] &= im.size == (140, 168)
    checks.setdefault("frames_rgba_alpha", True)
    checks["frames_rgba_alpha"] &= im.mode == "RGBA"
checks["frames_not_empty"] = all((a[..., 3] > 0).sum() > 1500 for a in frames)
checks["frames_transparent_background"] = all(a[0, 0, 3] == 0 and a[-1, -1, 3] == 0 and (a[..., 3] == 0).mean() > 0.5
                                              for a in frames)
sheet = rgba(EXP / "character_action.png")
checks["sheet_700x672"] = sheet.shape[:2] == (672, 700)
tiles_ok = True
for i, a in enumerate(frames):
    r, c = divmod(i, 5)
    tiles_ok &= np.array_equal(sheet[r * 168:(r + 1) * 168, c * 140:(c + 1) * 140], a)
checks["sheet_tiles_equal_frames_in_order"] = tiles_ok
rep = rgba(OUT / "logs" / "repeat" / "character_action.png")
checks["repeat_export_identical"] = np.array_equal(rep, sheet)
# exported frames equal the authored composites (visible pixels)
ref = sorted((OUT / "source" / "reference").glob("f*.png"))
diff = 0
for a, rp in zip(frames, ref):
    b = rgba(rp).astype(int)
    diff = max(diff, int(np.abs(a.astype(int) - b)[a[..., 3] > 0].max(initial=0)))
info["max_channel_diff_vs_authored"] = diff
checks["export_matches_authored"] = diff <= 2
checks["no_duplicate_frames"] = len({hashlib.sha256(a.tobytes()).hexdigest() for a in frames}) == 20

# ---------------- source cels: palette, alpha policy, baseline, not position-only
manifest = json.loads((OUT / "source" / "manifest.json").read_text(encoding="utf-8"))
off, semi, grounds, bodies = 0, 0, [], []
for fd in manifest["frames"]:
    body = np.zeros((168, 140), bool)
    for rel in fd["cels"][:-1]:
        c = rgba(OUT / "source" / rel)
        m = c[..., 3] > 0
        semi += int((m & (c[..., 3] < 255)).sum())
        off += sum(1 for px_ in c[m][:, :3] if tuple(px_) not in RGB_TO_KEY)
        body |= m
    fx = rgba(OUT / "source" / fd["cels"][-1])
    fm = fx[..., 3] > 0
    off += sum(1 for px_ in fx[fm][:, :3] if tuple(px_) not in RGB_TO_KEY)
    grounds.append(int(np.nonzero(body.any(1))[0].max()))
    bodies.append(body)
checks["palette_locked_37"] = off == 0
checks["body_no_semi_alpha"] = semi == 0
info["lowest_body_row_per_frame"] = grounds
checks["feet_on_ground_y140"] = all(g == 140 for g in grounds)


def best_shift_iou(a, b, r=8):
    best = 0.0
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            s = np.roll(np.roll(b, dy, 0), dx, 1)
            best = max(best, (a & s).sum() / max((a | s).sum(), 1))
    return best


shift_iou = []
start = 0
for anim in poses.ORDER:
    n = len(poses.ANIMS[anim])
    for i in range(n):
        j = (i + 1) % n
        shift_iou.append(round(best_shift_iou(bodies[start + i], bodies[start + j]), 3))
    start += n
info["neighbour_best_shift_silhouette_iou"] = shift_iou
checks["not_position_only_animation"] = max(shift_iou) < 0.97

# ---------------- pixelorama project
with zipfile.ZipFile(OUT / "character_action.pxo") as z:
    checks["pxo_zip_intact"] = z.testzip() is None
    data = json.loads(z.read("data.json"))
checks["pxo_meta"] = (data["size_x"], data["size_y"], len(data["frames"]), len(data["layers"])) == (140, 168, 20, 6)
insp = json.loads((OUT / "logs" / "inspect.json").read_text(encoding="utf-8"))
checks["pxo_reopen_cels_exact"] = insp["cels_compared"] == 120 and not insp["cel_mismatches"]
checks["pxo_tags"] = [(t["name"], t["from"], t["to"]) for t in insp["tags"]] == [
    ("idle", 1, 2), ("run", 3, 8), ("attack-a", 9, 14), ("attack-b", 15, 20)]
checks["pxo_durations"] = insp["durations_ms"] == [500] * 2 + [90] * 6 + [100] * 12
checks["pxo_project_palette"] = len(insp["project_palettes"].get("Lyra Spellblade", [])) == 37
gui = json.loads((OUT / "logs" / "gui.json").read_text(encoding="utf-8"))
checks["pixelorama_gui_playback"] = gui["ok"] and gui["zoom_at_native"] == 1.0 and gui["onion_skinning"]

# ---------------- browser
with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
server = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], cwd=OUT,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.0)
browser_info = {}
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 1500, "height": 1000})
        reqs, errs = [], []
        page.on("request", lambda r: reqs.append(r.url))
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append(str(e)))
        resp = page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load")
        page.wait_for_function("window.__lyra && window.__lyra.ready")
        page.wait_for_timeout(4500)
        res = page.evaluate("""() => {
          const q = s => document.querySelector(s);
          const ids = ['animation-preview','idle-preview','run-preview','attack-a-preview','attack-b-preview',
                       'contact-sheet','native-size-example','equal-display-size-example'];
          const out = {ids: Object.fromEntries(ids.map(i => [i, !!document.getElementById(i)]))};
          out.previews = [...document.querySelectorAll('[data-animation-preview]')].map(c => c.dataset.animationPreview);
          out.contact = [...document.querySelectorAll('[data-contact-frame]')].map(c => c.dataset.contactFrame);
          out.native = [...document.querySelectorAll('[data-native]')].map(c => [c.width, c.height, c.clientWidth, c.clientHeight]);
          out.rendering = getComputedStyle(q('#run-preview')).imageRendering;
          out.smoothing = q('#run-preview').getContext('2d').imageSmoothingEnabled;
          const g = q('[data-native="idle"]').getContext('2d');
          out.corner_alpha = g.getImageData(0, 0, 1, 1).data[3];
          out.center_alpha = g.getImageData(70, 60, 1, 1).data[3];
          out.log = window.__lyra.log; out.errors = window.__lyra.errors;
          return out; }""")
        page.screenshot(path=str(QA / "browser-full.png"), full_page=True)
        page.locator("#animation-preview").screenshot(path=str(QA / "browser-live.png"))
        b.close()
    intervals = {}
    for anim, log in res["log"].items():
        t = [e[1] for e in log]
        fr = [e[0] for e in log]
        d = [round(t[k + 1] - t[k]) for k in range(len(t) - 1)]
        intervals[anim] = {"frames_seen": sorted(set(fr)), "intervals_ms": d}
    exp = {"idle": 500, "run": 90, "attack-a": 100, "attack-b": 100}
    timing_ok = True
    for anim, v in intervals.items():
        d = v["intervals_ms"]
        normal = [x for x in d if x < exp[anim] + 200] if anim.startswith("attack") else d
        med = float(np.median(normal)) if normal else 0
        v["median_ms"] = med
        timing_ok &= abs(med - exp[anim]) <= 17
        if anim.startswith("attack"):
            v["hold_ms"] = max(d) if d else 0
            timing_ok &= abs(max(d) - (exp[anim] + 400)) <= 34
    counts_ok = all(len(intervals[a]["frames_seen"]) == n for a, n in
                    (("idle", 2), ("run", 6), ("attack-a", 6), ("attack-b", 6)))
    external = [u for u in reqs if not u.startswith(f"http://127.0.0.1:{port}/")]
    browser_info = {"status": resp.status, "requests": reqs, "external_requests": external, "js_errors": errs,
                    "dom": {k: res[k] for k in ("ids", "previews", "native", "rendering", "smoothing",
                                                "corner_alpha", "center_alpha")},
                    "contact_frames": res["contact"], "timing": intervals}
    checks["browser_loads"] = resp.status == 200 and not res["errors"]
    checks["browser_no_js_errors"] = not errs
    checks["browser_no_external_requests"] = not external and len(reqs) == 2
    checks["browser_required_ids"] = all(res["ids"].values())
    checks["browser_preview_attrs"] = res["previews"] == ["idle", "run", "attack-a", "attack-b"]
    checks["browser_contact_20_in_order"] = res["contact"] == [m["id"] for m in json.loads(
        (EXP / "character_action.meta.json").read_text())["frames"]]
    checks["browser_pixelated"] = res["rendering"] == "pixelated" and res["smoothing"] is False
    checks["browser_native_1x"] = all(n == [140, 168, 140, 168] for n in res["native"])
    checks["browser_alpha_preserved"] = res["corner_alpha"] == 0 and res["center_alpha"] == 255
    checks["browser_frame_counts"] = counts_ok
    checks["browser_timing"] = timing_ok
finally:
    server.terminate()

checks = {k: bool(v) for k, v in checks.items()}
report = {"all_passed": all(checks.values()), "checks": checks, "info": info, "browser": browser_info}
(QA / "verification.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
for k, v in checks.items():
    print(("PASS " if v else "FAIL ") + k)
print(json.dumps(info))
print({a: (v["frames_seen"], v["median_ms"], v.get("hold_ms")) for a, v in browser_info.get("timing", {}).items()})
print("ALL PASSED" if report["all_passed"] else "SOME FAILED")
