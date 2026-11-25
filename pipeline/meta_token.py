"""Meta token toolkit — mint long-lived Page/IG tokens locally, nothing in chat.

The pixel-guy brand uses the RGCIPZAH app (3407816569422177) — separate from
the Grand6 Moments Agency app that the GTA6 loop uses. App secrets are never
passed through chat: `wire` prompts with hidden input on your terminal.

  # one-shot: exchange short token -> find page -> mint never-expiring page
  # token -> upload to GitHub Secrets -> save a local copy for manual posts
  python pipeline/meta_token.py wire --short-token "EAA..." --page-name "techpixel guy"

  # manual steps (rarely needed):
  python pipeline/meta_token.py exchange --short-token "EAAG..."
  python pipeline/meta_token.py pages --token "EAA..."
  python pipeline/meta_token.py page-token --token "EAA..." --page-id 123456
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

GRAPH = "https://graph.facebook.com/v21.0"
CLIP_AGENCY_ENV = Path(r"C:\Users\ryang\clip-agency\.env")
PIXEL_APP_ID = "3407816569422177"  # RGCIPZAH
DEFAULT_REPO = "ryantheeditor28-ops/pixel-factory"
HOSTING_KEYS = ("IG_PUBLIC_URL_BASE", "IG_UPLOAD_ENDPOINT", "IG_UPLOAD_ACCESS_KEY",
                "IG_UPLOAD_SECRET_KEY", "IG_UPLOAD_REGION")


def _read_env(path: Path) -> dict:
    vals: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip()
    return vals


def app_creds() -> tuple[str, str]:
    vals = _read_env(CLIP_AGENCY_ENV)
    return vals.get("FB_APP_ID", ""), vals.get("FB_APP_SECRET", "")


def _get(path: str, **params: str) -> dict:
    qs = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(f"{GRAPH}/{path}?{qs}", timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            msg = (body.get("error") or {}).get("message", str(body))[:220]
        except Exception:
            msg = f"HTTP {exc.code}"
        sys.exit(f"Graph API error on /{path}: {msg}")


def exchange(short_token: str) -> str:
    app_id, app_secret = app_creds()
    if not app_id or not app_secret:
        sys.exit("FB_APP_ID / FB_APP_SECRET not found (set them or keep clip-agency/.env in place)")
    data = _get("oauth/access_token", grant_type="fb_exchange_token",
                client_id=app_id, client_secret=app_secret,
                fb_exchange_token=short_token)
    tok = data.get("access_token", "")
    print("long-lived user token:")
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
        print(ig_txt + "\n")


def wire(short_token: str, page_name: str, page_id: str, repo: str, app_id: str,
         app_secret: str | None = None) -> None:
    import getpass
    if not app_secret:
        app_secret = getpass.getpass(f"App secret for app {app_id} (input hidden): ").strip()
    if not app_secret:
        sys.exit("no app secret entered — get it from App Settings -> Basic -> App Secret")

    print("[1/5] exchanging short token for long-lived user token...")
    data = _get("oauth/access_token", grant_type="fb_exchange_token",
                client_id=app_id, client_secret=app_secret,
                fb_exchange_token=short_token)
    user_tok = data["access_token"]

    print("[2/5] listing pages...")
    data = _get("me/accounts", access_token=user_tok,
                fields="id,name,access_token,instagram_business_account{id,username}",
                limit="100")
    found = data.get("data") or []
    target = None
    for p in found:
        if page_id and str(p.get("id")) == page_id:
            target = p
            break
        if page_name and str(p.get("name", "")).strip().lower() == page_name.strip().lower():
            target = p
            break
    if target is None and page_name:
        for p in found:
            if page_name.lower() in str(p.get("name", "")).lower():
                target = p
                break
    if target is None and page_id:
        # fresh pages often lag behind /me/accounts — fetch the node directly
        try:
            direct = _get(page_id, access_token=user_tok,
                          fields="id,name,access_token,instagram_business_account{id,username}")
            if direct.get("access_token"):
                print("(page found via direct fetch — list lag on brand-new pages)")
                target = direct
        except SystemExit:
            pass
    if target is None:
        print("page not found. pages visible to this token:")
        for p in found:
            print(f"  - {p.get('name')} (id {p.get('id')})")
        sys.exit(1)

    pid = str(target["id"])
    pname = str(target.get("name"))
    page_token = str(target["access_token"])  # minted from a long-lived user token -> never expires
    ig = target.get("instagram_business_account") or {}

    print(f"[3/5] verifying page token for '{pname}'...")
    v = _get(pid, access_token=page_token, fields="name")
    if str(v.get("name")) != pname:
        sys.exit(f"token verification mismatch: expected '{pname}', got '{v.get('name')}'")

    def set_secret(name: str, value: str) -> None:
        subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--body", value],
                       check=True, capture_output=True, text=True)

    print(f"[4/5] setting GitHub secrets on {repo}...")
    secrets_set = ["FB_PAGE_ID", "FB_PAGE_ACCESS_TOKEN"]
    set_secret("FB_PAGE_ID", pid)
    set_secret("FB_PAGE_ACCESS_TOKEN", page_token)
    if ig.get("id"):
        # the linked Page token carries instagram_content_publish for this IG
        set_secret("IG_ACCESS_TOKEN", page_token)
        set_secret("IG_USER_ID", str(ig["id"]))
        secrets_set += ["IG_ACCESS_TOKEN", "IG_USER_ID"]
        envvals = _read_env(CLIP_AGENCY_ENV)
        for k in HOSTING_KEYS:
            if envvals.get(k):
                set_secret(k, envvals[k])
                secrets_set.append(k)

    print("[5/5] saving local copy for manual posts...")
    local = Path(__file__).resolve().parent.parent / ".secrets.local"
    lines = [f"FB_PAGE_ID={pid}", f"FB_PAGE_ACCESS_TOKEN={page_token}"]
    if ig.get("id"):
        lines += [f"IG_ACCESS_TOKEN={page_token}", f"IG_USER_ID={ig['id']}"]
        for k in HOSTING_KEYS:
            if _read_env(CLIP_AGENCY_ENV).get(k):
                lines.append(f"{k}={_read_env(CLIP_AGENCY_ENV)[k]}")
    local.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nDONE — page: {pname} (id {pid})")
    print(f"IG linked: {'@' + ig['username'] if ig.get('username') else 'none on this page (FB-only posting for now)'}")
    print(f"GitHub secrets set: {', '.join(secrets_set)}")
    print(f"local copy: {local} (gitignored)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Meta token toolkit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("exchange", help="short token -> long-lived user token")
    p1.add_argument("--short-token", required=True)
    p2 = sub.add_parser("pages", help="list pages + IG accounts")
    p2.add_argument("--token", required=True)
    p3 = sub.add_parser("page-token", help="mint one page token by page id")
    p3.add_argument("--token", required=True)
    p3.add_argument("--page-id", required=True)
    p4 = sub.add_parser("wire", help="one-shot: exchange -> pick page -> secrets")
    p4.add_argument("--short-token", required=True)
    p4.add_argument("--page-name", default=None)
    p4.add_argument("--page-id", default=None)
    p4.add_argument("--repo", default=DEFAULT_REPO)
    p4.add_argument("--app-id", default=PIXEL_APP_ID)
    p4.add_argument("--app-secret", default=None, help="skip the hidden prompt (use sparingly)")
    args = ap.parse_args()

    if args.cmd == "exchange":
        exchange(args.short_token)
    elif args.cmd == "pages":
        pages(args.token)
    elif args.cmd == "page-token":
        data = _get(str(args.page_id), access_token=args.token, fields="access_token,name")
        print(f"{data.get('name')}: {data.get('access_token')}")
    elif args.cmd == "wire":
        wire(args.short_token, args.page_name, args.page_id, args.repo, args.app_id,
             args.app_secret)


if __name__ == "__main__":
    main()
