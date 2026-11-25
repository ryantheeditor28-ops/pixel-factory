"""Stage 1 — pick a good topic and write the video script.

Topic source (free, no key): GitHub search API for repos created in the last
7 days sorted by stars — the exact "trending repo this week" format that wins
on the template channel. The LLM (free, keyless) turns one repo into a punchy
45-second script. If the LLM is down, a deterministic template script is built
from the repo metadata so the pipeline NEVER stalls.

Output: build/script.json
"""
from __future__ import annotations

import datetime as dt
import json
import random
import urllib.parse
import urllib.request

from llm import ask_json, dump_json, load_json

BUILD = None  # set by caller
ROOT = None

GESTURE_FLOW = ["point", "point", "thumbs", "think", "shrug", "thumbs", "wave", "point"]


def _http_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "pixel-factory/0.1",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)  # type: ignore[name-defined]


def pick_topic(used: set[str]) -> dict | None:
    """A trending young repo we haven't used yet. None if GitHub is unreachable."""
    since = (dt.datetime.now(dt.UTC) - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    url = ("https://api.github.com/search/repositories?q=created:>=" + since +
           "&sort=stars&order=desc&per_page=25")
    try:
        data = _http_json(url)
        items = data.get("items", [])
    except Exception:
        return None
    fresh = [r for r in items if r.get("full_name") and r["full_name"] not in used
             and (r.get("stargazers_count") or 0) >= 100
             and not r.get("fork")]
    if not fresh:
        return None
    random.shuffle(fresh)
    r = fresh[0]
    return {
        "id": r["full_name"],
        "name": r["full_name"],
        "desc": (r.get("description") or "").strip(),
        "stars": r.get("stargazers_count", 0),
        "lang": r.get("language") or "",
        "url": r.get("html_url", ""),
        "topics": r.get("topics") or [],
    }


def _fmt_stars(n) -> str:
    try:
        n = int(n)
    except Exception:
        return str(n)
    return f"{n/1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def fallback_script(topic: dict | None, keyword: str, cfg: dict) -> dict:
    """Deterministic script when the LLM is unreachable. Still follows the
    winning template shape: hook -> what/why -> proof -> CTA."""
    if topic:
        name = topic["name"]
        desc = topic["desc"] or "a brand new open-source project"
        stars = _fmt_stars(topic["stars"])
        segments = [
            {"gesture": "point", "card": {"kind": "repo", "name": name, "stars": stars,
                                          "desc": desc, "lang": topic["lang"]},
             "text": f"The number one new repo on GitHub right now is {name.split('/')[-1]}. "
                     f"Thousands of stars in seven days. Here is why everyone is watching it."},
            {"gesture": "thumbs", "card": {"kind": "plain"},
             "text": f"It does one thing extremely well: {desc[:110]}. "
                     f"No bloat, no subscriptions, just code that works."},
            {"gesture": "think", "card": {"kind": "stats", "big": stars, "label": "STARS IN 7 DAYS"},
             "text": f"And it is not hype. {stars} developers starred it in a single week, "
                     f"which puts it in the top one percent of new projects."},
            {"gesture": "point", "card": {"kind": "terminal", "lines": [
                "git clone " + topic["url"], "cd " + name.split("/")[1], "./run  # that's it"]},
             "text": f"You can try it in one line. Clone it, run it, done. "
                     f"Link in the comments."},
            {"gesture": "wave", "card": {"kind": "plain"},
             "text": f"Comment {keyword} and I will send you the link. "
                     f"Follow for one hidden gem every single day."},
        ]
        title_words = name.split("/")[-1].upper()
    else:
        segments = [
            {"gesture": "point", "card": {"kind": "plain"},
             "text": "Three free AI tools replaced my entire workflow this week. "
                     "Number three will save you hours."},
            {"gesture": "thumbs", "card": {"kind": "plain"},
             "text": "The first one writes code while you sleep. "
                     "The second one turns any video into a template."},
            {"gesture": "think", "card": {"kind": "plain"},
             "text": "And the third one is so new that almost nobody has found it yet."},
            {"gesture": "wave", "card": {"kind": "plain"},
             "text": f"Comment {keyword} and I will send you all three. Follow so you don't miss the next drop."},
        ]
        title_words = "3 FREE AI TOOLS"
        name = "daily-drops"
    return {
        "topic_id": name,
        "title": title_words[:28],
        "kicker": "GITHUB SPOTLIGHT" if topic else "AI TOOLBOX",
        "comment_keyword": keyword,
        "accent_word": title_words.split()[0] if title_words.split() else "",
        "segments": segments,
        "source": "fallback",
    }


PROMPT = """You write scripts for a viral faceless tech channel in the exact style of
the top-performing format: a hook in the first sentence, short spoken lines,
concrete numbers, zero fluff, one comment-bait CTA at the end.

Write a {target}second vertical video script about this trending GitHub repository:

name: {name}
description: {desc}
stars right now: {stars}
language: {lang}
url: {url}

Rules:
- {nseg} segments. Each segment is 1-3 spoken sentences (max ~55 words per segment).
- Segment 1 is the HOOK: bold claim about the repo, no greeting, no intro.
- Middle segments: what it does, why it is blowing up, one surprising detail.
- Final segment: CTA telling viewers to comment "{keyword}" to get the link + follow.
- Spoken text only in "text" fields: plain words, numbers as words where natural.
- "highlight" = 1-3 WORDS from that segment's text to accent-color on screen.
- "gesture" per segment, one of: point, thumbs, shrug, wave, think.
- "card.kind" per segment, one of: repo (segment 1), stats (a big number), terminal (2-3 shell lines), list (2-3 short items), demo (a "Claude Code builds the video" terminal with a progress bar and timeline - use for exactly ONE middle segment), plain.
- Use "plain" at most once, only for the final CTA. Middle segments prefer stats, terminal, list or demo. Always FILL the fields a kind needs (stats: big+label, terminal: lines, list: items, repo: name+stars+desc+lang, demo: cmd).

Respond with ONLY valid JSON, no markdown:
{{
  "title": "MAX 4 WORDS FOR THE TITLE CARD",
  "kicker": "2-3 WORD CATEGORY LABEL",
  "segments": [
    {{"gesture": "...", "highlight": "...",
      "card": {{"kind": "...", "name": "...", "stars": "...", "desc": "...", "lang": "...", "big": "...", "label": "...", "lines": ["..."], "items": ["..."], "cmd": "..."}},
      "text": "..."}}
  ]
}}
Omit card fields that a kind doesn't need. Keep every string in English."""


def _scrub(t) -> str:
    """Single-line, mojibake-proof text (replacement chars and odd hyphens out)."""
    s = str(t).replace("\ufffd", " ").replace("\u2011", "-") \
             .replace("\u2013", "-").replace("\u2014", "-")
    return " ".join(s.split())


def llm_script(topic: dict, keyword: str, cfg: dict, seed: int) -> dict | None:
    nseg = 5
    target = cfg.get("target_duration_sec", 45)
    prompt = PROMPT.format(target=target, name=topic["name"], desc=topic["desc"] or "n/a",
                           stars=_fmt_stars(topic["stars"]), lang=topic["lang"] or "n/a",
                           url=topic["url"], nseg=nseg, keyword=keyword)
    data = ask_json(prompt, seed=seed)
    if not isinstance(data, dict):
        return None
    segs = data.get("segments")
    if not isinstance(segs, list) or not (3 <= len(segs) <= 7):
        return None
    clean = []
    ok_gestures = {"point", "thumbs", "shrug", "wave", "think"}
    for i, s in enumerate(segs):
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or len(s["text"].strip()) < 10:
            return None
        card = s.get("card") if isinstance(s.get("card"), dict) else {"kind": "plain"}
        if card.get("kind") not in {"repo", "stats", "terminal", "list", "demo", "plain"}:
            card = {"kind": "plain"}
        # The LLM routinely underfills card fields — enforce required values per
        # kind from repo metadata so no card ever renders empty.
        stars_fmt = _fmt_stars(topic["stars"])
        if card["kind"] == "repo":
            card["name"] = _scrub(card.get("name") or topic["name"])
            card["stars"] = _scrub(card.get("stars") or stars_fmt)
            card["desc"] = _scrub(card.get("desc") or topic["desc"] or "")[:100]
            card["lang"] = _scrub(card.get("lang") or topic["lang"] or "")
        elif card["kind"] == "stats":
            card["big"] = _scrub(card.get("big") or stars_fmt)
            card["label"] = _scrub(card.get("label") or "STARS ON GITHUB").upper()[:28]
        elif card["kind"] == "terminal":
            url = topic["url"]
            lines = [_scrub(l).replace("<repo>", url).replace("<reponame>", topic["name"])
                     for l in card.get("lines", []) if _scrub(l)]
            card["lines"] = lines or [
                f"git clone {topic['url']}.git",
                f"cd {topic['name'].split('/')[-1]}",
                f"# {stars_fmt} stars - runs offline",
            ]
        elif card["kind"] == "list":
            items = [_scrub(i) for i in card.get("items", []) if _scrub(i)]
            card["items"] = items or ["100% free & open source", "No account needed",
                                      "Works fully offline"]
        elif card["kind"] == "demo":
            fallback_cmd = f"make a viral video about {topic['name'].split('/')[-1]}"
            card["cmd"] = _scrub(card.get("cmd") or fallback_cmd)[:64]
        clean.append({
            "gesture": s.get("gesture") if s.get("gesture") in ok_gestures else GESTURE_FLOW[i % len(GESTURE_FLOW)],
            "highlight": _scrub(s.get("highlight") or "")[:40],
            "card": card,
            "text": _scrub(s["text"]),
        })
    # The demo scene ("Claude Code builds your video") is a signature beat of the
    # template — guarantee exactly one in the middle even if the LLM skipped it.
    if len(clean) >= 4 and not any(c["card"].get("kind") == "demo" for c in clean[1:-1]):
        clean[3]["card"] = {"kind": "demo",
                            "cmd": f"make a viral video about {topic['name'].split('/')[-1]}"}
    title = _scrub(data.get("title", ""))[:30] or topic["name"].split("/")[-1].upper()
    return {
        "topic_id": topic["id"],
        "title": title,
        "kicker": _scrub(data.get("kicker", ""))[:24] or "GITHUB SPOTLIGHT",
        "comment_keyword": keyword,
        "accent_word": title.split()[0] if title.split() else "",
        "segments": clean,
        "source": "llm",
    }


def main(build_dir, cfg, state) -> dict:
    global BUILD
    BUILD = build_dir
    used = set(state.get("used_topics", []))
    topic = pick_topic(used)
    seed = random.randint(1, 10**6)
    keyword = random.choice(cfg.get("comment_keywords", ["DECODE"]))
    script = (llm_script(topic, keyword, cfg, seed) if topic else None) \
        or fallback_script(topic, keyword, cfg)
    script["accent_color"] = cfg.get("accent_color", "#2f6bff")
    out = build_dir / "script.json"
    dump_json(out, script)
    print(f"[script] source={script['source']} topic={script['topic_id']} "
          f"segments={len(script['segments'])} keyword={keyword}")
    return script


if __name__ == "__main__":
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    main(root / "build", load_json(root / "config.json"), {})
