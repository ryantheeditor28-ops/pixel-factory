"""Stage 5 — generate a HyperFrames project from timeline.json.

Writes build/video/ as a complete HyperFrames composition:
  index.html                    root: scene hosts + voice audio
  compositions/scene-NN.html    one scene per script segment
  assets/character/*.png        the pixel guy (copied)
  assets/voice/voice.mp3        full mixed voice track (copied)

Layout (1080x1920) follows the vertical safe-zone spec: kicker 190px, title from
285px, card from 700px, captions 1140-1275px, character below 1276px. Scene 1
shows the title/kicker/guy on FRAME 0 (the thumbnail); scenes tile the full
timeline with no blank gaps; mouth starts closed via a position-0 baseline tween.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from llm import dump_json, load_json


def _rm_tree(path: Path) -> None:
    """Windows-resilient rmtree: transient locks (Defender/Chrome handles) retried."""
    for attempt in range(6):
        try:
            shutil.rmtree(path)
            return
        except (PermissionError, OSError):
            time.sleep(0.5 * (attempt + 1))
    shutil.rmtree(path, ignore_errors=True)

MOUTH_SHAPES = {  # scaleX, scaleY of the max-size mouth box
    "A": (1.00, 1.05), "B": (0.85, 0.55), "C": (1.00, 0.40), "D": (1.05, 1.15),
    "E": (0.55, 0.22), "F": (0.50, 0.40), "G": (0.80, 0.80), "H": (0.70, 0.60),
    "X": (0.62, 0.10),
}

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
    <div class="cw-desc">{desc}</div>
    <div class="cw-foot"><span class="cw-stars">{STAR_SVG}<span>{stars}</span></span>{lang_row}</div>
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
            f'<div class="cw-item"><span class="cw-check">✓</span><span>{_esc(i)}</span></div>'
            for i in card.get("items", [])[:3])
        return f'''<div id="{uid}-card" class="clip hf-card" data-start="__CARDSTART__" data-duration="__CDUR__">
  <div class="cw-body"><div class="cw-list">{items}</div></div>
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
  #__UID__-cardwrap { position:absolute; top:700px; left:130px; right:130px; }
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
  .cw-item { display:flex; align-items:center; gap:20px; font:700 34px 'Inter'; color:#0e1220; }
  .cw-check { display:flex; align-items:center; justify-content:center; width:46px; height:46px;
    border-radius:50%; background:__ACCENT__; color:#fff; font-size:28px; flex:0 0 46px; }
  .cw-chip { text-align:center; padding:56px 20px 0; }
  .cw-chipword { font-family:'Archivo Black',sans-serif; font-size:140px; line-height:1;
    color:__ACCENT__; letter-spacing:-2px; }
  .cw-chipbar { width:66%; height:16px; margin:26px auto 0; border-radius:9px; background:__ACCENT__; opacity:.25; }
  #__UID__-caps { position:absolute; top:1142px; left:90px; right:90px; height:136px;
    text-align:center; }
  .phrase { position:absolute; left:0; right:0; top:0; font:900 60px/1.12 'Inter'; color:#10131a; }
  .phrase .acc { color:__ACCENT__; }
  #__UID__-guy { position:absolute; bottom:12px; left:calc(50% - 280px); width:560px; height:630px; }
  #__UID__-guy img { width:100%; height:100%; display:block; image-rendering:pixelated; }
  #__UID__-mouth { position:absolute; background:#43261a; border-radius:45%; }
"""


