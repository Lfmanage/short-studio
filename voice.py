"""Voix off française (OpenAI TTS) calée sur la durée exacte du Short."""
import re
import subprocess
from pathlib import Path

import requests

import config
from analyze import transcribe


def synthesize(text: str, dest: Path):
    r = requests.post("https://api.openai.com/v1/audio/speech",
                      headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                      json={"model": config.OPENAI_TTS_MODEL, "voice": config.OPENAI_TTS_VOICE,
                            "input": text, "response_format": "mp3",
                            "instructions": "Parle en français, voix de narrateur TikTok énergique, "
                                            "naturelle et claire, rythme soutenu."},
                      timeout=180)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def fit(src: Path, dest: Path, target: float):
    """Accélère légèrement si la voix dépasse (max x1.25), puis laisse 0,5 s de marge."""
    d = probe_audio(src)
    speed = 1.0
    if d > target - 0.5:
        speed = min(d / (target - 0.5), 1.25)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af",
                    f"atempo={speed:.4f},aresample=44100", "-t", str(target - 0.2), "-ac", "2",
                    str(dest)], check=True)
    return dest, speed


def probe_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return float(out.strip() or 0)


def words_for(audio: Path, text: str):
    """Horodatage mot à mot de la voix : Whisper si dispo, sinon estimation."""
    _, words = transcribe(audio)
    if words:
        return words
    tokens = re.findall(r"\S+", text)
    dur = probe_audio(audio)
    weights = [len(t) + (4 if t[-1] in ".!?" else 2 if t[-1] in ",;:" else 1) for t in tokens]
    total, t, out = sum(weights) or 1, 0.0, []
    for tok, w in zip(tokens, weights):
        d = dur * w / total
        out.append({"w": tok, "s": t, "e": t + d * 0.9})
        t += d
    return out


def make(text: str, work: Path, target: float):
    if not text or not config.OPENAI_API_KEY:
        return None, []
    raw = synthesize(text, work / "voice_raw.mp3")
    path, _ = fit(raw, work / "voice.m4a", target)
    return path, words_for(path, text)
