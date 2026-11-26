"""Comment-gate auto-DM — deliver the links the videos promise.

Every video's CTA says 'Comment "REPO" and I'll send you the link(s)'. This bot
watches the comments on posted reels/videos and sends ONE reply per matching
comment with the promised GitHub links.

Facebook + Instagram (Meta Messenger Platform 'private replies'):
- POST /{page-id}/messages with recipient={comment_id} and message={text} — the
  SAME endpoint works for Facebook comments and Instagram comments (IG must be a
  professional account linked to the page). Sent with the Page access token.
- Exactly one private reply per comment; only within 7 days of the comment;
  the person must reply before a normal conversation can continue.
- Standard-access apps can only DM people who have a role on the app; advanced
  access (Meta app review) lifts that. Send failures are logged with the exact
  Meta error and retried up to max_attempts on later runs (a failed send does
  not consume the one-reply budget).

YouTube (Data API v3, OAuth refresh token — no DMs exist there):
- ONE commentThreads.list call per run with allThreadsRelatedToChannelId (1-2
  quota units) covers every registered video; replies go through
  comments.insert with parentId (50 units per reply) as public replies —
  the native mechanism and good for engagement.
- Same dedupe/retry/age rules, shared quota bucket with the uploads.
- The threads listing is eventually consistent: a brand-new comment can take
  some minutes to appear, so fresh comments are answered on a later run
  (the bot's 2x/hour cadence + the 7-day window make that a non-issue).

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
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish import env, req  # noqa: E402  (same retry/creds plumbing as publishing)
from publish import yt_access_token  # noqa: E402

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
        elif e.get("platform") == "youtube":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            post_id = (q.get("v") or [""])[0]
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
    follow = "subscribe" if entry.get("platform") == "youtube" else "follow"
    lines.append(f"New drop every day — {follow} so you don't miss it.")
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


# ---- youtube (Data API v3) ----------------------------------------------------

YT_API = "https://www.googleapis.com/youtube/v3"


def yt_configured() -> bool:
    return bool(env("YT_CLIENT_ID") and env("YT_CLIENT_SECRET") and env("YT_REFRESH_TOKEN"))


def yt_api(token: str, path: str, *, params: dict | None = None,
           json_body: dict | None = None, method: str = "GET") -> requests.Response:
    url = f"{YT_API}/{path.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return req(method, url, json=json_body, timeout=60,
               headers={"Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=UTF-8"})


def yt_channel_id(token: str) -> str:
    r = yt_api(token, "channels", params={"part": "id", "mine": "true"})
    if r.status_code >= 400:
        raise RuntimeError(f"yt channels.list HTTP {r.status_code}: {r.text[:200]}")
    items = (r.json() or {}).get("items") or []
    if not items:
        raise RuntimeError("yt channels.list returned no channel for this token")
    return str(items[0]["id"])


def yt_fetch_channel_comments(token: str, channel_id: str, limit: int) -> list[dict]:
    """Top-level comments across ALL of the channel's videos in one paginated
    call (1 quota unit per page), normalized to the FB/IG comment shape."""
    out: list[dict] = []
    page_token: str | None = None
    while len(out) < limit:
        params = {"part": "snippet",
                  "allThreadsRelatedToChannelId": channel_id,
                  "order": "time", "maxResults": 100}
        if page_token:
            params["pageToken"] = page_token
        r = yt_api(token, "commentThreads", params=params)
        if r.status_code >= 400:
            raise RuntimeError(f"yt commentThreads.list HTTP {r.status_code}: {r.text[:200]}")
        data = r.json() or {}
        for th in (data.get("items") or []):
            top = ((th.get("snippet") or {}).get("topLevelComment")) or {}
            sn = top.get("snippet") or {}
            out.append({
                "id": str(top.get("id") or ""),
                "text": str(sn.get("textOriginal") or sn.get("textDisplay") or ""),
                "from": {"id": str((sn.get("authorChannelId") or {}).get("value") or "")},
                "created_time": str(sn.get("publishedAt") or ""),
                "videoId": str(sn.get("videoId") or ""),
            })
            if len(out) >= limit:
                break
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return out


def yt_reply(token: str, comment_id: str, text: str) -> tuple[bool, str]:
    """Public reply on the comment (YouTube's native mechanism — no DMs)."""
    r = yt_api(token, "comments", params={"part": "snippet"}, method="POST",
               json_body={"snippet": {"parentId": comment_id, "textOriginal": text}})
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

    fb_ready = bool(env("FB_PAGE_ID") and env("FB_PAGE_ACCESS_TOKEN"))
    yt_ready = yt_configured()
    if not fb_ready and not yt_ready:
        print("[dm] no platform credentials set — nothing to do")
        return 0

    registry = backfill_from_posted(dm_cfg)
    dm_log = _load(DM_LOG_PATH, {})
    now = dt.datetime.now(dt.UTC)
    stats = {"sent": 0, "failed": 0, "skipped": 0}
    changed = False

    def handle(c: dict, platform: str, entry: dict, self_id: str, krx: re.Pattern,
               send) -> None:
        """Dedupe/age/self/keyword gate + one reply — shared by every platform."""
        nonlocal changed
        cid = str(c.get("id") or "")
        if not cid:
            return
        rec = dm_log.get(cid) or {}
        if rec.get("status") in ("sent", "expired"):
            return
        if int(rec.get("attempts", 0)) >= max_attempts:
            return
        when = comment_time(c)
        if when and (now - when) > dt.timedelta(days=max_age_days):
            dm_log[cid] = {**rec, "status": "expired", "video": entry.get("video"),
                           "platform": platform}
            changed = True
            return
        # never reply to our own account
        if comment_from_id(c, platform) == self_id:
            return
        if not krx.search(comment_text(c)):
            return
        dm_text = compose_dm(entry)
        if args.dry_run:
            print(f"[dm] DRY-RUN would reply to {platform} comment {cid} "
                  f"({comment_text(c)[:40]!r}) -> {entry['permalink']}")
            stats["skipped"] += 1
            return
        ok, err = send(cid, dm_text)
        if ok:
            stats["sent"] += 1
            dm_log[cid] = {"status": "sent", "video": entry.get("video"),
                           "platform": platform, "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
            print(f"[dm] replied to {platform} comment {cid} on {entry['permalink']}")
        else:
            stats["failed"] += 1
            dm_log[cid] = {**rec, "status": "failed", "error": err,
                           "attempts": int(rec.get("attempts", 0)) + 1,
                           "video": entry.get("video"), "platform": platform,
                           "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
            print(f"[dm] FAILED {platform} comment {cid}: {err}")
        changed = True

    # Facebook + Instagram: private replies via the Messenger platform.
    if fb_ready:
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
            self_id = env("FB_PAGE_ID") if platform == "facebook" else env("IG_USER_ID")
            for c in comments:
                handle(c, platform, entry, self_id, krx, send_dm)

    # YouTube: public replies via the Data API. ONE channel-level thread read
    # covers every registered video (quota: 1-2 units/run; replies 50 each).
    if yt_ready:
        yt_entries = {str(e.get("post_id")): e for e in registry
                      if e.get("platform") == "youtube"}
        if yt_entries:
            try:
                token = yt_access_token()
                channel_id = yt_channel_id(token)
                comments = yt_fetch_channel_comments(token, channel_id, comment_limit)
            except RuntimeError as exc:
                print(f"[dm] {exc}")
                comments = []
            for c in comments:
                entry = yt_entries.get(str(c.get("videoId") or ""))
                if not entry:
                    continue  # comment on an unregistered (older) video
                kws = [entry["keyword"]] if entry.get("keyword") else keywords
                handle(c, "youtube", entry, channel_id, _keyword_regex(kws),
                       lambda cid, txt: yt_reply(token, cid, txt))

    # Always materialize the log outside dry-run: on a clean first run nothing
    # changed, but the CI commit step expects the file to exist (and seeding it
    # once means later clean runs are true no-ops with no diff to commit).
    if not args.dry_run and (changed or not DM_LOG_PATH.exists()):
        _save(DM_LOG_PATH, dm_log)
    print(f"[dm] done: {stats['sent']} sent, {stats['failed']} failed, "
          f"{stats['skipped']} dry-run skips, {len(registry)} posts watched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
