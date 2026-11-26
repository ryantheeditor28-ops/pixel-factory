"""Stage 5 — generate a HyperFrames project from timeline.json.

Writes build/video/ as a complete HyperFrames composition:
  index.html                    root: scene hosts + voice + SFX + brand logo
  compositions/scene-NN.html    one scene per script segment
  assets/character/*.png        the pixel guy (copied)
  assets/voice/voice.mp3        full mixed voice track (copied)
  assets/sfx/*.mp3              CC0 foley kit (Freesound; see sfx manifest)
  assets/brand/logo.png         TechPixel Guy wordmark, transparent, top overlay

Layout (1080x1920) follows the vertical safe-zone spec: brand logo 52-156px,
kicker 190px, title from 285px, card from 700px, captions 1136-1278px, character
below 1276px; the character is a chest-to-head CLOSE-UP (1.75x sprite scale,
frame cuts at mid-chest, y 1168-1920) matching the reference's presenter framing.
Scene 1 shows the title/kicker/guy on FRAME 0 (the thumbnail);
scenes tile the full timeline with no blank gaps; the mouth is a stack of
per-sound PNGs swapped on rhubarb cues (image mouths, template-style). Entrances
follow the reference-measured motion language (family-2 stack promo, frame-tracked:
wind-up drift -> fast snap -> soft settle, alternating horizontal deal-in, no
overshoot on big panels), small accents still spring with back.out, "demo" cards play the
Claude-Code-building-a-video scene, and ALL shot timing + sound cues come from
pipeline/shot_plan.py (video-shotcraft methodology: accelerating stagger, holds,
real-material foley — no game timbres).
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from llm import dump_json, load_json
from shot_plan import (BLOCK_OFFSETS, PRICE_ZERO_T, PROG_DURATION, PROG_START,
                       REPO_EXPL_T, TOOL_EXPL_T, TOOL_PING_T, TYPING_OFFSETS,
                       TYPING_T0, cta_plan, plan_shots)


def _rm_tree(path: Path) -> None:
    """Windows-resilient rmtree: transient locks (Defender/Chrome handles) retried."""
    for attempt in range(6):
        try:
            shutil.rmtree(path)
            return
        except (PermissionError, OSError):
            time.sleep(0.5 * (attempt + 1))
    shutil.rmtree(path, ignore_errors=True)

MOUTH_ORDER = ("A", "B", "C", "D", "E", "F", "G", "H", "X")  # one PNG per rhubarb sound

GITHUB_SVG = ('<svg viewBox="0 0 24 24" width="38" height="38" fill="#0e1220">'
              '<path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 '
              '11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-'
              '4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.'
              '084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 '
              '1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-'
              '5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 '
              '0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 '
              '.405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.'
              '84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 '
              '2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 '
              '17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>')

STAR_SVG = ('<svg viewBox="0 0 24 24" width="26" height="26" fill="#f7b500">'
            '<path d="M12 2l2.9 6.6 7.1.6-5.4 4.7 1.6 7-6.2-3.7L5.8 21l1.6-7L2 9.2l7.1-.6z"/></svg>')


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _plain_word(scene: dict, title: str) -> str:
    """A punchy keyword for plain scenes — from the text, not already in the title."""
    import re
    stop = {"because", "about", "there", "their", "would", "could", "should",
            "really", "actually", "literally", "basically", "going", "doing",
            "thing", "stuff", "without", "inside", "every", " completely"}
    title_words = {w.strip(".,!?\"'").lower() for w in title.split()}
    cands = []
    for w in re.findall(r"[A-Za-z][A-Za-z'-]+", scene.get("text", "")):
        lw = w.lower()
        if len(lw) >= 6 and lw not in title_words and lw not in stop:
            cands.append(w)
    cands.sort(key=len, reverse=True)
    if cands:
        return cands[0].upper()
    hl = (scene.get("highlight") or "").split()
    return (hl[-1] if hl else "FREE").upper()


def _highlight_html(text: str, highlight: str) -> str:
    if not highlight:
        return _esc(text)
    toks = [t for t in highlight.lower().replace("?", "").replace(".", "").replace('"', "").split() if t]
    if not toks:
        return _esc(text)
    lower = text.lower()
    spans = []
    for t in sorted(set(toks), key=len, reverse=True):
        start = 0
        while True:
            i = lower.find(t, start)
            if i < 0:
                break
            spans.append((i, i + len(t)))
            start = i + len(t)
    if not spans:
        return _esc(text)
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out, pos = [], 0
    for s, e in merged:
        if s < pos:
            continue
        out.append(_esc(text[pos:s]))
        out.append(f'<span class="acc">{_esc(text[s:e])}</span>')
        pos = e
    out.append(_esc(text[pos:]))
    return "".join(out)


def _cmd_chunks(cmd: str, max_chunks: int = 6) -> list[str]:
    """Group the demo card's command into a few word-chunks for the typing effect."""
    words = str(cmd).split()
    if not words:
        return ["make a viral video"]
    n = min(max_chunks, len(words))
    size = -(-len(words) // n)  # ceil division
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)][:max_chunks]


