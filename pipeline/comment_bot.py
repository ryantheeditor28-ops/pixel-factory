"""Comment-gate auto-DM — deliver the links the videos promise.

Every video's CTA says 'Comment "REPO" and I'll send you the link(s)'. This bot
watches the comments on posted reels and sends ONE private-reply DM per matching
comment with the promised GitHub links.

How it works (Meta Messenger Platform 'private replies'):
- POST /{page-id}/messages with recipient={comment_id} and message={text} — the
  SAME endpoint works for Facebook comments and Instagram comments (IG must be a
  professional account linked to the page). Sent with the Page access token.
- Exactly one private reply per comment; only within 7 days of the comment;
  the person must reply before a normal conversation can continue.
- Standard-access apps can only DM people who have a role on the app; advanced
  access (Meta app review) lifts that. Send failures are logged with the exact
  Meta error and retried up to max_attempts on later runs (a failed send does
  not consume the one-reply budget).

Polling design (serverless factory): webhooks would be instant but need a
public always-on HTTPS endpoint — against the $0/no-server architecture. This
bot runs on a GitHub Actions cron (hourly) instead; state/dm_log.json dedupes
across runs and is committed back only when it changed.

  python pipeline/comment_bot.py             # poll + reply (CI mode)
  python pipeline/comment_bot.py --dry-run   # show actions, send nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish import env, req  # noqa: E402  (same retry/creds plumbing as publishing)

ROOT = Path(__file__).resolve().parent.parent
POSTS_PATH = ROOT / "state" / "posts.json"
DM_LOG_PATH = ROOT / "state" / "dm_log.json"


def _load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def _save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _graph() -> str:
    return f"https://graph.facebook.com/{env('GRAPH_VERSION') or 'v21.0'}"


# ---- registry: which posts exist, what they promised -------------------------

def script_cta() -> dict:
    """keyword + github links + title from build/script.json (written at publish time)."""
    p = ROOT / "build" / "script.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    tids = [t for t in (d.get("topic_ids") or []) if t]
    if not tids:
        tid = d.get("topic_id") or ""
        tids = [t for t in str(tid).replace("listicle:", "").split("+") if t]
    links = [f"https://github.com/{t}" for t in tids]
    return {"keyword": str(d.get("comment_keyword") or "").upper(),
            "links": links, "title": str(d.get("title") or "")}


def record_post(platform: str, post_id: str, permalink: str, video: str) -> None:
    """Registry entry at publish time (publish.py calls this). Idempotent."""
    if not post_id:
        return
    registry = _load(POSTS_PATH, [])
    if any(e.get("platform") == platform and e.get("post_id") == post_id
           for e in registry):
        return
    cta = script_cta()
    registry.append({
        "video": video,
        "platform": platform,
        "post_id": post_id,
        "permalink": permalink,
        "keyword": cta.get("keyword") or None,
        "links": cta.get("links") or [],
        "title": cta.get("title") or "",
        "posted_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    })
    _save(POSTS_PATH, registry[-100:])


def backfill_from_posted(cfg: dict) -> list[dict]:
    """Registry entries for reels published before this feature existed: join
    state/posted.json with state/state.json (per-video repos). IG media ids are
    resolved once via the media list. Old keywords are unknown -> None (the bot
    then matches any configured trigger keyword)."""
    registry = _load(POSTS_PATH, [])
    known = {(e.get("platform"), e.get("post_id")) for e in registry}
    posted = _load(ROOT / "state" / "posted.json", [])
    state = _load(ROOT / "state" / "state.json", {})
    by_stamp = {v.get("stamp"): v for v in state.get("videos", [])}

    max_age = float(cfg.get("max_age_days", 7))
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=max_age)

    ig_ids: dict[str, str] = {}
    token = env("IG_ACCESS_TOKEN")
    if any(e["platform"] == "instagram" for e in posted):
        r = req("GET", f"{_graph()}/{env('IG_USER_ID')}/media",
                params={"fields": "id,permalink", "limit": 100, "access_token": token})
        for m in (r.json().get("data") or []) if r.status_code < 400 else []:
            ig_ids[str(m.get("permalink") or "").rstrip("/")] = str(m.get("id") or "")

    added = False
    for e in posted:
        try:
            when = dt.datetime.fromisoformat(e.get("posted_at", ""))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt.UTC)
        if when < cutoff:
            continue  # outside the private-reply window anyway
        url = str(e.get("url") or "").rstrip("/")
        if e.get("platform") == "facebook":
            post_id = url.split("/")[-1]
        else:
            post_id = ig_ids.get(url, "")
        if not post_id or (e["platform"], post_id) in known:
            continue
        v = by_stamp.get(str(e.get("video", "")).replace("video-", "").replace(".mp4", ""), {})
        topic = str(v.get("topic") or "")
        tids = topic.replace("listicle:", "").split("+") if topic else []
        links = [f"https://github.com/{t}" for t in tids if t and "/" in t]
        registry.append({
            "video": e.get("video"), "platform": e["platform"], "post_id": post_id,
            "permalink": url, "keyword": None, "links": links,
            "title": v.get("title") or "",
            "posted_at": e.get("posted_at"),
        })
        known.add((e["platform"], post_id))
        added = True
    if added:
        _save(POSTS_PATH, registry[-100:])
    return registry


# ---- comment fetching + matching ---------------------------------------------

def fetch_comments(entry: dict, limit: int) -> list[dict]:
    """Comments on one post. FB uses the page token, IG the IG user token."""
    if entry["platform"] == "facebook":
        token = env("FB_PAGE_ACCESS_TOKEN")
        fields = "id,message,from,created_time"
    else:
        token = env("IG_ACCESS_TOKEN")
        fields = "id,text,from,timestamp"
    r = req("GET", f"{_graph()}/{entry['post_id']}/comments",
            params={"fields": fields, "limit": limit, "access_token": token})
    if r.status_code >= 400:
        raise RuntimeError(f"comments read {entry['platform']}:{entry['post_id']} "
                           f"HTTP {r.status_code}: {r.text[:200]}")
    return (r.json().get("data") or [])


def _keyword_regex(keywords: list[str]) -> re.Pattern:
    alts = "|".join(re.escape(k) for k in keywords if k)
    return re.compile(rf"(?i)(?<![a-z0-9])({alts})(?![a-z0-9])")


def comment_text(c: dict) -> str:
    return str(c.get("message") or c.get("text") or "")


def comment_from_id(c: dict, platform: str) -> str:
    frm = c.get("from") or {}
    return str(frm.get("id") or "")


def comment_time(c: dict) -> dt.datetime | None:
    raw = c.get("created_time") or c.get("timestamp")
    if not raw:
        return None
    try:
        t = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.UTC)
    except ValueError:
        return None


# ---- the DM ------------------------------------------------------------------

def compose_dm(entry: dict) -> str:
    links = [l for l in (entry.get("links") or []) if l]
    if len(links) > 1:
        lines = ["Here are the links I promised 🔗"]
        lines += [f"{i}. {l}" for i, l in enumerate(links, start=1)]
    elif links:
        lines = ["Here's the link I promised 🔗", links[0]]
    else:
        lines = ["Thanks for commenting! 🚀"]
    lines.append("New drop every day — follow so you don't miss it.")
    return "\n".join(lines)


def send_dm(comment_id: str, text: str) -> tuple[bool, str]:
    """One private reply. Page token for BOTH platforms (Messenger Platform rule)."""
    r = req("POST", f"{_graph()}/{env('FB_PAGE_ID')}/messages", json={
        "recipient": {"comment_id": comment_id},
        "message": {"text": text},
    }, timeout=60)
    if r.status_code < 400:
        return True, ""
    return False, f"HTTP {r.status_code}: {r.text[:300]}"


# ---- main --------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="log actions, send nothing")
    args = ap.parse_args()

    cfg = _load(ROOT / "config.json", {})
    dm_cfg = cfg.get("comment_dm") or {}
    keywords = [k.upper() for k in (dm_cfg.get("keywords") or ["REPO"]) if k]
    max_age_days = float(dm_cfg.get("max_age_days", 7))
    comment_limit = int(dm_cfg.get("comment_limit", 50))
    max_attempts = int(dm_cfg.get("max_attempts", 3))

    if not env("FB_PAGE_ID") or not env("FB_PAGE_ACCESS_TOKEN"):
        print("[dm] page credentials not set — nothing to do")
        return 0

    registry = backfill_from_posted(dm_cfg)
    dm_log = _load(DM_LOG_PATH, {})
    rx = _keyword_regex(keywords)
    now = dt.datetime.now(dt.UTC)
    sent = failed = skipped = 0
    changed = False

    for entry in registry:
        platform = entry.get("platform")
        if platform not in ("facebook", "instagram"):
            continue
        try:
            comments = fetch_comments(entry, comment_limit)
        except RuntimeError as exc:
            print(f"[dm] {exc}")
            continue
        kws = [entry["keyword"]] if entry.get("keyword") else keywords
        krx = _keyword_regex(kws)
        for c in comments:
            cid = str(c.get("id") or "")
            if not cid:
                continue
            rec = dm_log.get(cid) or {}
            if rec.get("status") == "sent":
                continue
            if rec.get("status") == "expired":
                continue
            if int(rec.get("attempts", 0)) >= max_attempts:
                continue
            when = comment_time(c)
            if when and (now - when) > dt.timedelta(days=max_age_days):
                dm_log[cid] = {**rec, "status": "expired", "video": entry.get("video"),
                               "platform": platform}
                changed = True
                continue
            # never DM the page/IG account itself
            self_id = env("FB_PAGE_ID") if platform == "facebook" else env("IG_USER_ID")
            if comment_from_id(c, platform) == self_id:
                continue
            text = comment_text(c)
            if not krx.search(text):
                continue
            dm_text = compose_dm(entry)
            if args.dry_run:
                print(f"[dm] DRY-RUN would reply to {platform} comment {cid} "
                      f"({text[:40]!r}) -> {entry['permalink']}")
                skipped += 1
                continue
            ok, err = send_dm(cid, dm_text)
            if ok:
                sent += 1
                dm_log[cid] = {"status": "sent", "video": entry.get("video"),
                               "platform": platform, "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
                print(f"[dm] replied to {platform} comment {cid} on {entry['permalink']}")
            else:
                failed += 1
                dm_log[cid] = {**rec, "status": "failed", "error": err,
                               "attempts": int(rec.get("attempts", 0)) + 1,
                               "video": entry.get("video"), "platform": platform,
                               "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
                print(f"[dm] FAILED {platform} comment {cid}: {err}")
            changed = True

    if changed and not args.dry_run:
        _save(DM_LOG_PATH, dm_log)
    print(f"[dm] done: {sent} sent, {failed} failed, {skipped} dry-run skips, "
          f"{len(registry)} posts watched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
