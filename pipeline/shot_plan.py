"""Shot + sound plan for the reel composition.

Derived from the video-shotcraft methodology (six-phase pipeline, shot cards,
aesthetic rules) adapted to our HyperFrames reel system:

- S1 (sound): SFX vocabulary = whoosh / impact / riser-shimmer / sparkle + real
  foley (keystrokes). NO game-pack timbres, even though the channel is pixel art.
- S2 (sound): a declarative cue table (t + file + volume + action comment), with
  double-sample alternation and volume staircases on rapid repeats so nothing
  reads as machine-gun repetition.
- S4 (sound): every cue is cut to its action length (data-duration on the clip).
- R1/R2/R3 (rhythm): holds after key info lands, accelerating stagger intervals,
  entrance-then-hold pacing baked into the timing constants the renderer uses.
- R4: full-frame slams stay <= 3 per video (we use zero; impacts are element-level).

The plan is pure derived data: given the timeline it emits every cue with absolute
times, so a timeline change re-pins all SFX automatically (S3).
"""
from __future__ import annotations

# file, base volume. Files live in assets/sfx/ (Freesound CC0 previews, see
# assets/sfx/FREESOUND-CREDITS.md + audio-manifest.json for provenance/hashes).
SFX = {
    "whoosh":  ("fs-816261.mp3", 0.30),  # broomstick whoosh — dry, real material
    "shimmer": ("fs-449645.mp3", 0.32),  # rising shimmer — transition/lead-in
    "pop":     ("fs-669918.mp3", 0.45),  # bubble pop (main card/caption beat)
    "pop2":    ("fs-878245.mp3", 0.38),  # bubble pop (alternate for S2 alternation)
    "key1":    ("fs-564507.mp3", 0.26),  # enter-key keystroke (terminal foley)
    "key2":    ("fs-561094.mp3", 0.22),  # laptop key (alternating foley)
    "impact":  ("fs-879272.mp3", 0.55),  # low dry thud — hook title + final CTA
    "sparkle": ("fs-879797.mp3", 0.42),  # chime run — "built" moment + finale
}

# max playback seconds per cue type (S4: cut to action length)
CUT = {"whoosh": 0.47, "shimmer": 1.30, "pop": 0.30, "pop2": 0.24,
       "key1": 0.20, "key2": 0.20, "impact": 0.53, "sparkle": 1.70}

# demo-card timing constants — SINGLE SOURCE OF TRUTH shared with hf_project.py
# so the visuals and the foley never drift apart (S3: timeline change = re-pin).
# Typing: uneven human cadence (R3), not a machine-gun metronome.
TYPING_OFFSETS = (0.00, 0.17, 0.33, 0.48, 0.66, 0.84)
TYPING_T0 = 0.25          # after card entrance, relative to card_start
PROG_DURATION = 2.40      # progress-bar fill seconds
PROG_START = 0.35         # relative to card_start
# timeline blocks: accelerating batch entrance (R2), then everything settles
BLOCK_OFFSETS = (0.90, 1.06, 1.19, 1.29, 1.36, 1.41)


def _cues_for_scene(idx: int, sc: dict, total_scenes: int, n_cues: int) -> list[dict]:
    """Cues inside one scene. Times are scene-relative; the caller shifts by start."""
    out: list[dict] = []
    kind = (sc.get("card") or {}).get("kind", "plain")
    is_first = idx == 1
    is_last = idx == total_scenes
    card_start = 0.0 if is_first else 0.20

    # card lands -> pop (alternating samples keep repeats organic, S2).
    # Demo scenes skip it: the keystrokes ARE the entrance sound there.
    if not is_first and kind != "demo":
        out.append({"t": card_start + 0.28, "sfx": "pop" if idx % 2 else "pop2",
                    "action": "card entrance"})

    # demo card: keystroke foley on each typed chunk (S4: typing gets keyboard),
    # sparkle when the progress bar completes
    if kind == "demo":
        for i, off in enumerate(TYPING_OFFSETS):
            out.append({"t": card_start + TYPING_T0 + off,
                        "sfx": "key1" if i % 2 == 0 else "key2",
                        "action": f"terminal typing chunk {i + 1}"})
        out.append({"t": card_start + PROG_START + PROG_DURATION, "sfx": "sparkle",
                    "action": "progress bar complete"})

    # hook: the title punch lands -> low impact (element-level, R4-safe)
    if is_first:
        out.append({"t": 0.42, "sfx": "impact", "action": "hook title punch"})

    # finale: riser->impact->sparkle sentence at the tail of the last scene (S1)
    if is_last:
        dur = sc["duration"]
        out.append({"t": dur - 1.55, "sfx": "shimmer", "action": "finale lead-in"})
        out.append({"t": dur - 0.50, "sfx": "impact", "action": "final CTA hit"})
        out.append({"t": dur - 0.44, "sfx": "sparkle", "action": "final flourish"})

    return out


def plan_shots(tl_data: dict) -> list[dict]:
    """Absolute-time SFX cue table for the whole video, sorted, comments attached."""
    scenes = tl_data["scenes"]
    cues: list[dict] = []
    n = 0
    for idx, sc in enumerate(scenes, start=1):
        start = sc["start"]
        # scene transition whoosh (skip scene 1: it opens on frame 0, no cut-in)
        if idx > 1:
            cues.append({"t": round(start, 3),
                         "sfx": "whoosh" if idx % 2 == 0 else "shimmer",
                         "action": f"scene {idx} transition"})
        for c in _cues_for_scene(idx, sc, len(scenes), n):
            cues.append({"t": round(start + c["t"], 3), "sfx": c["sfx"],
                         "action": f"s{idx}: {c['action']}"})
        n += 1
    cues.sort(key=lambda c: c["t"])
    for c in cues:
        f, v = SFX[c["sfx"]]
        c["file"] = f"assets/sfx/{f}"
        c["vol"] = v
        c["cut"] = CUT[c["sfx"]]
        c.pop("sfx")
    return cues