def _card_html(card: dict, uid: str) -> str:
    kind = card.get("kind", "plain")
    if kind == "repo":
        name = _esc(card.get("name", "owner/repo"))
        stars = _esc(card.get("stars", ""))
        desc = _esc(card.get("desc", ""))
        lang = _esc(card.get("lang", ""))
        dot = "#3178c6"
        lang_row = (f'<div class="cw-langrow"><span class="cw-dotb" style="background:{dot}"></span>'
                    f'<span>{lang}</span></div>') if lang else ""
        return f'''<div id="{uid}-card" class="clip hf-card" data-start="__CARDSTART__" data-duration="__CDUR__">
  <div class="cw-head"><span class="cw-dot r"></span><span class="cw-dot y"></span><span class="cw-dot g"></span><span class="cw-title">github.com</span></div>
  <div class="cw-body">
    <div class="cw-reponame">{GITHUB_SVG}<span>{name}</span></div>
    <div id="{uid}-repodesc" class="cw-desc">{desc}</div>
    <div class="cw-foot"><span class="cw-stars">{STAR_SVG}<span id="{uid}-repostars">{stars}</span></span>{lang_row}</div>
  </div>
</div>'''
    if kind == "stats":
        big = _esc(card.get("big", ""))
        label = _esc(card.get("label", ""))
        return f'''<div id="{uid}-card" class="clip hf-card" data-start="__CARDSTART__" data-duration="__CDUR__">
  <div class="cw-stats"><div class="cw-big">{big}</div><div class="cw-label">{label}</div></div>
</div>'''
    if kind == "terminal":
        lines = "".join(
            f'<div class="cw-tline"><span class="cw-prompt">❯</span>{_esc(l)}</div>'
            for l in card.get("lines", [])[:3])
        return f'''<div id="{uid}-card" class="clip hf-card hf-term" data-start="__CARDSTART__" data-duration="__CDUR__">
  <div class="cw-head"><span class="cw-dot r"></span><span class="cw-dot y"></span><span class="cw-dot g"></span><span class="cw-title dark">terminal</span></div>
  <div class="cw-tbody">{lines}</div>
</div>'''
    if kind == "list":
        items = "".join(
            f'<div id="{uid}-item{j}" class="cw-item"><span class="cw-check">✓</span>'
            f'<span>{_esc(item)}</span></div>'
            for j, item in enumerate(card.get("items", [])[:3]))
        return f'''<div id="{uid}-card" class="clip hf-card" data-start="__CARDSTART__" data-duration="__CDUR__">
  <div class="cw-body"><div class="cw-list">{items}</div></div>
</div>'''
    if kind == "demo":
        # Claude-Code-building-your-video: typed prompt + filling progress bar,
        # stacked over a Timeline card whose colored segments pop in staggered.
        chunks = _cmd_chunks(card.get("cmd", "make a viral video"))
        spans = "".join(
            f'<span id="{uid}-cc{i}" class="cw-cchunk">{_esc(c)} </span>'
            for i, c in enumerate(chunks))
        colors = ("#2f6bff", "#28c840", "#ff9a3c", "#a06bff", "#ff5f57", "#18c3d8")
        widths = (1.5, 1.0, 1.9, 1.2, 0.9, 1.6)
        blocks = "".join(
            f'<div id="{uid}-blk{i}" class="cw-tlblock" style="flex:{widths[i]};background:{colors[i]};"></div>'
            for i in range(len(colors)))
        return f'''<div id="{uid}-card" class="clip hf-card hf-demo" data-start="__CARDSTART__" data-duration="__CDUR__">
  <div class="cw-term">
    <div class="cw-head"><span class="cw-dot r"></span><span class="cw-dot y"></span><span class="cw-dot g"></span><span class="cw-title dark">Claude Code</span></div>
    <div class="cw-termbody">
      <div class="cw-cmdrow"><span class="cw-spark">✦</span><span class="cw-cmd">{spans}<span id="{uid}-cur" class="cw-cur">▊</span></span></div>
      <div class="cw-build"><span class="cw-buildlabel">Building your video…</span>
        <div class="cw-prog"><div id="{uid}-progbar" class="cw-progbar"></div></div>
      </div>
    </div>
  </div>
  <div class="cw-tlcard">
    <div class="cw-head"><span class="cw-dot r"></span><span class="cw-dot y"></span><span class="cw-dot g"></span><span class="cw-title">Timeline</span></div>
    <div class="cw-tlbody">{blocks}</div>
  </div>
</div>'''
    if kind == "price":
        # listicle hook (Marktalksai shape C): struck-through monthly price -> $0 pill
        price = _esc(card.get("price", "$147"))
        zero = _esc(card.get("zero", "$0"))
        label = _esc(card.get("label", "PER MONTH"))
        return f'''<div id="{uid}-card" class="clip hf-card" data-start="__CARDSTART__" data-duration="__CDUR__">
  <div class="cw-price">
    <div class="cw-pricewrap"><span class="cw-pricebig">{price}</span><span id="{uid}-strike" class="cw-strike"></span></div>
    <div class="cw-pricelabel">{label}</div>
    <div id="{uid}-zero" class="cw-pricezero">{zero}</div>
  </div>
</div>'''
    if kind == "tool":
        # listicle body: numbered open-source tool card — number + app tile + name,
        # skeleton-UI mockup rows, "Open source" chip + stars (the winner reel's card system)
        n = int(card.get("n", 1))
        name = _esc(card.get("name", "owner/repo"))
        stars = _esc(card.get("stars", ""))
        desc = _esc(card.get("desc", ""))
        short = name.split("/")[-1] if "/" in str(card.get("name", "")) else str(card.get("name", ""))
        tile = _esc((short[:1] or "R").upper())
        rows = "".join(
            f'<div id="{uid}-mock{j}" class="cw-skrow" style="width:{w}%">'
            f'<i class="cw-skshine"></i></div>'
            for j, w in enumerate((78, 56, 66)))
        return f'''<div id="{uid}-card" class="clip hf-card" data-start="__CARDSTART__" data-duration="__CDUR__">
  <div class="cw-toolhead"><span id="{uid}-toolnum" class="cw-toolnum">#{n}</span><span id="{uid}-tooltile" class="cw-tooltile">{tile}</span>
    <div class="cw-toolmeta"><div class="cw-toolname">{short}</div><div id="{uid}-tooldesc" class="cw-tooldesc">{desc}</div></div></div>
  <div class="cw-toolmock">{rows}</div>
  <div class="cw-toolfoot"><span id="{uid}-osschip" class="cw-osschip">✓ Open source</span>
    <span class="cw-toolstars">{STAR_SVG}<span id="{uid}-starcount">{stars}</span></span></div>
</div>'''
    if kind == "comment":
        # CTA (both formats): a real comment box — placeholder, the keyword typed
        # char by char with a blinking caret (shot_plan.cta_plan beats), then the
        # send button submits. The typed text itself is set by the tween below.
        return f'''<div id="{uid}-card" class="clip hf-card" data-start="__CARDSTART__" data-duration="__CDUR__">
  <div class="cw-comment"><span class="cw-cavatar">T</span>
    <span class="cw-cinput"><span id="{uid}-cph" class="cw-cph">Add a comment...</span><span id="{uid}-ctext" class="cw-ctext"></span><span id="{uid}-caret" class="cw-caret"></span></span>
    <span id="{uid}-send" class="cw-csend">➤</span></div>
</div>'''
    return ""  # plain: replaced by the word chip in _scene_html


