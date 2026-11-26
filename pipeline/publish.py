"""Publish a finished video to Facebook Page Reels + Instagram Reels + YouTube.

Lifted from the proven GTA6 clip-agency posters (same Graph API flows), trimmed
for pixel-factory: one mp4 in, posts out — no package/queue machinery.

  python pipeline/publish.py                        # newest out/*.mp4, caption from build/script.json
  python pipeline/publish.py --platforms fb         # facebook only
  python pipeline/publish.py --platforms fb,ig,yt --video out/x.mp4 --caption "..."

Platform env (same names as the GTA6 project / clip-agency/.env, so secrets
copy over 1:1):
  Facebook : FB_PAGE_ID, FB_PAGE_ACCESS_TOKEN
  Instagram: IG_ACCESS_TOKEN, IG_USER_ID, IG_PUBLIC_URL_BASE
             (+ SigV4 host: IG_UPLOAD_ENDPOINT, IG_UPLOAD_ACCESS_KEY,
              IG_UPLOAD_SECRET_KEY, IG_UPLOAD_REGION default "auto")
  YouTube  : YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
             (mint with: python pipeline/yt_token.py — one consent flow per channel)

Missing variables -> that platform is skipped with a note and exit 0, so CI
can ship the GitHub Release even before credentials are wired. A real API
failure -> exit 1 (the run shows red, no silent loss).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import json
import sys
import time
import urllib.parse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
GRAPH_VERSION = "v21.0"          # valid until Jan 21, 2027; override via GRAPH_VERSION env
CAPTION_MAX = 2200
POLL_INTERVAL_SECS = 5
POLL_MAX_SECS = 420
RETRIES = 3
DEFAULT_HASHTAGS = "#aitools #opensource #github #ai #coding #techtok"


class PublishError(Exception):
    pass


_LOCAL_ENV: dict | None = None


def _local_env() -> dict:
    """Fallback creds from .secrets.local (written by meta_token.py wire) for manual runs."""
    global _LOCAL_ENV
    if _LOCAL_ENV is None:
        _LOCAL_ENV = {}
        f = ROOT / ".secrets.local"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition("=")
                    _LOCAL_ENV[k.strip()] = v.strip()
    return _LOCAL_ENV


def env(name: str) -> str:
    import os
    return (os.environ.get(name) or "").strip() or _local_env().get(name, "")


# ---- http with retry ---------------------------------------------------------

def req(method: str, url: str, *, timeout: int = 120, **kwargs) -> requests.Response:
    last: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.request(method, url, timeout=timeout, **kwargs)
            if r.status_code >= 500 and attempt < RETRIES:
                time.sleep(2 * attempt)
                continue
            return r
        except (requests.Timeout, requests.ConnectionError) as exc:
            last = exc
            if attempt < RETRIES:
                time.sleep(2 * attempt)
    raise PublishError(f"{method} {url} failed after {RETRIES} attempts: {last}")


def snippet(r: requests.Response) -> str:
    return (r.text or "")[:300]


# ---- caption -----------------------------------------------------------------

def caption_from_script(script_path: Path) -> str:
    d = json.loads(script_path.read_text(encoding="utf-8"))
    title = str(d.get("title") or "").strip() or "This free tool is unreal"
    keyword = str(d.get("comment_keyword") or "LINK").strip().upper()
    cta = f'Comment "{keyword}" and I\'ll send you the link \U0001F517'
    tags = env("HASHTAGS") or DEFAULT_HASHTAGS
    return f"{title}\n\n{cta}\n\n{tags}"[:CAPTION_MAX]


# ---- facebook (Page Reels, 3-phase, raw bytes — no public host needed) -------

def fb_configured() -> bool:
    return bool(env("FB_PAGE_ID") and env("FB_PAGE_ACCESS_TOKEN"))


def fb_post(video: Path, caption: str) -> dict:
    base = f"https://graph.facebook.com/{env('GRAPH_VERSION') or GRAPH_VERSION}"
    page_id, token = env("FB_PAGE_ID"), env("FB_PAGE_ACCESS_TOKEN")

    r = req("POST", f"{base}/{page_id}/video_reels",
            params={"upload_phase": "start", "access_token": token})
    if r.status_code >= 400:
        raise PublishError(f"fb reels start: HTTP {r.status_code}: {snippet(r)}")
    start = r.json() or {}
    video_id, upload_url = str(start.get("video_id") or ""), str(start.get("upload_url") or "")
    if not video_id or not upload_url:
        raise PublishError(f"fb reels start returned no video_id/upload_url: {snippet(r)}")

    size = video.stat().st_size
    with video.open("rb") as fh:
        r = req("POST", upload_url, data=fh.read(), timeout=600, headers={
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(size),
            "Content-Type": "application/octet-stream",
        })
    if r.status_code >= 400:
        raise PublishError(f"fb reels transfer: HTTP {r.status_code}: {snippet(r)}")
    if not ((r.json() or {}).get("success") or r.status_code == 200):
        raise PublishError(f"fb reels transfer not confirmed: {snippet(r)}")

    r = req("POST", f"{base}/{page_id}/video_reels", params={
        "upload_phase": "finish",
        "video_id": video_id,
        "video_state": "PUBLISHED",
        "description": caption[:CAPTION_MAX],
        "access_token": token,
    })
    if r.status_code >= 400:
        raise PublishError(f"fb reels finish: HTTP {r.status_code}: {snippet(r)}")
    return {"url": f"https://www.facebook.com/reel/{video_id}", "post_id": video_id}


# ---- instagram (container -> publish; needs a publicly reachable video_url) --

def ig_configured() -> bool:
    return bool(env("IG_ACCESS_TOKEN") and env("IG_USER_ID") and env("IG_PUBLIC_URL_BASE"))


def _sigv4_put_headers(url: str, payload_sha256: str, access_key: str,
                       secret_key: str, region: str) -> dict:
    """Minimal AWS SigV4 header signing (works with Cloudflare R2, region 'auto')."""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_sha256}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join([
        "PUT", parsed.path or "/", "", canonical_headers, signed_headers, payload_sha256,
    ])
    scope = f"{datestamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    k_date = _hmac(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, "s3")
    k_signing = _hmac(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
        "x-amz-content-sha256": payload_sha256,
        "x-amz-date": amz_date,
    }


def _public_video_url(video: Path) -> str:
    """PUT the mp4 to the public host and return the URL IG's servers will fetch."""
    public_base = env("IG_PUBLIC_URL_BASE").rstrip("/")
    name = video.name
    video_url = f"{public_base}/{name}"
    endpoint, ak, sk = env("IG_UPLOAD_ENDPOINT"), env("IG_UPLOAD_ACCESS_KEY"), env("IG_UPLOAD_SECRET_KEY")
    with video.open("rb") as fh:
        body = fh.read()
    headers = {"Content-Type": "video/mp4"}
    put_url = video_url
    if endpoint and ak and sk:
        put_url = f"{endpoint.rstrip('/')}/{name}"
        headers.update(_sigv4_put_headers(
            put_url, hashlib.sha256(body).hexdigest(), ak, sk,
            env("IG_UPLOAD_REGION") or "auto"))
    r = req("PUT", put_url, data=body, timeout=600, headers=headers)
    if r.status_code not in (200, 201):
        raise PublishError(f"video host PUT: HTTP {r.status_code}: {snippet(r)}")
    return video_url


