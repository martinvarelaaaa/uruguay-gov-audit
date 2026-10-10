"""Detalle por-video de backfill de YouTube de los canales oficiales del Estado uruguayo.

Estrategia SIN transcripción en backfill v1:
- yt-dlp --flat-playlist para listar todos los videos del canal (IDs, título, fecha)
- worklist JSON a data/metadata/youtube/<canal>.json
- descarga de auto-subs si existen (nivel 1, gratis)
- transcripcion whisper va en etapa separada (backfill_whisper.py)

Variables de entorno para canal: YTCANAL_<slug>=UCxxx...
Lista inicial en config/channels.json
"""
import json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(__file__))
from ledger import record_start, record_finish, start_run, finish_run, export_csv

OUT = os.path.join(os.path.dirname(__file__), "..", "data")
CONFIG = os.path.join(os.path.dirname(__file__), "..", "config", "channels.json")

YT_DLP = os.environ.get("GOVAUDIT_YTDLP") or os.path.join(os.path.dirname(__file__), "..", ".venv", "Scripts", "yt-dlp.exe")

def yt_dlp(*args):
    cmd = [YT_DLP, *args, "--no-warnings", "--quiet"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp fail {r.stderr[-300:]}")
    return r.stdout

def list_channel(cid):
    lines = yt_dlp(f"https://www.youtube.com/channel/{cid}/videos", "--flat-playlist", "--print", "%(id)s|%(title).80s|%(upload_date)s")
    out = []
    for ln in lines.strip().splitlines():
        parts = ln.split("|", 2)
        if len(parts) == 3:
            out.append({"id": parts[0], "title": parts[1], "upload_date": parts[2]})
    return out

def run(run_id="youtube-backfill", channels=None, subs=True, limit=0):
    start_run(run_id, "youtube", mode="backfill")
    ok = err = 0
    data = json.load(open(CONFIG, encoding="utf-8")) if os.path.exists(CONFIG) else {}
    chans = data.get("channels", []) if isinstance(data, dict) else data
    for ch in chans:
        slug, cid = ch["slug"], ch["channel_id"]
        try:
            vids = list_channel(cid)
        except Exception as e:
            eid = record_start(run_id, "youtube", f"channel/{slug}")
            record_finish(eid, "error", error=str(e))
            err += 1
            continue
        meta_dir = os.path.join(OUT, "metadata", "youtube")
        os.makedirs(meta_dir, exist_ok=True)
        with open(os.path.join(meta_dir, f"{slug}.json"), "w", encoding="utf-8") as f:
            json.dump(vids, f, ensure_ascii=False)
        ey = record_start(run_id, "youtube", f"channel/{slug}/list", meta={"videos": len(vids)})
        record_finish(ey, "ok", rows=len(vids))
        ok += 1
        if subs and limit:
            for v in vids[:limit]:
                sdir = os.path.join(OUT, "transcripts", slug)
                os.makedirs(sdir, exist_ok=True)
                sub = os.path.join(sdir, f"{v['id']}.es.vtt")
                if os.path.exists(sub):
                    continue
                ev = record_start(run_id, "youtube", f"{slug}/{v['id']}", item_url=f"https://youtube.com/watch?v={v['id']}")
                try:
                    yt_dlp(f"https://youtube.com/watch?v={v['id']}", "--write-auto-subs", "--sub-langs", "es.*",
                           "--skip-download", "-o", os.path.join(sdir, "%(id)s"))
                    record_finish(ev, "ok", file_path=sub if os.path.exists(sub) else None)
                except Exception as e:
                    record_finish(ev, "error", error=str(e))
                time.sleep(0.5)
    finish_run(run_id, status="ok")
    export_csv()
    return {"channels": len(chans), "ok": ok, "errors": err}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=f"youtube-{time.strftime('%Y%m%d')}")
    ap.add_argument("--no-subs", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(run(a.run_id, subs=not a.no_subs, limit=a.limit), ensure_ascii=False))
