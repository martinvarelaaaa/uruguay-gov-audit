# UruguayGovAuditMCP

Open source. Todo local. Cada extracción queda registrada.

**Qué hace**: pipeline que descarga toda la data pública disponible del Estado
uruguayo (datos abiertos CKAN, compras OCDS, YouTube oficial, PDFs) y la expone
como MCP server para que cualquier agente de IA pueda auditar el Estado.

## Estructura

```
pipeline/        # backfill + incremental (cada fuente un script)
  ledger.py      # TABLA CENTRAL de extracciones (SQLite + CSV export)
  backfill_ckan.py    # dump catalogodatos.gub.uy (API sin clave)
  backfill_ocds.py    # compras OCDS (bulk JSONL)
  backfill_youtube.py # canales YT oficiales (worklist + auto-subs)
mcp_server/      # FastMCP server (stdio)
config/          # canales YT verificados, fuentes RC
data/            # (no commitea) pesado
  ledger.sqlite3 # ← run ledger, ES parte del sistema de status
runs/            # manifests de corrida + ledger.csv (SÍ commitea)
```

## Run ledger (la clave del sistema)

Cada extracción (dataset, video, scrape) deja una fila en
`data/ledger.sqlite3` tabla `extractions`:
- al **arrancar**: `status=running`, `started_at`
- al **terminar**: `status=ok|error|skipped`, `finished_at`, `duration_s`,
  `rows`, `bytes`, `sha256`, `error` (si falló), `file_path` destino

Además cada corrida completa deja una fila en tabla `runs` (total empleados por estado).
El archivo `runs/ledger.csv` es export (append)(commit) para revisar en Excel/diff.

Query todo staleness desde el supervisor y MCP (tool `status_ingestion`):
"¿la fuente X está desactualizada? ¿la fuente Y tiene errores?" → un vistazo.

## Uso

```bash
# backfill inicial (chico, para probar)
python pipeline/backfill_ckan.py --limit 10

# backfill inicial (completo, horas)
python pipeline/backfill_ckan.py

# compras OCDS
python pipeline/backfill_ocds.py

# ver estado
python pipeline/ledger.py --summary
python pipeline/ledger.py --errors
python pipeline/ledger.py --export   # refresh runs/ledger.csv

# MCP server
python mcp_server/server.py          # FastMCP stdio
```

## Provenance

Cada tool del MCP devuelve un bloque `provenance` con la fuente y notas.
Cada archivo descargado trae su sha256 en el ledger. Los documentos extraídos
(PDF/OCRberg/transcripciones) llevan front-matter con URL origen+checksum+fecha.

## Contribuir

Toda fuente nueva = un script en `pipeline/backfill_<fuente>.py` que use el
ledger (`record_start`/`record_finish`). Lo unico exigible: registro en ledger + provenance.

Licencia: MIT.
