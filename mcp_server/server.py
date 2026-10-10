"""FastMCP server: UruguayGovAuditMCP v0.1.

Expone la data local (ledger + datasets descargados) como tools MCP.
Regla de oro: cada respuesta lleva provenance (fuente, item_url, checksum, fecha).
"""
import json, os, sqlite3, sys
from fastmcp import FastMCP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.environ.get("GOVAUDIT_LEDGER", os.path.join(ROOT, "data", "ledger.sqlite3"))

mcp = FastMCP("uruguay-gov-audit")

def _db():
    c = sqlite3.connect(LEDGER, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def _prov(mode="ledger"):
    return {"repositorio": "uruguay-gov-audit", "modo": mode,
            "datos_descargados_de": "catalogodatos.gub.uy / youtube.com (canales oficiales verificados)",
            "nota": "Datos originales públicos del Estado uruguayo; repolite solo código+índices."}

@mcp.tool()
def status_ingestion(source: str = "") -> dict:
    """Salud de la ingesta: qué fuentes se actualizaron, cuándo y errores recientes."""
    c = _db()
    q = "SELECT source, SUM(status='ok') ok, SUM(status='error') err, MAX(finished_at) last_ok FROM extractions"
    params = ()
    if source:
        q += " WHERE source=?"; params = (source,)
    q += " GROUP BY source"
    rows = [dict(r) for r in c.execute(q, params)]
    return {"fuentes": rows, "provenance": _prov()}

@mcp.tool()
def buscar_datasets(query: str, limit: int = 10) -> dict:
    """Busca datasets descargados del CKAN nacional por nombre/título (metadata local)."""
    meta_dir = os.path.join(ROOT, "data", "metadata", "ckan")
    if not os.path.isdir(meta_dir):
        return {"error": "metadata CKAN no descargada aún (correr backfill_ckan.py)", "provenance": _prov()}
    q = query.lower()
    hits = []
    for fn in os.listdir(meta_dir):
        if q in fn.lower():
            path = os.path.join(meta_dir, fn)
            if len(hits) < limit:
                try:
                    d = json.load(open(path, encoding="utf-8"))
                    hits.append({
                        "name": d.get("name"), "titulo": d.get("title"),
                        "organization": (d.get("organization") or {}).get("title"),
                        "url": f"https://catalogodatos.gub.uy/dataset/{d.get('name')}",
                        "num_resources": len(d.get("resources", [])),
                        "actualizado": d.get("last_major_update") or d.get("metadata_modified"),
                    })
                except Exception:
                    pass
    return {"results": hits, "count": len(hits), "provenance": _prov("metadata_local_ckan")}

@mcp.tool()
def listar_extracciones(source: str = "", limit: int = 20) -> dict:
    """Lista las últimas extracciones registradas (auditoría del pipeline)."""
    c = _db()
    q = "SELECT id,run_id,source,item_id,status,rows,bytes,duration_s,finished_at,error FROM extractions"
    params = ()
    if source:
        q += " WHERE source=?"; params = (source,)
    q += " ORDER BY id DESC LIMIT ?"; params = (*params, limit)
    return {"extractions": [dict(r) for r in c.execute(q, params)], "provenance": _prov()}

if __name__ == "__main__":
    mcp.run()
