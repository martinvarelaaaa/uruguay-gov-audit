"""Fuente: GOBIERNOS DEPARTAMENTALES (intendencias + juntas + municipios).

Qué baja:
1. CKAN nacional: orgs de intendencias y juntas departamentales ( datasets completos por org)
2. MEF finanzas departamentales: ingresos/egresos de gobiernos departamentales desde 1989
   (dataset OPP/Yaquu), y ejecución presupuestal de cada intendencia que la publique
3. IM: balance de ejecución presupuestal + metadata de su CKAN propia si accesible

Reutiliza el patrón backfill_ckan (ledger, checksum, skip si ya bajado).
"""
import json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from ledger import record_start, record_finish, start_run, finish_run, export_csv

ROOT = os.path.join(os.path.dirname(__file__), "..")
BASE = "https://catalogodatos.gub.uy/api/3/action"
OUT_META = os.path.join(ROOT, "data", "metadata", "departamentales")
OUT_FILES = os.path.join(ROOT, "data", "departamentales")
ORGS_DEPARTAMENTALES = [
    # juntas + intendencias presentes en CKAN nacional (verificado 10/10/26)
    "intendencia-de-canelones", "intendencia-de-durazno", "intendencia-de-florida",
    "intendencia-montevideo", "intendencia-de-rocha", "intendencia-de-san-jose",
    "junta-departamental-de-florida", "junta-departamental-de-maldonado",
]
DATASETS_FINANZAS = [
    "opp-ingresos-y-egresos-de-los-gobiernos-departamentales-y-egresos-de-los-gobiernos-municipales",  # OPP, desde 1989
    "balance-de-ejecucion-presupuestal",  # IM
]
UA = {"User-Agent": "govaudit/0.1 (datos abiertos uruguay; auditoria ciudadana)"}

def api(path):
    r = urllib.request.urlopen(urllib.request.Request(BASE + path, headers=UA), timeout=60)
    return json.load(r)

def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(dest, "wb") as f:
        f.write(r.read())
    return os.path.getsize(dest)

def run(run_id=None):
    run_id = run_id or f"departamentales-{time.strftime('%Y%m%d')}"
    start_run(run_id, "departamentales", mode="backfill")
    ok = err = skipped = 0
    # 1) datasets por org departamental
    for org in ORGS_DEPARTAMENTALES:
        eid = record_start(run_id, "departamentales", f"org:{org}", item_url=f"{BASE}/package_search?fq=organization:{org}")
        try:
            d = api(f"/package_search?fq=organization:{org}&rows=500")
            orgdir = os.path.join(OUT_META, org.split("-de-")[-1] if org.startswith("intendencia-de") else org.replace("intendencia-", ""))
            for p in d["result"]["results"]:
                os.makedirs(orgdir, exist_ok=True)
                fav = os.path.join(orgdir, f"{p['name']}.json")
                json.dump(p, open(fav, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            j = json.dumps({"org": org, "n_datasets": d["result"]["count"]}, ensure_ascii=False)
            record_finish(eid, "ok", rows=d["result"]["count"], file_path=orgdir)
            ok += 1
        except Exception as e:
            record_finish(eid, "error", error=str(e)); err += 1
    # 2) datasets de finanzas/ejecución (todos los resources tabulares)
    for ds in DATASETS_FINANZAS:
        eid = record_start(run_id, "departamentales", f"dataset:{ds}", item_url=f"https://catalogodatos.gub.uy/dataset/{ds}")
        try:
            d = api(f"/package_show?id={ds}")
            p = d["result"]
            saved = 0
            for i, res in enumerate(p.get("resources", [])):
                fmt = (res.get("format") or "").lower()
                if fmt not in ("csv", "json", "xlsx", "xls", "zip", "ods"):
                    continue
                dest = os.path.join(OUT_FILES, ds, f"{i:02d}_{res.get('name','').replace(' ','_')[:40]}.{fmt}")
                if os.path.exists(dest) and os.path.getsize(dest) == (res.get("size") or 0):
                    skipped += 1; continue
                try:
                    download(res["url"], dest); saved += 1
                except Exception as e2:
                    record_finish(record_start(run_id, "departamentales", f"{ds}/res-{i}", item_url=res["url"]), "error", error=str(e2)); err += 1
            record_finish(eid, "ok", rows=saved, file_path=os.path.join(OUT_FILES, ds))
            ok += 1
        except Exception as e:
            record_finish(eid, "error", error=str(e)); err += 1
    finish_run(run_id, status="ok" if err == 0 else "partial")
    export_csv()
    return {"ok": ok, "skipped": skipped, "errors": err}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    print(json.dumps(run(a.run_id), ensure_ascii=False))
