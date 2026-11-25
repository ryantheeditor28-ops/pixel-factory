"""Meta token toolkit — mint long-lived Page/IG tokens locally, nothing in chat.

Uses FB_APP_ID + FB_APP_SECRET (from the GTA6 clip-agency .env by default) with
the SAME app you already have (RGCIPZAH). An app authorizes posting to any
Page/IG account you admin — no new app needed.

  # 1) exchange a short Graph API Explorer token for a ~60-day user token
  python pipeline/meta_token.py exchange --short-token "EAAG..."

  # 2) list your Pages + linked IG accounts with that long-lived token
  python pipeline/meta_token.py pages --token "EAA..."

  # 3) mint a never-expiring Page token (run after choosing a page id)
  python pipeline/meta_token.py page-token --token "EAA..." --page-id 123456

Steps 2 and 3 can be combined: `pages` already prints the per-page token —
page tokens returned from /me/accounts with a long-lived user token never
expire. Paste them into GitHub Secrets (gh secret set FB_PAGE_ACCESS_TOKEN).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.facebook.com/v21.0"
CLIP_AGENCY_ENV = Path(r"C:\Users\ryang\clip-agency\.env")


def app_creds() -> tuple[str, str]:
    app_id = (app_creds._override or {}).get("FB_APP_ID", "")
    secret = (app_creds._override or {}).get("FB_APP_SECRET", "")
    if app_id and secret:
        return app_id, secret
    if CLIP_AGENCY_ENV.exists():
        vals = {}
        for line in CLIP_AGENCY_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
        return vals.get("FB_APP_ID", ""), vals.get("FB_APP_SECRET", "")
    return "", ""


app_creds._override = {}


def _get(path: str, **params: str) -> dict:
    qs = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{GRAPH}/{path}?{qs}", timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def exchange(short_token: str) -> str:
    app_id, app_secret = app_creds()
    if not app_id or not app_secret:
        sys.exit("FB_APP_ID / FB_APP_SECRET not found (set them or keep clip-agency/.env in place)")
    data = _get("oauth/access_token", grant_type="fb_exchange_token",
                client_id=app_id, client_secret=app_secret,
                fb_exchange_token=short_token)
    tok = data.get("access_token", "")
    expires = data.get("expires_in", "?")
    print(f"long-lived user token ({expires}s ~= {int(expires)//86400 if isinstance(expires, int) else '?'} days):")
    print(tok)
    return tok


def pages(token: str) -> None:
    data = _get("me/accounts", access_token=token,
                fields="id,name,instagram_business_account{username,id}",
                limit="50")
    found = data.get("data") or []
    if not found:
        print("no pages visible to this token — grant pages_show_list in Graph API Explorer")
        return
    print(f"{len(found)} page(s) visible:\n")
    for p in found:
        ig = p.get("instagram_business_account") or {}
        ig_txt = f"  IG: @{ig.get('username')} ({ig.get('id')})" if ig else "  IG: not linked"
        print(f"* {p.get('name')}  (page id {p.get('id')})")
        print(ig_txt)
        print(f"  page token (never expires): {p.get('access_token', '')[:25]}...")
        print()


def main() -> None:
    ap = argparse.ArgumentParser(description="Meta token toolkit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("exchange", help="short token -> long-lived user token")
    p1.add_argument("--short-token", required=True)
    p2 = sub.add_parser("pages", help="list pages + IG accounts + page tokens")
    p2.add_argument("--token", required=True)
    p3 = sub.add_parser("page-token", help="re-mint one page token by page id")
    p3.add_argument("--token", required=True)
    p3.add_argument("--page-id", required=True)
    args = ap.parse_args()

    if args.cmd == "exchange":
        exchange(args.short_token)
    elif args.cmd == "pages":
        pages(args.token)
    elif args.cmd == "page-token":
        data = _get(str(args.page_id), access_token=args.token, fields="access_token,name")
        print(f"{data.get('name')}: {data.get('access_token')}")


if __name__ == "__main__":
    main()
