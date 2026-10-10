"""Fuente: YouTube 'talks' — entrevistas/conferencias de representantes (discursos_y_redes).

Diferencia con pipeline/backfill_whisper.py: NO son sesiones de cámaras, son
entrevistas de canales de TV/podcast (VTV Sin Piedad, Desayunos Informales,
BÚSQUEDA, Arriba Gente, ruedas de prensa MEF, TV Ciudad Lado B). El worklist
vivo vive en data/metadata/youtube/talks.json — *agregar un canal o video es
sólo editar ese JSON* (convención spec: cómo_contribuir).

Fases por video (cada una con item propio en el ledger, source=youtube_talks):
  fetch_worklist -> atomic: extrae metadata de cada video (fechas reales via
                    oEmbed/yt-dlp), filtra dur, arma la lista a transcribir -> guardada en
                    data/metadata/youtube/talks_worklist.json
  download_audio -> yt-dlp mejor audio m4a (SIN login, videos públicos)
  transcribe     -> faster-whisper medium int8 CPU (mismo helper que el repo)
  markdown       -> data/transcripts/talks/<slug>/<video_id>.md con front-matter
                    provenance: URL, canal, politician (si está sembrado), fecha de upload real,
                    fecha de descarga, checksum del .md.

Rate limit: sleep >= 2s entre llamadas a YouTube (RespectfulLimit).
TODO: fecha de publicación REAL — oEmbed no la da; si baja de yt-dlp (upload_date)
es confiable, si no queda 'desconocida' y aria-label la reconfirma.
"""
import json, os, re, subprocess, sys, time, hashlib

sys.path.insert(0, os.path.dirname(__file__))
from ledger import record_start, record_finish, start_run, finish_run, export_csv

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data")
YT_DLP = os.environ.get("GOVAUDIT_YTDLP") or os.path.join(HERE, "..", ".venv", "Scripts", "yt-dlp.exe")
AUDIO_DIR = os.path.join(OUT, "audio", "talks")
TALKS_JSON = os.path.join(OUT, "metadata", "youtube", "talks.json")
WORKLIST_PATH = os.path.join(OUT, "metadata", "youtube", "talks_worklist.json")
TRANSCRIPTS_DIR = os.path.join(OUT, "transcripts", "talks")
MODEL = os.environ.get("GOVAUDIT_WHISPER_MODEL", "medium")
SLEEP_S = float(os.environ.get("GOVAUDIT_YT_SLEEP", "2.5"))

