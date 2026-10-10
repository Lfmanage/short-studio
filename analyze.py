"""Analyse de la vidéo source : durée, audio, scènes, énergie, transcription."""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

import config


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} a échoué : {r.stderr[-1500:]}")
    return r.stdout


def probe(path):
    info = json.loads(run(["ffprobe", "-v", "error", "-show_entries",
                           "format=duration:stream=codec_type,width,height",
                           "-of", "json", str(path)]))
    streams = info.get("streams", [])
    v = next((s for s in streams if s["codec_type"] == "video"), None)
    if not v:
        raise RuntimeError("Aucune piste vidéo trouvée dans le fichier.")
    return {
        "duration": float(info["format"]["duration"]),
        "has_audio": any(s["codec_type"] == "audio" for s in streams),
        "width": v.get("width"), "height": v.get("height"),
    }


def audio_energy(path, step=0.5):
    """RMS par tranche de `step` s, normalisé 0-1."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(16000 * step)
    if len(x) < n:
        return np.zeros(1), step
    rms = np.sqrt((x[: len(x) // n * n].reshape(-1, n) ** 2).mean(axis=1))
    return rms / (rms.max() + 1e-9), step


def scenes(path, threshold=10.0):
    """Instants de changement de plan (filtre scdet de FFmpeg)."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-an", "-vf",
                        f"scale=320:-2,scdet=threshold={threshold}", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(t) for t in re.findall(r"lavfi\.scd\.time:\s*([\d.]+)", r.stderr)]


def extract_audio(path, dest):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
         "-b:a", "48k", str(dest)])
    return dest


def transcribe(audio_path):
    """Retourne (segments, mots). segments: {s,e,text}; mots: {w,s,e}."""
    mode = config.TRANSCRIBE
    if mode == "api" and config.OPENAI_API_KEY:
        return _transcribe_api(audio_path)
    if mode in ("api", "local"):
        try:
            return _transcribe_local(audio_path)
        except ImportError:
            pass
    return [], []


def _transcribe_api(audio_path):
    import requests
    with open(audio_path, "rb") as f:
        r = requests.post("https://api.openai.com/v1/audio/transcriptions",
                          headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                          files={"file": (Path(audio_path).name, f)},
                          data=[("model", "whisper-1"), ("response_format", "verbose_json"),
                                ("timestamp_granularities[]", "word"),
                                ("timestamp_granularities[]", "segment")],
                          timeout=300)
    r.raise_for_status()
    d = r.json()
    segs = [{"s": s["start"], "e": s["end"], "text": s["text"].strip()} for s in d.get("segments", [])]
    words = [{"w": w["word"].strip(), "s": w["start"], "e": w["end"]} for w in d.get("words", [])]
    return segs, words


def _transcribe_local(audio_path):
    from faster_whisper import WhisperModel
    model = WhisperModel(config.WHISPER_LOCAL_MODEL, device="auto", compute_type="int8")
    out, _ = model.transcribe(str(audio_path), word_timestamps=True, vad_filter=True)
    segs, words = [], []
    for s in out:
        segs.append({"s": s.start, "e": s.end, "text": s.text.strip()})
        words += [{"w": w.word.strip(), "s": w.start, "e": w.end} for w in (s.words or [])]
    return segs, words


def analyze(path, work: Path, progress=lambda *a: None):
    info = probe(path)
    if info["duration"] > config.MAX_SOURCE_MIN * 60:
        raise RuntimeError(f"Vidéo trop longue (max {int(config.MAX_SOURCE_MIN)} min).")
    progress("Analyse de la vidéo", 0.08)
    cuts = scenes(path)
    energy, step = audio_energy(path) if info["has_audio"] else (np.zeros(1), 0.5)
    segs, words = [], []
    if info["has_audio"]:
        progress("Transcription", 0.2)
        segs, words = transcribe(extract_audio(path, work / "audio.mp3"))
    return {**info, "scenes": cuts, "energy": energy, "step": step,
            "segments": segs, "words": words}
