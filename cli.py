"""Test en local, sans Supabase.

    python cli.py ma_video.mp4
    python cli.py "https://www.dropbox.com/s/xxx/video.mp4?dl=0" --no-voice
"""
import argparse
import json
import tempfile
from pathlib import Path

import pipeline
from fetch import download


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="fichier vidéo ou lien direct (Drive, Dropbox, MP4)")
    ap.add_argument("-o", "--out", default="sortie")
    ap.add_argument("--no-voice", action="store_true")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(args.source)
        if args.source.startswith("http"):
            src = download(args.source, Path(tmp) / "source.mp4")
        res = pipeline.make_short(src, Path(args.out), with_voice=not args.no_voice,
                                  progress=lambda s, p: print(f"[{int(p * 100):3d}%] {s}"))
    m = res["meta"]
    print(f"\n✓ {res['video']}  ({m['duration']} s)")
    print("Titre :", m["title"] or "—")
    print("Hashtags :", " ".join(m["hashtags"]))
    print("Extraits :", json.dumps([(s["s"], s["e"]) for s in m["segments"]]))


if __name__ == "__main__":
    main()
