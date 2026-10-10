# UruguayGovAuditMCP — Arquitectura v0.1 (local-first)

Principios: **local-first**, **provenance obligatorio** (cada dato lleva fuente+checksum+fecha), **fetch/normalize/load separados**, **todo auditable** (logs de ingestión registren lo que salió bien y lo que falló, para que cualquier persona pueda re-runnear o auditar).

## Piezas (5 procesos)

```
┌─────────────┐   ┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────┐
│ 1. BACKFILL │ → │ 2. INCREMENT│ → │ 3. SUPERVISOR │ → │ 4. SERVIDOR  │ → │ 5. AGENTE│
│ (una vez)   │   │ AL (cron)   │   │ (verifica/    │   │ MCP FastMCP  │   │ (Hermes/ │
│ histórico   │   │             │   │  recupera)    │   │本地           │   │ Telegram)│
└─────────────┘   └─────────────┘   └──────────────┘   └──────────────┘   └──────────┘
```

### 1. Backfill (carga masiva inicial) — `pipeline/backfill.py`
Una corrida larga (semanas si hiciera falta, se reanuda). ETAPAS:

- **E1 — CKAN nacional** (horas, API sin clave): `package_search` paginado ~2.700 datasets + `package_show` por dataset → metapaís + resources. CSV/XLSX/JSON que se puedan descargar directo → dump `data/ckan/`.
- **E2 — OCDS compras** (horas, bulk): ARCE publica JSONL 2002–2026 → download directo, sin scraping. ~1-2 GB.
- **E3 — Parlamento** (horas): datasets CKAN de parlamento (diarios de sesiones, asistencia, proyectos) + versiones taquigráficas (scrape suave, respetando 403 en algunas rutas).
- **E4 — YouTube (el más voluminoso)**: tarifa de descarga de TODOS los videos de los ~34 canales oficiales verificados. Con `yt-dlp`: primero auto-subs (gratis, rápido) → ~500-1.000h/año de sesiones + conferencias diarias. Luego de a poco: audio m4a → faster-whisper (es-ml) → transcripciones con timestamps. ESTO corre en cola con rate-limit — es el backfill más pesado (dias/semanas de CPU si transcribimos todo). Prioridad: primero solos los auto-subs + metadata, transcripción on-demand o en background incremental.
- **E5 — scrape del resto** (IMPO, TCR, rendiciones Corte Electoral, UINS MSP, ANEP): Descarga/parsea PDF con Docling/pdfplumber → markdown estructurado.

Cada etapa es **reanudable** (checkpoint JSON de items done/failed) y corre con `--dry-run`/`--limit N` para probar.

### 2. Incremental (cron) — `pipeline/incremental_*.py`
∎ Cada fuente tiene su cadencia natural:
- CKAN / OCDS / presupuesto: diario (2 a.m.)
- Parlamento (sesiones nuevas): diario
- YouTube: cada 6 h (conferencias diarias de Presidencia, sesiones)
- Scrapes pesados (IMPO, TCR): semanal
- Todo lo ya descargado: solo, usando `If-Modified-Since`/checksum — volver a descargar si cambió.

Corre en Hermes como cron (`.py` como los crons existentes, no `.sh` — por el bug WSL/bash del runtime que ya conocé).

### 3. Supervisor / watchdog — `pipeline/supervisor.py`
- Lee los run-manifests de cada ingestión (`runs/<fuente>/<fecha>.json`: items, ok, failed, checksums).
- Detecta: fuente caída, dataset que desapareció, stream/video que no se pudo transcribir, TTL vencido (dato más viejo que la cadencia).
- **Recovery**: re-encola fallidos con backoff exponencial después de 3 reintentos → alerta.
- Reporte: `status.json` global (fuente/acceso ✓/✗) que el MCP expone como tool `status_ingestion` — así **cualquier usuario ve la salud del canal**.

