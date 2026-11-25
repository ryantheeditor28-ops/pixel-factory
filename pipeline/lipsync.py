"""Stage 3 — lip-sync phoneme timing via rhubarb-lip-sync (free, MIT).

Per segment: mp3 -> mono 16-bit wav (ffmpeg) -> rhubarb -f json -> mouth cues
[{"t0":..,"t1":..,"shape":"A".."H"|"X"}] in seconds, LOCAL to the segment.

Rhubarb binary resolution order:
  1. $RHUBARB_BIN env var
  2. tools/rhubarb/rhubarb(.exe)  (how the workflow caches it)
Download: https://github.com/DanielSWolf/rhubarb-lip-sync/releases (v1.14.0 ships Linux+macOS+Windows).
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from llm import dump_json

SHAPES = {"A", "B", "C", "D", "E", "F", "G", "H", "X"}


def rhubarb_bin() -> str:
    env = os.environ.get("RHUBARB_BIN")
    if env and Path(env).exists():
        return env
    root = Path(__file__).resolve().parent.parent
    exe = "rhubarb.exe" if platform.system() == "Windows" else "rhubarb"
    for cand in (root / "tools" / "rhubarb" / exe, root / "tools" / "rhubarb" / "rhubarb"):
        if cand.exists():
            return str(cand)
    found = shutil.which("rhubarb")
    if found:
        return found
    raise FileNotFoundError(
        "rhubarb binary not found. Set RHUBARB_BIN or download the release zip "
        "for your platform into tools/rhubarb/ "
        "(https://github.com/DanielSWolf/rhubarb-lip-sync/releases)")


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def lipsync_segment(mp3: Path, text: str, workdir: Path) -> dict:
    """wav + rhubarb for one segment. Returns {duration, cues:[{t0,t1,shape}]}."""
    workdir.mkdir(parents=True, exist_ok=True)
    wav = workdir / (mp3.stem + ".wav")
    cues_path = workdir / (mp3.stem + ".cues.json")
    dialog = workdir / (mp3.stem + ".dialog.txt")

    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(mp3),
         "-ac", "1", "-ar", "22050", "-sample_fmt", "s16", str(wav)],
        check=True, capture_output=True)

    if not cues_path.exists():
        dialog.write_text(text, encoding="utf-8")
        cmd = [rhubarb_bin(), "-f", "json", "--extendedShapes", "GHX",
               "--dialogFile", str(dialog), "-o", str(cues_path), str(wav)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not cues_path.exists():
            raise RuntimeError(f"rhubarb failed ({res.returncode}): {res.stderr[-400:]}")

    raw = json.loads(cues_path.read_text(encoding="utf-8"))
    cues = [{"t0": round(float(c["start"]), 3),
             "t1": round(float(c["end"]), 3),
             "shape": c["value"] if c["value"] in SHAPES else "X"}
            for c in raw.get("mouthCues", [])]
    dur = _ffprobe_duration(mp3)
    return {"duration": round(dur, 3), "cues": cues}


def lipsync_all(segments: list[dict], voice_dir: Path) -> list[dict]:
    out = []
    for seg in segments:
        info = lipsync_segment(seg["mp3"], seg["text"], voice_dir)
        seg = dict(seg)
        seg.update(info)
        out.append(seg)
    total = sum(s["duration"] for s in out)
    print(f"[lipsync] rhubarb done: {len(out)} segments, {total:.1f}s speech total")
    return out
