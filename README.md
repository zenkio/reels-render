# reels-render

Renders promo reels for the zenkio AI Gateway on GitHub Actions. **This repo is public: it holds no app data, prompts, media or secrets.**

- `.github/workflows/render.yml`: started by the gateway (`workflow_dispatch`, input `reel_id` only).
- `render.py`: fetches the reel's package from the gateway, makes a pan-and-zoom clip per shot with a caption, joins them (with music if given), uploads `reel.mp4` back. Logs only ids, step names and sizes.

Setup (owner, once): repo **variable** `GATEWAY_URL` (the gateway's public address) and repo **secret** `RENDER_TOKEN` (the same value as the gateway's `RENDER_TOKEN`). The gateway also needs `GITHUB_DISPATCH_TOKEN`, a fine-grained token limited to this repo with Actions: read and write.

Source of truth: `render/reels-render/` in the zenkio/ai-gateway repo; copy changes here.