### 4. Servidor MCP — `mcp_server/` (FastMCP, Python)
Tools atómicas (schema FastMCP, respuestas SIEMPRE con bloque provenance):
- `buscar_datasets`, `consultar_compras`, `buscar_proyectos_ley`, `sesiones_legislativas`, `conferencias_presidencia`{" — `consulta_cotizaciones` (SOAP BCU ya en ckán datasets anyway), `pedido_acceso_info` (generador Ley 18.381 + tracking 20 días), `ocr_documento` (Docling), `consulta_presupuesto`, `status_ingestion`.

### 5. RAG/índice
LlamaIndex + BGE-M3 embeddings → LanceDB local (sin servidor). Índice DOC→URL→página/timestamp para citas clicables.

## Storage y formatos

- **Git-repo estructura**:
  - `code` (pipeline, MCP, config) — versionado, push a GitHub
  - `data/` — **NO commitear**: históricos grandes (OCDS ~2GB, transcripciones, PDFs). `.gitignore`.
  - `data/metadata/` — pequeños, **sí vía git**: manifests del backfill, índices CKAN (composite JSON), catálogo del metapaís — eso ES open data y valioso en el repo (~decenas de MB).
  - `runs/` — manifests de ingestión (orden, ok, fallidos, checks). También push.
  - `data/vector/` — LanceDB local, no commitear.
- **Formatos**:
  - Tabulares: **Parquet** como almacén local (columnar, comprimido, lectura parcial, schema evolución tolerable; sqlite en OCDS-metapaís ya existe okfn — mantiene)
  - JSON/Manifests para índices/estructura/snapshots del catálogo
  - Markdown para transcripciones/OCR de documentos (neto LLM-friendly) con **front-matter de provenance** (url, fecha, checksum de la original)
  - CSV/export públicos: `data/export/…` de lo queInteresting apto para open data en el repo
- WHY Parquet + SQLite + LanceDB y no una DB server (Postgres):
  - **Zero admin**: esto corre en la máquina de cualquier persona que clona el repo — sin password, sin puerto, sin docker.
  - **Columnar = queries analíticas** ("gasto por inciso por año") con Parquet+DuckDB/Polars — ése es el 90% de las consultas.
  - **Git-friendly en el subset que importa** (manifests/small metadata), heavy binaries afuera (transcripciones de audio, OCDS raw) — así el repolite sí sube a GitHub, la data no (todos los datasets ya son públicos en origen; no hace falta replicarlos en GitHub).
  - LanceDB: embebido, sin server, columnar — para embeddings vector confusion.

## Storage sizing (estimado)
- OCDS 2002–2026 JSONL bulk: ~1-2 GB
- Parquet normalizado: ~0,5-1 GB
- Transcripciones whisper de todo el histórico: ~50 MB texto + cola de audio descartado (stream, no store)
- PDFs TCR/IMPO/rendiciones: ~1-2 GB si retenemos originales (recomiendo retenerlos con checksum — es evidencia)
- Vector (LanceDB): ~1-2 GB
Total: ~5 GB — manejable en cualquier laptop. No subimos la data, subimos el código + manifests + índices; quien quiera reconstruye con los scripts.

## .gitignore mente enorme picture
```
data/ckan/*
data/ocds/*
data/transcripts/*.m4a
data/pdf/*
data/vector/*
runs/logs/*
```
(commitear: código, config, manifests jsonl pequeños, status.json, INFORME_INTEGRADO.md)

## Cómo corre en Hermes (fase 1)
- cron `govaudit-incremental` (diario 02:00): llama a `pipeline/incremental_all.py` (CKAN+OCDS+parlamento) — ayuda si rate-limit, del tamaño del mango con.backoff.
- cron `govaudit-youtube` (cada 6 h): cola de post-proceso de videos nuevos (subs→whisper).
- cron `govaudit-supervisor` (cada 30 min): chequeo de status + alertas a Telegram.
- MCP server registrado (`hermes mcp add uruguay-gov-audit` → stdio FastMCP).

## Roadmapientos de implementación (orden sugerido)
1. **S1 (v0.1 — E1+E2)**: CKAN dump + OCDS download → Parquet/SQLite → MCP con `buscar_datasets`+`consultar_compras`+`status_ingestion`. En una semana beta.
2. **S2 (E3+E5)**: parlamento CKAN + scrape diarios de sesiones + Tipos de Docling para TCR/IMPO.
3. **S3 (E4)**： backfill de YouTube progressive + indexación de transcripciones.
4. **S4**： módulo Ley 18.381 (SAIP / email), `pedido_acceso_info` + tracking.
5. **S5**： publicar a GitHub, README "auditá vos", page pública (más adelante, cuando decidamos hosting/data-mirror).