SCENE_CSS = """
  #root { position:absolute; inset:0; font-family:'Inter',sans-serif; overflow:hidden;
          background:linear-gradient(180deg,#f8f9ff 0%,#eef1fb 55%,#e9edf9 100%); }
  .blob { position:absolute; border-radius:50%; filter:blur(70px); }
  #__UID__-kicker { position:absolute; top:190px; left:50%; margin-left:-170px; width:340px;
    text-align:center; font:700 30px/1 'Inter'; letter-spacing:5px; color:#4a5470;
    background:rgba(16,20,40,.06); border-radius:999px; padding:18px 0 16px; }
  #__UID__-title { position:absolute; top:288px; left:110px; right:110px; text-align:center;
    font-family:'Archivo Black',sans-serif; font-size:104px; line-height:1.06; color:#0e1220;
    letter-spacing:-1px; text-transform:uppercase; }
  #__UID__-title .acc { color:__ACCENT__; }
  #__UID__-cardwrap { position:absolute; top:660px; left:130px; right:130px; }
  .hf-card { position:relative; }
  .cw-head { display:flex; align-items:center; gap:11px; padding:18px 24px;
    background:#f2f3f7; border-radius:26px 26px 0 0; }
  .cw-dot { width:18px; height:18px; border-radius:50%; }
  .cw-dot.r { background:#ff5f57; } .cw-dot.y { background:#febc2e; } .cw-dot.g { background:#28c840; }
  .cw-title { margin-left:12px; font:600 26px 'Inter'; color:#5f6679; }
  .cw-title.dark { color:#8a93ad; }
  .cw-body { background:#ffffff; padding:34px 34px 30px; border-radius:0 0 26px 26px; }
  .cw-reponame { display:flex; align-items:center; gap:16px; font:800 36px 'Inter'; color:#0e1220;
    word-break:break-word; }
  .cw-desc { margin-top:20px; font:500 31px/1.38 'Inter'; color:#3d4356; }
  .cw-foot { margin-top:24px; display:flex; align-items:center; gap:30px; }
  .cw-stars { display:flex; align-items:center; gap:9px; font:800 28px 'Inter'; color:#0e1220; }
  .cw-langrow { display:flex; align-items:center; gap:10px; font:600 26px 'Inter'; color:#3d4356; }
  .cw-dotb { width:22px; height:22px; border-radius:50%; }
  .hf-term .cw-tbody { background:#101423; padding:28px 30px; border-radius:0 0 26px 26px; }
  .cw-tline { font:500 29px/1.65 'JetBrains Mono',monospace; color:#d7e4ff; }
  .cw-prompt { color:#5df0a6; margin-right:14px; }
  .cw-stats { background:#ffffff; border-radius:26px; padding:52px 36px; text-align:center; }
  .cw-big { font-family:'Archivo Black',sans-serif; font-size:150px; line-height:1; color:__ACCENT__; }
  .cw-label { margin-top:14px; font:800 30px 'Inter'; letter-spacing:5px; color:#3d4356; }
  .cw-list { display:flex; flex-direction:column; gap:24px; }
  .cw-item { display:flex; align-items:center; gap:20px; font:700 34px 'Inter'; color:#0e1220; opacity:0; }
  .cw-check { display:flex; align-items:center; justify-content:center; width:46px; height:46px;
    border-radius:50%; background:__ACCENT__; color:#fff; font-size:28px; flex:0 0 46px; }
  .cw-chip { text-align:center; padding:56px 20px 0; }
  .cw-chipword { font-family:'Archivo Black',sans-serif; font-size:140px; line-height:1;
    color:__ACCENT__; letter-spacing:-2px; }
  .cw-chipbar { width:66%; height:16px; margin:26px auto 0; border-radius:9px; background:__ACCENT__; opacity:.25; }
  #__UID__-caps { position:absolute; top:1140px; left:64px; right:64px; height:206px;
    text-align:center; }
  .phrase { position:absolute; left:0; right:0; top:0; }
  .caps-l1 { display:block; font:900 80px/1.02 'Inter'; color:__ACCENT__; letter-spacing:-1px; }
  .caps-l2 { display:block; margin-top:10px; font:800 60px/1.06 'Inter'; color:#10131a; }
  #__UID__-guy { position:absolute; top:1260px; left:calc(50% - 560px); width:1120px; height:1260px; }
  #__UID__-body { position:absolute; inset:0; }
  #__UID__-body .pose { position:absolute; left:0; top:0; width:100%; height:100%;
    opacity:0; image-rendering:auto; }
  #__UID__-guy img { width:100%; height:100%; display:block; image-rendering:auto; }
  #__UID__-mouth { position:absolute; }
  #__UID__-mouth .mshape { position:absolute; left:0; top:0; width:100%; height:100%;
    opacity:0; image-rendering:auto; }
  .hf-demo { display:flex; flex-direction:column; }
  .cw-term { background:#101423; border-radius:26px; overflow:hidden;
    box-shadow:0 26px 60px rgba(8,12,26,.35); }
  .cw-term .cw-head { background:#1b2138; }
  .cw-termbody { padding:24px 28px 26px; }
  .cw-cmdrow { display:flex; align-items:center; }
  .cw-spark { color:#ff9a3c; font-size:30px; margin-right:14px; }
  .cw-cmd { font:500 30px/1.35 'JetBrains Mono',monospace; color:#e8ecff; }
  .cw-cchunk { opacity:0; }
  .cw-cur { color:#ff9a3c; font:700 28px 'JetBrains Mono',monospace; }
  .cw-build { margin-top:20px; display:flex; align-items:center; gap:16px; }
  .cw-buildlabel { font:600 23px 'Inter'; color:#8f9cc4; white-space:nowrap; }
  .cw-prog { flex:1; height:18px; background:#242c4a; border-radius:9px; overflow:hidden; }
  .cw-progbar { height:100%; width:4%; background:linear-gradient(90deg,#ffb03c,#ff6a3c); border-radius:9px; }
  .cw-tlcard { margin-top:24px; background:#ffffff; border-radius:26px; overflow:hidden;
    box-shadow:0 26px 60px rgba(8,12,26,.16); }
  .cw-tlbody { display:flex; gap:12px; padding:24px 22px; height:96px; align-items:stretch; }
  .cw-tlblock { border-radius:12px; }
  .cw-price { background:#ffffff; border-radius:26px; padding:56px 36px 48px; text-align:center;
    box-shadow:0 26px 60px rgba(8,12,26,.16); }
  .cw-pricewrap { position:relative; display:inline-block; }
  .cw-pricebig { font-family:'Archivo Black',sans-serif; font-size:150px; line-height:1; color:#0e1220; }
  .cw-strike { position:absolute; left:-6%; right:-6%; top:50%; height:16px; margin-top:-8px;
    background:__ACCENT__; border-radius:8px; }
  .cw-pricelabel { margin-top:24px; font:800 26px 'Inter'; letter-spacing:5px; color:#3d4356; }
  .cw-pricezero { display:inline-block; margin-top:28px; padding:20px 56px; border-radius:999px;
    background:__ACCENT__; color:#fff; font-family:'Archivo Black',sans-serif; font-size:96px;
    line-height:1; opacity:0; }
  .cw-toolhead { display:flex; align-items:flex-start; gap:22px; padding:34px 34px 24px;
    background:#ffffff; border-radius:26px 26px 0 0; }
  .cw-toolnum { font-family:'Archivo Black',sans-serif; font-size:46px; line-height:1;
    color:__ACCENT__; margin-top:24px; }
  .cw-tooltile { display:flex; align-items:center; justify-content:center; width:92px; height:92px;
    border-radius:24px; background:__ACCENT__; color:#fff; font:900 46px 'Inter'; flex:0 0 92px; }
  .cw-toolmeta { min-width:0; }
  .cw-toolname { font:800 38px/1.1 'Inter'; color:#0e1220; word-break:break-word; }
  .cw-tooldesc { margin-top:10px; font:500 27px/1.3 'Inter'; color:#3d4356; }
  .cw-toolmock { background:#ffffff; padding:4px 34px 0; }
  .cw-skrow { position:relative; overflow:hidden; height:20px; border-radius:10px; background:#eef0f6; margin-bottom:14px; opacity:0; }
  .cw-skshine { position:absolute; top:0; bottom:0; left:0; width:34%; border-radius:10px;
    background:linear-gradient(90deg,rgba(255,255,255,0),rgba(255,255,255,.92),rgba(255,255,255,0)); }
  .cw-toolfoot { display:flex; align-items:center; gap:18px; padding:8px 34px 34px;
    background:#ffffff; border-radius:0 0 26px 26px; }
  .cw-osschip { display:inline-flex; align-items:center; gap:10px; padding:14px 26px;
    border-radius:999px; background:#e7f7ec; color:#1f9d55; font:800 26px 'Inter'; opacity:0; }
  .cw-toolstars { display:flex; align-items:center; gap:9px; font:800 28px 'Inter'; color:#0e1220; }
  .cw-comment { display:flex; align-items:center; gap:20px; background:#ffffff;
    border-radius:999px; padding:26px 30px; box-shadow:0 26px 60px rgba(8,12,26,.16); }
  .cw-cavatar { display:flex; align-items:center; justify-content:center; width:74px; height:74px;
    border-radius:50%; background:#101423; color:#fff; font:900 32px 'Inter'; flex:0 0 74px; }
  .cw-cinput { flex:1; min-width:0; display:flex; align-items:center; gap:2px;
    text-align:left; font:700 34px 'Inter'; color:#10131a; white-space:nowrap;
    overflow:hidden; background:#eef0f6; border-radius:999px; padding:16px 26px; }
  .cw-cph { color:#9aa1b5; }
  .cw-ctext { font-weight:800; }
  .cw-caret { flex:0 0 3px; width:3px; height:38px; margin-left:6px; border-radius:2px;
    background:__ACCENT__; opacity:0; }
  .cw-csend { display:flex; align-items:center; justify-content:center; width:78px; height:78px;
    border-radius:50%; background:__ACCENT__; color:#fff; font-size:36px; flex:0 0 78px; }
"""

