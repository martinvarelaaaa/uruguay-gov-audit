"""Supervisor: vigila el ledger, identifica stale/failures, y decide recovery.

- Lee data/ledger.sqlite3 (tabla extractions + runs)
- Detecta: items 'running' colgados (>1h sin terminar), items error,
  fuentes sin ingesta reciente vs su cadencia esperada
- Recovery: para errores transitorios escribe runs/recovery_queue.json con
  los items a reintentar (los backfills skip-ean lo ya descargado, así que
  re-lanzarlos ES el recovery idempotente)
- Escribe runs/status.json (salud global) que el MCP y cualquier persona
  puede leer. Modo: python supervisor.py [--check | --enqueue-recovery]
"""
import json, os, sqlite3, sys, time
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.environ.get("GOVAUDIT_LEDGER", os.path.join(ROOT, "data", "ledger.sqlite3"))
RUNS = os.path.join(ROOT, "runs")

# cadencia esperada por fuente (horas) — "¿está desactualizada?"
CADENCIA = {
    "ckan": 24,        # diario
    "ocds": 24,
    "youtube": 6,      # cada 6h
    "parlamento": 24,
    "impo": 168,       # semanal
    "tcr": 168,
    "corte_electoral": 168,
}
# errores que vale la pena reintentar (transitorios) vs no (skip permanente)
TRANSIENT = ("Server disconnected", "timed out", "Timeout", "ReadError", "ConnectError",
             "connection reset", "RemoteProtocol", "ssl", "SSL", "CERTIFICATE")

def now():
    return datetime.now(timezone.utc).astimezone()

def check():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    out = {"generated_at": now().isoformat(), "fuentes": {}, "hung": [], "recoverable": [], "permanent_errors": []}
    # estado por fuente
    for r in c.execute("""SELECT source, SUM(status='ok') ok, SUM(status='error') err,
                          SUM(status='skipped') skipped, SUM(status='running') running,
                          MAX(finished_at) last_finish FROM extractions GROUP BY source"""):
        f = dict(r)
        last = f["last_finish"]
        stale = None
        if last and f["source"] in CADENCIA:
            age_h = (now() - datetime.fromisoformat(last)).total_seconds() / 3600
            if age_h > CADENCIA[f["source"]]:
                stale = round(age_h, 1)
        f["stale_horas"] = stale
        out["fuentes"][r["source"]] = f
    # hung (running >1h)
    cutoff = (now() - timedelta(hours=1)).isoformat(timespec="seconds")
    for r in c.execute("SELECT id,run_id,source,item_id,started_at FROM extractions WHERE status='running' AND started_at < ?", (cutoff,)):
        out["hung"].append(dict(r))
    # errors
    for r in c.execute("SELECT id,run_id,source,item_id,item_url,error FROM extractions WHERE status='error'"):
        e = dict(r)
        if any(t in (e.get("error") or "") for t in TRANSIENT):
            out["recoverable"].append(e)
        else:
            out["permanent_errors"].append(e)
    # runs abiertos hace mucho
    for r in c.execute("SELECT run_id,source,mode,started_at,status FROM runs WHERE status='running'"):
        out.setdefault("runs_abiertos", []).append(dict(r))
    return out

def write_status(state):
    os.makedirs(RUNS, exist_ok=True)
    path = os.path.join(RUNS, "status.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, path)
    return path

def enqueue_recovery(state):
    """Graba la cola de recovery para que el próximo rerun del backfill la consuma (skip-ean)."""
    if not state["recoverable"]:
        return None
    os.makedirs(RUNS, exist_ok=True)
    path = os.path.join(RUNS, "recovery_queue.json")
    existing = []
    if os.path.exists(path):
        try: existing = json.load(open(path, encoding="utf-8"))
        except Exception: existing = []
    ids = {e["item_id"] for e in existing}
    for e in state["recoverable"]:
        if e["item_id"] not in ids:
            existing.append({"source": e["source"], "item_id": e["item_id"], "url": e.get("item_url"), "queued_at": now().isoformat()})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return path

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--enqueue-recovery", action="store_true")
    a = ap.parse_args()
    state = check()
    if a.enqueue_recovery:
        p = enqueue_recovery(state)
        if p: print(f"recovery queue: {p} ({len(state['recoverable'])} items)")
    p = write_status(state)
    # resumen en consola
    print(json.dumps({k: v for k, v in state.items() if k != "permanent_errors"}, ensure_ascii=False, default=str)[:2000])
    print(f"status → {p}")

if __name__ == "__main__":
    main()
