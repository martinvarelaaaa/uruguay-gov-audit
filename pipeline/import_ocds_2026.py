"""Importa incrementalmente data/ocds/ocds-2026/a-MM-2026.json a govaudit.sqlite3 (compras).
Idempotente: INSERT OR IGNORE por ocid. Uso: python import_ocds_2026.py [meses CSV, default=todos]."""
import os, sys, json, glob, time
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "govaudit.sqlite3")
SRC = os.path.join(ROOT, "data", "ocds", "ocds-2026")

def main():
    meses = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    files = sorted(glob.glob(os.path.join(SRC, "a-*-2026.json")))
    if meses:
        files = [f for f in files if any(f"a-{m}-2026" in f for m in meses)]
    c = sqlite3.connect(DB)
    total_new = total_seen = 0
    t0 = time.time()
    for f in files:
        fname = os.path.basename(f)
        d = json.load(open(f, encoding="utf8"))
        n = 0
        for rec in d.get("releases", []):
            total_seen += 1
            ocid = rec.get("ocid")
            if not ocid:
                continue
            buyer = (rec.get("buyer") or {}).get("name")
            title = None; tv = None; cur = None
            awd = rec.get("awards") or [{}]
            if awd:
                a0 = awd[0]
                title = a0.get("title") or title
                v = a0.get("value") or {}
                tv = v.get("amount") or tv; cur = v.get("currency") or cur
                if tv is None:
                    try:
                        amt = sum(((it.get("unit") or {}).get("value") or {}).get("amount", 0) * (it.get("quantity") or 1)
                                  for it in (a0.get("items") or [])
                                  if ((it.get("unit") or {}).get("value") or {}).get("amount") is not None) or None
                    except Exception:
                        amt = None
                    tv = amt
                    if tv is not None and cur is None:
                        for it in (a0.get("items") or []):
                            u_v = (it.get("unit") or {}).get("value") or {}
                            if u_v.get("currency"): cur = u_v["currency"]; break
                for it in (a0.get("items") or []):
                    dsc = ((it.get("classification") or {}).get("description") or "").strip()
                    if dsc: title = dsc; break
                sups = a0.get("suppliers") or []
                sup = ",".join(str(p.get("name") or "") for p in sups)
                if not sup:
                    parts = rec.get("parties") or []
                    sup = ",".join(str(p.get("name") or "") for p in parts if "supplier" in (p.get("roles") or []))
            url = f"https://comprasestatales.gub.uy/portal/detalle?ocid={ocid}"
            cur_ = c.execute("SELECT 1 FROM compras WHERE ocds_id=?", (ocid,)).fetchone()
            if cur_:
                continue
            c.execute("INSERT INTO compras VALUES (?,?,?,?,?,?,?,?,?)", (ocid, 2026, buyer, sup, tv, cur, title, url, fname))
            n += 1; total_new += 1
        c.commit()
        print(f"{fname}: +{n} nuevos")
    print(f"TOTAL releases vistos {total_seen}, nuevos {total_new} | {time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
