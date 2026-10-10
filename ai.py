"""Choix des meilleurs moments + script voix + titre/hashtags.

1. Découpe la vidéo en extraits candidats (phrases + changements de plan).
2. Score heuristique (pics audio, rythme, densité de parole, ponctuation forte).
3. Si une clé OpenAI est présente, le LLM choisit le hook, l'histoire et écrit
   le texte. Sinon, sélection heuristique (ça marche, en moins fin).
4. Assemblage à durée EXACTE : hook en premier, puis ordre chronologique.
"""
import json
import random

import numpy as np
import requests

import config

MIN_SEG, MAX_SEG = 2.5, 9.0


# ---------- candidats ----------

def candidates(a):
    dur = a["duration"]
    out = []
    if a["segments"]:
        cur = None
        for s in a["segments"]:
            if cur is None:
                cur = dict(s)
            elif s["e"] - cur["s"] <= MAX_SEG and cur["e"] - cur["s"] < MIN_SEG + 1:
                cur["e"], cur["text"] = s["e"], cur["text"] + " " + s["text"]
            else:
                out.append(cur)
                cur = dict(s)
        if cur:
            out.append(cur)
        fixed = []
        for c in out:   # coupe les phrases trop longues
            t = c["s"]
            while c["e"] - t > MAX_SEG:
                fixed.append({"s": t, "e": t + 6.0, "text": c["text"]})
                t += 6.0
            if c["e"] - t >= 1.2:
                fixed.append({"s": t, "e": c["e"], "text": c["text"]})
        out = fixed
    else:
        cuts = [0.0] + [t for t in a["scenes"] if 0 < t < dur] + [dur]
        for x, y in zip(cuts, cuts[1:]):
            t = x
            while y - t >= MIN_SEG:
                e = min(t + random.uniform(4, 6), y)
                out.append({"s": t, "e": e, "text": ""})
                t = e
    for i, c in enumerate(out):
        c["id"] = i
        c["s"], c["e"] = round(max(0, c["s"] - 0.1), 2), round(min(dur, c["e"] + 0.15), 2)
    return [c for c in out if c["e"] - c["s"] >= 1.0]


def score(cands, a):
    en, step = a["energy"], a["step"]
    cuts = np.array(a["scenes"] or [-99])
    def seg_energy(c):
        i, j = int(c["s"] / step), max(int(c["e"] / step), int(c["s"] / step) + 1)
        w = en[i:j]
        return (float(w.mean()), float(w.max() - w.min())) if len(w) else (0.0, 0.0)
    for c in cands:
        mean, swing = seg_energy(c)
        d = c["e"] - c["s"]
        words = len(c["text"].split())
        n_cuts = int(((cuts > c["s"]) & (cuts < c["e"])).sum())
        excl = c["text"].count("!") + c["text"].count("?")
        c["score"] = round(100 * (0.35 * mean + 0.25 * swing + 0.15 * min(words / d / 3, 1)
                                  + 0.15 * min(n_cuts / 2, 1) + 0.10 * min(excl, 2) / 2), 1)
    return cands


# ---------- LLM ----------

SYSTEM = """Tu es monteur de Shorts viraux (TikTok, Reels, YouTube Shorts) en français.
On te donne les extraits candidats d'une vidéo (id, début, fin, texte transcrit, score d'intensité).
Construis un Short de {target:.0f} secondes qui retient l'attention jusqu'au bout :
- "hook" : l'id de l'extrait le plus fort, choc, drôle ou intrigant. Il ouvrira la vidéo.
- "ids" : les autres extraits retenus, qui racontent une histoire cohérente (contexte, montée, moment fort, chute).
  La somme des durées (hook inclus) doit faire entre {lo:.0f} et {hi:.0f} secondes.
- N'invente rien : uniquement ce qui est dans la vidéo.
- "title" : titre accrocheur (max 70 caractères), "description" : 1-2 phrases, "hashtags" : 5 à 8 hashtags.
{voice}
Réponds UNIQUEMENT en JSON : {{"hook": id, "ids": [id,...], "title": "...", "description": "...", "hashtags": ["#..."]{voice_key}}}"""

VOICE_RULE = """- "voiceover" : texte de narration en français, 110 à 135 mots, ton naturel et rythmé, qui
  commence par une phrase d'accroche, raconte ce qu'on voit dans l'ordre du montage et n'invente AUCUN fait
  absent de la transcription. Pas d'emoji, pas de hashtag."""


def llm_plan(cands, a, voice, exclude=()):
    if not config.OPENAI_API_KEY:
        return None
    rows = [{"id": c["id"], "start": c["s"], "end": c["e"], "text": c["text"][:220], "score": c["score"]}
            for c in cands]
    if len(rows) > 220:   # longue vidéo : on garde les plus forts
        rows = sorted(sorted(rows, key=lambda r: -r["score"])[:220], key=lambda r: r["start"])
    sys = SYSTEM.format(target=config.TARGET, lo=config.TARGET - 2, hi=config.TARGET + 6,
                        voice=VOICE_RULE if voice else "",
                        voice_key=', "voiceover": "..."' if voice else "")
    payload = {"duree_video": round(a["duration"], 1), "extraits": rows}
    if exclude:
        payload["consigne"] = ("Propose un montage DIFFÉRENT du précédent. Ces ids ne peuvent pas être le hook : "
                               + ", ".join(map(str, sorted(exclude))))
    user = json.dumps(payload, ensure_ascii=False)
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                          json={"model": config.OPENAI_MODEL, "temperature": 0.8 if exclude else 0.4,
                                "response_format": {"type": "json_object"},
                                "messages": [{"role": "system", "content": sys},
                                             {"role": "user", "content": user}]},
                          timeout=120)
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print("LLM indisponible, sélection automatique :", e)
        return None


