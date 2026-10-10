"""Fuente: X/Twitter (sólo tweets públicos, SIN login/cookies) — discursos_y_redes.

Protocolo (ver docs/discursos_y_redes.md): X bloqueó el scraping anónimo de
timelines (snscrape/Twint/Nitter muertos; gallery-dl exige cookies => NO usamos
según spec). Vía pública que SÍ funciona y es usada por el widget oficial de
embed de X (https://publish.twitter.com), sin cuenta ni cookies:

 1) timeline de un handle:
    https://syndication.twitter.com/srv/timeline-profile/screen-name/<handle>
    -> HTML con __NEXT_DATA__ JSON embebido; los id_str de tweets van en orden
       aleatorio SIN cursor (límite real: ~100 tweets recientes, elegidos al azar
       en una ventana de [ahora-5meses, ahora-1mes]).
    NOTA 2026-10-10: el campo `latest_tweet_id` de pageProps SÍ da el id del
    tweet más reciente del perfil (1 req) — por eso en modo `id-only` sacamos
    exactamente ESO, y las fechas reales de cada tweet vienen de syntweet.
 2) tweet individual:
    https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=x&lang=es
    -> JSON público del embed: created_at, full text, media, user.
    Con el id más reciente basta para registrar "última intervención".

Provenance: cada tweet deja URL exacta, fecha real de publicación, handle,
checksum (sha256 del texto+id), fecha de descarga. Nada de datos privados.
Rate limit: sleep >= 2s entre requests (RespectfulLimit).
"""
import json, os, re, sys, time, hashlib, urllib.parse
import httpx

