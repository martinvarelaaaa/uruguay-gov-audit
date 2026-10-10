"""Fuente: catálogo OCDS de compras estatales (ARCE/comprasestatales.gub.uy).

Descarga los JSONL bulk del estándar Open Contracting Data Standard
(OpenCtractsUruguay). Cada año aparte. Registro accrual en ledger.
Endpoint real verificado en la investigación (reporte_fuentes_estado_uruguay.md).
"""
import json, os, sys, time
import httpx

sys.path.insert(0, os.path.dirname(__file__))
from ledger import record_start, record_finish, start_run, finish_run, sha256_file, export_csv

CATALOG_URL = "https://catalogodatos.gub.uy/api/3/action/package_search"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "ocds")
os.makedirs(OUT, exist_ok=True)

def find_ocds_packages():
    """Busca datasets OCDS en el CKAN (publisher: ARCE)."""
    r = httpx.get(CATALOG_URL, params={"q": "OCDS", "rows": 50}, timeout=60,
                  headers={"User-Agent": "uruguay-gov-audit/0.1"}).json()
    return r["result"]["results"]

def run(run_id="ocds-backfill", max_files=0):
    start_run(run_id, "ocds", mode="backfill")
    ok = err = 0
    pkgs = find_ocds_packages()
    for p in pkgs:
        for res in p.get("resources", []):
            url = res.get("url") or ""
            if not url.lower().endswith((".jsonl", ".json", ".csv", ".zip")):
                continue
            fname = os.path.join(OUT, os.path.basename(url.split("?")[0]) or f"{res['id']}.json")
            eid = record_start(run_id, "ocds", item_id=res["id"], item_url=url, meta={"dataset": p["name"]})
            try:
                if os.path.exists(fname) and os.path.getsize(fname) > 0:
                    record_finish(eid, "skipped", file_path=fname, bytes_=os.path.getsize(fname))
                    continue
                with httpx.stream("GET", url, timeout=600, follow_redirects=True,
                                  headers={"User-Agent": "uruguay-gov-audit/0.1"}) as r:
                    r.raise_for_status()
                    tmp = fname + ".part"
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                    os.replace(tmp, fname)
                record_finish(eid, "ok", bytes_=os.path.getsize(fname), sha256=sha256_file(fname), file_path=fname)
                ok += 1
            except Exception as e:
                record_finish(eid, "error", error=str(e))
                err += 1
                try: os.remove(fname + ".part")
                except OSError: pass
            if max_files and ok + err >= max_files:
                break
        if max_files and ok + err >= max_files:
            break
    finish_run(run_id, status="ok" if err == 0 else "partial")
    export_csv()
    return {"ok": ok, "errors": err}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=f"ocds-{time.strftime('%Y%m%dT%H%M')}")
    ap.add_argument("--max-files", type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(run(a.run_id, a.max_files), ensure_ascii=False))