def ig_post(video: Path, caption: str) -> dict:
    base = f"https://graph.facebook.com/{env('GRAPH_VERSION') or GRAPH_VERSION}"
    user_id, token = env("IG_USER_ID"), env("IG_ACCESS_TOKEN")
    video_url = _public_video_url(video)

    r = req("POST", f"{base}/{user_id}/media", params={
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption[:CAPTION_MAX],
        "share_to_feed": "true",
        "access_token": token,
    })
    if r.status_code >= 400:
        raise PublishError(f"ig container: HTTP {r.status_code}: {snippet(r)}")
    container_id = str((r.json() or {}).get("id") or "")
    if not container_id:
        raise PublishError(f"ig container returned no id: {snippet(r)}")

    deadline = time.monotonic() + POLL_MAX_SECS
    while time.monotonic() < deadline:
        r = req("GET", f"{base}/{container_id}",
                params={"fields": "status_code", "access_token": token})
        if r.status_code >= 400:
            raise PublishError(f"ig container status: HTTP {r.status_code}: {snippet(r)}")
        status = str((r.json() or {}).get("status_code") or "")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise PublishError(f"ig container {status.lower()}")
        time.sleep(POLL_INTERVAL_SECS)
    else:
        raise PublishError(f"ig container not FINISHED after {POLL_MAX_SECS}s")

    r = req("POST", f"{base}/{user_id}/media_publish",
            params={"creation_id": container_id, "access_token": token})
    if r.status_code >= 400:
        raise PublishError(f"ig publish: HTTP {r.status_code}: {snippet(r)}")
    media_id = str((r.json() or {}).get("id") or "")
    if not media_id:
        raise PublishError(f"ig publish returned no media id: {snippet(r)}")

    r = req("GET", f"{base}/{media_id}",
            params={"fields": "permalink,shortcode", "access_token": token})
    if r.status_code < 400:
        data = r.json() or {}
        if data.get("permalink"):
            return {"url": str(data["permalink"]), "post_id": media_id}
        if data.get("shortcode"):
            return {"url": f"https://www.instagram.com/reel/{data['shortcode']}/",
                    "post_id": media_id}
    return {"url": f"https://www.instagram.com/reel/{media_id}/", "post_id": media_id}


