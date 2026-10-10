"""Fuente: YouTube sin auto-subs — audio m4a + faster-whisper local (CPU int8).

Agenda: lee worklists data/metadata/youtube/<canal>.json, para cada video SIN
transcript noch baja audio (fbopt: audio only) y transcribe con faster-whisper
modelo medium int8, output markdown con front-matter provenance + timestamps.
Checkpoints: skips los que ya tienen .md. Ledger por item.
"""
import json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(__file__))
from ledger import record_start, record_finish, start_run, finish_run, export_csv

OUT = os.path.join(os.path.dirname(__file__), "..", "data")
YT_DLP = os.environ.get("GOVAUDIT_YTDLP") or os.path.join(os.path.dirname(__file__), "..", ".venv", "Scripts", "yt-dlp.exe")
AUDIO_DIR = os.path.join(OUT, "audio")
MODEL = os.environ.get("GOVAUDIT_WHISPER_MODEL", "medium")
CHANNELS = ["senado", "diputados", "presidencia", "parlamento"]

def yt(*args):
    r = subprocess.run([YT_DLP, *args, "--no-warnings", "--quiet"], capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp: {r.stderr[-200:]}")

def new_md_path(slug, vid):
    return os.path.join(OUT, "transcripts", "whisper", slug, f"{vid}.md")

def transcribe(audio, vid, slug):
    from faster_whisper import WhisperModel
    md_path = new_md_path(slug, vid)
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=8)
    segments, info = model.transcribe(audio, language="es", vad_filter=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"""---
video_id: {vid}
canal: {slug}
url: https://youtube.com/watch?v={vid}
generado: faster-whisper {MODEL} int8, local
fecha_proceso: {time.strftime('%Y-%m-%dT%H:%M')}
idioma_deteccion: {getattr(info, 'language', 'es')}
---

# Transcripción (whisper local)

""")
        for seg in segments:
            mm, ss = int(seg.start // 60), int(seg.start % 60)
            f.write(f"[{mm:02d}:{ss:02d}] {seg.text.strip()}\n")
    return md_path

def run(run_id="whisper-backfill", priority_recent=True, limit=0):
    start_run(run_id, "youtube_whisper", mode="backfill")
    ok = skipped = err = 0
    for slug in CHANNELS:
        wl_path = os.path.join(OUT, "metadata", "youtube", f"{slug}.json")
        if not os.path.exists(wl_path):
            continue
        vids = json.load(open(wl_path, encoding="utf-8"))
        if priority_recent:
            vids.sort(key=lambda v: v.get("upload_date") or "", reverse=True)
        for v in vids:
            vid = v["id"]
            md = new_md_path(slug, vid)
            if os.path.exists(md):
                skipped += 1; continue
            eid = record_start(run_id, "youtube_whisper", f"{slug}/{vid}", item_url=f"https://youtube.com/watch?v={vid}")
            os.makedirs(AUDIO_DIR, exist_ok=True)
            audio = os.path.join(AUDIO_DIR, f"{vid}.m4a")
            try:
                if not os.path.exists(audio):
                    yt(f"https://youtube.com/watch?v={vid}", "-f", "bestaudio[ext=m4a]/bestaudio",
                       "-o", audio)
                if not os.path.exists(audio) or os.path.getsize(audio) < 10000:
                    raise RuntimeError("audio no descargado o inválido")
                md_path = transcribe(audio, vid, slug)
                record_finish(eid, "ok", file_path=md_path, bytes_=os.path.getsize(md_path))
                ok += 1
                # descartar audio (re-descargable si hace falta) para no llenar disco
                os.remove(audio)
            except Exception as e:
                record_finish(eid, "error", error=str(e))
                err += 1
                try: os.remove(audio + ".part")
                except OSError: pass
                time.sleep(2)  # backoff suave para rate limit
            if limit and ok >= limit:
                break
        if limit and ok >= limit:
            break
    finish_run(run_id, status="ok" if err == 0 else "partial")
    export_csv()
    return {"ok": ok, "skipped_ya_hechos": skipped, "errors": err}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=f"whisper-{time.strftime('%Y%m%d')}")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(run(a.run_id, limit=a.limit), ensure_ascii=False))