# listicle format overrides (Marktalksai shape C): warm cream sketchbook background,
# italic-serif accent word (Playfair Display is bundled), progress-dots header
LISTICLE_CSS = """
  #root { background:linear-gradient(180deg,#f9f4ea 0%,#f3ecdd 55%,#ece3d0 100%); }
  #__UID__-kicker { top:206px; }
  #__UID__-title { top:300px; }
  #__UID__-title .acc { font-family:'Playfair Display',serif; font-style:italic;
    text-transform:none; letter-spacing:0; }
  #__UID__-dots { position:absolute; top:166px; left:0; right:0; display:flex;
    justify-content:center; align-items:center; gap:14px; }
  .cw-pdot { width:14px; height:14px; border-radius:50%; background:rgba(46,36,18,.16); }
  .cw-pdot.on { background:__ACCENT__; }
  .cw-pdot.cur { width:18px; height:18px; margin-top:-2px; }
"""


def _ref_entrance_tl(sel: str, start: float, xd: float = 0.0, dy: float = 110,
                     visible_from: bool = False, small: bool = False) -> list[str]:
    """Reference-measured entrance, as GSAP-core keyframes (no plugin).

    Frame-tracking the family-2 stack promo gave a three-phase curve for every
    panel entrance: a slow wind-up that drifts PAST the start (~0.15-0.3s, often
    partially transparent), a fast snap that lands ~70% of the travel in
    ~0.10-0.2s, and a soft decelerating settle (~0.2-0.3s) with NO overshoot on
    big elements; panels deal in with alternating horizontal drift. Small
    sub-elements (rows/chips) keep a tighter version. visible_from=True keeps
    frame 0 on screen (scene-1 thumbnail rule) by starting visible but off-pose.
    """
    if small:
        init = (f'  tl.set("{sel}",{{opacity:0,y:{dy},x:{xd:.0f}}},{start:.2f});')
        return [init,
                f'  tl.to("{sel}",{{keyframes:['
                f'{{y:{dy + 8},opacity:0.45,duration:0.10,ease:"sine.inOut"}},'
                f'{{y:-2,x:0,opacity:1,duration:0.14,ease:"power3.out"}},'
                f'{{y:1,duration:0.09,ease:"power2.out"}},'
                f'{{y:0,duration:0.12,ease:"sine.out"}}'
                f']}},{start:.2f});']
    if visible_from:
        init = (f'  tl.set("{sel}",{{y:{dy * 0.22:.0f},scale:0.97,x:{xd:.0f}}},{start:.2f});')
        return [init,
                f'  tl.to("{sel}",{{keyframes:['
                f'{{y:{dy * 0.30:.0f},duration:0.11,ease:"sine.inOut"}},'
                f'{{y:-2,scale:1.004,x:0,duration:0.16,ease:"power3.out"}},'
                f'{{y:1,duration:0.11,ease:"power2.out"}},'
                f'{{y:0,scale:1,duration:0.14,ease:"sine.out"}}'
                f']}},{start:.2f});']
    init = (f'  tl.set("{sel}",{{opacity:0,y:{dy:.0f},x:{xd:.0f},scale:0.94}},'
            f'{start:.2f});')
    return [init,
            f'  tl.to("{sel}",{{keyframes:['
            f'{{y:{dy + 12:.0f},opacity:0.4,duration:0.14,ease:"sine.inOut"}},'
            f'{{y:-3,x:0,scale:1.004,opacity:1,duration:0.19,ease:"power3.out"}},'
            f'{{y:1,duration:0.12,ease:"power2.out"}},'
            f'{{y:0,scale:1,duration:0.16,ease:"sine.out"}}'
            f']}},{start:.2f});']


