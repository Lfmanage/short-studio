"""Pipeline complet : vidéo -> Short 1080x1920 de durée exacte + infos de publication."""
import json
import tempfile
from pathlib import Path

import config
import ai
import analyze
import render
import subs
import voice as vo


def make_short(src: Path, out_dir: Path, *, with_voice=True, exclude=(), forced=None,
               background="", music="", progress=lambda step, p: None):
    """Retourne un dict {video, thumb, meta}. `forced` = liste de {s,e} choisie à la main."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        a = analyze.analyze(src, work, progress)

        progress("Détection des meilleurs moments", 0.35)
        p = ai.plan(a, voice=with_voice, exclude=exclude, forced=forced)
        segs = p["segments"]

        voice_path, words = None, []
        if with_voice and p["voiceover"]:
            progress("Voix française", 0.5)
            try:
                voice_path, words = vo.make(p["voiceover"], work, config.TARGET)
            except Exception as e:      # la voix ne doit jamais bloquer le Short
                print("Voix indisponible :", e)
                voice_path, words = None, []
        if not voice_path:
            words = subs.map_source_words(a["words"], segs)

        progress("Montage et sous-titres", 0.62)
        hook_text = (p["title"] or "").strip()
        subs_file = subs.build(words, work / "subs.ass", config.TARGET, hook_text if hook_text else "")
        top = render.top_track(src, segs, a["has_audio"], work)
        bg = render.background(work, background)
        track = render.music(music)

        progress("Rendu 1080×1920", 0.8)
        video = render.compose(top, bg, subs_file, out_dir / "short.mp4", work, voice_path, track)
        thumb = render.thumbnail(video, out_dir / "thumb.jpg")

    meta = {
        "duration": round(analyze.probe(video)["duration"], 2),
        "title": p["title"], "description": p["description"], "hashtags": p["hashtags"],
        "voiceover": p["voiceover"] if voice_path else "",
        "segments": [{"s": s["s"], "e": s["e"], "score": s.get("score", 0),
                      "text": (s.get("text") or "")[:120]} for s in segs],
        "candidates": [{"id": c["id"], "s": c["s"], "e": c["e"], "score": c["score"]}
                       for c in p["candidates"]][:400],
        "source_duration": round(a["duration"], 2),
        "with_voice": bool(voice_path),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    progress("Terminé", 1.0)
    return {"video": video, "thumb": thumb, "meta": meta}
