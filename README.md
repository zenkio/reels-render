# reels-render

Public render worker for the [zenkio AI gateway](https://github.com/zenkio/ai-gateway) (plan: `docs/reels-and-images-plan.md` there, sections 4.6-4.9).

It turns approved stills into one reel: pan and zoom per shot, captions, optional music, one MP4. GitHub Actions runners have ffmpeg and public repos are not charged for minutes; the gateway runs on Cloudflare, which cannot run ffmpeg.

**Status: skeleton.** `render.py --demo` works (it is run by the Self-test workflow on every push). The gateway side (`POST /v1/reels`, the approval email, `/v1/render/{id}/package`, the dispatch call) is **not built yet**, so `Render reel` has nothing to render.

## Privacy rules (this repo is public)

- Workflow **logs are public**: the script logs only the reel id, step names, sizes and timings. ffmpeg runs with `-loglevel error`, and captions go through a text file, never a command line.
- Workflow **dispatch inputs are public**: the only input is the unguessable reel id.
- **No artifacts** are uploaded and nothing is committed: the MP4 goes straight back to the gateway (and Actions storage stays at zero).
- **No app data** lives here: no prompts, stills, captions, music or links.
- Secrets are masked in logs and are not available to forks or pull requests.

## Setup (once the gateway side exists)

Repository settings:
- Variable `GATEWAY_URL`: the gateway's address.
- Secret `RENDER_TOKEN`: a render-scoped gateway token that can only fetch a reel's package and upload its MP4 (rotate like the Colab worker token).

The gateway starts a render with a `workflow_dispatch` call using a separate fine-grained token (this repo only, Actions write only), stored on the gateway.

## Package (draft interface)

`GET /v1/render/{reel}/package` returns `{aspect, fps, music?, shots: [{still, seconds, caption, motion}]}` with signed links; `PUT /v1/render/{reel}/reel.mp4` takes the result. Limits: 12 shots, 8 s per shot, 60 MB per input. Aspects: `9:16` (default), `1:1`, `16:9`, `4:5`. Motions: `zoom_in`, `zoom_out`, `pan_left`, `pan_right` (rotated by shot when not given).

## Try it

```bash
python3 render.py --demo --out out        # synthetic stills, writes out/demo.mp4
python3 render.py --package package.json  # a local package
```

AI-generated clips (image-to-video) are not part of this repo; they come from Colab or Kaggle and would be optional inputs later.
