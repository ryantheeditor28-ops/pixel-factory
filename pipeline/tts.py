"""Stage 2 — free TTS with word-level timestamps (edge-tts, Microsoft neural voices).

No key, no cost, runs anywhere including GitHub Actions runners. Each script
segment is synthesized separately so we get:
  build/voice/seg-01.mp3      the audio for that segment
  build/voice/seg-01.words.json  [{t0,t1,text}, ...] word timings (seconds)

Word timings are what makes the captions pop word-by-word and the beats land
word-anchored, exactly like the template channel.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import edge_tts

from llm import dump_json


def _mp3_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


async def _synth_segment(text: str, voice: str, rate: str, mp3: Path, words_path: Path,
                         pitch: str = "+0Hz") -> None:
    words: list[dict] = []
    # boundary="WordBoundary" is REQUIRED: edge-tts 7.x defaults to
    # SentenceBoundary, which yields no per-word events at all.
    # The free endpoint occasionally refuses datacenter IPs (NoAudioReceived /
    # connection resets) — retry with backoff so one transient 403 doesn't kill
    # an unattended CI run.
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            words = []
            # pitch below neutral reads as confident/authoritative delivery
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch,
                                        boundary="WordBoundary")
            with open(mp3, "wb") as f:
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        txt = (chunk.get("text") or "").strip()
                        if txt:
                            words.append({
                                "t0": round(chunk["offset"] / 1e7, 3),
                                "t1": round((chunk["offset"] + chunk["duration"]) / 1e7, 3),
                                "text": txt,
                            })
            if mp3.exists() and mp3.stat().st_size > 1000:
                break
            raise RuntimeError(f"empty audio from edge-tts (attempt {attempt + 1})")
        except Exception as e:  # noqa: BLE001 - retry any transport-level failure
            last_err = e
            mp3.unlink(missing_ok=True)
            await asyncio.sleep(2.0 * (attempt + 1))
    else:
        raise RuntimeError(f"TTS failed after 4 attempts: {last_err}")
    if not words:  # paranoid fallback: one phrase covering the real duration
        dur = _mp3_duration(mp3) or 2.0
        words = [{"t0": 0.0, "t1": round(dur, 3), "text": text[:48]}]
    dump_json(words_path, words)


def synth_segments(script: dict, cfg: dict, voice_dir: Path) -> list[dict]:
    """Returns per-segment [{mp3, words_path, text}] in script order."""
    voice_dir.mkdir(parents=True, exist_ok=True)
    voice = cfg["voice"]
    rate = cfg.get("rate", "+8%")
    pitch = cfg.get("pitch", "+0Hz")
    segs = []

    async def run():
        jobs = []
        for i, seg in enumerate(script["segments"], start=1):
            mp3 = voice_dir / f"seg-{i:02d}.mp3"
            words_path = voice_dir / f"seg-{i:02d}.words.json"
            jobs.append(_synth_segment(seg["text"], voice, rate, mp3, words_path, pitch))
            segs.append({"mp3": mp3, "words_path": words_path, "text": seg["text"]})
        await asyncio.gather(*jobs)

    asyncio.run(run())
    for s in segs:
        assert s["mp3"].exists() and s["mp3"].stat().st_size > 1000, f"TTS failed for {s['mp3']}"
    print(f"[tts] {len(segs)} segments synthesized with {voice} ({rate}, {pitch})")
    return segs