def yt(*args, timeout=900):
    r = subprocess.run([YT_DLP, *args, "--no-warnings", "--quiet"], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp: {r.stderr[-300:]}")
    return r.stdout

def oembed_author(vid):
    time.sleep(SLEEP_S)
    import httpx
    r = httpx.get(f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json",
                  headers={"user-agent": "Mozilla/5.0"}, timeout=20)
    if r.status_code == 200:
        return r.json().get("author_name")
    return None

def build_worklist(limit=0, vids=None):
    """De talks.json -> data/metadata/youtube/talks_worklist.json con metadata real por video."""
    cfg = json.load(open(TALKS_JSON, encoding="utf-8"))
    canales = {c["slug"]: c for c in cfg["canales"]}
    items = []
    for v in cfg.get("videos_semilla", []):
        if vids and v["video_id"] not in vids:
            continue
        vid = v["video_id"]
        slug = v["slug"]
        canal = canales.get(slug, {})
        eid = record_start("talks-worklist", "youtube_talks", f"{slug}/{vid}",
                          item_url=f"https://youtube.com/watch?v={vid}",
                          meta={"fase": "worklist"})
        try:
            # metadata exacta con yt-dlp (dur, canal, fecha de upload si el cliente la da)
            out = yt("--skip-download", "--print", "%(upload_date)s|%(duration)s|%(channel)s|%(title)s",
                     f"https://youtube.com/watch?v={vid}")
            up, dur, ch, title = (out.strip().split("|", 3) + ["", "", "", ""])[:4]
            author_oembed = oembed_author(vid)
            item = {"video_id": vid, "slug": slug,
                    "canal": canal.get("nombre") or ch or author_oembed or "",
                    "channel_id": canal.get("channel_id") or "",
                    "titulo": title,
                    "politico": v.get("politico"),
                    "tema": v.get("tema"),
                    "duracion_s": int(float(dur)) if dur else None,
                    "upload_date": up if up and up != "NA" else None,
                    "url": f"https://youtube.com/watch?v={vid}"}
            items.append(item)
            record_finish(eid, "ok", file_path=WORKLIST_PATH)
        except Exception as e:
            record_finish(eid, "error", error=f"{type(e).__name__}: {e}")
            print(f"[talks] worklist SKIP {slug}/{vid}: {e}")
        if limit and len(items) >= limit:
            break
    # merge with existing (idempotent)
    old = []
    if os.path.exists(WORKLIST_PATH):
        old = json.load(open(WORKLIST_PATH, encoding="utf-8"))
    by_id = {o["video_id"]: o for o in old}
    for it in items:
        by_id[it["video_id"]] = it
    merged = sorted(by_id.values(), key=lambda x: x.get("upload_date") or "", reverse=True)
    with open(WORKLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=1)
    return merged

def download_audio(vid):
    os.makedirs(AUDIO_DIR, exist_ok=True)
    audio = os.path.join(AUDIO_DIR, f"{vid}.m4a")
    if os.path.exists(audio) and os.path.getsize(audio) > 10000:
        return audio
    time.sleep(SLEEP_S)
    yt(f"https://youtube.com/watch?v={vid}", "-f", "bestaudio[ext=m4a]/bestaudio", "-o", audio)
    if not os.path.exists(audio) or os.path.getsize(audio) < 10000:
        raise RuntimeError(f"audio no descargado o inválido: {audio}")
    return audio

def transcribe(audio, item):
    from faster_whisper import WhisperModel
    slug = item["slug"]
    vid = item["video_id"]
    md_dir = os.path.join(TRANSCRIPTS_DIR, slug)
    os.makedirs(md_dir, exist_ok=True)
    md_path = os.path.join(md_dir, f"{vid}.md")
    model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=8)
    segments, info = model.transcribe(audio, language="es", vad_filter=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"""---
video_id: {vid}
canal: {item.get('canal', '')}
channel_id: {item.get('channel_id', '')}
politico: {item.get('politico') or 'desconocido'}
tema: {item.get('tema') or ''}
url: {item.get('url')}
upload_date: {item.get('upload_date') or 'desconocida'}
generado: faster-whisper {MODEL} int8, local
fecha_proceso: {time.strftime('%Y-%m-%dT%H:%M')}
modulo: discursos_y_redes (talks)
---

# Transcripción (whisper local)

""")
        for seg in segments:
            mm, ss = int(seg.start // 60), int(seg.start % 60)
            f.write(f"[{mm:02d}:{ss:02d}] {seg.text.strip()}\n")
    return md_path

def run(run_id="", limit=0, build_first=True):
    run_id = run_id or f"talks-{time.strftime('%Y%m%dT%H%M')}"
    source = "youtube_talks"
    start_run(run_id, source, mode="backfill")
    if build_first:
        wl = build_worklist()
    else:
        wl = json.load(open(WORKLIST_PATH, encoding="utf-8")) if os.path.exists(WORKLIST_PATH) else []
    done = ok = skipped = err = 0
    for item in wl:
        md_existing = os.path.join(TRANSCRIPTS_DIR, item["slug"], f"{item['video_id']}.md")
        if os.path.exists(md_existing):
            skipped += 1
            continue
        if limit and done >= limit:
            break
        eid = record_start(run_id, source, f"{item['slug']}/{item['video_id']}",
                          item_url=item.get("url"), meta={"politico": item.get("politico"), "canal": item.get("canal")})
        audio = os.path.join(AUDIO_DIR, f"{item['video_id']}.m4a")
        try:
            audio = download_audio(item["video_id"])
            md_path = transcribe(audio, item)
            sha = hashlib.sha256(open(md_path, "rb").read()).hexdigest()
            record_finish(eid, status="ok", file_path=md_path, bytes_=os.path.getsize(md_path), sha256=sha)
            print(f"[talks] OK {item['slug']}/{item['video_id']} -> {md_path}")
            ok += 1
        except Exception as e:
            record_finish(eid, status="error", error=f"{type(e).__name__}: {e}")
            print(f"[talks] ERROR {item['slug']}/{item['video_id']}: {e}")
            err += 1
            time.sleep(2)  # backoff suave
        finally:
            try:
                if os.path.exists(audio):
                    os.remove(audio)
            except OSError:
                pass
        done += 1
    finish_run(run_id, status="ok" if err == 0 else ("partial" if ok > 0 else "error"))
    export_csv()
    return {"ok": ok, "skipped_ya_hechos": skipped, "errors": err}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="backfill de charlas/entrevistas YouTube (discursos_y_redes)")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-worklist", action="store_true", help="usar talks_worklist.json existente")
    a = ap.parse_args()
    print(json.dumps(run(a.run_id, limit=a.limit, build_first=not a.no_worklist), ensure_ascii=False))
