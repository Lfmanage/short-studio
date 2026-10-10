"""Sous-titres animés (style TikTok) au format ASS, rendus par FFmpeg/libass."""
import re
from pathlib import Path

import config


def _ts(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _clean(w):
    return re.sub(r"\s+", " ", w).strip().upper()


def _no_emoji(t):
    return re.sub(r"[^\u0000-\uFFFF]|[\u2600-\u27BF\uFE0F]", "", t.replace("\n", " ")).strip()


def map_source_words(words, segments):
    """Replace les mots de la vidéo source sur la timeline du Short."""
    out, off = [], 0.0
    for seg in segments:
        a, b = seg["s"], seg["e"]
        for w in words:
            if a <= w["s"] < b - 0.05:
                out.append({"w": w["w"], "s": off + w["s"] - a, "e": off + min(w["e"], b) - a})
        off += b - a
    return out


def groups(words, max_words=3, max_chars=16):
    merged = []
    for w in words:   # « fou ! » -> « FOU! » (ponctuation collée au mot)
        txt = _clean(w["w"])
        if not txt:
            continue
        if merged and re.fullmatch(r"[!?.,;:…»]+", txt):
            merged[-1] = {**merged[-1], "w": merged[-1]["w"] + txt, "e": w["e"]}
        else:
            merged.append({**w, "w": txt})
    cur, out = [], []
    for w in merged:
        txt = w["w"]
        item = {**w, "w": txt}
        if cur and (len(cur) >= max_words or sum(len(x["w"]) + 1 for x in cur) + len(txt) > max_chars
                    or item["s"] - cur[-1]["e"] > 0.6):
            out.append(cur)
            cur = []
        cur.append(item)
        if txt[-1] in ".!?":
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def build(words, path: Path, duration: float, title_hook: str = ""):
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,"
        "Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Sub,{config.SUB_FONT},84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,8,3,5,50,50,0,1\n"
        f"Style: Hook,{config.SUB_FONT},64,&H00000000,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,18,0,8,80,80,140,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    y = config.TOP_H
    lines = []
    if title_hook:   # bandeau d'accroche les 3 premières secondes
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(3)},Hook,,0,0,0,,"
                     r"{\fad(120,250)}" + _no_emoji(title_hook)[:60])
    for g in groups(words):
        for i, cur in enumerate(g):
            start = cur["s"]
            end = g[i + 1]["s"] if i + 1 < len(g) else max(cur["e"], start + 0.25) + 0.12
            end = min(end, duration)
            if end <= start:
                continue
            parts = []
            for k, x in enumerate(g):
                if k == i:
                    parts.append(r"{\c&H0000E5FF&\fscx112\fscy112}" + x["w"] + r"{\c&H00FFFFFF&\fscx100\fscy100}")
                else:
                    parts.append(x["w"])
            anim = r"{\an5\pos(540," + str(y) + r")\fscx90\fscy90\t(0,80,\fscx100\fscy100)}" if i == 0 \
                else r"{\an5\pos(540," + str(y) + r")}"
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Sub,,0,0,0,,{anim}{' '.join(parts)}")
    path.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    return path
