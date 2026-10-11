"""build_index.py — construye el índice de consulta del proyecto.

1. Normaliza CSV/Excel tabulares de data/ckan/files + data/departamentales a Parquet (con columnas estandarizadas: source, dataset_id, file, row_id)
2. FTS5 index de transcripciones (data/transcripts/**/*.md)
3. SQLite compras OCDS: importa los JSONL a una tabla compras fija para SQL directo

Uso: python build_index.py [--limit N]
"""
import os, sys, glob, json, time
import sqlite3
sys.path.insert(0, os.path.dirname(__file__))
from ledger import export_csv

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "data")
PARQUET = os.path.join(DATA, "export", "parquet")
DB = os.path.join(ROOT, "data", "govaudit.sqlite3")

def ensure_db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS compras (
        ocds_id TEXT, Compras YEAR INTEGER, buyer_name TEXT, supplier_names TEXT,
        tender_value DOUBLE, currency TEXT, tender_title TEXT, url TEXT,
        source_file TEXT)""")
    c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS transcripciones_fts
        USING fts5(video_id, canal, minuto, texto, url)""")
    return c

def import_ocds(c):
    """Importa zips bulk de ARCE (ocds-<year>.zip, dentro <year>/*.json con releases[])."""
    import zipfile, glob as g
    files = sorted(g.glob(os.path.join(DATA, "ocds", "ocds-*.zip")))
    total = 0
    for f in files:
        fname = os.path.basename(f)
        year = fname.replace('ocds-','').replace('.zip','')
        z = zipfile.ZipFile(f)
        for n in z.namelist():
            if not n.endswith('.json'):
                continue
            try:
                d = json.loads(z.read(n))
            except Exception:
                continue
            for rec in d.get('releases', []):
                ocid = rec.get('ocid'); buyer = (rec.get('buyer') or {}).get('name')
                title = None; tv = None; cur = None
                awd = rec.get('awards') or [{}]
                if awd:
                    a0 = awd[0]
                    title = a0.get('title') or title
                    v = (a0.get('value') or {})
                    tv = v.get('amount') or tv; cur = v.get('currency') or cur
                parts = rec.get('parties') or []
                sup = ','.join(str(p.get('name') or '') for p in parts if 'supplier' in (p.get('roles') or []))
                url = f"https://comprasestatales.gub.uy/portal/detalle?ocid={ocid}"
                c.execute("INSERT INTO compras VALUES (?,?,?,?,?,?,?,?,?)",
                          (ocid, year, buyer, sup, tv, cur, title, url, fname))
                total += 1
                if total % 50000 == 0:
                    print(f'  compras: {total} rows...'); c.commit()
        c.commit()
    return total

def index_transcripts(c):
    n = 0
    ya = {r[0] for r in c.execute("SELECT DISTINCT video_id FROM transcripciones_fts")}
    for md in glob.glob(os.path.join(DATA, "transcripts", "**", "*.md"), recursive=True):
        vid = os.path.basename(md).replace('.md','')
        if vid in ya:
            continue
        canal = os.path.basename(os.path.dirname(md))
        url = f"https://youtube.com/watch?v={vid}"
        texts = []
        for line in open(md, encoding='utf-8'):
            if line.startswith('---') or line.startswith('#') or not line.strip(): continue
            if '] ' in line[:12] or '[' == line[0]:
                mm_ss = line.split(']')[0].strip('[')
                texto = line.split(']',1)[1].strip() if ']' in line else line.strip()
                texts.append((vid, canal, mm_ss, texto, url))
        for row in texts:
            c.execute("INSERT INTO transcripciones_fts VALUES (?,?,?,?,?)", row)
            n += 1
    c.commit()
    return n

def main(limit=0):
    c = ensure_db()
    t0 = time.time()
    # compras
    n_ocds = 0
    if not c.execute("SELECT COUNT(*) FROM compras").fetchone()[0]:
        n_ocds = import_ocds(c)
    n_fts = index_transcripts(c)
    print(f"compras: {n_ocds} nuevos rows | transcripciones indexados: {n_fts} segmentos | {time.time()-t0:.0f}s")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    main(a.limit)
