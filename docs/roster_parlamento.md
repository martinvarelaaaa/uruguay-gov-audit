# roster_parlamento — Roster 100% del Parlamento (legislatura 50, 2025-2030)

## Qué es
Snapshot estructurado de los 145 legisladores que integran hoy el Parlamento uruguayo
(31 Senadores incl. Presidenta + 99 Representantes titulares + 14 suplentes en ejercicio),
con partido/lema, sector (agrupación-política y sublema de la hoja de votación 2024,
ordinal y rol), trayectoria de legislaturas, contacto oficial y handle X cuando existe.

## Archivos (git-able, under data/metadata/roster/)
- `roster_parliament_v1.json` — roster completo (145 registros). Campos:
  - `camara`, `nombre`, `legislador_id` (id numérico del portal), `url` ficha oficial
  - `partido_lema`, `descripcion` (cargo/depto según ficha oficial), `cargo` (Presidente/a)
  - `banca`: `titular` | `suplente_en_ejercicio`; `en_ejercicio` bool
  - `sustituciones` (texto oficial de la suplencia activa)
  - `sector_lista`: lista de candidaturas 2024 (agrupación/sublema/ordinal/rol) — fuente: CSV integración hojas de votación (Corte Electoral)
  - `lista_principal`: la candidatura primera (mayor jerarquía) de `sector_lista`
  - `trayectoria_legislaturas`: las legislaturas del portal (L, XLIX, XLVIII…)
  - `mails`, `bio_pdf` (URL del CV oficial si existe)
  - `handle_x` + `handle_x_verificacion` — cuando la verificación pública vía syndication (sin login) ya corrió; los no verificados quedan en `handles_x_candidatos` con candaditos ordenados por verosimilitud
- `export/roster_2025_2030.csv` — export plano para consumo fácil.
- `integracion_senadores.json` / `integracion_representantes.json` — JSON oficial de integración de cada Cámara (actuantes hoy + sustituciones).
- `titulares_tab.json` / `titulares_map.json` — titularidad de banca vs actuante, con el id del titular reemplazado.
- `asistencias_*.json` — asistencias legislatura 50 (portal datos abiertos).
- `fichas_pages/<id>.json` — ficha por legislador (141 + 4 en licencia = 145 irrelevantes en runtime).

## Fuentes (provenance)
- `parlamento.gub.uy` — integración de plenarios (HTML+JSON `/integracion/json`), fichas de legisladores, asistencias.
  URLs exactas grabadas en cada JSON (`href`, `url`, `sustituciones` son texto literal de latada).
- Corte Electoral: `data/electoral/2024_-integracion-de-hojas-de-votacion-eleccion-nacional.csv`
  (descarga de CKAN; checksum en ledger `resultados_electoral`) para lista/sublema/ordinal.
- X: verificación vía `syndication.twitter.com/srv/timeline-profile/screen-name/<handle>` (público, sin login,
  mismo protocolo que `pipeline/backfill_x.py`); nombres/bio/followers/latest_tweet_id registrados en `x_handles.json`.

## Cómo actualizar (refresh)
1. Actantes hoy: `GET https://parlamento.gub.uy/camarasycomisiones/{senadores|representantes}/plenario/integracion/json?page&_format=json`
   (y `/titulares`) → re-parse con los regex de `titulares_map.json` parsing (script paso pendiente de modularizar).
2. X: loop `x_queue.py --` a 70s/handle; resumible: reiniciar el proceso y sigue del último pendiente.
3. Refresh full: re-corrida de `scrape_fichas.py` (idempotente por `fichas_pages/`).

## Cautela
- La relación banca↔persona cambia por licencias/pasos a ministerios con frecuencia; refrescar semanal
  (el mismo endpoint define a quién se le atribuyen discursos/asistencias).
- Handles X: verificación por per-auditable vía public endpoint; sólo quedan `handle_x` cuando el match de nombre/descriptiva
  es directo. Para los demás, `handles_x_candidatos` necesita revisión humana o verificación posterior.
