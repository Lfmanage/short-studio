"""Montage final 1080x1920 : ta vidéo en haut, fond satisfaisant en bas, sous-titres, voix, musique."""
import random
import subprocess
from pathlib import Path

import requests

import config
from analyze import run

BG_QUERIES = ["kinetic sand", "slime satisfying", "satisfying cutting", "paint mixing",
              "soap cutting", "sand art", "satisfying", "marble run", "hydraulic press"]


# ---------- fond du bas ----------

def background(work: Path, choice: str = "") -> Path:
    local = sorted((config.ASSETS / "backgrounds").glob("*.mp4")) if (config.ASSETS / "backgrounds").exists() else []
    if choice and (config.ASSETS / "backgrounds" / choice).exists():
        return config.ASSETS / "backgrounds" / choice
    if config.PEXELS_API_KEY:
        p = _pexels()
        if p:
            return p
    if local:
        return random.choice(local)
    dest = work / "bg_generated.mp4"
    c = random.choice([("0x6a11cb", "0x2575fc", "0xff6ec7"), ("0x11998e", "0x38ef7d", "0x0ea5e9"),
                       ("0xf12711", "0xf5af19", "0xff2e63")])
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"gradients=s={config.W}x{config.BOT_H}:d=12:speed=0.02:c0={c[0]}:c1={c[1]}:c2={c[2]}:nb_colors=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest)])
    return dest


def _pexels():
    try:
        r = requests.get("https://api.pexels.com/videos/search",
                         headers={"Authorization": config.PEXELS_API_KEY},
                         params={"query": random.choice(BG_QUERIES), "per_page": 20,
                                 "orientation": "portrait", "size": "medium"}, timeout=20)
        r.raise_for_status()
        vids = [v for v in r.json().get("videos", []) if v.get("duration", 0) >= 8]
        if not vids:
            return None
        v = random.choice(vids)
        f = min(v["video_files"], key=lambda f: abs((f.get("width") or 0) - 1080))
        config.CACHE.mkdir(parents=True, exist_ok=True)
        dest = config.CACHE / f"pexels_{v['id']}.mp4"
        if not dest.exists():
            with requests.get(f["link"], stream=True, timeout=120) as d:
                d.raise_for_status()
                tmp = dest.with_suffix(".part")
                with open(tmp, "wb") as out:
                    for chunk in d.iter_content(1 << 20):
                        out.write(chunk)
                tmp.rename(dest)
        return dest
    except Exception as e:
        print("Pexels indisponible :", e)
        return None


def music(choice: str = ""):
    folder = config.ASSETS / "music"
    tracks = sorted(folder.glob("*.mp3")) + sorted(folder.glob("*.m4a")) if folder.exists() else []
    if choice == "none" or not tracks:
        return None
    return random.choice(tracks)


# ---------- partie haute ----------

def top_track(src: Path, segments, has_audio: bool, work: Path) -> Path:
    files = []
    for i, s in enumerate(segments):
        d = s["e"] - s["s"]
        z = 1.0 if i % 2 == 0 else 1.12         # punch-in un plan sur deux
        if i == 0:
            z = 1.06
        vf = (f"scale=-2:{int(config.TOP_H * z)}:flags=lanczos,"
              f"scale='max(iw,{config.W})':-2,"
              f"crop={config.W}:{config.TOP_H},fps={config.FPS},setsar=1,format=yuv420p")
        out = work / f"seg{i:03d}.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{s['s']:.3f}", "-i", str(src)]
        if not has_audio:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        cmd += ["-t", f"{d:.3f}", "-vf", vf]
        fade = f"afade=t=in:d=0.03,afade=t=out:st={max(d - 0.04, 0):.3f}:d=0.04,aresample=44100,aformat=channel_layouts=stereo"
        cmd += ["-af", fade, "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-g", "30",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(out)]
        run(cmd)
        files.append(out)
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{f.name}'\n" for f in files))
    top = work / "top.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(top)],
        cwd=work)
    return top


# ---------- assemblage final ----------

def compose(top: Path, bg: Path, subs: Path, out: Path, work: Path, voice: Path = None, track: Path = None):
    T = config.TARGET
    inputs = ["-i", str(top), "-stream_loop", "-1", "-i", str(bg)]
    idx = 2
    vi = mi = None
    if voice:
        inputs += ["-i", str(voice)]
        vi, idx = idx, idx + 1
    if track:
        inputs += ["-stream_loop", "-1", "-i", str(track)]
        mi, idx = idx, idx + 1

    f = [
        f"[0:v]tpad=stop_mode=clone:stop_duration={T},setpts=PTS-STARTPTS[top]",
        f"[1:v]scale={config.W}:{config.BOT_H}:force_original_aspect_ratio=increase,"
        f"crop={config.W}:{config.BOT_H},fps={config.FPS},setsar=1,setpts=PTS-STARTPTS[bot]",
        "[top][bot]vstack=inputs=2,drawbox=x=0:y=" + str(config.TOP_H - 3) + ":w=iw:h=6:color=black@0.9:t=fill[stack]",
        f"[stack]ass={subs.name},format=yuv420p[vout]",
    ]
    mix = []
    src_vol = 0.22 if vi is not None else 1.0
    f.append(f"[0:a]volume={src_vol},apad[a0]")
    mix.append("[a0]")
    if vi is not None:
        f.append(f"[{vi}:a]adelay=150|150,volume=1.15,apad[av]")
        mix.append("[av]")
    if mi is not None:
        f.append(f"[{mi}:a]volume={0.07 if vi is not None else 0.12},"
                 f"afade=t=out:st={T - 1.5}:d=1.5[am]")
        mix.append("[am]")
    f.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
             f"atrim=0:{T},afade=t=out:st={T - 0.6}:d=0.6,loudnorm=I=-14:TP=-1.5:LRA=11,"
             f"aresample=44100[aout]")
    (work / "filter.txt").write_text(";\n".join(f))
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex_script", "filter.txt",
         "-map", "[vout]", "-map", "[aout]", "-t", f"{T:.3f}",
         "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
         "-r", str(config.FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
         "-movflags", "+faststart", str(out)], cwd=work)
    return out


def thumbnail(video: Path, dest: Path):
    run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", str(video), "-frames:v", "1",
         "-vf", "scale=540:-2", "-q:v", "4", str(dest)])
    return dest