def _scene_html(idx: int, scene: dict, tl_data: dict, lead: float) -> str:
    uid = f"sn{idx:02d}"
    accent = tl_data["accent_color"]
    duration = scene["duration"]
    is_first = idx == 1
    t0 = "0.000" if is_first else "0.040"
    card_start = 0.0 if is_first else 0.20
    card_dur = max(duration - card_start - 0.05, 0.5)
    manifest = load_json(Path(__file__).resolve().parent.parent / "assets" / "character" / "character.json")
    mx, my, mw, mh = manifest["mouth"]["x"], manifest["mouth"]["y"], manifest["mouth"]["w"], manifest["mouth"]["h"]
    gw, gh = manifest["grid"]["w"], manifest["grid"]["h"]
    mouth_style = (f"left:{mx/gw*100:.2f}%;top:{my/gh*100:.2f}%;"
                   f"width:{mw/gw*100:.2f}%;height:{mh/gh*100:.2f}%;")
    card_html = _card_html(scene.get("card", {"kind": "plain"}), uid)
    if not card_html:  # plain: big accent word chip fills the card zone
        kw = str(tl_data.get("comment_keyword") or "").strip()
        if kw and kw.lower() in str(scene.get("text") or "").lower():
            # comment-gate scene: the chip IS the keyword — never a text heuristic
            # (longest-word once rendered "COMMENTS" over a WRANGLE gate)
            word = kw.upper()
        else:
            word = _plain_word(scene, tl_data["_titles"][idx - 1] if "_titles" in tl_data else "")
        card_html = (f'<div id="{uid}-card" class="clip hf-card" data-start="__CARDSTART__" data-duration="__CDUR__">\n'
                     f'  <div class="cw-chip"><div class="cw-chipword">{_esc(word)}</div>'
                     f'<div class="cw-chipbar"></div></div>\n'
                     f'</div>')
    card_html = (card_html.replace("__CARDSTART__", f"{card_start:.2f}")
                          .replace("__CDUR__", f"{card_dur:.2f}"))

    # listicle format (Marktalksai shape C): progress-dots header tracking the
    # scene position — the winner reels' retention device. Static per scene,
    # current dot pops in when the scene starts.
    is_listicle = tl_data.get("format") == "listicle"
    dots_html = ""
    dots_tl: list[str] = []
    if is_listicle:
        n_total = len(tl_data["scenes"])
        spans = "".join(
            f'<span class="cw-pdot{" on" if i < idx else ""}{" cur" if i == idx - 1 else ""}"></span>'
            for i in range(n_total))
        dots_html = (f'  <div id="{uid}-dots" class="clip cw-dots" data-start="{t0}" '
                     f'data-duration="__KDUR__" data-layout-allow-overlap>{spans}</div>')
        dots_tl.append(f'  tl.fromTo("#{uid}-dots .cw-pdot.cur",{{scale:0.5}},'
                       f'{{scale:1,duration:0.30,ease:"back.out(2.2)",immediateRender:false}},0.12);')

    # listicle card choreography (R2: accelerating deal-in, then stillness):
    # price hook -> strike draws -> $0 pill pops; tool -> skeleton rows deal in
    # -> chip pops; comment CTA -> send button pulses on the finale impact.
    kind = (scene.get("card") or {}).get("kind", "plain")
    listicle_tl: list[str] = []
    if is_listicle and kind == "price":
        # strike: from-state applied at registration (no CSS pre-hide), so the
        # bar is invisible until it draws across the price
        listicle_tl.append(
            f'  tl.fromTo("#{uid}-strike",{{scaleX:0,rotate:-6}},'
            f'{{scaleX:1,rotate:-6,duration:0.35,ease:"power2.inOut",immediateRender:true}},'
            f'{card_start + 0.55:.2f});')
        listicle_tl.append(
            f'  tl.fromTo("#{uid}-zero",{{scale:0.5,opacity:0}},'
            f'{{scale:1,opacity:1,duration:0.34,ease:"back.out(2.2)",immediateRender:false}},'
            f'{card_start + PRICE_ZERO_T:.2f});')
    if is_listicle and kind == "tool":
        # measured sub-row cadence: near-uniform ~0.18s beats (the reference's
        # stagger barely accelerates), each row wind-up -> snap -> settle
        t = card_start + 0.45
        for j in range(3):
            listicle_tl.extend(_ref_entrance_tl(f"#{uid}-mock{j}", t, dy=30, small=True))
            t += 0.18 * (0.92 ** j)
        listicle_tl.append(
            f'  tl.fromTo("#{uid}-osschip",{{scale:0.6,opacity:0}},'
            f'{{scale:1,opacity:1,duration:0.30,ease:"back.out(2.2)",immediateRender:false}},'
            f'{t + 0.05:.2f});')
        # motion graphics while the narration explains what the repo does:
        # the description wipes in, the info rows shimmer on a loop, the star
        # count ticks up, the app tile floats, the #N badge pings. All tweens
        # are bounded-repeat (seek-safe for the frame-accurate render).
        t_expl = card_start + TOOL_EXPL_T  # shot_plan beat: desc wipe + badge ping
        listicle_tl.append(
            f'  tl.set("#{uid}-tooldesc",{{clipPath:"inset(-6% 100% -6% 0)"}},{card_start + 0.01:.2f});')
        listicle_tl.append(
            f'  tl.to("#{uid}-tooldesc",{{clipPath:"inset(-6% 0% -6% 0)",duration:0.9,ease:"power2.out"}},{t_expl:.2f});')
        stars_raw = str((scene.get("card") or {}).get("stars", "")).replace(",", "").strip()
        if stars_raw.isdigit():
            listicle_tl.append(
                f'  tl.set("#{uid}-starcount",{{innerText:0}},{card_start + 0.01:.2f});')
            listicle_tl.append(
                f'  tl.to("#{uid}-starcount",{{innerText:{int(stars_raw)},snap:"innerText",'
                f'duration:0.9,ease:"power1.out"}},{t_expl:.2f});')
        t_shine = card_start + 1.15
        loop = max(int((max(duration - 0.35, t_shine + 1.2) - t_shine) / 1.15), 1)
        for j in range(3):
            listicle_tl.append(
                f'  tl.fromTo("#{uid}-mock{j} .cw-skshine",{{xPercent:-150}},'
                f'{{xPercent:330,duration:0.85,ease:"power1.inOut",repeat:{loop},repeatDelay:0.30}},'
                f'{t_shine + j * 0.22:.2f});')
        fl = max(int((duration - card_start - 1.2) / 1.0), 1) * 2
        listicle_tl.append(
            f'  tl.to("#{uid}-tooltile",{{y:-9,duration:1.0,yoyo:true,repeat:{fl},'
            f'ease:"sine.inOut",immediateRender:false}},{card_start + 1.20:.2f});')
        listicle_tl.append(
            f'  tl.fromTo("#{uid}-toolnum",{{scale:1}},'
            f'{{scale:1.14,duration:0.42,yoyo:true,repeat:3,ease:"sine.inOut",immediateRender:false}},'
            f'{card_start + TOOL_PING_T:.2f});')
    if kind == "repo":
        # same explain-time motion on the single-mode GitHub card: description
        # wipes in as the narration reads it, stars tick up from 0
        t_expl = card_start + REPO_EXPL_T
        cardtl = [
            f'  tl.set("#{uid}-repodesc",{{clipPath:"inset(-6% 100% -6% 0)"}},{card_start + 0.01:.2f});',
            f'  tl.to("#{uid}-repodesc",{{clipPath:"inset(-6% 0% -6% 0)",duration:0.9,ease:"power2.out"}},{t_expl:.2f});',
        ]
        stars_raw = str((scene.get("card") or {}).get("stars", "")).replace(",", "").strip()
        if stars_raw.isdigit():
            cardtl.append(
                f'  tl.set("#{uid}-repostars",{{innerText:0}},{card_start + 0.01:.2f});')
            cardtl.append(
                f'  tl.to("#{uid}-repostars",{{innerText:{int(stars_raw)},snap:"innerText",'
                f'duration:0.9,ease:"power1.out"}},{t_expl:.2f});')
        listicle_tl.extend(cardtl)
    if kind == "comment":
        # the comment box is a performance: placeholder -> keyword typed char by
        # char (blinking caret, keystroke foley from the shot plan) -> the send
        # button presses and settles into a green "sent" state. Beat times come
        # from shot_plan.cta_plan so sounds and letters can never drift (S3).
        kw = (str((scene.get("card") or {}).get("keyword")
                  or tl_data.get("comment_keyword") or "REPO").strip())[:12] or "REPO"
        plan = cta_plan(card_start, kw, duration)
        chars, t_send = plan["chars"], plan["send"]
        listicle_tl.append(
            f'  tl.set("#{uid}-caret",{{opacity:1}},{chars[0] - 0.12:.2f});')
        listicle_tl.append(
            f'  tl.set("#{uid}-cph",{{opacity:0}},{chars[0] - 0.02:.2f});')
        for i, tc in enumerate(chars):
            listicle_tl.append(
                f'  tl.set("#{uid}-ctext",{{innerText:{json.dumps(kw[:i + 1])}}},{tc:.2f});')
        blinks = max(int((t_send - chars[0]) / 0.53), 1) * 2
        listicle_tl.append(
            f'  tl.to("#{uid}-caret",{{opacity:0,duration:0.20,yoyo:true,repeat:{blinks},'
            f'ease:"power1.inOut",immediateRender:false}},{chars[0]:.2f});')
        listicle_tl.append(
            f'  tl.set("#{uid}-caret",{{opacity:0}},{t_send + 0.05:.2f});')
        # submit: press dip -> overshoot -> settle into the green "sent" state
        listicle_tl.append(
            f'  tl.to("#{uid}-send",{{scale:0.82,duration:0.09,ease:"power2.in",'
            f'immediateRender:false}},{t_send:.2f});')
        listicle_tl.append(
            f'  tl.to("#{uid}-send",{{scale:1.16,duration:0.13,ease:"power2.out"}},'
            f'{t_send + 0.09:.2f});')
        listicle_tl.append(
            f'  tl.to("#{uid}-send",{{scale:1,backgroundColor:"#1f9d55",'
            f'duration:0.16,ease:"power2.out"}},{t_send + 0.22:.2f});')
        # the typed comment does a tiny proud hop as it "posts"
        listicle_tl.append(
            f'  tl.to("#{uid}-ctext",{{y:-6,duration:0.16,yoyo:true,repeat:1,'
            f'ease:"sine.inOut",immediateRender:false}},{t_send + 0.10:.2f});')

    # captions — two-line style per phrase: line 1 = the hook words (accent blue),
    # line 2 = the supporting words (black) below. Each group rises in with an ease
    # while fading 0 -> 100, ends just before the next phrase starts (no overlap).
    phrases_html, cap_tl = [], []
    phrases = scene.get("phrases", [])
    hl_set = {(t.strip(".,!?;:")) for t in
              (scene.get("highlight") or "").lower().replace('"', "").split() if t}
    for pi, ph in enumerate(phrases):
        pstart = ph["t0"] + lead
        end = ph["t1"] + lead
        if pi + 1 < len(phrases):
            end = min(end, phrases[pi + 1]["t0"] + lead - 0.02)
        pdur = max(end - pstart, 0.15)
        words = [w["text"].strip() for w in ph["words"] if w["text"].strip()]
        l1_idx = [i for i, w in enumerate(words) if w.strip(".,!?;:").lower() in hl_set]
        if not l1_idx:
            l1_idx = [0]  # no highlight here: lead word carries the blue line
        l1_ws = [words[i] for i in l1_idx]
        l2_ws = [w for i, w in enumerate(words) if i not in l1_idx]
        l2_html = (f'<span class="caps-l2">{_esc(" ".join(l2_ws))}</span>' if l2_ws else "")
        phrases_html.append(
            f'<div id="{uid}-p{pi}" class="clip phrase" data-start="{pstart:.3f}" '
            f'data-duration="{pdur:.3f}"><span class="caps-l1">{_esc(" ".join(l1_ws))}</span>{l2_html}</div>')
        # ease rise: slide up + opacity 0 -> 100 together
        cap_tl.append(f'  tl.fromTo("#{uid}-p{pi}",{{y:34,opacity:0}},'
                      f'{{y:0,opacity:1,duration:0.32,ease:"power3.out",immediateRender:false}},{pstart:.3f});')
        if pdur >= 0.45:  # soften the exit for anything on screen long enough
            cap_tl.append(f'  tl.to("#{uid}-p{pi}",{{opacity:0,duration:0.12,immediateRender:false}},'
                          f'{pstart + pdur - 0.12:.3f});')

    # gestures: hard-cut pose swaps on speech beats (every 2nd phrase start), so the
    # guy changes gestures naturally while talking instead of once per scene.
    POSE_ORDER = ("idle", "point", "chest", "thumbs", "think", "shrug", "spread", "wave")
    pose0 = scene.get("gesture", "idle")
    if pose0 not in POSE_ORDER:
        pose0 = "idle"
    pose_imgs = "".join(
        f'<img id="{uid}-pose-{p}" class="pose" src="assets/character/{p}.png" alt="">'
        for p in POSE_ORDER)
    gesture_tl = [f'  tl.set("#{uid}-pose-{pose0}",{{opacity:1}},0);']
    prev_pose = pose0
    flow = [g for g in ("point", "chest", "thumbs", "wave", "think", "shrug", "spread") if g != pose0]
    beats = [round(max(phrases[bi]["t0"] + lead, 0.5), 3)
             for bi in range(2, len(phrases), 2)]
    for bi, t in enumerate(beats):
        new = flow[bi % len(flow)]
        if new == prev_pose:
            continue
        gesture_tl.append(f'  tl.set("#{uid}-pose-{prev_pose}",{{opacity:0}},{t:.3f});')
        gesture_tl.append(f'  tl.set("#{uid}-pose-{new}",{{opacity:1}},{t:.3f});')
        prev_pose = new

    # mouth: stacked per-sound PNGs, swapped on rhubarb cues (template-style image mouths)
    cues = scene.get("cues") or [{"t0": 0, "t1": duration, "shape": "X"}]
    mouth_imgs = "".join(
        f'<img id="{uid}-m{s}" class="mshape" src="assets/character/mouth-{s}.png" alt="">'
        for s in MOUTH_ORDER)
    mouth_tl = [f'  tl.set("#{uid}-mX",{{opacity:1}},0);']
    prev = "X"
    for c in cues:
        s = c["shape"] if c["shape"] in MOUTH_ORDER else "X"
        if s == prev:
            continue
        t = round(max(c["t0"] + lead, 0.02), 3)
        mouth_tl.append(f'  tl.set("#{uid}-m{prev}",{{opacity:0}},{t});')
        mouth_tl.append(f'  tl.set("#{uid}-m{s}",{{opacity:1}},{t});')
        prev = s
    if prev != "X":  # settle back to closed when the line ends
        t_close = round(min(max(cues[-1]["t1"] + lead + 0.06, 0.2), max(duration - 0.05, 0.25)), 3)
        mouth_tl.append(f'  tl.set("#{uid}-m{prev}",{{opacity:0}},{t_close});')
        mouth_tl.append(f'  tl.set("#{uid}-mX",{{opacity:1}},{t_close});')
    bob_repeat = max(int((duration - lead) / 0.68), 1) * 2

    # frame-0 (thumbnail) rule: scene 1 shows everything immediately — no opacity entrances.
    # Entrance + bob target the -body wrapper so the mouth rides along with the body.
    xd = 72 if idx % 2 == 0 else -72  # measured: panels deal in from alternating sides
    if is_first:
        guy_tl = _ref_entrance_tl(f"#{uid}-body", 0.0, 0, dy=52, visible_from=True) + [
            f'  tl.fromTo("#{uid}-body",{{y:0}},{{y:-12,duration:0.34,yoyo:true,repeat:{bob_repeat},ease:"sine.inOut",immediateRender:false}},{lead + 0.62:.2f});',
        ]
        title_tl = _ref_entrance_tl(f"#{uid}-title", 0.01, xd * 0.5, dy=44, visible_from=True)
        kicker_tl = []
    else:
        guy_tl = _ref_entrance_tl(f"#{uid}-body", 0.05, 0, dy=56) + [
            f'  tl.fromTo("#{uid}-body",{{y:0}},{{y:-12,duration:0.34,yoyo:true,repeat:{bob_repeat},ease:"sine.inOut",immediateRender:false}},{lead + 0.70:.2f});',
        ]
        title_tl = _ref_entrance_tl(f"#{uid}-title", 0.04, xd * 0.5, dy=48)
        kicker_tl = [f'  tl.fromTo("#{uid}-kicker",{{opacity:0,y:-14}},{{opacity:1,y:0,duration:0.30,ease:"back.out(1.7)"}},0.10);']
    card_tl = (_ref_entrance_tl(f"#{uid}-card", card_start, xd, dy=110,
                                visible_from=is_first) if card_html else [])

    # measured transition beat: outgoing elements leave with a quick power-in
    # drift (the reference's pre-entrance phase) while the next scene assembles
    exit_tl: list[str] = []
    if idx < len(tl_data["scenes"]):
        t_out = max(duration - 0.17, card_start + 0.80)
        exit_tl = [
            f'  tl.to("#{uid}-card",{{y:-26,x:{-xd * 0.4:.0f},opacity:0,duration:0.16,ease:"power2.in",immediateRender:false}},{t_out:.2f});',
            f'  tl.to("#{uid}-title",{{y:-18,opacity:0,duration:0.15,ease:"power2.in",immediateRender:false}},{t_out:.2f});',
            f'  tl.to("#{uid}-body",{{y:-20,opacity:0,duration:0.16,ease:"power2.in",immediateRender:false}},{t_out:.2f});',
        ]

    # demo card: typed command -> filling progress bar -> staggered timeline blocks
    # (all offsets come from shot_plan so the keystroke foley lands exactly on each
    # chunk reveal, and the blocks pop with an accelerating batch cadence — R2)
    demo_tl = []
    if scene.get("card", {}).get("kind") == "demo":
        chunks = _cmd_chunks(scene["card"].get("cmd", ""))
        for i in range(min(len(chunks), len(TYPING_OFFSETS))):
            t = card_start + TYPING_T0 + TYPING_OFFSETS[i]
            demo_tl.append(f'  tl.fromTo("#{uid}-cc{i}",{{opacity:0}},{{opacity:1,duration:0.05,immediateRender:false}},{t:.2f});')
        demo_tl.append(f'  tl.fromTo("#{uid}-cur",{{opacity:1}},{{opacity:0,duration:0.4,yoyo:true,repeat:99,ease:"steps(1)"}},{card_start + 0.20:.2f});')
        demo_tl.append(f'  tl.fromTo("#{uid}-progbar",{{width:"4%"}},{{width:"96%",duration:{PROG_DURATION},ease:"power1.inOut",immediateRender:false}},{card_start + PROG_START:.2f});')
        for i, off in enumerate(BLOCK_OFFSETS):
            demo_tl.append(f'  tl.fromTo("#{uid}-blk{i}",{{scale:0,opacity:0}},{{scale:1,opacity:1,duration:0.26,ease:"back.out(2.4)",immediateRender:false}},{card_start + off:.2f});')

    # list card: items deal in with an accelerating cadence, then the batch
    # settles (R2: never uniform, always accelerating, 0.4s+ of stillness after)
    list_tl = []
    if scene.get("card", {}).get("kind") == "list":
        t = card_start + 0.30
        for j in range(3):
            list_tl.extend(_ref_entrance_tl(f"#{uid}-item{j}", t, dy=34, small=True))
            t += 0.22 * (0.92 ** j)

    html = f'''<template>
<style>{SCENE_CSS.replace("__UID__", uid).replace("__ACCENT__", accent)}{LISTICLE_CSS.replace("__UID__", uid).replace("__ACCENT__", accent) if is_listicle else ""}</style>
<div id="root" data-composition-id="{uid}" data-width="1080" data-height="1920">
  <div id="{uid}-blob1" class="blob" data-layout-ignore
       style="width:560px;height:560px;left:-140px;top:380px;background:rgba(47,107,255,.16);"></div>
  <div id="{uid}-blob2" class="blob" data-layout-ignore
       style="width:480px;height:480px;right:-120px;top:920px;background:rgba(255,90,47,.12);"></div>
{dots_html}
  <div id="{uid}-kicker" class="clip" data-start="{t0}" data-duration="__KDUR__"
       data-var-text="kicker">{_esc(tl_data["kicker"])}</div>
  <div id="{uid}-title" class="clip" data-start="{t0}" data-duration="__TDUR__">
    <h1 style="all:unset;display:block;">{_highlight_html(tl_data["_titles"][idx - 1], scene.get("highlight", ""))}</h1>
  </div>
  <div id="{uid}-cardwrap">{card_html}</div>
  <div id="{uid}-caps" data-track-kind="captions">{''.join(phrases_html)}</div>
  <div id="{uid}-guy" class="clip" data-start="{t0}" data-duration="__GDUR__">
    <div id="{uid}-body">
      {pose_imgs}
      <div id="{uid}-mouth" style="{mouth_style}">{mouth_imgs}</div>
    </div>
  </div>
</div>
<script>
  const tl = gsap.timeline({{ paused: true }});
{chr(10).join(title_tl + kicker_tl + card_tl + guy_tl + demo_tl + list_tl + listicle_tl + dots_tl + gesture_tl + exit_tl)}
  tl.fromTo("#{uid}-blob1", {{ x: 0, y: 0 }}, {{ x: 60, y: -50, duration: 4, yoyo: true, repeat: 99, ease: "sine.inOut", immediateRender: false }}, 0);
  tl.fromTo("#{uid}-blob2", {{ x: 0, y: 0 }}, {{ x: -50, y: 60, duration: 5, yoyo: true, repeat: 79, ease: "sine.inOut", immediateRender: false }}, 0);
{chr(10).join(mouth_tl)}
{chr(10).join(cap_tl)}
  window.__timelines["{uid}"] = tl;
</script>
</template>'''
    html = (html.replace("__KDUR__", f"{max(duration - 0.02, 0.5):.2f}")
                .replace("__TDUR__", f"{max(duration - 0.01, 0.5):.2f}")
                .replace("__GDUR__", f"{max(duration - 0.01, 0.5):.2f}"))
    return html


