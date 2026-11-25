"""Stage 4 — build the master timeline and the sample-accurate voice track.

Merges script + per-segment word timings + per-segment rhubarb cues into
build/timeline.json, the single file the HyperFrames project generator consumes.

Global clock:  scene i starts at seg_start[i]; words/cues stay LOCAL to each
scene (scene clock starts at 0 at its host's data-start — the HyperFrames way).
Audio: WAV concat (sample-accurate) -> final mp3. No mp3-frame drift.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from llm import dump_json, load_json

LEAD = 0.45      # silence before the hook (first frame shows the title = thumbnail)
GAP = 0.28       # breath between segments (template pacing: quick cuts, no dead air)
OUTRO = 0.95     # hold the last frame


def _silence_wav(path: Path, seconds: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"anullsrc=r=22050:cl=mono", "-t", f"{seconds:.3f}",
         "-c:a", "pcm_s16le", str(path)],
        check=True, capture_output=True)


def _concat_wavs(wavs: list[Path], out_wav: Path, workdir: Path) -> None:
    list_file = workdir / "concat.txt"
    lines = [f"file '{w.as_posix()}'" for w in wavs]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c:a", "pcm_s16le", str(out_wav)],
        check=True, capture_output=True)


def group_phrases(words: list[dict], max_words: int = 3, max_gap: float = 0.4,
                  max_dur: float = 2.2) -> list[dict]:
    """Split a segment's words into caption phrases (what pops on screen together)."""
    phrases, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words
                    or w["t0"] - cur[-1]["t1"] > max_gap
                    or w["t1"] - cur[0]["t0"] > max_dur):
            phrases.append(cur)
            cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)
    return [{
        "t0": round(p[0]["t0"], 3),
        "t1": round(min(p[-1]["t1"] + 0.18, p[-1]["t1"] + 0.18), 3),
        "words": p,
    } for p in phrases]


def build(script: dict, segments: list[dict], cfg: dict, build_dir: Path) -> dict:
    voice_dir = build_dir / "voice"

    # --- global clock ---
    # Scene HOSTS tile [0, total] contiguously (no blank flashes): the boundary
    # between scene k and k+1 falls mid-gap between their speech. Words/cues are
    # LOCAL to each scene: scene 1 shifts by LEAD (its speech starts after the
    # lead-in silence), every later scene by GAP/2 (speech starts half a breath
    # into its window). Audio = LEAD silence + segs + gaps + OUTRO silence.
    boundaries = [0.0]
    t = LEAD
    for i, seg in enumerate(segments, start=1):
        t += seg["duration"]
        t += (GAP / 2 if i < len(segments) else OUTRO)
        boundaries.append(round(t, 3))
        if i < len(segments):
            t += GAP / 2
    total = round(t, 3)

    scenes = []
    for i, seg in enumerate(segments, start=1):
        scenes.append({
            "index": i,
            "start": boundaries[i - 1],
            "duration": round(boundaries[i] - boundaries[i - 1], 3),
            "audio_offset": round(LEAD if i == 1 else GAP / 2, 3),
            "speech_dur": round(seg["duration"], 3),
        })

    # --- sample-accurate voice track ---
    wavs: list[Path] = []
    lead = voice_dir / "sil-lead.wav"
    _silence_wav(lead, LEAD)
    wavs.append(lead)
    for i, seg in enumerate(segments, start=1):
        wavs.append(voice_dir / f"seg-{i:02d}.wav")
        if i < len(segments):
            gap = voice_dir / f"sil-gap-{i:02d}.wav"
            _silence_wav(gap, GAP)
            wavs.append(gap)
    tail = voice_dir / "sil-tail.wav"
    _silence_wav(tail, OUTRO)
    wavs.append(tail)
    voice_wav = voice_dir / "voice.wav"
    _concat_wavs(wavs, voice_wav, voice_dir)
    voice_mp3 = voice_dir / "voice.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(voice_wav),
                    "-c:a", "libmp3lame", "-b:a", "160k", str(voice_mp3)],
                   check=True, capture_output=True)

    # --- scenes with local captions + mouth cues ---
    out_scenes = []
    for scene, seg, script_seg in zip(scenes, segments, script["segments"], strict=True):
        words = load_json(seg["words_path"])
        out_scenes.append({
            "id": f"scene-{scene['index']:02d}",
            "start": scene["start"],
            "duration": scene["duration"],
            "audio_offset": scene["audio_offset"],
            "speech_dur": scene["speech_dur"],
            "gesture": script_seg.get("gesture", "idle"),
            "highlight": script_seg.get("highlight", ""),
            "card": script_seg.get("card", {"kind": "plain"}),
            "text": seg["text"],
            "words": words,
            "phrases": group_phrases(words),
            "cues": seg["cues"],
        })

    timeline = {
        "fps": cfg.get("fps", 30),
        "width": cfg.get("width", 1080),
        "height": cfg.get("height", 1920),
        "total": total,
        "title": script["title"],
        "kicker": script["kicker"],
        "comment_keyword": script["comment_keyword"],
        "accent_color": script.get("accent_color", "#2f6bff"),
        "format": script.get("format", "single"),
        "topic_id": script["topic_id"],
        "voice_src": "assets/voice/voice.mp3",
        "scenes": out_scenes,
    }
    dump_json(build_dir / "timeline.json", timeline)
    print(f"[timeline] {len(out_scenes)} scenes, total {total:.1f}s -> timeline.json")
    return timeline


if __name__ == "__main__":
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    build(root / "build", [], {})
