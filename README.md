# UruguayGovAuditMCP

> Pipeline open-source que descarga la data pública del Estado uruguayo, la
> indexa localmente y la expone como **MCP server** para que cualquier agente
> de IA pueda auditar al Estado con cifras citables.

Todo corre en tu máquina. Cada extracción queda registrada con checksum.
Sin claves de API: solo endpoints públicos oficiales.

## Estado de los datos (11/10/2026)

| Fuente | Alcance | Registros | Peso |
|---|---|---|---|
| Datos abiertos (CKAN, catalogodatos.gub.uy) | lo disponible por dataset | 2.718 datasets · 70 organismos | 74 GB |
| Compras del Estado (OCDS, comprasestatales.gub.uy) | 2002–2025 | 2.060.405 contratos (1,4M con monto declarado (≈ UY 4,2 billones en UYU/USD y otras monedas)) | 26 zips |
| Intendencias | presupuestos/licitaciones/rendiciones 2020–2026 | 1.238 documentos, 12 dominios | — |
| Electoral | elecciones 1984–2024 | resultados + hojas de votación por serie | — |
| Parlamento | roster 2025–2030 · votaciones nominales · asistencias 2005–2026 | 145 legisladores · 38 sesiones | — |
| YouTube oficial | Senado, Diputados, Parlamento, Presidencia + talks | 528 videos transcriptos · 888.000 segmentos indexados (FTS) | 20.121 catalogados |
| Planes de gobierno | 1990–2026 | planes históricos + 2024 | — |

**Índice local**: `data/govaudit.sqlite3` (0,75 GB) con tabla `compras`
(2M+ filas, índices por buyer/año) y FTS5 de transcripciones.
**Registro de ingesta**: `data/ledger.sqlite3` — cada archivo descargado con
`sha256`, URL de origen y timestamp.

## Cómo funciona

```
pipeline/            un script por fuente (backfill_*), todos usan ledger.py
  ledger.py          tabla central: status/bytes/sha256/URL por extracción
  backfill_ckan.py   dump catalogodatos.gub.uy (API sin clave)
  backfill_ocds.py   bulk zips ARCE → tabla compras (valor desde items)
  backfill_youtube.py / backfill_autotranscripts.py   canales → auto-subs
  backfill_whisper.py  faster-whisper local (int8) para videos sin subs
  backfill_intendencias.py / backfill_electoral.py / backfill_palnes…
  build_index.py     SQLite: compras + FTS transcripciones
  supervisor.py      re-lanza lo fallido (cron 30 min)
mcp_server/server.py FastMCP stdio — las tools que consume cualquier cliente MCP
config/              canales verificados, fuentes, worklists
docs/                ficha técnica por módulo
data/                (fuera de git) descargas + metadata + export
runs/                manifests de corrida + ledger.csv (commit)
```

Cada write de una fuente declara `cobertura_periodo` explícito
(**límite oficial: post-1985**), ver `docs/CONVENCIONES.md`.

## MCP server

```bash
python mcp_server/server.py        # stdio, sin red, local
```

Tools (v0.2 + 2 nuevas):

- `compras_buscar(consulta)` — busqueda full en 2M contratos por comprador/proveedor/año
- `compras_gasto_proveedor(proveedor, anio?)` — total, contratos y compradores de un proveedor
- `compras_estadisticas(anio?)` — total anual + top proveedores + top compradores (nuevo)
- `compras_alertas` — patrones sospechosos: concentración, fraccionamiento, repeticiones
- `parlamento_buscar(consulta)` — datasets parlamentarios locales (repartidos, proyectos)
- `discursos_buscar(consulta)` — FTS en transcripciones YouTube con link al minuto exacto (nuevo)
- `rep_declaraciones(handle)` — declaraciones de medios de los actores políticos
- `estados_sistema` / `ayuda_sistema` — estado real de la ingesta y catálogo de capacidades

Las salidas van en markdown con **provenance embebido** (dataset, URL oficial,
fecha de descarga). Negative capabilities declaradas en cada docstring.

## Docker (sin instalar Python)

```bash
docker build -t govaudit-mcp .
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' | \
  docker run --rm -v "$PWD/data:/app/data" -i govaudit-mcp   # responde con capabilities → OK
```

## Data inicial sin correr el pipeline

Release `data-bundle-20261011` con la base completa (compras 2.12M + votaciones +
ledger + roster): `gh release download data-bundle-20261011 -R
martinvarelaaaa/uruguay-gov-audit -p "*.zip" -O bundle.zip && unzip bundle.zip`

## Onboarding para agentes de código

Hermes / OpenClaw / Claude Code / Cursor / Claude Desktop: ver
`docs/AGENT_ONBOARDING.md` — instalación, carga inicial (bundle pre-construido o
regenerar desde la fuente), checklist de verificación con tool-calls, y
actualización incremental.

## Uso rápido

```bash
# backfill inicial (chico para probar / completo horas)
python pipeline/backfill_ckan.py --limit 10
python pipeline/backfill_ckan.py            # full: 2.7k datasets

# compras + índice
python pipeline/backfill_ocds.py
python pipeline/build_index.py              # rebuild compras + FTS (idempotente)

# estado
python pipeline/ledger.py --summary
python pipeline/ledger.py --errors
python pipeline/ledger.py --export          # → runs/ledger.csv

# hay errores de descarga puntual? retry con fallback TLS
python pipeline/retry_ckan_errors.py
```

## Cliente MCP (ej. Claude Desktop / Hermes)

```json
{
  "mcpServers": {
    "uruguay-gov-audit": {
      "command": "python",
      "args": ["mcp_server/server.py"]
    }
  }
}
```

## Telegram

El proyecto incluye un bot ciudadano (`@Govuyauditormcp_bot`) construido sobre
este MCP: responde preguntas de auditoría con citas. Config por perfil en
`HERMES_HOME` (perfil `govaudit`), `SOUL.md` con reglas de fiscal técnico
(cita o callá, sin opinión partidaria).

## Provenance y seguridad

- Cada archivo descargado: `sha256` + URL en `ledger.sqlite3`.
- Los documentos extraidos (PDF/transcripciones) llevan front-matter con origen.
- Las tools citan fuente y fecha al pie de cada dato. Nada inventado.
- Sin datos personales privados: solo datasets públicos oficiales (Ley 18.381).

## Licencia

MIT — ver `LICENSE`.
