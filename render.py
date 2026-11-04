#!/usr/bin/env python3
"""Render one reel (zenkio AI Gateway, api-schema.md §21.4).

Runs in a PUBLIC repo, so its logs are public: it prints only the reel id, step names, counts and sizes. Never
captions, prompts or links. Captions go to ffmpeg through text files, never the command line. The token comes from
the RENDER_TOKEN repo secret (masked), the gateway address from the GATEWAY_URL repo variable.
"""
import json, os, subprocess, sys, tempfile, textwrap, urllib.request

GATEWAY = os.environ["GATEWAY_URL"].rstrip("/")
TOKEN = os.environ["RENDER_TOKEN"]
REEL = os.environ["REEL_ID"]
FPS = 30
SIZES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
FONT = next((f for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf") if os.path.exists(f)), None)


def log(msg):
    print(f"[reel {REEL}] {msg}", flush=True)


def call(method, url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"Bearer {TOKEN}", **(headers or {})})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def download(url, path):
    # Signed links need no token; send none so it is never forwarded.
    with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    return os.path.getsize(path)


def ffmpeg(*args):
    p = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], capture_output=True, text=True)
    if p.returncode != 0:
        log("ffmpeg failed, last lines:")
        print("\n".join(p.stderr.strip().splitlines()[-4:]), flush=True)
        sys.exit(1)


def motion_filter(note, w, h, frames):
    """A slow pan or zoom from the shot's motion note (words like in, out, left, right)."""
    n = (note or "").lower()
    big = f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2}"
    step = 0.25 / frames
    if "out" in n:
        z, x, y = f"max(1.25-{step}*on,1)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif "left" in n:
        z, x, y = "1.15", f"(iw-iw/zoom)*(1-on/{frames})", "ih/2-(ih/zoom/2)"
    elif "right" in n:
        z, x, y = "1.15", f"(iw-iw/zoom)*(on/{frames})", "ih/2-(ih/zoom/2)"
    else:  # push in
        z, x, y = f"min(1+{step}*on,1.25)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    return f"{big},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={FPS}"


def clip(tmp, i, shot, still, w, h):
    secs = max(1, int(shot["seconds"]))
    frames = secs * FPS
    cap = os.path.join(tmp, f"cap{i}.txt")
    width = 18 if h > w else 30
    with open(cap, "w", encoding="utf-8") as f:
        f.write("\n".join(textwrap.wrap(shot["caption"], width=width)))
    size = max(40, w // 14)
    text = (
        f"drawtext=textfile={cap}:fontcolor=white:fontsize={size}:line_spacing=10:box=1:boxcolor=black@0.45:boxborderw=24:"
        f"x=(w-text_w)/2:y=h-text_h-{h // 9}" + (f":fontfile={FONT}" if FONT else "")
    )
    out = os.path.join(tmp, f"clip{i}.mp4")
    vf = f"{motion_filter(shot.get('motion'), w, h, frames)},{text},fade=t=in:d=0.3,fade=t=out:st={secs - 0.3}:d=0.3,format=yuv420p"
    ffmpeg("-loop", "1", "-framerate", str(FPS), "-i", still, "-t", str(secs), "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", out)
    return out


def main():
    pkg = json.loads(call("GET", f"{GATEWAY}/v1/render/{REEL}/package"))
    w, h = SIZES[pkg["aspect"]]
    shots = [s for s in pkg["shots"] if s.get("still")]
    if not shots:
        log("no pictures in the package")
        sys.exit(1)
    log(f"package: {len(shots)} shots, {pkg['aspect']}")
    with tempfile.TemporaryDirectory() as tmp:
        clips = []
        for i, s in enumerate(shots, 1):
            path = os.path.join(tmp, f"still{i}.img")
            log(f"shot {i}: picture {download(s['still'], path)} bytes")
            clips.append(clip(tmp, i, s, path, w, h))
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.write("".join(f"file '{c}'\n" for c in clips))
        joined = os.path.join(tmp, "joined.mp4")
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined)
        total = sum(int(s["seconds"]) for s in shots)
        music = os.path.join(tmp, "music.audio")
        has_music = False
        if pkg.get("music"):
            try:
                log(f"music: {download(pkg['music'], music)} bytes")
                has_music = True
            except Exception:
                log("music could not be fetched; continuing without it")
        final = os.path.join(tmp, "reel.mp4")
        audio = ["-i", music, "-af", f"volume=0.6,afade=t=out:st={max(0, total - 1.5)}:d=1.5"] if has_music else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        ffmpeg("-i", joined, *audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-t", str(total), "-movflags", "+faststart", final)
        size = os.path.getsize(final)
        log(f"rendered {size} bytes, {total} s; uploading")
        with open(final, "rb") as f:
            call("PUT", f"{GATEWAY}/v1/render/{REEL}/result", f.read(), {"Content-Type": "video/mp4"})
    log("done")


if __name__ == "__main__":
    main()
