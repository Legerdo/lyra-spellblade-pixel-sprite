"""Run the stable Pixelorama v1.2.3 desktop build in an isolated, workspace-local environment.

APPDATA/LOCALAPPDATA/TEMP are redirected into the workspace so Pixelorama's config, logs,
backups and extension folder never touch the user's real profile.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
STABLE = ROOT / ".devspace" / "pixelorama-stable-v1.2.3" / "Pixelorama-Windows-64bit" / "Pixelorama.exe"
ENV_ROOT = ROOT / ".devspace" / "lyra-env"
USER_DIR = ENV_ROOT / "AppData" / "Roaming" / "pixelorama"
OUT = ROOT / "artifacts" / "lyra-spellblade"


def isolated_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    roaming = ENV_ROOT / "AppData" / "Roaming"
    local = ENV_ROOT / "AppData" / "Local"
    temp = ENV_ROOT / "Temp"
    for p in (roaming, local, temp):
        p.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"APPDATA": str(roaming), "LOCALAPPDATA": str(local), "TEMP": str(temp), "TMP": str(temp),
                "USERPROFILE": str(ENV_ROOT)})
    if extra:
        env.update(extra)
    return env


def install_extension() -> Path:
    """Pack the driver extension as a zip resource pack and enable it in the isolated config."""
    ext_dir = USER_DIR / "extensions"
    ext_dir.mkdir(parents=True, exist_ok=True)
    target = ext_dir / "LyraDriver.zip"
    src = TOOL / "extension"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(src).as_posix())
    cfg = USER_DIR / "config.ini"
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    if "[extensions]" not in text:
        text += "\n[extensions]\n\nLyraDriver=true\n"
    elif "LyraDriver=true" not in text:
        text = text.replace("[extensions]", "[extensions]\n\nLyraDriver=true", 1)
    cfg.write_text(text, encoding="utf-8")
    return target


def run(mode: str, args: list[str] | None = None, headless: bool = True, timeout: int = 180,
        extra_env: dict[str, str] | None = None, log_name: str | None = None) -> subprocess.CompletedProcess:
    install_extension()
    env = isolated_env({"LYRA_MODE": mode, "LYRA_OUT": str(OUT), **(extra_env or {})})
    cmd = [str(STABLE)]
    if headless:
        cmd.append("--headless")
    cmd += args or []
    t = time.perf_counter()
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=timeout, cwd=str(ROOT))
    ms = round((time.perf_counter() - t) * 1000)
    log = OUT / "logs"
    log.mkdir(parents=True, exist_ok=True)
    (log / f"{log_name or mode}.log").write_text(
        json.dumps(cmd) + f"\nexit={res.returncode} ms={ms}\n" + res.stdout + "\n--- stderr ---\n" + res.stderr,
        encoding="utf-8")
    return res


if __name__ == "__main__":
    r = run(sys.argv[1] if len(sys.argv) > 1 else "probe", sys.argv[2:])
    print(r.returncode)
    print("\n".join(l for l in r.stdout.splitlines() if "LYRA" in l or "ERROR" in l or "SCRIPT" in l))
    print(r.stderr[-3000:])