def _scene_html(idx: int, scene: dict, tl_data: dict, lead: float) -> str:
    uid = f"sn{idx:02d}"
    accent = tl_data["accent_color"]
    duration = scene["duration"]
    is_first = idx == 1
    t0 = "0.000" if is_first else "0.040"
    card_start = 0.0 if is_first else 0.20
    card_dur = max(duration - card_start - 0.05, 0.5)
    guy = f"assets/character/{scene.get('gesture', 'idle')}.png"
    manifest = load_json(Path(__file__).resolve().parent.parent / "assets" / "character" / "character.json")
    mx, my, mw, mh = manifest["mouth"]["x"], manifest["mouth"]["y"], manifest["mouth"]["w"], manifest["mouth"]["h"]
    gw, gh = manifest["grid"]["w"], manifest["grid"]["h"]
    mouth_style = (f"left:{mx/gw*100:.2f}%;top:{my/gh*100:.2f}%;"
                   f"width:{mw/gw*100:.2f}%;height:{mh/gh*100:.2f}%;")
    card_html = _card_html(scene.get("card", {"kind": "plain"}), uid)
    if not card_html:  # plain: big accent word chip fills the card zone
        word = _plain_word(scene, tl_data["_titles"][idx - 1] if "_titles" in tl_data else "")
        card_html = (f'<div id="{uid}-card" class="clip hf-card" data-start="__CARDSTART__" data-duration="__CDUR__">\n'
                     f'  <div class="cw-chip"><div class="cw-chipword">{_esc(word)}</div>'
                     f'<div class="cw-chipbar"></div></div>\n'
                     f'</div>')
    card_html = (card_html.replace("__CARDSTART__", f"{card_start:.2f}")
                          .replace("__CDUR__", f"{card_dur:.2f}"))

    # caption phrases
    phrases_html, word_pops = [], []
    for pi, ph in enumerate(scene.get("phrases", [])):
        pstart = ph["t0"] + lead
        pdur = max(ph["t1"] - ph["t0"], 0.4)
        hl = (scene.get("highlight") or "").lower().replace('"', "").split()
        spans = []
        for w in ph["words"]:
            clean = w["text"].strip().strip(".,!?;:").lower()
            cls = ' class="acc"' if clean and clean in hl else ""
            spans.append(f'<span id="{uid}-w{len(word_pops)}"{cls}>{_esc(w["text"])}</span>')
            word_pops.append((f"#{uid}-w{len(word_pops)}", round(w["t0"] + lead, 3)))
        phrases_html.append(
            f'<div id="{uid}-p{pi}" class="clip phrase" data-start="{pstart:.3f}" '
            f'data-duration="{pdur:.3f}">{" ".join(spans)}</div>')

    # mouth cues: baseline (closed X) at position 0, then step tweens per cue
    cues = scene.get("cues") or [{"t0": 0, "t1": duration, "shape": "X"}]
    x = MOUTH_SHAPES["X"]
    mouth_tl = [f'  tl.fromTo("#{uid}-mouth",{{scaleX:{x[0]},scaleY:{x[1]}}},'
                f'{{scaleX:{x[0]},scaleY:{x[1]},duration:0.01,ease:"none"}},0);']
    prev = x
    for c in cues:
        s = MOUTH_SHAPES.get(c["shape"], x)
        if s == prev:
            continue
        t = round(max(c["t0"] + lead, 0.02), 3)
        mouth_tl.append(
            f'  tl.fromTo("#{uid}-mouth",{{scaleX:{prev[0]},scaleY:{prev[1]}}},'
            f'{{scaleX:{s[0]},scaleY:{s[1]},duration:0.03,ease:"none",immediateRender:false}},{t});')
        prev = s
    bob_repeat = max(int((duration - lead) / 0.68), 1) * 2

    # frame-0 (thumbnail) rule: scene 1 shows everything immediately — no opacity entrances
    if is_first:
        guy_tl = [
            f'  tl.fromTo("#{uid}-img",{{scale:0.96,y:12}},{{scale:1,y:0,duration:0.28,ease:"power3.out"}},0);',
            f'  tl.fromTo("#{uid}-img",{{y:0}},{{y:-12,duration:0.34,yoyo:true,repeat:{bob_repeat},ease:"sine.inOut",immediateRender:false}},{lead + 0.15:.2f});',
        ]
        title_tl = [f'  tl.fromTo("#{uid}-title",{{y:26}},{{y:0,duration:0.30,ease:"power3.out",immediateRender:false}},0.01);']
        kicker_tl = []
    else:
        guy_tl = [
            f'  tl.fromTo("#{uid}-img",{{scale:0.94,y:18,opacity:0}},{{scale:1,y:0,opacity:1,duration:0.30,ease:"power3.out"}},0.05);',
            f'  tl.fromTo("#{uid}-img",{{y:0}},{{y:-12,duration:0.34,yoyo:true,repeat:{bob_repeat},ease:"sine.inOut",immediateRender:false}},{lead + 0.15:.2f});',
        ]
        title_tl = [f'  tl.fromTo("#{uid}-title",{{opacity:0,y:36}},{{opacity:1,y:0,duration:0.30,ease:"power3.out"}},0.04);']
        kicker_tl = [f'  tl.fromTo("#{uid}-kicker",{{opacity:0}},{{opacity:1,duration:0.25}},0.10);']
    card_tl = ([f'  tl.fromTo("#{uid}-card",{{opacity:0,y:60}},{{opacity:1,y:0,duration:0.35,ease:"power3.out",immediateRender:false}},{card_start:.2f});']
               if card_html else [])

    html = f'''<template>
<style>{SCENE_CSS.replace("__UID__", uid).replace("__ACCENT__", accent)}</style>
<div id="root" data-composition-id="{uid}" data-width="1080" data-height="1920">
  <div id="{uid}-blob1" class="blob" data-layout-ignore
       style="width:560px;height:560px;left:-140px;top:380px;background:rgba(47,107,255,.16);"></div>
  <div id="{uid}-blob2" class="blob" data-layout-ignore
       style="width:480px;height:480px;right:-120px;top:920px;background:rgba(255,90,47,.12);"></div>
  <div id="{uid}-kicker" class="clip" data-start="{t0}" data-duration="__KDUR__"
       data-var-text="kicker">{_esc(tl_data["kicker"])}</div>
  <div id="{uid}-title" class="clip" data-start="{t0}" data-duration="__TDUR__">
    <h1 style="all:unset;display:block;">{_highlight_html(tl_data["_titles"][idx - 1], scene.get("highlight", ""))}</h1>
  </div>
  <div id="{uid}-cardwrap">{card_html}</div>
  <div id="{uid}-caps" data-track-kind="captions">{''.join(phrases_html)}</div>
  <div id="{uid}-guy" class="clip" data-start="{t0}" data-duration="__GDUR__">
    <img id="{uid}-img" src="{guy}" alt="">
    <div id="{uid}-mouth" style="{mouth_style}"></div>
  </div>
</div>
<script>
  const tl = gsap.timeline({{ paused: true }});
{chr(10).join(title_tl + kicker_tl + card_tl + guy_tl)}
  tl.fromTo("#{uid}-blob1", {{ x: 0, y: 0 }}, {{ x: 60, y: -50, duration: 4, yoyo: true, repeat: 99, ease: "sine.inOut", immediateRender: false }}, 0);
  tl.fromTo("#{uid}-blob2", {{ x: 0, y: 0 }}, {{ x: -50, y: 60, duration: 5, yoyo: true, repeat: 79, ease: "sine.inOut", immediateRender: false }}, 0);
{chr(10).join(mouth_tl)}
{chr(10).join(f'  tl.fromTo("{sel}", {{ opacity: 0, scale: 0.5, y: 16 }}, {{ opacity: 1, scale: 1, y: 0, duration: 0.16, ease: "back.out(2.2)", immediateRender: false }}, {t});' for sel, t in word_pops)}
  window.__timelines["{uid}"] = tl;
</script>
</template>'''
    html = (html.replace("__KDUR__", f"{max(duration - 0.02, 0.5):.2f}")
                .replace("__TDUR__", f"{max(duration - 0.01, 0.5):.2f}")
                .replace("__GDUR__", f"{max(duration - 0.01, 0.5):.2f}"))
    return html