def _root_html(tl_data: dict, total: float, sfx_cues: list[dict]) -> str:
    hosts = []
    for sc in tl_data["scenes"]:
        vals = json.dumps({"kicker": tl_data["kicker"]}, ensure_ascii=True).replace("'", "&#39;")
        hosts.append(
            f'    <div id="{sc["id"]}" data-composition-id="{sc["id"]}" '
            f'data-composition-src="compositions/{sc["id"]}.html" '
            f'data-start="{sc["start"]:.3f}" data-duration="{sc["duration"]:.3f}" '
            f'data-track-index="1" data-track-kind="graphics" '
            f'data-width="1080" data-height="1920" data-variable-values=\'{vals}\'></div>')
    # SFX cues from the shot plan: declarative table -> audio clips, each cut to
    # its action length, spread over 4 tracks so neighbours never cut each other.
    audios = []
    for i, c in enumerate(sfx_cues):
        track = 10 + (i % 4)
        audios.append(
            f'      <audio data-start="{c["t"]:.3f}" data-duration="{c["cut"]:.2f}" '
            f'data-track-index="{track}" data-volume="{c["vol"]}" src="{c["file"]}"></audio>'
            f'<!-- {c["action"]} -->')
    return f'''<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><meta name="viewport" content="width=1080, height=1920" />
    <style>
      #brand {{ position:absolute; top:52px; left:0; right:0; display:flex;
               justify-content:center; z-index:50; pointer-events:none; }}
      #brand img {{ height:104px; filter:drop-shadow(0 6px 18px rgba(10,14,28,.18)); }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total:.3f}"
         data-width="1080" data-height="1920">
{chr(10).join(hosts)}
      <div id="brand" data-layout-ignore><img src="assets/brand/logo.png" alt="TechPixel Guy"></div>
      <audio id="voice" data-start="0" data-duration="{total:.3f}" data-track-index="9"
             data-volume="1" src="assets/voice/voice.mp3"></audio>
{chr(10).join(audios)}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo("#brand", {{ scale: 0.92 }}, {{ scale: 1, duration: 0.40, ease: "back.out(1.8)" }}, 0.05);
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>'''