# ---- youtube (Data API v3 resumable upload; refresh-token -> access token) ---

YT_TITLE_MAX = 100          # YouTube hard limit
YT_DESC_MAX = 5000
YT_CATEGORY_TECH = "28"     # Science & Technology


def yt_configured() -> bool:
    return bool(env("YT_CLIENT_ID") and env("YT_CLIENT_SECRET") and env("YT_REFRESH_TOKEN"))


def yt_access_token() -> str:
    r = req("POST", "https://oauth2.googleapis.com/token", data={
        "client_id": env("YT_CLIENT_ID"),
        "client_secret": env("YT_CLIENT_SECRET"),
        "refresh_token": env("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    })
    if r.status_code >= 400:
        raise PublishError(f"yt token refresh: HTTP {r.status_code}: {snippet(r)}")
    token = str((r.json() or {}).get("access_token") or "")
    if not token:
        raise PublishError(f"yt token refresh returned no access_token: {snippet(r)}")
    return token


def yt_post(video: Path, caption: str) -> dict:
    """Resumable upload; caption's first line becomes the title, rest the description."""
    token = yt_access_token()
    lines = [ln.strip() for ln in caption.splitlines() if ln.strip()]
    title = (lines[0] if lines else video.stem)[:YT_TITLE_MAX]
    description = "\n".join(lines[1:])[:YT_DESC_MAX] or title
    privacy = (env("YT_PRIVACY") or "public").lower()

    r = req("POST",
            "https://www.googleapis.com/upload/youtube/v3/videos"
            "?uploadType=resumable&part=snippet,status",
            json={
                "snippet": {
                    "title": title,
                    "description": description,
                    "categoryId": YT_CATEGORY_TECH,
                },
                "status": {
                    "privacyStatus": privacy,
                    "selfDeclaredMadeForKids": False,
                },
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(video.stat().st_size),
            })
    if r.status_code >= 400:
        raise PublishError(f"yt session start: HTTP {r.status_code}: {snippet(r)}")
    session_url = r.headers.get("Location") or ""
    if not session_url:
        raise PublishError(f"yt session start returned no Location header: {snippet(r)}")

    with video.open("rb") as fh:
        r = req("PUT", session_url, data=fh.read(), timeout=600, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "video/mp4",
        })
    if r.status_code >= 400:
        raise PublishError(f"yt upload: HTTP {r.status_code}: {snippet(r)}")
    video_id = str((r.json() or {}).get("id") or "")
    if not video_id:
        raise PublishError(f"yt upload returned no video id: {snippet(r)}")
    return {"url": f"https://www.youtube.com/watch?v={video_id}", "post_id": video_id}


# ---- state + main ------------------------------------------------------------

def record(video: Path, platform: str, url: str) -> None:
    path = ROOT / "state" / "posted.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    if path.exists():
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            entries = []
    entries.append({
        "video": video.name,
        "platform": platform,
        "url": url,
        "posted_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    path.write_text(json.dumps(entries[-500:], indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Post the latest video to FB + IG")
    ap.add_argument("--video", type=Path, default=None, help="mp4 to post (default: newest out/*.mp4)")
    ap.add_argument("--caption", default=None, help="caption text (default: from build/script.json)")
    ap.add_argument("--platforms", default="fb,ig,yt", help="comma list: fb,ig,yt")
    ap.add_argument("--privacy", default=None, help="YT privacy: public (default) / unlisted / private")
    args = ap.parse_args()

    video = args.video
    if video is None:
        outs = sorted((ROOT / "out").glob("*.mp4"))
        if not outs:
            print("[publish] no out/*.mp4 found — nothing to post")
            return 0
        video = outs[-1]
    if not video.exists():
        print(f"[publish] video not found: {video}")
        return 1

    if args.privacy:
        import os
        os.environ["YT_PRIVACY"] = args.privacy

    caption = args.caption
    if caption is None:
        script = ROOT / "build" / "script.json"
        caption = caption_from_script(script) if script.exists() else (
            f"{video.stem}\n\n{(env('HASHTAGS') or DEFAULT_HASHTAGS)}")
    print(f"[publish] video: {video.name}  ({video.stat().st_size // 1024} KB)")
    print(f"[publish] caption: {caption[:90]!r}...")

    platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
    failures = 0
    for p in platforms:
        if p == "fb":
            if not fb_configured():
                print("[publish] facebook: skipped (FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set)")
                continue
            try:
                res = fb_post(video, caption)
                record(video, "facebook", res["url"])
                # registry for the comment-gate auto-DM (keyword + promised links)
                try:
                    import comment_bot
                    comment_bot.record_post("facebook", res["post_id"], res["url"], video.name)
                except Exception as exc:  # registry must never break publishing
                    print(f"[publish] registry write skipped: {exc}")
                print(f"[publish] facebook OK -> {res['url']}")
            except PublishError as exc:
                failures += 1
                print(f"[publish] facebook FAILED: {exc}")
        elif p == "ig":
            if not ig_configured():
                print("[publish] instagram: skipped (IG_ACCESS_TOKEN / IG_USER_ID / IG_PUBLIC_URL_BASE not set)")
                continue
            try:
                res = ig_post(video, caption)
                record(video, "instagram", res["url"])
                try:
                    import comment_bot
                    comment_bot.record_post("instagram", res["post_id"], res["url"], video.name)
                except Exception as exc:
                    print(f"[publish] registry write skipped: {exc}")
                print(f"[publish] instagram OK -> {res['url']}")
            except PublishError as exc:
                failures += 1
                print(f"[publish] instagram FAILED: {exc}")
        elif p == "yt":
            if not yt_configured():
                print("[publish] youtube: skipped (YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN not set)")
                continue
            try:
                res = yt_post(video, caption)
                record(video, "youtube", res["url"])
                try:
                    import comment_bot
                    comment_bot.record_post("youtube", res["post_id"], res["url"], video.name)
                except Exception as exc:
                    print(f"[publish] registry write skipped: {exc}")
                print(f"[publish] youtube OK -> {res['url']}")
            except PublishError as exc:
                failures += 1
                print(f"[publish] youtube FAILED: {exc}")
        else:
            print(f"[publish] unknown platform '{p}' ignored")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
