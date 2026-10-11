# Onboarding para agentes de código (Hermes / OpenClaw / Claude Code / Cursor / etc.)

Guía para que un agente autónomo levante el proyecto completo local: instalación,
data inicial y actualizaciones. Todo sin claves de API.

## 0. Requisitos

- Python 3.11+ (o Docker)
- git
- `pdftotext` (xpdf/poppler) — solo para `backfill_votaciones.py`
- ~5 GB de disco (full) / ~2 GB (solo compras parlamento)

## 1. Instalación

```bash
git clone https://github.com/martinvarelaaaa/uruguay-gov-audit.git
cd uruguay-gov-audit
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Linux/Mac: source .venv/bin/activate primero
```

## 2. Data inicial — DOS caminos

### Camino A (rápido): descargar bundle pre-construido (~1 vuelta)

```bash
# Bajar el release "data-bundle" (govaudit.sqlite3 compactado + ledger + votaciones + roster)
gh release download data-bundle-20261011 -R martinvarelaaaa/uruguay-gov-audit -p "*.zip" -O bundle.zip
python -c "import zipfile; zipfile.ZipFile('bundle.zip').extractall('.')"
mv data/govaudit-compact.sqlite3 data/govaudit.sqlite3 && rm bundle.zip
```

Verificación inmediata (el agente DEBE correr esto y mostrar la salida):

```bash
python - <<'EOF'
import sqlite3
c = sqlite3.connect('data/govaudit.sqlite3')
print('compras:', c.execute("SELECT COUNT(*) FROM compras").fetchone()[0])
print(' PTSD fts videos:', c.execute("SELECT COUNT(DISTINCT video_id) FROM transcripciones_fts").fetchone()[0])
EOF
# esperado: compras ≈ 2,12M ; fts videos ≈ 528
```

### Camino B (completo): regenerar desde la fuente

Orden con dependencias (cada paso usa `data/ledger.sqlite3`):

```bash
python pipeline/backfill_ckan.py --limit 10   # prueba
python pipeline/backfill_ckan.py              # full: 70 GB, se puede dejar corriendo
python pipeline/backfill_ocds.py              # bulk zips ARCE 2002-2025 (~30 min)
python pipeline/backfill_ocds_2026.py 01,02,... # meses faltantes 2026 vía RSS (~11 min/mes)
python pipeline/build_index.py                # tabla compras + FTS (idempotente)
python pipeline/backfill_item_titles.py       # títulos reales 84% (requiere idx_compras_ocid que ya crea build_index)
python pipeline/backfill_votaciones.py --camara senadores --periodo 2025
python pipeline/backfill_votaciones.py --camara senadores --periodo 2026
python pipeline/backfill_votaciones.py --camara representantes --periodo 2025
python pipeline/backfill_votaciones.py --camara representantes --periodo 2026
python pipeline/backfill_youtube.py           # canales Senado/Diputados/Presid/Parlamento
python pipeline/backfill_autotranscripts2.py  # subs auto de lo listado
```

Estimaciones: OCDS full ~30 min, votaciones ~45 min (4s/req por cortesía al portal),
YouTube full con whisper → horas/días (opcional: solo auto-subs primero).

Dentro de Docker, cada script con la imagen: `docker compose run --rm gov-audit-mcp pipeline/backfill_votaciones.py --camara senadores --periodo 2025` (modifica el ENTRYPOINT).

## 3. Conectar el MCP al agente (cada superficie)

### Claude Desktop / Claude local (claude_desktop_config.json)

```json
{
  "mcpServers": {
    "uruguay-gov-audit": {
      "command": "python",
      "args": ["/ruta/abs/a/uruguay-gov-audit/mcp_server/server.py"]
    }
  }
}
```

Con Docker:

```json
{
  "mcpServers": {
    "uruguay-gov-audit": {
      "command": "docker",
      "args": ["run", "--rm", "-v", "./data:/app/data", "-i", "govaudit-mcp"]
    }
  }
}
```

### Hermes Agent (perfil nuevo `govaudit`)

```bash
hermes mcp add uruguay-gov-audit --command .venv/Scripts/python.exe --args mcp_server/server.py
hermes mcp list --profile govaudit   # verificar: enabled=true, 10 tools
hermes -p govaudit chat -q "usa estados_sistema y résumemelo en una línea"
```

### OpenClaw / Otros clientes MCP estándar

Lo mismo del bloque Claude Desktop (el server es stdio FastMCP estándar).

## 4. Verificación post-conexión (checklist del agente)

LLamar estas tools EN ORDEN y validar cada respuesta:

1. `estados_sistema` — devuelve JSON con fuentes de ingesta + frescura
2. `compras_buscar(consulta='medicamentos', anio=2025, limite=2)` — esperado: rows con ocid `ocds-yfs5dr-…`
3. `compras_estadisticas(anio=2026)` — esperado: ~46.272 contratos (con outlier STILER documentado en docs/outliers_compras.md)
4. `discursos_buscar('presupuesto', limite=1)` — esperado: cita con link YouTube + minuto

Si (2) falla: correr `backfill_ocds.py` + `build_index.py`.

## 5. Actualización incremental (mensual / semanal)

```bash
# compras: mes anterior de 2026
python pipeline/backfill_ocds_2026.py $(date +%m --date='1 month ago')
# votaciones nuevas sesiones
python pipeline/backfill_votaciones.py --camara senadores --periodo 2026
python pipeline/backfill_votaciones.py --camara representantes --periodo 2026
```

Todo idempotente: re-corre es seguro (ledger registra cada extracción con sha256).
`python pipeline/supervisor.py` para re-lanzar lo que quedó error.

## 6. Qué NO hace el sistema (para que el agente no prometa de más)

- No hay voto nominal individual donde el diario no lo declara (ver docs/roster_parlamento.md y limitación del portal)
- No hay versiones taquigráficas oficiales del Parlamento (solo diario de sesión + transcripción de la señal)
- No lista datasets CKAN si no se corrió backfill_ckan, etc. — todos los módulos son opt-in
