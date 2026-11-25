"""The one-and-only sketch guy (v2 — hand-drawn style, code-drawn).

Drawn entirely in code (no AI credits, no licensed assets) so he is free forever,
identical in every video, and fully automatable. Style-matched to the family-2
sketch reference (hand-drawn look, big head, gesture vocabulary: point-up, shrug,
wave, hand-on-chest, thinking, arms-spread) with a CHANGED appearance: no cap
(the ref's signature — deliberately avoided), messy dark hair instead, and our
brand-blue hoodie. Kid-safe: open hands everywhere, soft round features.

Produces:
  assets/character/<pose>.png   transparent sprites (idle, point, chest, thumbs,
                                shrug, wave, think, spread)
  assets/character/character.json   manifest: canvas size, mouth anchor (for
                                rhubarb lip sync), pose list
  assets/character/sheet.png    contact sheet for quick visual inspection

The mouth is NOT baked in: the renderer overlays an animated mouth at the
manifest anchor, driven by rhubarb-lip-sync phoneme cues (A-H + X).
"""
from __future__ import annotations

import json
import math
import random
import zlib
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 640, 720  # same 32:36 aspect as the layout container (498x560)
OUT = Path(__file__).resolve().parent.parent / "assets" / "character"

# sketch palette — warm charcoal ink, no pure black
INK = (58, 46, 42, 255)
SKIN = (248, 216, 186, 255)
SKIN_SH = (233, 193, 158, 255)
HAIR = (70, 48, 38, 255)
HAIR_HI = (96, 70, 55, 255)
HOODIE = (47, 107, 255, 255)      # brand blue
HOODIE_SH = (36, 84, 205, 255)
STRING = (250, 248, 242, 255)
JEANS = (52, 58, 76, 255)
SHOE = (242, 239, 232, 255)
SOLE = (205, 200, 190, 255)
BLUSH = (243, 182, 166, 255)


def _mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


HATCH_HOODIE = _mix(INK, HOODIE, 0.30)
HATCH_JEANS = _mix(INK, JEANS, 0.30)

RNG = random.Random(0)


def _reseed(name: str) -> None:
    """Deterministic wobble per pose — the sheet matches the saved sprites."""
    RNG.seed(zlib.crc32(name.encode()) ^ 0xA11CE)


def _j(p, amt=2.5):
    return (p[0] + RNG.uniform(-amt, amt), p[1] + RNG.uniform(-amt, amt))


def _sketch_poly(d, pts, fill, outline=INK, width=6, amt=2.5):
    jp = [_j(p, amt) for p in pts]
    if fill is not None:
        d.polygon(jp, fill=fill)
    d.line(jp + [jp[0]], fill=outline, width=width, joint="curve")


def _sketch_ellipse(d, cx, cy, rx, ry, fill, outline=INK, width=6, amt=2.5, n=48):
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.append((cx + math.cos(a) * (rx + RNG.uniform(-amt, amt)),
                    cy + math.sin(a) * (ry + RNG.uniform(-amt, amt))))
    if fill is not None:
        d.polygon(pts, fill=fill)
    d.line(pts + [pts[0]], fill=outline, width=width, joint="curve")


