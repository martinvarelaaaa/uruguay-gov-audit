# Spec — módulo `discursos_y_redes` (UruguayGovAuditMCP)

## Objetivo
Registrar lo que los representantes públicos URUGUAYOS **dicen** en redes (X/Twitter) y en entrevistas/charlas de YouTube, para cruzar con lo que **hacen** (votos, presupuestos, compras OCDS). Mismo estándar del repo:

- **Ledger obligatorio**: usar `pipeline/ledger.py` (`record_start`/`record_finish`) con `source=x_representantes` y `source=youtube_talks`. Nunca fetch sin registro.
- **Provenance obligatoria**: cada tweet/intervención lleva URL exacta del tweet/video, fecha real de publicación, handle/canal, checksum, fecha de descarga.
- **Solo datos PÚBLICOS**: tweets públicos, videos públicos. NO login, NO cookies, NO datos privados de terceros. Rate-limit respetuoso (sleep >= 2s entre requests, max ~1 req/s sostenido).

## Estructura esperada (nueva, en el repo	sprintf)
```
pipeline/backfill_x.py          # extracción de tweets (handle x handle)
pipeline/backfill_talks.py      # buscando político en metadata de canals de entrevistas + descarga + whisper
config/representantes.json      # cada representante: nombre, cargo, partido, handle_X, aliases
data/x/<handle>.jsonl           # tweets: {id, handle, fecha, texto, url, media_url?, retweet?}
data/transcripts/talks/<slug>/<video_id>.md   # mismo formato whisper que ya existe
data/metadata/youtube/talks/<canal>.json      # worklist de canales de entrevistas
```

## config/representantes.json (semilla, handle verificada en investigación previa)
```json
{"representantes": [
  {"nombre": "Yamandú Orsi", "cargo": "Presidente de la República", "partido": "Frente Amplio", "handle_x": "OrsiYamandu"},
  {"nombre": "Gabriel Oddone", "cargo": "Ministro de Economía y Finanzas", "partido": "Frente Amplio", "handle_x": "OddoneGabriel"},
  {"nombre": "Carina Lubetkin", "cargo": "Ministra de Salud (MSP)", "partido": "Frente Amplio", "handle_x": "MinLubetkinUy"},
  {"nombre": "Gabriel García", "cargo": "Ministro de Interior", "partido": "Frente Amplio", "handle_x": "Minterioruy"},
  {"nombre": "Edgardo Ortuño", "cargo": "Ministro de Ambiente", "partido": "Frente Amplio", "handle_x": "OrtunoEdgardo"}
]}
```
(† Verificar estos handles antes de confiar: @Minterioruy es cuenta institucional del ministerio — no del ministro personal. Re-verificar cada handle en la ejecución y anotar en el JSON si es cuenta institucional o personal.)

## Canales de YouTube de entrevistas/charlas (semilla, verifícalo al correr)
- Senado / Diputados (ya en config/channels.json) — sesiones oficiales (referencia "hecho")
- Entrevistas: canal de entrevistas de Canal 10/12/ObD: ej. canal de periodistas - "ponentes", podcasts políticos; drones con políticos en TEDx (búscalo: YouTube busca el nombre del político en título/desc del video)
- Ejecutar: worklist + yt-dlp (ya existe helper en pipeline/backfill_whisper.py) + whisper medium int8 (mismo helper)

## Esquema de data (jsonl de tweets, para que sea grep/duckdb friendly)
```json
{"tweet_id": "123", "handle": "OrsiYamandu", "fecha": "2026-01-15T18:30", "texto": "…", "url": "https://x.com/…", "media": "…", "es_retweet": false, "descargado": "2026-10-10T20:00", "checksum": "…"}
```

## Queries que deben quedar naturales
1. `que_dijo(nombre O handle, tema|fecha desde/hasta)` → tweets + fragmentos de charlas
2. `que_hizo(nombre)` → (fase 2) cruza con datos oficiales ya bajados (parlamento, OCDS)
3. `discrepancias(nombre)` → (fase 2) join semántico

## Checklist de aceptación del subagent (verifica antes de reportar)
- [ ] `python pipeline/backfill_x.py --run-id x-test` corre, deja filas en `data/x/<handle>.jsonl` y en el ledger
- [ ] Cada tweet tiene URL + fecha + texto + checksum
- [ ] `python pipeline/backfill_talks.py --limit 3 --run-id talks-test` corre, genera los .md whisper
- [ ] 0 excepciones sin catch; errores van al ledger con mensaje claro
- [ ] Rate limit: sleep real en el código
- [ ] README del módulo (docs/discursos_y_redes.md) con cómo correr + cómo contribuir (agregar handle/canal = solo editar JSON)
- [ ] Commits limpios en la repo, al menos 2: (1) pipeline + config, (2) primeros datos de prueba (SMALL: solo los JSONL/MD, NUNCA audios ni .venv)

## Fuera de scope (no haga)
- No tocar pipeline/backfill_ckan.py, backfill_ocds.py, backfill_whisper.py, ledger.py, supervisor.py, mcp_server/server.py (pienso en la data oficial)
- Facebook/Instagram/tiktok (fase siguiente)
- Data de parladores multadores no verificados, data en_sc/premium twitter (solo tweets públicos)
