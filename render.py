#!/usr/bin/env python3
"""Render one reel from stills: pan and zoom per shot, captions, optional music, one MP4.

Standard library only (the runner has ffmpeg). Nothing here is logged except the reel id, step names,
sizes and timings: this repo is public, so run logs are public (see README.md).

  python render.py --demo                      # synthetic stills, no network, writes out/demo.mp4
  python render.py --reel <id>                 # fetch the package from the gateway, render, upload
  python render.py --package package.json ...  # render a local package (stills as local paths)

Package (draft interface, agreed in the gateway repo before it is built):
  {"aspect": "9:16", "fps": 30, "music": "<url or path, optional>",
   "shots": [{"still": "<url or path>", "seconds": 4, "caption": "text", "motion": "zoom_in|zoom_out|pan_left|pan_right"}]}
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time, urllib.request

SIZES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080), "4:5": (1080, 1350)}
MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"]
MAX_SHOTS, MAX_SECONDS, MAX_BYTES = 12, 8, 60 * 2**20


def log(msg):
    print(msg, flush=True)  # ids, step names, sizes and timings only


def run(*cmd):
    r = subprocess.run(list(cmd), capture_output=True, text=True)
    if r.returncode != 0:
        # ffmpeg's own error, last lines only, and never the caption text or links
        raise RuntimeError(f"{cmd[0]} failed (exit {r.returncode}): {r.stderr.strip()[-400:]}")


def fetch(src, dest, headers=None):
    if not src.startswith(("http://", "https://")):
        shutil.copyfile(src, dest)
        return
    req = urllib.request.Request(src, headers=headers or {})
    size = 0
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while block := r.read(1 << 20):
            size += len(block)
            if size > MAX_BYTES:
                raise RuntimeError("an input is larger than 60 MB")
            f.write(block)


def zoompan(motion, frames, w, h):
    """The zoompan expression for one shot, on an input already scaled to 2x the output size."""
    zin = f"min(1+0.18*on/{frames},1.18)"
    zout = f"max(1.18-0.18*on/{frames},1.0)"
    if motion == "zoom_out":
        return f"z='{zout}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    if motion == "pan_right":
        return f"z='1.12':x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'"
    if motion == "pan_left":
        return f"z='1.12':x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)'"
    return f"z='{zin}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"


def render_shot(work, i, shot, w, h, fps):
    seconds = max(1.0, min(float(shot.get("seconds", 4)), MAX_SECONDS))
    frames = int(seconds * fps)
    still = os.path.join(work, f"still{i}")
    out = os.path.join(work, f"shot{i}.mp4")
    motion = shot.get("motion") or MOTIONS[i % len(MOTIONS)]
    vf = [f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2}", f"zoompan={zoompan(motion, frames, w, h)}:d={frames}:s={w}x{h}:fps={fps}"]
    caption = (shot.get("caption") or "").strip()
    if caption:
        textfile = os.path.join(work, f"caption{i}.txt")
        with open(textfile, "w", encoding="utf-8") as f:
            f.write(caption)  # a text file, so the words never appear on a command line
        vf.append(
            f"drawtext=textfile={textfile}:fontcolor=white:fontsize={h // 28}:box=1:boxcolor=black@0.55:boxborderw={h // 90}"
            f":x=(w-text_w)/2:y=h-text_h-{h // 10}:alpha='min(1,t/0.4)*min(1,({seconds}-t)/0.4)'"
        )
    vf.append("format=yuv420p")
    run("ffmpeg", "-y", "-loglevel", "error", "-i", still, "-vf", ",".join(vf), "-frames:v", str(frames), "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out)
    return out, seconds


def render(package, out_path, fetch_headers=None):
    shots = package.get("shots") or []
    if not 1 <= len(shots) <= MAX_SHOTS:
        raise ValueError(f"a reel has 1 to {MAX_SHOTS} shots")
    w, h = SIZES.get(package.get("aspect", "9:16"), SIZES["9:16"])
    fps = int(package.get("fps", 30))
    with tempfile.TemporaryDirectory() as work:
        parts, total = [], 0.0
        for i, shot in enumerate(shots):
            t0 = time.time()
            fetch(shot["still"], os.path.join(work, f"still{i}"), fetch_headers)
            path, seconds = render_shot(work, i, shot, w, h, fps)
            parts.append(path)
            total += seconds
            log(f"shot {i + 1}/{len(shots)} {seconds:.0f}s rendered in {time.time() - t0:.1f}s")
        listing = os.path.join(work, "list.txt")
        with open(listing, "w") as f:
            f.writelines(f"file '{p}'\n" for p in parts)
        joined = os.path.join(work, "joined.mp4")
        run("ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", joined)
        music = package.get("music")
        if music:
            track = os.path.join(work, "music")
            fetch(music, track, fetch_headers)
            run("ffmpeg", "-y", "-loglevel", "error", "-i", joined, "-i", track, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-af", f"afade=t=out:st={max(total - 1.5, 0)}:d=1.5", "-t", str(total), out_path)
        else:
            shutil.copyfile(joined, out_path)
    size = os.path.getsize(out_path)
    log(f"reel done: {total:.0f}s, {size / 2**20:.1f} MB")
    return total, size


def demo(out_dir):
    """Synthetic stills so the whole path can be checked with no network and no secrets."""
    os.makedirs(out_dir, exist_ok=True)
    shots = []
    for i, color in enumerate(["0x2b6cb0", "0x2f855a", "0xb7791f"]):
        path = os.path.join(out_dir, f"demo-still{i}.png")
        run("ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c={color}:s=1200x1600", "-frames:v", "1", path)
        shots.append({"still": path, "seconds": 2, "caption": f"Demo shot {i + 1}"})
    render({"aspect": "9:16", "fps": 30, "shots": shots}, os.path.join(out_dir, "demo.mp4"))


def gateway(reel_id):
    base = os.environ["GATEWAY_URL"].rstrip("/")
    token = os.environ["RENDER_TOKEN"]
    auth = {"Authorization": f"Bearer {token}", "User-Agent": "reels-render/1.0"}
    req = urllib.request.Request(f"{base}/v1/render/{reel_id}/package", headers=auth)
    with urllib.request.urlopen(req, timeout=60) as r:
        package = json.load(r)
    out = os.path.join(tempfile.gettempdir(), "reel.mp4")
    render(package, out)  # package links are signed: no credentials are sent to them
    with open(out, "rb") as f:
        data = f.read()
    put = urllib.request.Request(f"{base}/v1/render/{reel_id}/reel.mp4", data=data, method="PUT", headers={**auth, "Content-Type": "video/mp4"})
    urllib.request.urlopen(put, timeout=300).read()
    log(f"uploaded {len(data) / 2**20:.1f} MB for reel {reel_id}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--reel")
    ap.add_argument("--package")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    try:
        if a.demo:
            demo(a.out)
        elif a.package:
            os.makedirs(a.out, exist_ok=True)
            render(json.load(open(a.package)), os.path.join(a.out, "reel.mp4"))
        elif a.reel:
            gateway(a.reel)
        else:
            ap.error("one of --demo, --package or --reel is required")
    except Exception as e:  # noqa: BLE001
        log(f"render failed: {type(e).__name__}: {str(e)[-300:]}")
        sys.exit(1)
