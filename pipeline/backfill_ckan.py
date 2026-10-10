"""Fuente: catalogodatos.gub.uy (CKAN) — dump del metapaís + descarga de resources.

Backfill: pagina package_search hasta agotar, guarda metadata de cada dataset
en data/ckan/metadata/<pkg>.json y descarga resources tabulares/CSV/JSON/XLSX
a data/downloads/. Cada acción queda registrada en el ledger.
"""
import io, json, os, sys, time, zipfile
from urllib.parse import urlparse

import httpx

sys.path.insert(0, os.path.dirname(__file__))
from ledger import record_start, record_finish, start_run, finish_run, sha256_file, export_csv

BASE = "https://catalogodatos.gub.uy/api/3/action"
OUT = os.path.join(os.path.dirname(__file__), "..", "data")
META_DIR = os.path.join(OUT, "metadata", "ckan")
DL_DIR = os.path.join(OUT, "ckan", "files")
os.makedirs(META_DIR, exist_ok=True); os.makedirs(DL_DIR, exist_ok=True)

PAGE = 200
DOWNLOAD_FMTS = {"CSV", "XLS", "XLSX", "JSON", "JSONL", "TSV", "PARQUET", "SHP", "GEOJSON", "ODS", "ZIP"}
MAX_FMTS_PAYLOAD_BYTES = 500 * 1_000_000  # no bajar un resource >500MB

def ckan(action, **params):
    r = httpx.get(f"{BASE}/{action}", params=params, timeout=90, follow_redirects=True,
                  headers={"User-Agent": "uruguay-gov-audit/0.1 (open source)"})
    r.raise_for_status()
    j = r.json()
    if not j.get("success"):
        raise RuntimeError(f"CKAN error: {j}")
    return j["result"]

def run(run_id="ckan-backfill", limit=0, download=True):
    start_run(run_id, "ckan", mode="backfill")
    n = downloaded = failed = 0
    start = 0
    while True:
        res = ckan("package_search", rows=PAGE, start=start, sort="views_recent desc")
        pkgs = res["results"]
        if not pkgs:
            break
        for p in pkgs:
            n += 1
            pkg_id = p.get("id")
            pkg_name = p.get("name") or pkg_id
            # metadata del dataset
            pm = os.path.join(META_DIR, f"{pkg_name}.json")
            if not os.path.exists(pm):
                try: 
                    with open(pm, "w", encoding="utf-8") as f: json.dump(p, f, ensure_ascii=False)
                except OSError: pass
            # resources
            for i, resr in enumerate(p.get("resources", [])):
                fmt = (resr.get("format") or "").upper()
                url = resr.get("url") or ""
                rid = resr.get("id", f"r{i}")
                if not download or fmt not in DOWNLOAD_FMTS or not url.startswith("http"):
                    continue
                item_id = f"{pkg_name}/{rid}"
                eid = record_start(run_id, "ckan", item_id, item_url=url, meta={"dataset": pkg_name, "format": fmt})
                fname = os.path.join(DL_DIR, pkg_name[:80], f"{rid}.{fmt.lower()}")
                try:
                    if os.path.exists(fname) and os.path.getsize(fname) > 0:
                        record_finish(eid, "skipped", file_path=fname, sha256=None, bytes_=os.path.getsize(fname))
                        continue
                    os.makedirs(os.path.dirname(fname), exist_ok=True)
                    with httpx.stream("GET", url, timeout=180, follow_redirects=True,
                                      headers={"User-Agent": "uruguay-gov-audit/0.1"}) as r:
                        r.raise_for_status()
                        cl = int(r.headers.get("content-length") or 0)
                        if cl > MAX_FMTS_PAYLOAD_BYTES:
                            record_finish(eid, "skipped", error=f"resource too big ({cl}B)")
                            continue
                        tmp = fname + ".part"
                        with open(tmp, "wb") as f:
                            for chunk in r.iter_bytes(1 << 20):
                                f.write(chunk)
                        os.replace(tmp, fname)
                    record_finish(eid, "ok", bytes_=os.path.getsize(fname), file_path=os.path.relpath(fname, os.path.dirname(OUT)), sha256=sha256_file(fname))
                    downloaded += 1
                except Exception as e:
                    record_finish(eid, "error", error=str(e))
                    failed += 1
                    try: os.remove(fname + ".part")
                    except OSError: pass
                    time.sleep(1)
            if limit and n >= limit:
                break
        if limit and n >= limit:
            break
        start += len(pkgs)
    finish_run(run_id, status="ok" if failed == 0 else "partial")
    export_csv()
    return {"datasets": n, "downloads": downloaded, "errors": failed}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=f"ckan-{time.strftime('%Y%m%dT%H%M')}")
    ap.add_argument("--limit", type=int, default=0, help="max datasets (0 = todos)")
    ap.add_argument("--no-download", action="store_true", help="solo metadata")
    a = ap.parse_args()
    print(json.dumps(run(a.run_id, a.limit, download=not a.no_download), ensure_ascii=False))
