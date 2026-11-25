"""Orchestrator — one command makes one video, end to end, for free.

  python pipeline/make_video.py                 # full run: topic -> mp4
  python pipeline/make_video.py --from-script   # reuse build/script.json
  python pipeline/make_video.py --no-render     # stop after HyperFrames project
  python pipeline/make_video.py --skip-check    # skip the lint gate (not recommended)

Stages: character sprites -> topic+script (GitHub trending + pollinations, with
deterministic fallback) -> edge-tts with word timestamps -> rhubarb lip sync ->
timeline -> HyperFrames project -> hyperframes check -> hyperframes render.

The HyperFrames CLI version is PINNED (matches video-template) so renders stay
reproducible on CI forever.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm import dump_json, load_json  # noqa: E402

HF_VERSION = "0.9.56"


def _npx() -> str:
    exe = "npx.cmd" if platform.system() == "Windows" else "npx"
    found = shutil.which(exe) or shutil.which("npx")
    if not found:
        raise FileNotFoundError("npx not found — install Node.js 22+")
    return found


def ensure_character() -> None:
    char_dir = ROOT / "assets" / "character"
    if not (char_dir / "idle.png").exists():
        import character
        character.main()


def run_check(project: Path) -> None:
    res = subprocess.run(
        [_npx(), "--yes", f"hyperframes@{HF_VERSION}", "check", "--json"],
        cwd=project, capture_output=True, text=True, timeout=600)
    out = res.stdout.strip()
    try:
        data = json.loads(out[out.index("{"):out.rindex("}") + 1])
        errors = [v for v in data.get("violations", []) if v.get("severity") == "error"]
        warnings = [v for v in data.get("violations", []) if v.get("severity") != "error"]
        print(f"[check] {len(errors)} errors, {len(warnings)} warnings")
        for v in (errors + warnings)[:20]:
            print(f"  - [{v.get('severity')}] {v.get('rule')}: {str(v.get('message'))[:140]}")
        if errors:
            raise SystemExit("check failed with errors — fix before rendering")
    except (ValueError, KeyError):
        print(f"[check] unparseable output (rc={res.returncode}); tail: {(res.stdout + res.stderr)[-400:]}")
        if res.returncode != 0:
            raise SystemExit("check failed")


def run_render(project: Path) -> Path:
    print("[render] npx hyperframes render (deterministic frame-seek + ffmpeg)…")
    res = subprocess.run(
        [_npx(), "--yes", f"hyperframes@{HF_VERSION}", "render"],
        cwd=project, capture_output=True, text=True, timeout=3600)
    tail = (res.stdout + "\n" + res.stderr).strip()[-1500:]
    print(tail)
    if res.returncode != 0:
        raise SystemExit(f"render failed rc={res.returncode}")
    mp4s = [p for p in project.rglob("*.mp4") if "assets" not in p.parts]
    if not mp4s:
        raise SystemExit("render finished but no mp4 found in project")
    return max(mp4s, key=lambda p: p.stat().st_mtime)


def update_state(script: dict) -> dict:
    state_dir = ROOT / "state"
    state_dir.mkdir(exist_ok=True)
    state_path = state_dir / "state.json"
    state = load_json(state_path) if state_path.exists() else {"used_topics": [], "videos": []}
    tid = script.get("topic_id")
    if tid and tid not in state["used_topics"]:
        state["used_topics"].append(tid)
    state["used_topics"] = state["used_topics"][-500:]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    state["videos"].append({"stamp": stamp, "topic": tid, "source": script.get("source"),
                            "title": script.get("title")})
    state["videos"] = state["videos"][-500:]
    dump_json(state_path, state)
    return state


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-script", action="store_true", help="reuse build/script.json")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--skip-check", action="store_true")
    args = ap.parse_args()

    cfg = load_json(ROOT / "config.json")
    build_dir = ROOT / "build"
    build_dir.mkdir(exist_ok=True)

    print("[1/7] character sprites")
    ensure_character()

    script_path = build_dir / "script.json"
    if args.from_script and script_path.exists():
        script = load_json(script_path)
        print(f"[2/7] reusing script ({script.get('source')}) topic={script.get('topic_id')}")
    else:
        print("[2/7] topic + script")
        state = load_json(ROOT / "state" / "state.json") if (ROOT / "state" / "state.json").exists() else {}
        import generate_script
        script = generate_script.main(build_dir, cfg, state)

    print("[3/7] voice (edge-tts, word timestamps)")
    import tts
    segments = tts.synth_segments(script, cfg, build_dir / "voice")

    print("[4/7] lip-sync data (rhubarb)")
    import lipsync
    segments = lipsync.lipsync_all(segments, build_dir / "voice")

    print("[5/7] timeline")
    import build_timeline
    timeline = build_timeline.build(script, segments, cfg, build_dir)

    print("[6/7] HyperFrames project")
    import hf_project
    project = hf_project.generate(timeline, build_dir)

    if args.no_render:
        print("stopped before check/render (--no-render)")
        return

    if not args.skip_check:
        print("[7/7] check")
        run_check(project)
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    mp4 = run_render(project)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    final = out_dir / f"video-{stamp}.mp4"
    shutil.copy2(mp4, final)

    state = update_state(script)
    print(f"\nDONE -> {final}")
    print(f"  topic:  {script.get('topic_id')} ({script.get('source')})")
    print(f"  length: {timeline['total']:.1f}s, {len(timeline['scenes'])} scenes")
    print(f"  videos made so far: {len(state.get('videos', []))}")


if __name__ == "__main__":
    main()
