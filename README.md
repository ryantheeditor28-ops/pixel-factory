# pixel-factory

**One automated faceless video per run. $0. No PC needed.**

A pixel guy explains a trending GitHub repo / AI tool with punchy word-anchored
captions, gestures and frame-accurate lip sync — in the proven style of the
@theericmichaud template set (`C:\Users\ryang\video-templates\ericmichaud`).

```
topic (GitHub trending API, free)  ─┐
                                    ├─> script (pollinations LLM, free, keyless)
fallback topics (state/used.json)  ─┘
        │
        ▼
voice — edge-tts (free, no key) + per-WORD timestamps
        │
        ▼
lip sync — rhubarb-lip-sync v1.14 (MIT) -> mouth shapes A–H/X
        │
        ▼
video — HyperFrames project generated per run (HTML + GSAP, contract-compliant)
        │           └── the ONE pixel guy: drawn in code (pipeline/character.py),
        │               6 gestures, mouth overlaid at render time — reused forever
        ▼
npx hyperframes check -> render (deterministic, headless Chrome + ffmpeg, Apache-2.0)
        │
        ▼
GitHub Release (the mp4) + state commit (used topics, history)
```

## Everything is free

| Piece | Cost | Why |
|---|---|---|
| Topic discovery | $0 | GitHub public search API |
| Script writing | $0 | text.pollinations.ai, keyless, with deterministic fallback |
| Voice | $0 | edge-tts (Microsoft neural voices, no clone) |
| Lip sync | $0 | rhubarb-lip-sync (MIT, official Linux build cached on CI) |
| Render | $0 | hyperframes CLI (Apache-2.0, no per-render fees) |
| Runner | $0 | ubuntu-latest GitHub Actions + cron-job.org dispatch (free tier) |
| The pixel guy | $0 | drawn in code — no AI credits, no licenses, identical forever |

## Run it

Local (Windows, for testing): `powershell -File run_local.ps1` (downloads rhubarb once).

Useful variants:
```
python pipeline/make_video.py --no-render     # everything except the render
python pipeline/make_video.py --from-script   # re-render the same script
```

Inspect frames without a full render (inside `build/video`):
```
npx --yes hyperframes@0.9.56 snapshot --at 1,5,10
```

## GitHub Actions

`.github/workflows/factory.yml` — every 6h + manual dispatch. Publishes each
video as a repo **Release** (no repo bloat) and commits `state/state.json`
(used topics so nothing repeats).

Reliable triggering (GitHub cron skips slots): reuse the cron-job.org pattern
from grand6-loop — POST to
`/repos/<owner>/pixel-factory/actions/workflows/factory.yml/dispatches`
with a fine-grained PAT that has **Actions: read/write** on this repo.

## Config (config.json)

`voice` (edge-tts voice), `rate`, niche, fps/canvas, target duration,
comment CTA keywords, accent colors. Change by editing the file — or just ask
in chat.

## Layout rules baked in (from the templates + HyperFrames vertical spec)

- 1080x1920, 30fps, hook visible on frame 0 (thumbnail rule)
- content inside the 168–1330px band; character + texture below (platform UI zone)
- captions pop word-by-word, max 3 words per phrase, bottom of the safe band
- a new visual beat every 2–4s; punchy colored keyword in every title
