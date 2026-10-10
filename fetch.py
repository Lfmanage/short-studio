"""Récupération d'une vidéo depuis un lien direct (Drive, Dropbox, MP4 en ligne).

Les plateformes (YouTube, TikTok, Instagram, Facebook, X…) ne sont pas
téléchargées : leurs conditions l'interdisent. L'utilisateur importe le fichier.
"""
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests

BLOCKED = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com",
           "fb.watch", "x.com", "twitter.com", "twitch.tv", "kick.com", "snapchat.com")
MAX_BYTES = 2 * 1024 ** 3


class LinkError(Exception):
    """Message lisible, affiché tel quel dans l'appli."""


def normalize(url: str) -> str:
    u = urlparse(url.strip())
    host = u.netloc.lower()
    if any(host == b or host.endswith("." + b) for b in BLOCKED):
        raise LinkError("Ce lien vient d'une plateforme qui ne permet pas le téléchargement. "
                        "Importe directement le fichier vidéo.")
    if "drive.google.com" in host:
        m = re.search(r"/d/([\w-]+)", u.path) or re.search(r"id=([\w-]+)", u.query)
        if not m:
            raise LinkError("Lien Google Drive non reconnu.")
        return f"https://drive.usercontent.google.com/download?id={m.group(1)}&export=download&confirm=t"
    if "dropbox.com" in host:
        q = parse_qs(u.query)
        q["dl"] = ["1"]
        return urlunparse(u._replace(query=urlencode(q, doseq=True)))
    if u.scheme not in ("http", "https"):
        raise LinkError("Lien invalide.")
    return url


def download(url: str, dest: Path) -> Path:
    real = normalize(url)
    try:
        with requests.get(real, stream=True, timeout=60, allow_redirects=True,
                          headers={"User-Agent": "ShortStudio/1.0"}) as r:
            if r.status_code in (401, 403):
                raise LinkError("Accès refusé : partage le fichier en « tous ceux qui ont le lien ».")
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "text/html" in ctype:
                raise LinkError("Le lien mène à une page web, pas à un fichier vidéo. "
                                "Vérifie le partage ou importe le fichier.")
            size = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise LinkError("Vidéo trop lourde (2 Go maximum).")
                    f.write(chunk)
    except requests.RequestException as e:
        raise LinkError(f"Impossible de récupérer la vidéo ({e.__class__.__name__}).") from e
    return dest
