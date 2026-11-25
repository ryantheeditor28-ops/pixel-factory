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
import os
import random
import urllib.parse
import urllib.request

from llm import ask_json, dump_json, load_json

BUILD = None  # set by caller
ROOT = None

GESTURE_FLOW = ["point", "chest", "thumbs", "think", "shrug", "spread", "wave", "point"]


def _http_json(url: str, timeout: int = 30):
    headers = {
        "User-Agent": "pixel-factory/0.1",
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GITHUB_TOKEN")  # CI: workflow's own token, 5k req/hr
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
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


def pick_topics(used: set[str], n: int = 3) -> list[dict]:
    """n fresh trending repos for one listicle video. [] if GitHub is unreachable."""
    since = (dt.datetime.now(dt.UTC) - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    url = ("https://api.github.com/search/repositories?q=created:>=" + since +
           "&sort=stars&order=desc&per_page=40")
    try:
        data = _http_json(url)
        items = data.get("items", [])
    except Exception:
        return []
    fresh = [r for r in items if r.get("full_name") and r["full_name"] not in used
             and (r.get("stargazers_count") or 0) >= 100
             and not r.get("fork")]
    if len(fresh) < n:
        return []
    random.shuffle(fresh)
    return [{
        "id": r["full_name"],
        "name": r["full_name"],
        "desc": (r.get("description") or "").strip(),
        "stars": r.get("stargazers_count", 0),
        "lang": r.get("language") or "",
        "url": r.get("html_url", ""),
        "topics": r.get("topics") or [],
    } for r in fresh[:n]]


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
            {"gesture": "thumbs", "card": {"kind": "demo",
                                           "cmd": "make a viral video about " + name.split("/")[-1]},
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


def fallback_list_script(topics: list[dict], keyword: str, cfg: dict) -> dict:
    """Deterministic listicle script (LLM down): hook price card -> N tool cards -> CTA.
    Shape C from the Marktalksai winner catalogue (16.3K views): struck-price hook,
    numbered open-source tool cards, Comment REPO gate."""
    n = len(topics)
    price = "$" + str(27 * n + 66)  # plausible monthly stack cost, deterministic
    segments = [{
        "gesture": "point",
        "card": {"kind": "price", "price": price, "zero": "$0",
                 "label": f"PER MONTH FOR {n} TOOLS"},
        "text": f"These {n} free open-source tools quietly replace {price} a month "
                f"of software. Number {n} is so new that almost nobody has found it.",
    }]
    for i, t in enumerate(topics, start=1):
        stars = _fmt_stars(t["stars"])
        tail = {1: "Open source, zero cost, no account.",
                2: "Also free. It runs entirely on your machine.",
                3: "And it is 100 percent free forever."}.get(i, "Fully open source.")
        segments.append({
            "gesture": ["point", "thumbs", "think"][min(i - 1, 2)],
            "card": {"kind": "tool", "n": i, "name": t["name"], "stars": stars,
                     "desc": _trim_words(t["desc"] or "a brand new open-source project", 80),
                     "lang": t["lang"]},
            "text": f"Number {i}: {t['name'].split('/')[-1]}. "
                    f"{_trim_words(t['desc'] or 'A brand new open-source project', 90)}. {tail}",
        })
    segments.append({
        "gesture": "wave",
        "card": {"kind": "comment", "keyword": keyword},
        "text": f"Comment {keyword} and I will send you all {n} links. "
                f"Follow for one hidden gem every single day.",
    })
    return {
        "format": "listicle",
        "topic_id": "listicle:" + "+".join(t["id"] for t in topics),
        "topic_ids": [t["id"] for t in topics],
        "title": f"{n} FREE TOOLS",
        "kicker": "OPEN SOURCE DROPS",
        "comment_keyword": keyword,
        "accent_word": "FREE",
        "segments": segments,
        "source": "fallback",
    }


LIST_PROMPT = """You write scripts for a viral faceless tech channel in the exact style of
the top-performing listicle format: a struck-price hook, then numbered open-source
tools, then a comment gate.

Write a {target}second vertical video script covering these {n} trending GitHub repositories:

{topic_block}

Rules:
- Exactly {nseg} segments. Each segment is 1-3 spoken sentences (max ~50 words).
- Delivery: CONFIDENT and declarative. Short punchy sentences. State facts, never
  hedge — no "maybe", "perhaps", "I think", "kind of". No filler words.
- Segment 1 is the HOOK: how much per month these free tools replace. "price" = a
  realistic combined USD monthly cost of the paid equivalents, like "$148".
- Segments 2..{ntools}: ONE tool each, in order. Card kind "tool" with n={seq} and that
  repo's fields. Say "Number 1/2/3" out loud. One surprising or concrete detail each.
- Final segment: CTA with card kind "comment" telling viewers to comment "{keyword}".
- "highlight" = 1-3 WORDS from that segment's text to accent on screen.
- "gesture" per segment, one of: point, chest (hand-on-chest), thumbs, shrug, wave, think, spread (arms wide).
- Fill every field a kind needs: price (price+zero+label), tool (n+name+stars+desc+lang),
  comment (keyword).

Respond with ONLY valid JSON, no markdown:
{{
  "title": "MAX 4 WORDS FOR THE TITLE CARD",
  "kicker": "2-3 WORD CATEGORY LABEL",
  "segments": [
    {{"gesture": "...", "highlight": "...",
      "card": {{"kind": "...", "price": "...", "zero": "$0", "label": "...", "n": 1, "name": "...", "stars": "...", "desc": "...", "lang": "...", "keyword": "..."}} ,
      "text": "..."}}
  ]
}}
Keep every string in English."""


def llm_list_script(topics: list[dict], keyword: str, cfg: dict, seed: int) -> dict | None:
    n = len(topics)
    topic_block = "\n\n".join(
        f"repo {i}: {t['name']}\ndescription: {t['desc'] or 'n/a'}\n"
        f"stars: {_fmt_stars(t['stars'])}\nlanguage: {t['lang'] or 'n/a'}"
        for i, t in enumerate(topics, start=1))
    prompt = LIST_PROMPT.format(target=cfg.get("target_duration_sec", 45), n=n,
                                nseg=n + 2, ntools=n, seq="{1..%d}" % n,
                                topic_block=topic_block, keyword=keyword)
    data = ask_json(prompt, seed=seed)
    if not isinstance(data, dict):
        return None
    segs = data.get("segments")
    if not isinstance(segs, list) or not (n + 1 <= len(segs) <= n + 3):
        return None
    ok_gestures = {"point", "chest", "thumbs", "shrug", "wave", "think", "spread"}
    price = _scrub(data.get("price", "") or "") or f"${27 * n + 66}"
    if not price.startswith("$"):
        price = "$" + price.lstrip("$")
    clean = []
    for i, s in enumerate(segs):
        if not isinstance(s, dict) or not isinstance(s.get("text"), str) or len(s["text"].strip()) < 10:
            return None
        card = s.get("card") if isinstance(s.get("card"), dict) else {"kind": "plain"}
        kind = card.get("kind")
        pos = i  # 0=hook, 1..n=tools, last=cta
        if pos == 0:
            card = {"kind": "price", "price": _scrub(card.get("price") or price)[:8],
                    "zero": "$0", "label": _scrub(card.get("label") or f"PER MONTH FOR {n} TOOLS").upper()[:30]}
        elif 1 <= pos <= n and kind == "tool":
            t = topics[pos - 1]
            card["n"] = pos
            card["name"] = _scrub(card.get("name") or t["name"])
            card["stars"] = _scrub(card.get("stars") or _fmt_stars(t["stars"]))
            card["desc"] = _trim_words(card.get("desc") or t["desc"] or "", 90)
            card["lang"] = _scrub(card.get("lang") or t["lang"] or "")
        elif pos >= n + 1:
            card = {"kind": "comment", "keyword": keyword}
        else:
            card = {"kind": "tool", "n": pos, "name": topics[pos - 1]["name"],
                    "stars": _fmt_stars(topics[pos - 1]["stars"]),
                    "desc": _trim_words(topics[pos - 1]["desc"] or "", 90),
                    "lang": topics[pos - 1]["lang"] or ""}
        clean.append({
            "gesture": s.get("gesture") if s.get("gesture") in ok_gestures else GESTURE_FLOW[i % len(GESTURE_FLOW)],
            "highlight": _scrub(s.get("highlight") or "")[:40],
            "card": card,
            "text": _scrub(s["text"]),
        })
    # guarantee the CTA lands as the last segment
    clean = clean[:n + 2]
    if clean[-1]["card"].get("kind") != "comment":
        clean = clean[:n] + [{
            "gesture": "wave", "highlight": keyword, "card": {"kind": "comment", "keyword": keyword},
            "text": f"Comment {keyword} and I will send you all {n} links. Follow for one drop every day.",
        }]
    title = _scrub(data.get("title", ""))[:30] or f"{n} FREE TOOLS"
    return {
        "format": "listicle",
        "topic_id": "listicle:" + "+".join(t["id"] for t in topics),
        "topic_ids": [t["id"] for t in topics],
        "title": title,
        "kicker": _scrub(data.get("kicker", ""))[:24] or "OPEN SOURCE DROPS",
        "comment_keyword": keyword,
        "accent_word": title.split()[0] if title.split() else "",
        "segments": clean,
        "source": "llm",
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
- {nseg} segments. Each segment is 1-3 spoken sentences (max ~50 words per segment).
- Delivery: CONFIDENT and declarative. Short punchy sentences. State facts, never
  hedge — no "maybe", "perhaps", "I think", "kind of". No filler words.
- Segment 1 is the HOOK: bold claim about the repo, no greeting, no intro.
- Middle segments: what it does, why it is blowing up, one surprising detail.
- Final segment: CTA telling viewers to comment "{keyword}" to get the link + follow.
- Spoken text only in "text" fields: plain words, numbers as words where natural.
- "highlight" = 1-3 WORDS from that segment's text to accent-color on screen.
- "gesture" per segment, one of: point, chest (hand-on-chest), thumbs, shrug, wave, think, spread (arms wide).
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


def _trim_words(s: str, limit: int) -> str:
    """Scrubbed text cut at a word boundary — never mid-word."""
    s = _scrub(s)
    return s if len(s) <= limit else s[:limit].rsplit(" ", 1)[0]


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
    ok_gestures = {"point", "chest", "thumbs", "shrug", "wave", "think", "spread"}
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
    # Pin the CTA accent to the configured keyword — the LLM once highlighted
    # "comment comments" over a WRANGLE gate, which the chip then rendered.
    if clean and keyword and keyword.lower() in clean[-1]["text"].lower():
        clean[-1]["highlight"] = keyword
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
    seed = random.randint(1, 10**6)
    every = max(int(cfg.get("listicle_every", 2) or 0), 0)
    videos_made = len(state.get("videos", []))
    # format rotation: every Nth video is the listicle (Marktalksai shape C —
    # the 16.3K-view "open-source tools replace paid ones" winner format)
    mode = "listicle" if every and (videos_made % every) == every - 1 else "single"
    if mode == "listicle":
        topics = pick_topics(used, 3)
        if topics:
            # the winner reel gates with "Comment REPO" — the keyword matches the format
            keyword = "REPO" if "REPO" in cfg.get("comment_keywords", []) \
                else random.choice(cfg.get("comment_keywords", ["DECODE"]))
            script = (llm_list_script(topics, keyword, cfg, seed)
                      or fallback_list_script(topics, keyword, cfg))
        else:
            topic = pick_topic(used)
            keyword = random.choice(cfg.get("comment_keywords", ["DECODE"]))
            script = fallback_script(topic, keyword, cfg)
            mode = "single"
    else:
        topic = pick_topic(used)
        keyword = random.choice(cfg.get("comment_keywords", ["DECODE"]))
        script = (llm_script(topic, keyword, cfg, seed) if topic else None) \
            or fallback_script(topic, keyword, cfg)
    script["accent_color"] = (cfg.get("accent_color_hot", "#ff5a2f") if mode == "listicle"
                              else cfg.get("accent_color", "#2f6bff"))
    out = build_dir / "script.json"
    dump_json(out, script)
    print(f"[script] source={script['source']} mode={mode} topic={script['topic_id']} "
          f"segments={len(script['segments'])} keyword={script['comment_keyword']}")
    return script


if __name__ == "__main__":
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    main(root / "build", load_json(root / "config.json"), {})
