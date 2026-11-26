"""One-shot SFX prep: loudness-match the Freesound kit + synthesize UI tones.

Outputs are committed to assets/sfx/ so CI never runs this:
  fs-XXXXXX-n.mp3   normalized copy of fs-XXXXXX.mp3 — mean loudness pulled to
                    -20 dBFS, true peak capped ~ -3 dBFS (alimiter). The raw
                    previews were mastered wildly differently (key1 mean -30.7 dB
                    vs key2 -27.9 vs shimmer -21.4), which made alternating
                    samples pump and the whoosh nearly inaudible under the voice.
  syn-ping.mp3      clean two-partial UI ping (1318 Hz + overtone, exp decay) —
                    the $0 pill pop and the #N badge ping. Synthesized locally
                    (ffmpeg aevalsrc), no license, no game-pack timbre.
  syn-ding.mp3      soft two-partial chime on G6 — the star count-up landing.

Originals stay untouched (provenance: audio-manifest.json sha256 hashes).
The shot plan cues only the -n / syn- files; per-role trim lives in
shot_plan.SFX so the whole chain stays declarative.

Run:  python pipeline/prep_sfx.py
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

SFX = Path(__file__).resolve().parent.parent / "assets" / "sfx"
TARGET_DB = -20.0          # shared loudness baseline before per-role trims
PEAK_LIMIT = 0.7           # alimiter linear ceiling (~ -3.1 dBFS)

SYNTH = {
    "syn-ping.mp3": ("aevalsrc=0.55*sin(2*PI*1318*t)*exp(-16*t)"
                     "+0.20*sin(2*PI*2637*t)*exp(-22*t):d=0.35:s=44100", 0.35),
    "syn-ding.mp3": ("aevalsrc=0.5*sin(2*PI*1568*t)*exp(-6*t)"
                     "+0.22*sin(2*PI*3136*t)*exp(-9*t):d=0.95:s=44100", 0.95),
}


def mean_dbfs(path: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"], capture_output=True, text=True).stderr
    for line in out.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    raise RuntimeError(f"no mean_volume for {path}")


def normalize(src: Path, dst: Path):
    gain = TARGET_DB - mean_dbfs(src)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af",
         f"volume={gain:.2f}dB,alimiter=limit={PEAK_LIMIT}",
         "-c:a", "libmp3lame", "-b:a", "192k", str(dst)], check=True)
    print(f"{dst.name}: gain {gain:+.1f} dB")


def main() -> None:
    for name, (expr, _dur) in SYNTH.items():
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "tone.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                            "-i", expr, str(wav)], check=True)
            normalize(wav, SFX / name)
    manifest = json.loads((SFX / "audio-manifest.json").read_text(encoding="utf-8"))
    for asset in manifest["assets"]:
        normalize(SFX / asset["file"],
                  SFX / asset["file"].replace(".mp3", "-n.mp3"))


if __name__ == "__main__":
    main()