sys.path.insert(0, os.path.dirname(__file__))
from ledger import record_start, record_finish, start_run, finish_run, export_csv

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data")
X_DIR = os.path.join(OUT, "x")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
SLEEP_S = float(os.environ.get("GOVAUDIT_X_SLEEP", "2.5"))
NEXT_DATA_RE = re.compile(r'__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
SYND_PROFILE = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{}?{}"
SYND_TWEET_JSON = "https://cdn.syndication.twimg.com/tweet-result?id={}&token=x&lang=es"

def _client():
    return httpx.Client(headers={"user-agent": UA, "accept-language": "es"}, timeout=30)

def fetch_profile_timeline(s, handle):
    """Devuelve (tweets_crudos, latest_tweet_id). Duermen SLEEP_S antes."""
    time.sleep(SLEEP_S)
    url = SYND_PROFILE.format(handle, urllib.parse.urlencode({"showReplies": "false"}))
    r = s.get(url)
    if r.status_code == 429:
        raise RuntimeError(f"x: rate-limited (429) en timeline-profile de @{handle}; reintentar más tarde")
    m = NEXT_DATA_RE.search(r.text)
    if not m:
        raise RuntimeError(f"x: sin __NEXT_DATA__ en respuesta de @{handle} (status={r.status_code}) —午饭 de esquema: la respuesta no contiene timeline-público")
    d = json.loads(m.group(1))
    pp = d["props"]["pageProps"]
    tweets = [e["content"]["tweet"] for e in pp["timeline"].get("entries", [])
              if e.get("content", {}).get("tweet") and e["content"]["tweet"].get("id_str")]
    return tweets, pp.get("latest_tweet_id")

def fetch_tweet_json(s, tweet_id):
    time.sleep(SLEEP_S)
    r = s.get(SYND_TWEET_JSON.format(tweet_id))
    if r.status_code == 429:
        raise RuntimeError(f"x: rate-limited (429) en tweet-result id={tweet_id}")
    d = r.json()
    if d.get("__typename") != "Tweet":
        raise RuntimeError(f"x: tweet {tweet_id} no disponible en syndication ({d.get('__typename')})")
    return d

def tweet_record(raw, downloaded):
    tweet_id = str(raw.get("id_str") or raw.get("id"))
    user = raw.get("user") or {}
    handle = (user.get("screen_name") or "").lstrip("@")
    texto = raw.get("text") or raw.get("full_text") or ""
    fecha = raw.get("created_at") or ""
    media = None
    md = raw.get("mediaDetails") or []
    if md:
        media = md[0].get("media_url_https")
    is_rt = bool(raw.get("retweeted")) or texto.startswith("RT @")
    safe_text = re.sub(r"https://t\.co/\w+$", "", texto).strip()
    payload = f"{tweet_id}|{handle}|{fecha}|{safe_text}".encode("utf-8")
    return {
        "tweet_id": tweet_id,
        "handle": handle,
        "fecha": fecha,
        "texto": texto,
        "url": f"https://x.com/{handle}/status/{tweet_id}",
        "media": media,
        "es_retweet": is_rt,
        "descargado": downloaded,
        "checksum": hashlib.sha256(payload).hexdigest(),
    }

def process_handle(s, handle, run_id, limit=0):
    """Para cada handle: latest_tweet_id (exacto) + JSON completo de ese tweet."""
    out_path = os.path.join(X_DIR, f"{handle}.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    downloaded = time.strftime("%Y-%m-%dT%H:%M")
    tweets_raw, latest_id = fetch_profile_timeline(s, handle)
    written = 0
    # el timeline de ~100 aleatorios SIRVE de rtv pero no de "exacto"; el item del ledger
    # es por handle, con los datos del tweet MÁS RECIENTE (exacto vía tweet-result).
    target_id = latest_id or (tweets_raw[0]["id_str"] if tweets_raw else None)
    if not target_id:
        raise RuntimeError(f"x: @{handle} sin tweets públicos disponibles")
    eid = record_start(run_id, "x_representantes", f"{handle}/latest",
                       item_url=f"https://x.com/{handle}", meta={"latest_tweet_id": target_id})
    try:
        detail = fetch_tweet_json(s, target_id)
        rec = tweet_record(detail, downloaded)
        rec["handle"] = handle  # forzar el handle pedido (la ventana puede variar)
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        record_finish(eid, "ok", rows=1, file_path=out_path, sha256=rec["checksum"])
        written = 1
    except Exception as e:
        record_finish(eid, "error", error=f"{type(e).__name__}: {e}")
        raise
    return {"handle": handle, "tweets_en_timeline": len(tweets_raw), "escritos": written}

def run(run_id="", limit=0, handles=None):
    run_id = run_id or f"x-{time.strftime('%Y%m%dT%H%M')}"
    start_run(run_id, "x_representantes", mode="backfill")
    cfg_path = os.path.join(HERE, "..", "config", "representantes.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    reps = [r for r in cfg["representantes"] if r.get("handle_x")]
    if handles:
        handles_set = {h.lstrip("@") for h in handles}
        reps = [r for r in reps if r["handle_x"] in handles_set]
    ok = err = 0
    s = _client()
    for rep in reps:
        handle = rep["handle_x"]
        eid = record_start(run_id, "x_representantes", f"{handle}/timeline",
                          item_url=f"https://x.com/{handle}",
                          meta={"representante": rep["nombre"], "tipo_cuenta": rep.get("tipo_cuenta", "?")})
        try:
            res = process_handle(s, handle, run_id)
            record_finish(eid, "ok", rows=res["escritos"])
            ok += 1
            print(f"[x] {handle}: timeline {res['tweets_en_timeline']} info, 1 tweet reciente escrito")
        except Exception as e:
            record_finish(eid, "error", error=f"{type(e).__name__}: {e}")
            err += 1
            print(f"[x] ERROR {handle}: {e}")
    finish_run(run_id, status="ok" if err == 0 else "partial")
    export_csv()
    return {"ok": ok, "errors": err}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="backfill de tweets públicos (discursos_y_redes)")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--limit", type=int, default=0, help="sólo primeros N handles (para tests)")
    ap.add_argument("--handles", nargs="*", help="limitar a estos handles")
    a = ap.parse_args()
    res = run(a.run_id, limit=a.limit, handles=a.handles)
    print(json.dumps(res, ensure_ascii=False))
