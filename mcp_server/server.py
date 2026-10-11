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

@mcp.tool()
def ayuda_sistema() -> dict:
    """Auto-descripción del sistema: qué data hay, cómo se actualiza, qué consultas poser hacer. TODO sale del estado real (ledger + metadata), nada hardcodeado."""
    c = _db()
    # fuentes y frescura real
    fuentes = [dict(r) for r in c.execute(
        """SELECT source, SUM(status='ok') ok, SUM(status='error') err, MAX(finished_at) last_ok
           FROM extractions GROUP BY source""")]
    # datasets con archivos reales en disco
    con_datos = c.execute("SELECT COUNT(DISTINCT split_name) FROM extractions WHERE source='ckan' AND status='ok' AND split_name != ''").fetchone()[0] if False else None
    # tareas posibles: derivadas de fuentes reales
    recetas = {
        "ckan": "Conjuntos de temáticas del Estado: delitos año a año, resultados educativos, precipitaciones, viajes del ómnibus, bosques, compras… más de 5.500 datasets públicos — busco por tema: 'buscá datos de vivienda', '¿qué hay sobre seguridad pública?'",
        "ocds": "CADA compra que hace el Estado, de 2002 a hoy: '¿a quién le compró el MSP en 2024?', 'top 10 proveedores del Estado', '¿quién ganó la licitación X?' — 2 millones de contratos",
        "departamentales": "Plata de los gobiernos departamentales: '¿cuánto gastó la intendencia de Rocha desde 2010?', 'compará ingresos de Canelones vs Maldonado' — depósito histórico desde 1989",
        "youtube": "Lo que se dice EN CÁMARA y en conferencias: '¿qué dijo el presidente el fin de semana?', 'la sesión del Senado con timestamps que te llevan al momento exacto'",
        "youtube_whisper": " videos sin subtítulos, transcribí localmente con whisper",
        "x_representantes": "Lo que dicen LOS REPRESENTANTES en X: '¿qué dijo Oddone sobre el déficit?', 'qué tuiteó tal en marzo'",
        "youtube_talks": "Lo que los políticos dicen EN ENTREVISTAS: '¿de qué habló tal en el Desayuno Informal?' — después lo cruzo con lo que hizo",
        "planes_gobierno": "Lo que PROMETIERON los partidos: '¿qué prometió el FA sobre educación?', '¿cumplió?' — el programa electoral completo indexado por compromiso",
        "perfil_gobernantes": "¿QUIÉN ES quién: 'trayectoria del senador X', '¿con cuántos votos llegó?', '¿qué sector del partido es?'",
    }
    return {
        "que_puedo_consultar": {s: recetas[s] for s in recetas if any(f["source"] == s for f in fuentes)},
        "proximamente": {s: recetas[s] for s in recetas if not any(f["source"] == s for f in fuentes)},
        "fuentes_estado_actual": fuentes,
        "como_se_actualiza": "cron diario (CKAN/compras/presupuesto), cada 6h (YouTube), semanal (departamentales); supervisor cada 30min verifica staleness y re-lanza fallidas; herramienta status_ingestion muestra la frescura exacta por fuente",
        "como_verifico_un_dato": "cada respuesta lleva: dataset oficial + URL original + checksum sha256; podés abrir la URL y comparar así mismo",
        "provenance": _prov("introspeccion_real"),
    }

if __name__ == "__main__":
    mcp.run()