def _root_html(tl_data: dict, total: float) -> str:
    hosts = []
    for sc in tl_data["scenes"]:
        vals = json.dumps({"kicker": tl_data["kicker"]}, ensure_ascii=True).replace("'", "&#39;")
        hosts.append(
            f'    <div id="{sc["id"]}" data-composition-id="{sc["id"]}" '
            f'data-composition-src="compositions/{sc["id"]}.html" '
            f'data-start="{sc["start"]:.3f}" data-duration="{sc["duration"]:.3f}" '
            f'data-track-index="1" data-track-kind="graphics" '
            f'data-width="1080" data-height="1920" data-variable-values=\'{vals}\'></div>')
    return f'''<!doctype html>
<html lang="en">
  <head><meta charset="UTF-8" /><meta name="viewport" content="width=1080, height=1920" /></head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total:.3f}"
         data-width="1080" data-height="1920">
{chr(10).join(hosts)}
      <audio id="voice" data-start="0" data-duration="{total:.3f}" data-track-index="9"
             data-volume="1" src="assets/voice/voice.mp3"></audio>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
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
    char_src = Path(__file__).resolve().parent.parent / "assets" / "character"
    char_dst = proj / "assets" / "character"
    char_dst.mkdir(parents=True, exist_ok=True)
    for png in char_src.glob("*.png"):
        shutil.copy2(png, char_dst / png.name)
    shutil.copy2(build_dir / "voice" / "voice.mp3", proj / "assets" / "voice" / "voice.mp3")

    tl_data = dict(timeline)
    # per-scene title lines: scene 1 carries the big video title; later scenes use
    # a short punch derived from their highlight/text start.
    titles = [tl_data["title"]]
    for sc in tl_data["scenes"][1:]:
        words = " ".join(w["text"] for w in sc.get("words", [])[:4])
        punch = (sc.get("highlight") or words).upper()
        titles.append(punch[:26])
    tl_data["_titles"] = titles

    (proj / "index.html").write_text(_root_html(tl_data, timeline["total"]), encoding="utf-8", newline="\n")
    for i, sc in enumerate(tl_data["scenes"], start=1):
        html = _scene_html(i, sc, tl_data, sc.get("audio_offset", 0.0))
        (proj / "compositions" / f"scene-{i:02d}.html").write_text(html, encoding="utf-8", newline="\n")

    dump_json(proj / "timeline-copy.json", timeline)
    print(f"[hf] project generated at {proj} ({len(tl_data['scenes'])} scenes, {timeline['total']:.1f}s)")
    return proj
