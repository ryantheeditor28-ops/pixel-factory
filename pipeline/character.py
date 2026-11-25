"""The one-and-only pixel guy.

Drawn entirely in code (no AI credits, no licensed assets) so he is free forever,
identical in every video, and fully automatable. Produces:

  assets/character/<pose>.png   transparent sprites (idle, point, thumbs, shrug, wave, think)
  assets/character/character.json   manifest: grid size, mouth anchor (for rhubarb lip sync), poses
  assets/character/sheet.png    contact sheet for quick visual inspection

The mouth is NOT baked in: the renderer overlays an animated pixel mouth at the
manifest anchor, driven by rhubarb-lip-sync phoneme cues (A-H + X).
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

GRID_W, GRID_H = 32, 36
SCALE = 20  # px per grid cell -> 640x720 sprite

OUT = Path(__file__).resolve().parent.parent / "assets" / "character"

PAL = {
    "o": (36, 31, 28, 255),     # outline
    "s": (240, 185, 141, 255),  # skin
    "S": (217, 154, 108, 255),  # skin shade
    "h": (51, 37, 31, 255),     # hair
    "H": (74, 56, 46, 255),     # hair highlight
    "t": (31, 168, 155, 255),   # hoodie teal
    "T": (23, 138, 128, 255),   # hoodie shade
    "d": (245, 242, 234, 255),  # drawstring
    "j": (61, 79, 119, 255),    # jeans
    "J": (46, 59, 92, 255),     # jeans shade
    "w": (236, 233, 226, 255),  # shoe
    "W": (201, 196, 184, 255),  # sole
    "e": (36, 31, 28, 255),     # eye
    "g": (255, 255, 255, 255),  # eye glint
}


def new_grid() -> list[list[str]]:
    return [["."] * GRID_W for _ in range(GRID_H)]


def rect(g, r0, r1, c0, c1, ch):
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            if 0 <= r < GRID_H and 0 <= c < GRID_W:
                g[r][c] = ch


def px(g, r, c, ch):
    g[r][c] = ch


def hline(g, r, c0, c1, ch):
    rect(g, r, r, c0, c1, ch)


def base() -> list[list[str]]:
    g = new_grid()
    # --- hair (rounded top, tuft, messy fringe dips) ---
    rect(g, 2, 9, 9, 23, "h")
    hline(g, 1, 11, 20, "h")          # rounded crown
    px(g, 0, 14, "h"); px(g, 0, 15, "h")  # tuft
    for c in range(9, 24):
        if c % 3 != 1:
            px(g, 10, c, "h")
    px(g, 3, 12, "H"); px(g, 4, 19, "H"); px(g, 6, 10, "H"); px(g, 7, 21, "H")
    # --- face ---
    rect(g, 10, 16, 10, 22, "s")
    # ears
    rect(g, 11, 13, 8, 9, "s"); rect(g, 11, 13, 22, 23, "s")
    px(g, 12, 8, "S"); px(g, 12, 23, "S")
    # brows + eyes (2x2 each, glint top-right)
    rect(g, 11, 11, 12, 14, "h"); rect(g, 11, 11, 17, 19, "h")
    rect(g, 12, 13, 12, 13, "e"); rect(g, 12, 13, 18, 19, "e")
    px(g, 12, 13, "g"); px(g, 12, 19, "g")
    # nose + closed-mouth fallback line (the renderer's mouth overlays here)
    px(g, 14, 16, "S")
    rect(g, 15, 15, 15, 16, "S")
    # --- hood bunch behind neck ---
    rect(g, 16, 17, 11, 21, "T")
    # --- torso (teal hoodie) ---
    rect(g, 16, 25, 10, 21, "t")
    rect(g, 16, 17, 9, 9, "t"); rect(g, 16, 17, 22, 22, "t")  # shoulder caps
    # kangaroo pocket
    rect(g, 22, 24, 12, 19, "T")
    hline(g, 22, 12, 19, "o")
    # drawstrings
    px(g, 18, 13, "d"); px(g, 19, 13, "d"); px(g, 18, 18, "d"); px(g, 19, 18, "d")
    # --- waist + legs ---
    rect(g, 26, 26, 10, 21, "j")
    rect(g, 27, 30, 10, 14, "j"); rect(g, 27, 30, 17, 21, "j")
    hline(g, 27, 10, 21, "J")
    for r in range(27, 31):
        px(g, r, 14, "J"); px(g, r, 17, "J")
    # --- shoes ---
    rect(g, 31, 32, 9, 15, "w"); rect(g, 31, 32, 17, 23, "w")
    hline(g, 33, 9, 15, "W"); hline(g, 33, 17, 23, "W")
    return g


# ---------- arms (overlays) ----------
def arm_left_idle(g):
    rect(g, 16, 22, 8, 9, "t"); rect(g, 23, 24, 8, 9, "s")


def arm_right_idle(g):
    rect(g, 16, 22, 22, 23, "t"); rect(g, 23, 24, 22, 23, "s")


def pose_idle():
    g = base(); arm_left_idle(g); arm_right_idle(g); return g


def pose_point():
    g = base(); arm_left_idle(g)
    rect(g, 16, 17, 22, 24, "t")   # shoulder connect
    sleeve = [(15, 24), (15, 25), (14, 25), (14, 26), (13, 26), (13, 27),
              (12, 27), (12, 28), (11, 28), (10, 28), (10, 29)]
    for r, c in sleeve:
        px(g, r, c, "t")
    rect(g, 8, 10, 27, 29, "s")   # fist (3x3)
    rect(g, 5, 7, 28, 28, "s")    # index finger (1 wide, centered)
    px(g, 9, 28, "S")             # knuckle shade
    return g


def pose_thumbs():
    g = base(); arm_left_idle(g)
    rect(g, 17, 18, 22, 24, "t")   # upper arm out (horizontal)
    rect(g, 16, 19, 24, 25, "t")   # forearm vertical up
    rect(g, 14, 16, 23, 25, "s")   # fist at shoulder height (3x3)
    rect(g, 11, 13, 24, 24, "s")   # thumb up above fist
    px(g, 15, 24, "S")             # knuckle shade
    return g


def pose_shrug():
    g = base()
    for r, c in [(16, 8), (16, 9), (17, 7), (17, 8), (18, 6), (18, 7)]:
        px(g, r, c, "t")
    rect(g, 17, 18, 4, 6, "s")     # left palm up
    for r, c in [(16, 22), (16, 23), (17, 23), (17, 24), (18, 24), (18, 25)]:
        px(g, r, c, "t")
    rect(g, 17, 18, 25, 27, "s")   # right palm up
    return g


def pose_wave():
    g = base(); arm_left_idle(g)
    sleeve = [(16, 23), (16, 24), (15, 24), (15, 25), (14, 25), (14, 26),
              (13, 26), (13, 27), (12, 27), (12, 28), (11, 28)]
    for r, c in sleeve:
        px(g, r, c, "t")
    rect(g, 6, 9, 26, 28, "s")     # open palm
    px(g, 6, 27, "."); px(g, 7, 28, ".")  # finger notches
    return g


def pose_think():
    g = base(); arm_left_idle(g)
    for r, c in [(16, 23), (17, 24), (18, 24), (19, 25), (18, 25), (17, 25),
                 (16, 25), (15, 25)]:
        px(g, r, c, "t")
    rect(g, 12, 14, 23, 24, "s")   # hand beside face
    rect(g, 14, 15, 22, 22, "s")   # touching the chin/cheek edge
    px(g, 13, 22, "s")             # index on cheek
    px(g, 13, 24, "S")             # hand shade
    return g


def auto_outline(g):
    """1px dark contour: every transparent cell touching a filled cell."""
    filled = [[g[r][c] != "." for c in range(GRID_W)] for r in range(GRID_H)]
    for r in range(GRID_H):
        for c in range(GRID_W):
            if filled[r][c]:
                continue
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                rr, cc = r + dr, c + dc
                if 0 <= rr < GRID_H and 0 <= cc < GRID_W and filled[rr][cc]:
                    g[r][c] = "o"
                    break


def to_image(g, scale: int) -> Image.Image:
    img = Image.new("RGBA", (GRID_W * scale, GRID_H * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for r in range(GRID_H):
        for c in range(GRID_W):
            ch = g[r][c]
            if ch == ".":
                continue
            d.rectangle([c * scale, r * scale, (c + 1) * scale - 1, (r + 1) * scale - 1],
                        fill=PAL[ch])
    return img


POSES = {
    "idle": pose_idle,
    "point": pose_point,
    "thumbs": pose_thumbs,
    "shrug": pose_shrug,
    "wave": pose_wave,
    "think": pose_think,
}

MOUTH = {"x": 15.0, "y": 14.6, "w": 2.0, "h": 1.6}  # grid units, top-left origin


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "grid": {"w": GRID_W, "h": GRID_H},
        "scale_px": SCALE,
        "sprite": {"w": GRID_W * SCALE, "h": GRID_H * SCALE},
        "mouth": MOUTH,
        "poses": {},
        "note": "One pixel guy, drawn in code. Reused in every video. Mouth overlaid at render time.",
    }
    for name, fn in POSES.items():
        g = fn()
        auto_outline(g)
        img = to_image(g, SCALE)
        path = OUT / f"{name}.png"
        img.save(path)
        manifest["poses"][name] = f"{name}.png"

    # contact sheet for inspection (checker background)
    sheet_scale = 8
    pad = 8
    w = (GRID_W * sheet_scale + pad) * len(POSES) + pad
    h = GRID_H * sheet_scale + 2 * pad
    sheet = Image.new("RGB", (w, h), (246, 247, 250))
    d = ImageDraw.Draw(sheet)
    for y in range(0, h, 16):
        for x in range(0, w, 16):
            if (x // 16 + y // 16) % 2 == 0:
                d.rectangle([x, y, x + 15, y + 15], fill=(232, 235, 240))
    for i, name in enumerate(POSES):
        g = POSES[name]()
        auto_outline(g)
        spr = to_image(g, sheet_scale)
        sheet.paste(spr, (pad + i * (GRID_W * sheet_scale + pad), pad), spr)
    sheet.save(OUT / "sheet.png")

    (OUT / "character.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"character -> {OUT}")
    for p in sorted(OUT.iterdir()):
        print("  ", p.name, p.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
