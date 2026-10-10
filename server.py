"""Worker Supabase : prend les jobs en file, fabrique les Shorts, fait le ménage.

Variables : SUPABASE_URL, SUPABASE_SERVICE_KEY (+ OPENAI_API_KEY, PEXELS_API_KEY).
Lancement : python server.py
"""
import os
import tempfile
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import pipeline
from fetch import LinkError, download

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
POLL = float(os.getenv("POLL_SECONDS", "3"))
KEEP_AFTER_DOWNLOAD_H = float(os.getenv("KEEP_AFTER_DOWNLOAD_H", "3"))
KEEP_MAX_H = float(os.getenv("KEEP_MAX_H", "24"))


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


# ---------- REST ----------

def db(method, query="", json=None, prefer="return=representation"):
    r = requests.request(method, f"{URL}/rest/v1/jobs{query}", json=json,
                         headers={**H, "Prefer": prefer, "Content-Type": "application/json"}, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else []


def update(job_id, **fields):
    fields["updated_at"] = iso(now())
    db("PATCH", f"?id=eq.{job_id}", fields, prefer="return=minimal")


def storage_get(bucket, path, dest: Path):
    with requests.get(f"{URL}/storage/v1/object/{bucket}/{path}", headers=H, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


def storage_put(bucket, path, file: Path, ctype):
    with open(file, "rb") as f:
        r = requests.post(f"{URL}/storage/v1/object/{bucket}/{path}", data=f, timeout=600,
                          headers={**H, "Content-Type": ctype, "x-upsert": "true",
                                   "cache-control": "3600"})
    r.raise_for_status()


def storage_rm(bucket, paths):
    paths = [p for p in paths if p]
    if paths:
        requests.delete(f"{URL}/storage/v1/object/{bucket}", headers=H, json={"prefixes": paths},
                        timeout=60)


# ---------- traitement ----------

def claim():
    rows = db("GET", "?status=eq.queued&order=created_at.asc&limit=1&select=id")
    if not rows:
        return None
    got = db("PATCH", f"?id=eq.{rows[0]['id']}&status=eq.queued",
             {"status": "processing", "step": "Préparation", "progress": 0.02, "updated_at": iso(now())})
    return got[0] if got else None


def process(job):
    jid, uid, opts = job["id"], job["user_id"], job.get("options") or {}
    last = [0.0]

    def progress(step, p):
        if p - last[0] >= 0.04 or p >= 1:
            last[0] = p
            try:
                update(jid, step=step, progress=round(min(p, 0.99), 2))
            except Exception:
                pass

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "source.mp4"
        source_path = job.get("source_path")
        if source_path:
            storage_get("sources", source_path, src)
        elif job.get("source_url"):
            progress("Récupération du lien", 0.04)
            download(job["source_url"], src)
            # on garde la source pour pouvoir modifier/refaire la sélection
            source_path = f"{uid}/{jid}/source.mp4"
            storage_put("sources", source_path, src, "video/mp4")
            update(jid, source_path=source_path)
        else:
            raise LinkError("Aucune vidéo fournie.")

        res = pipeline.make_short(
            src, tmp / "out", with_voice=opts.get("voice", True), exclude=opts.get("exclude") or (),
            forced=opts.get("segments"), background=opts.get("background", ""),
            music=opts.get("music", ""), progress=progress)

        base = f"{uid}/{jid}"
        storage_put("shorts", f"{base}/short.mp4", res["video"], "video/mp4")
        storage_put("shorts", f"{base}/thumb.jpg", res["thumb"], "image/jpeg")
        update(jid, status="done", step="Terminé", progress=1, meta=res["meta"],
               result_path=f"{base}/short.mp4", thumb_path=f"{base}/thumb.jpg", finished_at=iso(now()))


def handle(job):
    t0 = time.time()
    print(f"▶ job {job['id']}")
    try:
        process(job)
        print(f"✓ job {job['id']} en {time.time() - t0:.0f}s")
    except LinkError as e:
        update(job["id"], status="error", error=str(e))
    except Exception as e:
        traceback.print_exc()
        update(job["id"], status="error", error="Le montage a échoué. Réessaie ou importe le fichier. "
                                                 f"({e.__class__.__name__})")


# ---------- ménage automatique ----------

def expire(job):
    storage_rm("shorts", [job.get("result_path"), job.get("thumb_path")])
    update(job["id"], status="expired", result_path=None, thumb_path=None)
    sp = job.get("source_path")
    if sp:
        alive = db("GET", f"?source_path=eq.{sp}&status=neq.expired&id=neq.{job['id']}&select=id")
        if not alive:
            storage_rm("sources", [sp])


def cleanup():
    t = now()
    sel = "&select=id,result_path,thumb_path,source_path"
    old_dl = db("GET", f"?status=eq.done&downloaded_at=lt.{iso(t - timedelta(hours=KEEP_AFTER_DOWNLOAD_H))}{sel}")
    too_old = db("GET", f"?status=in.(done,error)&created_at=lt.{iso(t - timedelta(hours=KEEP_MAX_H))}{sel}")
    for j in {j["id"]: j for j in old_dl + too_old}.values():
        expire(j)
    stuck = db("GET", f"?status=eq.processing&updated_at=lt.{iso(t - timedelta(minutes=20))}&select=id")
    for j in stuck:
        update(j["id"], status="error", error="Le traitement a été interrompu. Relance-le.")


def cleanup_loop():
    while True:
        try:
            cleanup()
        except Exception:
            traceback.print_exc()
        time.sleep(300)


def main():
    print("Short Studio worker prêt.")
    threading.Thread(target=cleanup_loop, daemon=True).start()
    while True:
        try:
            job = claim()
            if job:
                handle(job)
                continue
        except Exception:
            traceback.print_exc()
        time.sleep(POLL)


if __name__ == "__main__":
    main()
