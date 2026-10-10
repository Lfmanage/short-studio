"""Réglages du worker (tout se règle par variables d'environnement)."""
import os
from pathlib import Path

TARGET = float(os.getenv("SHORT_DURATION", "60"))   # durée finale exacte (s)
W, H = 1080, 1920
TOP_H = 1056            # ~55 % : ta vidéo
BOT_H = H - TOP_H       # ~45 % : fond satisfaisant / ASMR
FPS = 30
MAX_SOURCE_MIN = float(os.getenv("MAX_SOURCE_MIN", "90"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "onyx")
TRANSCRIBE = os.getenv("TRANSCRIBE", "api")          # api | local | none
WHISPER_LOCAL_MODEL = os.getenv("WHISPER_LOCAL_MODEL", "small")

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
SUB_FONT = os.getenv("SUB_FONT", "Montserrat")

BASE = Path(__file__).parent
ASSETS = Path(os.getenv("ASSETS_DIR", BASE / "assets"))
CACHE = Path(os.getenv("CACHE_DIR", BASE / "cache"))
