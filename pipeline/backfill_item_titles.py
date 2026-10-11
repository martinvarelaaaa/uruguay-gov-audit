"""Backfill: tender_title real desde items[].classification.description.

El bulk ARCE trae awards[].title = código del proceso (R/...), así que la tabla
compras quedó con títulos inútiles para búsqueda por texto. Este script reparsea
los zips OCDS y hace UPDATE de tender_title solo donde el título actual es un
código (empieza con 'R/' o similar) o está vacío. Idempotente.
"""
import os, sys, json, zipfile, sqlite3, time, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
DB = os.path.join(ROOT, "data", "govaudit.sqlite3")
CODE_RE = re.compile(r"^[A-Z]?R?[/\-]?\d|^\d|^[A-Z]{1,3}/")

def main():
    import glob as g
    t0 = time.time()
    c = sqlite3.connect(DB, timeout=60)
    c.row_factory = sqlite3.Row
    # ocids con título inútil
    rows = c.execute("""SELECT ocds_id FROM compras
                        WHERE tender_title IS NULL OR tender_title = ''
                           OR tender_title LIKE 'R/%'
                        GROUP BY ocds_id""").fetchall()
    targets = {r[0] for r in rows}
    print(f"ocids a backfillea­r: {len(targets)}", flush=True)
    if not targets:
        print("nada que hacer")
        return
    updates, seen = [], set()
    files = sorted(g.glob(os.path.join(ROOT, "data", "ocds", "ocds-*.zip")))
    for f in files:
        z = zipfile.ZipFile(f)
        nf = 0
        for n in z.namelist():
            if not n.endswith(".json"):
                continue
            try:
                d = json.loads(z.read(n))
            except Exception:
                continue
            for rec in d.get("releases", []) or []:
                ocid = rec.get("ocid")
                if ocid not in targets or ocid in seen:
                    continue
                for a in (rec.get("awards") or []):
                    for it in (a.get("items") or []):
                        dsc = ((it.get("classification") or {}).get("description") or "").strip()
                        if dsc and len(dsc) > 8:
                            updates.append((dsc, ocid))
                            seen.add(ocid)
                            break
                    if ocid in seen:
                        break
            nf += 1
            if nf % 200 == 0:
                print(f"  {os.path.basename(f)}: {nf} json, {len(updates)} updates", flush=True)
        c.executemany("UPDATE compras SET tender_title = ? WHERE ocds_id = ? AND (tender_title IS NULL OR tender_title = '' OR tender_title LIKE 'R/%')", updates)
        c.commit()
        print(f"{os.path.basename(f)} commit: +{len(updates)} títulos | {time.time()-t0:.0f}s", flush=True)
        updates = []
    # último barrido por si quedaron updates sin commit
    if updates:
        c.executemany("UPDATE compras SET tender_title = ? WHERE ocds_id = ? AND (tender_title IS NULL OR tender_title = '' OR tender_title LIKE 'R/%')", updates)
        c.commit()
    left = c.execute("""SELECT COUNT(*) FROM compras
                        WHERE tender_title IS NULL OR tender_title = '' OR tender_title LIKE 'R/%'""").fetchone()[0]
    tot = c.execute("SELECT COUNT(*) FROM compras").fetchone()[0]
    good = c.execute("""SELECT COUNT(*) FROM compras
                        WHERE tender_title IS NOT NULL AND tender_title != '' AND tender_title NOT LIKE 'R/%'""").fetchone()[0]
    print(f"listo: {good}/{tot} con título real ({good*100//tot}%), {left} sin descripción | {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
