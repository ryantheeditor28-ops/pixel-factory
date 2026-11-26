"""One-time OAuth consent flow that mints a YouTube refresh token for a channel.

Run on the PC (it opens the browser and catches the redirect on localhost):

  python pipeline/yt_token.py                # reads YT_CLIENT_ID/YT_CLIENT_SECRET
                                             # from .secrets.local or env if given
  python pipeline/yt_token.py --client-id ... --client-secret ...

Log in as the Google account that owns the target channel (for a brand
channel, pick that channel on the chooser screen). On success the script
writes YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN into .secrets.local
and prints the exact values to add as GitHub repo secrets.

Scopes: youtube.upload (posting) + youtube.force-ssl (comment read/reply, so
the comment-gate bot can be extended to YouTube without re-authing).

Setup prerequisite: the OAuth client must allow the loopback redirect.
Desktop-type clients accept http://localhost:8080 out of the box; if yours is
a Web-application client, add http://localhost:8080 as an Authorized redirect
URI in Google Cloud Console -> APIs & Services -> Credentials first.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".secrets.local"
PORT = 8080
REDIRECT_URI = f"http://localhost:{PORT}"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
TOKEN_URL = "https://oauth2.googleapis.com/token"


class _Handler(BaseHTTPRequestHandler):
    code: str = ""
    error: str = ""

    def do_GET(self):  # noqa: N802 (stdlib API)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if "code" in q:
            _Handler.code = q["code"][0]
            body = b"<h2>Token received - you can close this tab and go back to the terminal.</h2>"
        else:
            _Handler.error = (q.get("error") or ["unknown error"])[0]
            body = f"<h2>Consent failed: {_Handler.error}</h2>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):  # silence request logging
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Mint a YouTube refresh token (one consent flow)")
    ap.add_argument("--client-id", default="")
    ap.add_argument("--client-secret", default="")
    args = ap.parse_args()

    local = {}
    if SECRETS.exists():
        for line in SECRETS.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                local[k.strip()] = v.strip()
    client_id = args.client_id or local.get("YT_CLIENT_ID", "")
    client_secret = args.client_secret or local.get("YT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("client id/secret missing - pass --client-id/--client-secret or "
              "add YT_CLIENT_ID / YT_CLIENT_SECRET to .secrets.local first")
        return 1

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    })
    print("Opening the consent page in your browser...")
    print("(if nothing opens, paste this URL into a browser)\n")
    print(auth_url, "\n")
    try:
        import webbrowser
        webbrowser.open(auth_url)
    except Exception:
        pass

    server = HTTPServer(("localhost", PORT), _Handler)
    print(f"Waiting for the redirect on {REDIRECT_URI} (Ctrl+C to abort)...")
    while not _Handler.code and not _Handler.error:
        server.handle_request()
    if _Handler.error:
        print(f"consent failed: {_Handler.error}")
        return 1

    r = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode({
            "code": _Handler.code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(r, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    refresh = str(data.get("refresh_token") or "")
    if not refresh:
        print("no refresh_token in the response - was prompt=consent honored? "
              "Re-run and make sure to click 'Allow' (not a previous grant).")
        return 1

    for k, v in (("YT_CLIENT_ID", client_id), ("YT_CLIENT_SECRET", client_secret),
                 ("YT_REFRESH_TOKEN", refresh)):
        local[k] = v
    lines = [f"{k}={v}" for k, v in local.items()]
    SECRETS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"saved -> {SECRETS}")
    print("\nNow add these three secrets to the GitHub repo")
    print("(Settings -> Secrets and variables -> Actions -> New repository secret):\n")
    print(f"  YT_CLIENT_ID      = {client_id}")
    print(f"  YT_CLIENT_SECRET  = {client_secret}")
    print(f"  YT_REFRESH_TOKEN  = {refresh}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