def generate(timeline: dict, build_dir: Path) -> Path:
    proj = build_dir / "video"
    if proj.exists():
        _rm_tree(proj)
    (proj / "compositions").mkdir(parents=True)
    (proj / "assets" / "voice").mkdir(parents=True)
    root = Path(__file__).resolve().parent.parent
    char_src = root / "assets" / "character"
    char_dst = proj / "assets" / "character"
    char_dst.mkdir(parents=True, exist_ok=True)
    for png in char_src.glob("*.png"):
        shutil.copy2(png, char_dst / png.name)
    shutil.copy2(build_dir / "voice" / "voice.mp3", proj / "assets" / "voice" / "voice.mp3")
    # brand logo + SFX kit ship with every project (transparent wordmark overlay
    # + the Freesound CC0 foley the shot plan cues)
    brand_src = root / "assets" / "brand" / "logo.png"
    if brand_src.exists():
        (proj / "assets" / "brand").mkdir(parents=True, exist_ok=True)
        shutil.copy2(brand_src, proj / "assets" / "brand" / "logo.png")
    sfx_src = root / "assets" / "sfx"
    if sfx_src.exists():
        (proj / "assets" / "sfx").mkdir(parents=True, exist_ok=True)
        for f in sfx_src.glob("*.mp3"):
            shutil.copy2(f, proj / "assets" / "sfx" / f.name)

    tl_data = dict(timeline)
    # per-scene title lines: scene 1 carries the big video title; later scenes use
    # a short punch derived from their highlight/text start. Listicle scenes punch
    # the claim ("NUMBER 2" / "COMMENT REPO") like the winner reel — the tool name
    # already lives big inside the card, and repo names would truncate mid-word.
    titles = [tl_data["title"]]
    kw = str(tl_data.get("comment_keyword") or "").strip()
    for sc in tl_data["scenes"][1:]:
        card = sc.get("card") or {}
        kind = card.get("kind")
        # comment-gate detection by content (works for both formats: listicle's
        # "comment" card and the single format's plain-card CTA): the spoken text
        # asks for the keyword, so title + accent are pinned to it — never the
        # LLM's own word choice (it once rendered "COMMENT COMMENTS" over WRANGLE)
        is_gate = bool(kw) and kw.lower() in str(sc.get("text") or "").lower()
        if kind == "tool":
            punch = f"NUMBER {card.get('n', '')}"
            if not (sc.get("highlight") or "").strip():
                sc["highlight"] = f"number {card.get('n', '')}"
        elif kind == "comment" or is_gate:
            punch = f"COMMENT {kw or 'REPO'}"
            if not (sc.get("highlight") or "").strip():
                sc["highlight"] = kw
        else:
            words = " ".join(w["text"] for w in sc.get("words", [])[:4])
            punch = (sc.get("highlight") or words).upper()
        titles.append(punch[:26])
    tl_data["_titles"] = titles

    # shot + sound plan (video-shotcraft methodology): every SFX cue with absolute
    # time, file, volume and action comment; re-derived on every build so a
    # timeline change re-pins the whole table (S3).
    cues = plan_shots(tl_data)
    dump_json(proj / "sfx-cue-table.json",
              {"video_total_s": timeline["total"], "cues": cues})

    (proj / "index.html").write_text(
        _root_html(tl_data, timeline["total"], cues), encoding="utf-8", newline="\n")
    for i, sc in enumerate(tl_data["scenes"], start=1):
        html = _scene_html(i, sc, tl_data, sc.get("audio_offset", 0.0))
        (proj / "compositions" / f"scene-{i:02d}.html").write_text(html, encoding="utf-8", newline="\n")

    dump_json(proj / "timeline-copy.json", timeline)
    print(f"[hf] project generated at {proj} ({len(tl_data['scenes'])} scenes, {timeline['total']:.1f}s)")
    return proj