def llm_voice_for(segs, a):
    """Écrit la voix off + titre pour une sélection faite à la main."""
    if not config.OPENAI_API_KEY:
        return {}
    sys = ("Tu écris la narration française d'un Short de " + f"{config.TARGET:.0f}" + " s monté à partir de ces "
           "extraits (dans l'ordre). 110 à 135 mots, accroche dès la 1re phrase, ton TikTok naturel, "
           "n'invente rien d'absent des textes. Réponds en JSON : "
           '{"voiceover": "...", "title": "...", "description": "...", "hashtags": ["#..."]}')
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
                          headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                          json={"model": config.OPENAI_MODEL, "temperature": 0.5,
                                "response_format": {"type": "json_object"},
                                "messages": [{"role": "system", "content": sys},
                                             {"role": "user", "content": json.dumps(
                                                 [{"start": s["s"], "end": s["e"], "text": s["text"][:300]}
                                                  for s in segs], ensure_ascii=False)}]},
                          timeout=120)
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print("LLM indisponible :", e)
        return {}


# ---------- assemblage ----------

def assemble(order, cands_by_id, pool, target):
    """order : ids dans l'ordre (hook d'abord). Complète/coupe pour durer exactement `target`."""
    chosen = [dict(cands_by_id[i]) for i in order if i in cands_by_id]
    total = sum(c["e"] - c["s"] for c in chosen)
    for c in pool:  # complète avec les meilleurs extraits restants
        if total >= target:
            break
        if any(c["id"] == x["id"] for x in chosen):
            continue
        chosen.append(dict(c))
        total += c["e"] - c["s"]
    hook, rest = chosen[:1], sorted(chosen[1:], key=lambda c: c["s"])
    for x, y in zip(rest, rest[1:]):   # pas de répétition entre deux plans qui se suivent
        if y["s"] < x["e"]:
            y["s"] = x["e"]
    rest = [c for c in rest if c["e"] - c["s"] >= 1.0]
    chosen = hook + rest
    while sum(c["e"] - c["s"] for c in chosen) < target and chosen:   # source trop courte : boucle
        chosen += [dict(c) for c in chosen[1:] or chosen]
    out, acc = [], 0.0
    for c in chosen:
        d = min(c["e"] - c["s"], target - acc)
        if d < 0.6:
            if out:   # rallonge le dernier plutôt qu'un micro-plan
                out[-1]["e"] += target - acc
            break
        out.append({"s": round(c["s"], 3), "e": round(c["s"] + d, 3), "text": c.get("text", ""),
                    "score": c.get("score", 0)})
        acc += d
        if acc >= target - 1e-3:
            break
    return out


def plan(a, voice=True, exclude=(), forced=None):
    """Retourne {segments, title, description, hashtags, voiceover}."""
    target = config.TARGET
    random.seed(int(a["duration"] * 1000))
    cands = score(candidates(a), a)
    excl_ids = set()
    for x in exclude or ():
        xs, xe = float(x["s"]), float(x["e"])
        for c in cands:
            ov = min(c["e"], xe) - max(c["s"], xs)
            if ov > 0.5 * (c["e"] - c["s"]):
                excl_ids.add(c["id"])
                c["score"] = round(c["score"] - 30, 1)
    exclude = excl_ids
    if not cands:
        cands = [{"id": 0, "s": 0.0, "e": a["duration"], "text": "", "score": 50}]
    by_id = {c["id"]: c for c in cands}
    if forced:   # sélection manuelle depuis l'appli
        segs = [{"s": float(x["s"]), "e": float(x["e"]), "text": "", "score": x.get("score", 0)} for x in forced]
        fake = {i: {**s, "id": i} for i, s in enumerate(segs)}
        segs = assemble(list(fake), fake, [], target)
        for sg in segs:   # retrouve le texte prononcé dans chaque extrait
            sg["text"] = " ".join(s["text"] for s in a["segments"] if s["e"] > sg["s"] and s["s"] < sg["e"])
        extra = llm_voice_for(segs, a) if voice else {}
        return {"segments": segs, "title": extra.get("title", ""), "description": extra.get("description", ""),
                "hashtags": extra.get("hashtags", []), "voiceover": extra.get("voiceover", ""),
                "candidates": cands}
    pool = sorted(cands, key=lambda c: -c["score"])
    if exclude:   # nouvelle sélection : un peu de hasard pour varier
        pool = sorted(cands, key=lambda c: -(c["score"] + random.uniform(0, 25)))
    res = llm_plan(cands, a, voice, exclude) or {}
    order = []
    if isinstance(res.get("hook"), int) and res["hook"] in by_id and res["hook"] not in exclude:
        order.append(res["hook"])
    order += [i for i in res.get("ids", []) if isinstance(i, int) and i in by_id and i not in order]
    if not order:   # sans IA : le plus intense en hook
        order = [next((c["id"] for c in pool if c["id"] not in exclude), pool[0]["id"])]
    segs = assemble(order, by_id, pool, target)
    hashtags = [h if h.startswith("#") else "#" + h for h in res.get("hashtags", []) if isinstance(h, str)]
    return {
        "segments": segs,
        "title": res.get("title", ""),
        "description": res.get("description", ""),
        "hashtags": hashtags or ["#shorts", "#viral", "#pourtoi", "#fyp"],
        "voiceover": res.get("voiceover", "") if voice else "",
        "candidates": cands,
    }