def _limb(d, p0, p1, w0, w1, fill):
    """Tapered sleeve with hand-drawn wobble + ink outline."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    ln = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / ln, dx / ln
    pts = [(p0[0] + nx * w0, p0[1] + ny * w0), (p1[0] + nx * w1, p1[1] + ny * w1),
           (p1[0] - nx * w1, p1[1] - ny * w1), (p0[0] - nx * w0, p0[1] - ny * w0)]
    _sketch_poly(d, pts, fill, width=5, amt=2.0)
    # cuff line at the wrist
    cx, cy = (p1[0] + nx * w1 * 0.7, p1[1] + ny * w1 * 0.7)
    d.line([_j((cx - nx * 12, cy - ny * 12), 1.5), _j((cx + nx * 12, cy + ny * 12), 1.5)],
           fill=INK, width=4)


def _hand(d, cx, cy, r=26, spread=False, fingers=True):
    """Skin hand with ink outline; optionally an open hand with spread fingers
    (kid-safe: never a lone raised finger)."""
    if fingers and spread:
        for ang in (-64, -32, 0, 26):
            a = math.radians(ang - 90)
            x0, y0 = cx + math.cos(a) * r * 0.55, cy + math.sin(a) * r * 0.55
            x1, y1 = cx + math.cos(a) * (r + 20), cy + math.sin(a) * (r + 20)
            d.line([(x0, y0), (x1, y1)], fill=INK, width=15)
            d.line([(x0, y0), (x1, y1)], fill=SKIN, width=9)
    _sketch_ellipse(d, cx, cy, r, r * 0.92, SKIN, width=5, amt=1.5, n=28)


def _hatch(d, x, y, n, ang_deg, ln=26, color=INK, width=3, gap=9):
    a = math.radians(ang_deg)
    for i in range(n):
        ox, oy = x + math.cos(a + math.pi / 2) * gap * i, y + math.sin(a + math.pi / 2) * gap * i
        d.line([(ox, oy), (ox + math.cos(a) * ln, oy + math.sin(a) * ln)],
               fill=color, width=width)


# ---------- body parts (shared by every pose) ----------

def _shadow(img):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ov).ellipse([180, 668, 460, 706], fill=(40, 34, 30, 46))
    img.alpha_composite(ov)


def _legs(d):
    for x0, x1 in ((252, 302), (338, 388)):
        _sketch_poly(d, [(x0, 545), (x1, 545), (x1 - 4, 655), (x0 + 4, 655)],
                     JEANS, width=5, amt=2.0)
    _hatch(d, 262, 560, 3, -55, color=HATCH_JEANS)
    _hatch(d, 348, 560, 3, -55, color=HATCH_JEANS)
    for x0, x1 in ((238, 312), (328, 402)):
        _sketch_poly(d, [(x0, 652), (x1, 652), (x1 - 6, 696), (x0 + 6, 696)],
                     SHOE, width=5, amt=1.5)
        d.line([_j((x0 + 8, 684), 1.5), _j((x1 - 8, 684), 1.5)], fill=SOLE, width=5)


def _torso(d):
    _sketch_poly(d, [(218, 360), (422, 360), (444, 552), (196, 552)],
                 HOODIE, width=6, amt=2.5)
    # kangaroo pocket + drawstrings + hatching
    _sketch_poly(d, [(272, 470), (368, 470), (382, 545), (258, 545)],
                 HOODIE_SH, width=4, amt=2.0)
    for x0, x1 in (((300, 382), (292, 420)), ((340, 382), (348, 420))):
        d.line([_j(x0, 1.5), _j(x1, 1.5)], fill=STRING, width=5)
        d.ellipse([x1[0] - 5, x1[1] - 3, x1[0] + 5, x1[1] + 7], fill=STRING)
    _hatch(d, 214, 420, 4, -50, color=HATCH_HOODIE)


def _collar(d):
    _sketch_ellipse(d, 320, 350, 54, 30, HOODIE_SH, width=5, amt=2.0)


def _head(d):
    # ears first (peek out), then head, hair, face
    _sketch_ellipse(d, 173, 218, 20, 26, SKIN, width=5, amt=1.5, n=30)
    _sketch_ellipse(d, 467, 218, 20, 26, SKIN, width=5, amt=1.5, n=30)
    _sketch_ellipse(d, 320, 208, 148, 132, SKIN, width=6, amt=2.5)
    # messy hair (no cap — deliberately different from the ref's orange cap)
    for cx, cy, rx, ry in ((320, 118, 132, 62), (225, 150, 55, 42), (415, 150, 55, 42),
                           (320, 162, 95, 40), (180, 205, 26, 38), (460, 205, 26, 38)):
        _sketch_ellipse(d, cx, cy, rx, ry, HAIR, width=5, amt=3.0, n=36)
    _hatch(d, 250, 96, 3, -35, color=HAIR_HI, width=4)
    # stray strands
    for x0, y0, x1, y1 in ((262, 66, 244, 26), (320, 52, 318, 12), (376, 66, 394, 28)):
        d.line([_j((x0, y0), 2), _j((x1, y1), 2)], fill=INK, width=4)
    # face
    d.line([_j((240, 182), 1.5), _j((288, 176), 1.5)], fill=INK, width=7)
    d.line([_j((352, 176), 1.5), _j((400, 182), 1.5)], fill=INK, width=7)
    for ex in (264, 376):
        d.ellipse([ex - 15, 196, ex + 15, 236], fill=INK)
        d.ellipse([ex - 6, 202, ex + 4, 212], fill=(255, 255, 255, 255))
    d.line([_j((310, 256), 1.5), _j((320, 266), 1.5), _j((330, 256), 1.5)],
           fill=INK, width=4, joint="curve")
    for bx in (232, 408):
        _sketch_ellipse(d, bx, 258, 22, 12, BLUSH, outline=None, width=0, amt=2.0, n=24)


# ---------- poses (arm choreography only; body/head shared) ----------

def _render(name, arms, hands, extras=None):
    _reseed(name)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _shadow(img)
    d = ImageDraw.Draw(img)
    _legs(d)
    _torso(d)
    _collar(d)
    arms(d)
    _head(d)
    for h in hands:
        h(d)
    if extras:
        extras(d)
    return img


def _arms_idle(d):
    _limb(d, (240, 375), (226, 492), 17, 13, HOODIE)
    _limb(d, (400, 375), (414, 492), 17, 13, HOODIE)


def pose_idle():
    return _render("idle", _arms_idle,
                   [lambda d: _hand(d, 224, 512), lambda d: _hand(d, 416, 512)])


def pose_point():
    def arms(d):
        _limb(d, (240, 375), (226, 492), 17, 13, HOODIE)
        _limb(d, (400, 375), (468, 190), 17, 12, HOODIE)

    def hand(d):
        _hand(d, 478, 156, r=27, spread=True, fingers=True)
        _sketch_ellipse(d, 452, 172, 9, 7, SKIN, width=4, amt=1.0, n=20)  # thumb nub

    return _render("point", arms, [hand])


def pose_shrug():
    def arms(d):
        for sx, ex in ((240, 148), (400, 492)):
            _limb(d, (sx, 380), (ex, 336), 16, 12, HOODIE)
        _sketch_ellipse(d, 252, 354, 22, 12, HOODIE, width=4, amt=1.5, n=22)
        _sketch_ellipse(d, 388, 354, 22, 12, HOODIE, width=4, amt=1.5, n=22)

    def hands(d):
        _sketch_ellipse(d, 130, 320, 26, 19, SKIN, width=5, amt=1.5, n=28)
        _sketch_ellipse(d, 510, 320, 26, 19, SKIN, width=5, amt=1.5, n=28)

    return _render("shrug", arms, [hands])


def pose_wave():
    def arms(d):
        _limb(d, (240, 375), (226, 492), 17, 13, HOODIE)
        _limb(d, (400, 375), (458, 205), 17, 12, HOODIE)

    def hand(d):
        _hand(d, 470, 172, r=27, spread=True, fingers=True)

    def extras(d):
        for i, (x, y) in enumerate(((416, 148), (402, 184))):
            d.arc([x, y, x + 26, y + 30], start=300 - i * 20, end=360 - i * 20,
                  fill=INK, width=3)

    return _render("wave", arms, [hand], extras)


def pose_think():
    def arms(d):
        _limb(d, (240, 375), (226, 492), 17, 13, HOODIE)
        _limb(d, (400, 375), (392, 318), 16, 11, HOODIE)

    def hand(d):
        # hand at the CHEEK (hmm-pose) — clear of the mouth overlay box
        _sketch_ellipse(d, 396, 292, 22, 19, SKIN, width=5, amt=1.5, n=28)
        d.line([_j((392, 280), 1.0), _j((380, 262), 1.0)], fill=INK, width=13)
        d.line([_j((392, 280), 1.0), _j((380, 262), 1.0)], fill=SKIN, width=8)

    return _render("think", arms, [hand])


def pose_chest():
    def arms(d):
        _limb(d, (240, 375), (226, 492), 17, 13, HOODIE)
        _limb(d, (400, 375), (348, 424), 16, 12, HOODIE)

    def hand(d):
        _sketch_ellipse(d, 334, 434, 27, 19, SKIN, width=5, amt=1.5, n=28)

    return _render("chest", arms, [hand])


def pose_thumbs():
    def arms(d):
        _limb(d, (240, 375), (226, 492), 17, 13, HOODIE)
        _limb(d, (400, 380), (418, 288), 17, 13, HOODIE)

    def hand(d):
        _sketch_ellipse(d, 422, 264, 24, 21, SKIN, width=5, amt=1.5, n=28)
        # thumb up: sketched stub (ink edge + skin fill), no cuff line
        d.line([_j((424, 252), 1.0), _j((428, 216), 1.0)], fill=INK, width=15)
        d.line([_j((424, 252), 1.0), _j((428, 216), 1.0)], fill=SKIN, width=9)

    return _render("thumbs", arms, [hand])


def pose_spread():
    def arms(d):
        _limb(d, (240, 378), (122, 352), 17, 12, HOODIE)
        _limb(d, (400, 378), (518, 352), 17, 12, HOODIE)

    def hands(d):
        _hand(d, 104, 346, r=24)
        _hand(d, 536, 346, r=24)

    return _render("spread", arms, [hands])


POSES = {
    "idle": pose_idle,
    "point": pose_point,
    "chest": pose_chest,
    "thumbs": pose_thumbs,
    "think": pose_think,
    "shrug": pose_shrug,
    "spread": pose_spread,
    "wave": pose_wave,
}

MOUTH = {"x": 281, "y": 277, "w": 78, "h": 46}  # canvas px, top-left origin

# ---------- mouth shapes: one PNG per rhubarb sound, exactly like the template ----------
MOUTH_COLORS = {
    "outline": INK,
    "inside": (67, 38, 26, 255),
    "deep": (40, 20, 13, 255),
    "teeth": (250, 248, 240, 255),
    "tongue": (201, 92, 82, 255),
}
MOUTH_ORDER = ("A", "B", "C", "D", "E", "F", "G", "H", "X")


def mouth_image(shape: str, w: int, h: int) -> Image.Image:
    """One mouth per rhubarb shape, drawn to the manifest mouth box."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    O = MOUTH_COLORS["outline"]; IN = MOUTH_COLORS["inside"]
    DP = MOUTH_COLORS["deep"]; TE = MOUTH_COLORS["teeth"]; TO = MOUTH_COLORS["tongue"]

    def box(a, b, c, e):  # fractional box -> pixel coords
        return (int(a * w), int(b * h), int(c * w) - 1, int(e * h) - 1)

    if shape == "X":    # silence: soft closed line
        d.rounded_rectangle(box(0.16, 0.42, 0.84, 0.58), radius=max(h // 7, 2), fill=O)
    elif shape == "A":  # big open (AH)
        d.ellipse(box(0.02, 0.00, 0.98, 1.00), fill=IN, outline=O, width=3)
        d.ellipse(box(0.30, 0.08, 0.70, 0.26), fill=DP)
        d.ellipse(box(0.26, 0.60, 0.74, 0.96), fill=TO)
    elif shape == "B":  # mid open (EH)
        d.ellipse(box(0.08, 0.10, 0.92, 0.90), fill=IN, outline=O, width=3)
        d.ellipse(box(0.34, 0.62, 0.66, 0.88), fill=TO)
    elif shape == "C":  # slightly open, wide (consonants)
        d.rounded_rectangle(box(0.04, 0.34, 0.96, 0.70), radius=max(h // 4, 2),
                            fill=IN, outline=O, width=2)
    elif shape == "D":  # jaw drop (OH)
        d.rounded_rectangle(box(0.04, 0.00, 0.96, 1.00), radius=max(h // 3, 3),
                            fill=IN, outline=O, width=3)
        d.ellipse(box(0.30, 0.64, 0.70, 0.96), fill=TO)
    elif shape == "E":  # top teeth showing
        d.rounded_rectangle(box(0.04, 0.26, 0.96, 0.76), radius=max(h // 5, 2),
                            fill=IN, outline=O, width=3)
        d.rectangle(box(0.09, 0.29, 0.91, 0.45), fill=TE)
    elif shape == "F":  # pucker (OO/W)
        d.ellipse(box(0.24, 0.04, 0.76, 0.96), fill=IN, outline=O, width=3)
        d.ellipse(box(0.38, 0.28, 0.62, 0.72), fill=DP)
    elif shape == "G":  # teeth pressed (F/V)
        d.rounded_rectangle(box(0.06, 0.30, 0.94, 0.72), radius=max(h // 6, 2),
                            fill=TE, outline=O, width=3)
        d.rectangle(box(0.10, 0.47, 0.90, 0.56), fill=O)
    else:               # H: relaxed half open with tongue
        d.ellipse(box(0.06, 0.12, 0.94, 0.88), fill=IN, outline=O, width=3)
        d.ellipse(box(0.22, 0.52, 0.78, 0.86), fill=TO)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "grid": {"w": W, "h": H},
        "sprite": {"w": W, "h": H},
        "mouth": MOUTH,
        "poses": {},
        "style": "sketch-v2 (code-drawn, deterministic wobble; family-2 style-match)",
        "note": "One sketch guy, drawn in code. Reused in every video. Mouth overlaid at render time.",
    }
    for name, fn in POSES.items():
        img = fn()
        img.save(OUT / f"{name}.png")
        manifest["poses"][name] = f"{name}.png"

    # --- mouth sprites (one per rhubarb sound; the renderer swaps these) ---
    mw_px, mh_px = MOUTH["w"], MOUTH["h"]
    manifest["mouth_shapes"] = {}
    for s in MOUTH_ORDER:
        mouth_image(s, mw_px, mh_px).save(OUT / f"mouth-{s}.png")
        manifest["mouth_shapes"][s] = f"mouth-{s}.png"

    # contact sheet for inspection (checker background) with a mouth strip below
    pad = 10
    thumb_h = 240
    thumb_w = int(W * thumb_h / H)
    mouth_zoom = 2
    w = (thumb_w + pad) * len(POSES) + pad
    h = thumb_h + mh_px * mouth_zoom + 3 * pad
    sheet = Image.new("RGB", (w, h), (246, 247, 250))
    d = ImageDraw.Draw(sheet)
    for y in range(0, h, 16):
        for x in range(0, w, 16):
            if (x // 16 + y // 16) % 2 == 0:
                d.rectangle([x, y, x + 15, y + 15], fill=(232, 235, 240))
    for i, name in enumerate(POSES):
        spr = POSES[name]().resize((thumb_w, thumb_h), Image.LANCZOS)
        sheet.paste(spr, (pad + i * (thumb_w + pad), pad), spr)
    for i, s in enumerate(MOUTH_ORDER):
        m = mouth_image(s, mw_px, mh_px).resize(
            (mw_px * mouth_zoom, mh_px * mouth_zoom), Image.LANCZOS)
        sheet.paste(m, (pad + i * (mw_px * mouth_zoom + pad), thumb_h + 2 * pad), m)
    sheet.save(OUT / "sheet.png")

    (OUT / "character.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"character -> {OUT}")
    for p in sorted(OUT.glob("*.png")):
        print(f"   {p.name} {p.stat().st_size} bytes")


if __name__ == "__main__":
    main()
