"""Shot + sound plan for the reel composition.

Derived from the video-shotcraft methodology (six-phase pipeline, shot cards,
aesthetic rules) adapted to our HyperFrames reel system:

- S1 (sound): SFX vocabulary = whoosh / impact / pop / keystroke foley / ping +
  ding (clean synthesized UI tones) + chime. NO game-pack timbres, even though
  the channel is pixel art. Every sample is loudness-matched by
  pipeline/prep_sfx.py (raw Freesound previews spanned 15 dB — alternating
  samples pumped and the whoosh drowned under the voice).
- S2 (sound): a declarative cue table (t + file + volume + action comment), with
  double-sample alternation and volume staircases on rapid repeats so nothing
  reads as machine-gun repetition.
- S4 (sound): every cue is cut to its action length (data-duration on the clip).
- R1/R2/R3 (rhythm): holds after key info lands, accelerating stagger intervals,
  entrance-then-hold pacing baked into the timing constants the renderer uses.
- R4: full-frame slams stay <= 3 per video (we use zero; impacts are element-level).

The plan is pure derived data: given the timeline it emits every cue with absolute
times, so a timeline change re-pins all SFX automatically (S3). The card-beat and
comment-typing constants below are the SINGLE SOURCE OF TRUTH shared with
hf_project.py — the visuals import them, so sounds and motion cannot drift.
"""
from __future__ import annotations

# file, base volume. Files live in assets/sfx/: loudness-matched copies of the
# Freesound CC0 kit (*-n.mp3, see assets/sfx/FREESOUND-CREDITS.md +
# audio-manifest.json for provenance/hashes) plus locally synthesized UI tones
# (syn-*.mp3, prep_sfx.py). All samples sit at ~ -20 dBFS mean, so the role
# trims below are the actual in-mix levels (voice: mean -22 dB, max -4 dB).
SFX = {
    "whoosh":  ("fs-816261-n.mp3", 0.70),  # dry real-material whoosh — every scene cut
    "shimmer": ("fs-449645-n.mp3", 0.55),  # dreamy riser — retired from rotation, kept in the kit
    "pop":     ("fs-669918-n.mp3", 0.80),  # bubble pop — card entrance beat
    "pop2":    ("fs-878245-n.mp3", 0.80),  # bubble pop (alternate, loudness-matched)
    "key1":    ("fs-564507-n.mp3", 0.50),  # enter-key foley — typing (demo + comment box)
    "key2":    ("fs-561094-n.mp3", 0.50),  # laptop key (alternate — same loudness now)
    "impact":  ("fs-879272-n.mp3", 0.90),  # low dry thud — hook title + comment submit
    "sparkle": ("fs-879797-n.mp3", 0.70),  # chime run — sent flourish / demo progress
    "ping":    ("syn-ping.mp3",    0.75),  # clean UI ping — $0 pill, #N badge
    "ding":    ("syn-ding.mp3",    0.65),  # soft chime — star count-up lands
}

# max playback seconds per cue type (S4: cut to action length)
CUT = {"whoosh": 0.47, "shimmer": 1.30, "pop": 0.30, "pop2": 0.24,
       "key1": 0.20, "key2": 0.20, "impact": 0.53, "sparkle": 1.70,
       "ping": 0.32, "ding": 0.85}

# demo-card timing constants — SINGLE SOURCE OF TRUTH shared with hf_project.py
# so the visuals and the foley never drift apart (S3: timeline change = re-pin).
# Typing: uneven human cadence (R3), not a machine-gun metronome.
TYPING_OFFSETS = (0.00, 0.17, 0.33, 0.48, 0.66, 0.84)
TYPING_T0 = 0.25          # after card entrance, relative to card_start
PROG_DURATION = 2.40      # progress-bar fill seconds
PROG_START = 0.35         # relative to card_start
# timeline blocks: accelerating batch entrance (R2), then everything settles
BLOCK_OFFSETS = (0.90, 1.06, 1.19, 1.29, 1.36, 1.41)

# --- card beat constants (listicle/tool/price choreography) — shared S3 source ---
PRICE_STRIKE_T = 0.55     # strike draws over the monthly price
PRICE_ZERO_T = 1.00       # $0 pill pops            -> ping
TOOL_EXPL_T = 1.30        # desc wipe-in starts
TOOL_PING_T = 1.30        # #N badge ping (same beat as the wipe)
TOOL_STARS_END_T = 2.20   # star count-up lands     -> ding
REPO_EXPL_T = 0.85        # single-mode repo card: desc wipe + star count start
REPO_STARS_END_T = 1.75   #                         -> ding

# comment-box typing (CTA): placeholder out, keyword typed char by char with a
# blinking caret, then the send button presses (submit). Times computed here so
# the keystroke/submit cues and the on-screen letters are the same numbers.
CTA_TYPE_T0 = 0.70        # after card_start: first char lands
CTA_TYPE_STEP = 0.26      # per character (human cadence, R3)
CTA_SEND_GAP = 0.14       # last char -> send press
CTA_TAIL_KEEP = 0.85      # seconds of calm kept after the send press


