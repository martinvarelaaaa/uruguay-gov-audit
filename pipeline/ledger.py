"""Run ledger: registro central de TODAS las extracciones del sistema.

Cada extracción (dataset descargado, canal procesado, scrape corrido) deja:
- INSERT al arrancar (status=running)
- UPDATE al terminar (status=ok/error, rows, bytes, error, duración)

Esta EN SQLite (ledger.sqlite3) porque es la forma más simple de hacer
queries agregadas ("¿qué fuentes están desactualizadas?") desde el
supervisor y el MCP, sin servicios externos. Además se exporta a
runs/ledger.csv (append) para consumo humano/git diff.
"""
import sqlite3, time, csv, os, hashlib, json, threading
from datetime import datetime, timezone

DB_PATH = os.environ.get("GOVAUDIT_LEDGER", os.path.join(os.path.dirname(__file__), "..", "data", "ledger.sqlite3"))

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS extractions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,           -- id de corrida (p.ej. ckan-backfill-20261010T2000)
  source TEXT NOT NULL,           -- fuente: ckan | ocds | youtube | parlamento | impo | tcr | corte_electoral | ...
  item_id TEXT NOT NULL,          -- identificador del item (dataset id, video id, url)
  item_url TEXT,                  -- URL de origen
  status TEXT NOT NULL DEFAULT 'running',  -- running | ok | error | skipped
  attempt INTEGER NOT NULL DEFAULT 1,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  duration_s REAL,
  rows INTEGER,                   -- filas/registros extraídos
  bytes INTEGER,                  -- tamaño descargado
  file_path TEXT,                 -- destino local
  sha256 TEXT,
  error TEXT,
  meta TEXT                       -- json libre
);
CREATE INDEX IF NOT EXISTS idx_ext_source ON extractions(source, status);
CREATE INDEX IF NOT EXISTS idx_ext_item ON extractions(source, item_id);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  mode TEXT NOT NULL,             -- backfill | incremental
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT DEFAULT 'running',  -- running | ok | error | partial
  items_total INTEGER,
  items_ok INTEGER,
  items_error INTEGER,
  note TEXT
);
"""

def _conn():
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        c = sqlite3.connect(os.path.abspath(DB_PATH), timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        _local.conn = c
    return c

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def start_run(run_id, source, mode="backfill", note=""):
    _conn().execute("INSERT OR REPLACE INTO runs(run_id,source,mode,started_at,status,note) VALUES(?,?,?,?,?,?)",
                    (run_id, source, mode, now_iso(), "running", note))
    _conn().commit()

def finish_run(run_id, status="ok", note=None):
    c = _conn()
    f, e, t = "items_total", "items_error", "items_ok"
    row = c.execute(f"SELECT COUNT(*) n, SUM(status='ok') ok, SUM(status='error') err FROM extractions WHERE run_id=?", (run_id,)).fetchone()
    c.execute(f"UPDATE runs SET finished_at=?, status=?, {f}=?, {t}=?, {e}=?, note=COALESCE(?,note) WHERE run_id=?",
              (now_iso(), status, row["n"], row["ok"], row["err"], note, run_id))
    c.commit()

def record_start(run_id, source, item_id, item_url=None, meta=None):
    c = _conn()
    cur = c.execute("INSERT INTO extractions(run_id,source,item_id,item_url,status,started_at,meta) VALUES(?,?,?,?,?,?,?)",
                    (run_id, source, item_id, item_url, "running", now_iso(), json.dumps(meta or {}, ensure_ascii=False)))
    c.commit()
    return cur.lastrowid

def record_finish(extraction_id, status="ok", rows=None, bytes_=None, file_path=None, sha256=None, error=None):
    c = _conn()
    c.execute("""UPDATE extractions SET status=?, finished_at=?, duration_s=(julianday('now')-julianday(started_at))*86400,
                 rows=?, bytes=?, file_path=?, sha256=?, error=? WHERE id=?""",
              (status, now_iso(), rows, bytes_, file_path, sha256, (error or None) and str(error)[:500], extraction_id))
    c.commit()

def log_event(source, item_id, status, error=None, **kw):
    """API corta para extracciones de un solo paso (start+finish inmediato)."""
    run_id = kw.pop("run_id", "adhoc")
    eid = record_start(run_id, source, item_id, kw.get("item_url"), kw.get("meta"))
    record_finish(eid, status(status_kw := status) if callable(status) else status, **{k: v for k, v in kw.items() if k in ("rows", "bytes_", "file_path", "sha256")}, error=error)
    return eid

def export_csv(path=None):
    c = _conn()
    path = path or os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "..", "runs", "ledger.csv")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    rows = c.execute("SELECT * FROM extractions ORDER BY id").fetchall()
    cols = ["id","run_id","source","item_id","item_url","status","attempt","started_at","finished_at","duration_s","rows","bytes","file_path","sha256","error","meta"]
    with open(os.path.abspath(path), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in cols})
    return os.path.abspath(path)

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def summary():
    c = _conn()
    out = []
    for r in c.execute("""SELECT source,
        SUM(status='ok') ok, SUM(status='error') err, SUM(status='running') running,
        MAX(finished_at) last_finish FROM extractions GROUP BY source"""):
        out.append(dict(r))
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Run ledger — tabla de todas las extracciones")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--recent", type=int, default=20)
    ap.add_argument("--errors", action="store_true")
    a = ap.parse_args()
    if a.summary:
        for row in summary():
            print(row)
    elif a.export:
        print(export_csv())
    elif a.errors:
        for r in _conn().execute("SELECT id,source,item_id,error FROM extractions WHERE status='error' ORDER BY id DESC LIMIT ?", (a.recent,)):
            print(dict(r))
    else:
        c = _conn()
        for r in c.execute("SELECT id,run_id,source,item_id,status,rows,bytes,duration_s,finished_at FROM extractions ORDER BY id DESC LIMIT ?", (a.recent,)):
            print(dict(r))
