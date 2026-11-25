"""Free, keyless LLM access via text.pollinations.ai (GET), with hard fallbacks.

Every caller must survive the LLM being down: callers pass a `fallback` factory
and get deterministic output when the network or the model misbehaves.
All JSON we write anywhere uses ensure_ascii + explicit UTF-8 (no BOM) —
lesson learned from the cp1252/BOM bugs in the previous automation.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

ENDPOINT = "https://text.pollinations.ai/{prompt}"
TIMEOUT = 90
RETRIES = 3


def ask(prompt: str, *, seed: int | None = None, model: str | None = None) -> str | None:
    """One LLM question. Returns text or None on total failure (never raises)."""
    q = urllib.parse.quote(prompt[:6000], safe="")
    url = ENDPOINT.format(prompt=q)
    params = []
    if seed is not None:
        params.append(f"seed={seed}")
    if model:
        params.append(f"model={model}")
    if params:
        url += "?" + "&".join(params)
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pixel-factory/0.1"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                text = resp.read().decode("utf-8", "replace").strip()
            if text:
                return text
        except Exception:
            time.sleep(2 * (attempt + 1))
    return None


def ask_json(prompt: str, *, seed: int | None = None) -> dict | list | None:
    """Ask for strict JSON and parse it defensively. Returns None on failure."""
    text = ask(prompt, seed=seed)
    if not text:
        return None
    # strip code fences and any chatter around the JSON object/array
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        return None
    depth = 0
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    for i in range(start, len(text)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def dump_json(path, data) -> None:
    """UTF-8, no BOM, ascii-safe. The only way this project writes JSON."""
    path = str(path)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
        f.write("\n")


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as f:  # -sig tolerates a BOM if one sneaks in
        return json.load(f)