def cta_plan(card_start: float, kw: str, dur: float) -> dict:
    """Char times + send time for the comment-box typing (shared S3 source)."""
    kw = kw or "REPO"
    n = max(len(kw), 1)
    t0 = card_start + CTA_TYPE_T0
    budget = max(dur - CTA_TAIL_KEEP - t0 - CTA_SEND_GAP, n * 0.16)
    step = min(CTA_TYPE_STEP, budget / n)
    chars = [t0 + i * step for i in range(n)]
    return {"chars": chars, "send": chars[-1] + CTA_SEND_GAP}


def _cues_for_scene(idx: int, sc: dict, total_scenes: int) -> list[dict]:
    """Cues inside one scene. Times are scene-relative; the caller shifts by start."""
    out: list[dict] = []
    card = sc.get("card") or {}
    kind = card.get("kind", "plain")
    is_first = idx == 1
    is_last = idx == total_scenes
    card_start = 0.0 if is_first else 0.20

    # card lands -> pop (alternating samples keep repeats organic, S2).
    # Demo scenes skip it: the keystrokes ARE the entrance sound there.
    if not is_first and kind != "demo":
        out.append({"t": card_start + 0.28, "sfx": "pop" if idx % 2 else "pop2",
                    "action": "card entrance"})

    # demo card: keystroke foley on each typed chunk (S4: typing gets keyboard),
    # chime when the progress bar completes
    if kind == "demo":
        for i, off in enumerate(TYPING_OFFSETS):
            out.append({"t": card_start + TYPING_T0 + off,
                        "sfx": "key1" if i % 2 == 0 else "key2",
                        "action": f"terminal typing chunk {i + 1}"})
        out.append({"t": card_start + PROG_START + PROG_DURATION, "sfx": "sparkle",
                    "action": "progress bar complete"})

    # price hook: $0 pill pop gets a clean UI ping
    if kind == "price":
        out.append({"t": card_start + PRICE_ZERO_T, "sfx": "ping",
                    "action": "$0 pill pops"})

    # tool card: badge ping when the #N pulses, chime when the star count lands
    if kind == "tool":
        out.append({"t": card_start + TOOL_PING_T, "sfx": "ping",
                    "action": "#N badge pings"})
        out.append({"t": card_start + TOOL_STARS_END_T, "sfx": "ding",
                    "action": "star count-up lands"})

    # single-mode repo card: chime when its star count lands
    if kind == "repo":
        out.append({"t": card_start + REPO_STARS_END_T, "sfx": "ding",
                    "action": "star count-up lands"})

    # hook: the title punch lands -> low impact (element-level, R4-safe)
    if is_first:
        out.append({"t": 0.42, "sfx": "impact", "action": "hook title punch"})

    # comment box: keystroke per typed character, then the submit sentence —
    # low impact ON the send press, chime on the sent flash. The typing IS the
    # finale lead-in now (suspense), so the old tail-anchored trio is gone here.
    if kind == "comment":
        plan = cta_plan(card_start, str(card.get("keyword") or ""), sc["duration"])
        for i, tc in enumerate(plan["chars"]):
            out.append({"t": tc, "sfx": "key1" if i % 2 == 0 else "key2",
                        "action": f"comment typing char {i + 1}"})
        out.append({"t": plan["send"], "sfx": "impact",
                    "action": "comment send submit"})
        out.append({"t": plan["send"] + 0.12, "sfx": "sparkle",
                    "action": "sent flourish"})
    elif is_last:
        # non-comment finale fallback: riser->impact->sparkle at the tail (S1)
        dur = sc["duration"]
        out.append({"t": dur - 1.55, "sfx": "shimmer", "action": "finale lead-in"})
        out.append({"t": dur - 0.50, "sfx": "impact", "action": "final CTA hit"})
        out.append({"t": dur - 0.44, "sfx": "sparkle", "action": "final flourish"})

    return out


def plan_shots(tl_data: dict) -> list[dict]:
    """Absolute-time SFX cue table for the whole video, sorted, comments attached."""
    scenes = tl_data["scenes"]
    cues: list[dict] = []
    for idx, sc in enumerate(scenes, start=1):
        start = sc["start"]
        # scene transition whoosh (skip scene 1: it opens on frame 0, no cut-in).
        # One consistent transition sound — the old whoosh/shimmer alternation
        # read as "silent cut, dreamy whoosh, silent cut, ..." (sloppy).
        if idx > 1:
            cues.append({"t": round(start, 3),
                         "sfx": "whoosh",
                         "action": f"scene {idx} transition"})
        for c in _cues_for_scene(idx, sc, len(scenes)):
            cues.append({"t": round(start + c["t"], 3), "sfx": c["sfx"],
                         "action": f"s{idx}: {c['action']}"})
    cues.sort(key=lambda c: c["t"])
    for c in cues:
        f, v = SFX[c["sfx"]]
        c["file"] = f"assets/sfx/{f}"
        c["vol"] = v
        c["cut"] = CUT[c["sfx"]]
        c.pop("sfx")
    return cues
