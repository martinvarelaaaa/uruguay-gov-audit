# discursos_y_redes — módulo de "lo que DICEN" (X/Twitter + YouTube talks)

**Parte del UruguayGovAuditMCP** (auditoría ciudadana). Este módulo registra lo que
cada representante público uruguayo **dice** —tweets públicos y entrevistas/charlas
de YouTube— para poder cruzarlo (en la fase 2) con lo que **hace**
(votos en el parlamento, presupuestos, compras OCDS, datos CKAN).

## Principios (idénticos al resto del repo)

- **Ledger obligatorio**: toda extracción pasa por `pipeline/ledger.py` (`record_start`/`record_finish`)
  con `source=x_representantes` (tweets) o `source=youtube_talks` (charlas). Nunca fetch sin registro.
- **Provenance obligatoria**: cada tweet/transcripción lleva URL exacta, fecha real de
  publicación, handle/canal, checksum (sha256) y fecha de descarga.
- **Sólo datos PÚBLICOS**: sin login, sin cookies, sin datos privados de terceros.
- **Rate limit respetuoso**: sleep >= 2s entre requests (config con `GOVAUDIT_X_SLEEP` /
  `GOVAUDIT_YT_SLEEP`, default 2.5s), y sleep de backoff en errores.

## Cómo correr

```bash
# tweets (X/Twitter):
.venv/Scripts/python.exe pipeline/backfill_x.py --run-id x-$(date +%Y%m%d)
# sólo algunos handles:
.venv/Scripts/python.exe pipeline/backfill_x.py --handles OrsiYamandu mef_Uruguay

# charlas (YouTube):
.venv/Scripts/python.exe pipeline/backfill_talks.py --run-id talks-$(date +%Y%m%d) --limit 3
```

Salidas:
- `data/x/<handle>.jsonl` — tweets con `{tweet_id, handle, fecha, texto, url, media,
  es_retweet, descargado, checksum}` (schema grep/duckdb-friendly del spec).
- `data/transcripts/talks/<slug>/<video_id>.md` — transcripciones whisper con front-matter
  provenance (URL, canal, channel_id, político, tema, upload_date real, fecha_proceso).
- `data/metadata/youtube/talks.json` — worklist de canales + videos semilla.
- `data/metadata/youtube/talks_worklist.json` — metadata real de cada video (duración,
  fecha de upload), la arman `build_worklist`.

Ledger: `python pipeline/ledger.py --summary` / `--errors` para auditar las corridas.

## Cómo contribuir (agregar representante / canal / video)

1. **Tweet del representante**: editá `config/representantes.json` y sumá una entrada
   `nombre, cargo, partido, handle_x, tipo_cuenta` ('personal' o 'institucional' — ver
   nota abajo). Nada más: el backfill lee ese JSON solo.
2. **Canal de entrevistas de YouTube**: editá `data/metadata/youtube/talks.json` — sumá el
   canal (slug, channel_id, nombre, tipo) y/o el `video_id` del tweet ya verificado.
3. **Que una entidad es institucional o personal**: anotá `tipo_cuenta`. El módulo no asume: cada handle registra su verificación en el campo `verificado` del mismo JSON.

### Verificación de handles (2026-10-10)

El handle del spec estaba **stale/incorrecto** en 3 de los 5 representantes de la semilla.
Correcciones hechas con investigación web antes de registrar en `config/representantes.json`:

| spec decía          | realidad (verificada 2026-10-10)                                        |
|---------------------|-------------------------------------------------------------------------|
| OrsiYamandu         | ✅ correcto — cuenta **personal** del presidente (bio 2025-2030)         |
| OddoneGabriel (stale) | el ministro no tiene cuenta personal activa; MEF institucional: **mef_Uruguay** (cuenta del ministerio que habla en su nombre) |
| MinLubetkinUy "Carina Lubetkin, Ministra de Salud" | **EQUIVOCADO**: Mario Lubetkin es el **Canciller** (no Carina; @MinLubetkinUy es su cuenta de canciller). Asumimos: la ministra de Salud es **Cristina Lustemberg**, handle **LustembergC** (personal). |
| Minterioruy "Gabriel García, Ministro de Interior" | **EQUIVOCADO**: el ministro es **Carlos Negro** (@CNegro7, personal). @Minterioruy es la cuenta institucional del Ministerio — la mantenemos como entrada separada. |
| OrtunoEdgardo       | ✅ correcto — cuenta personal del ministro de Ambiente                   |

### Verificación de canales de YouTube (2026-10-10)

Channels verificados con oEmbed o yt-dlp (channel_id real ≠ handle):

- **TV Ciudad** `UCcEFFCUo9fD5DK1FcclyKUA` (@TVCiudad6.1) — Lado B, Info Capital, Mirá Montevideo.
- **Arriba Gente (Canal 10)** `UCxtwLYYm-TUBDd_uOkjLB9A` (@ArribaGente_uy) — entrevistas matinales.
- **Desayunos Informales** `UCFFAin85cmlgsKj8c6mNP9w` — podcast político.
- **VTV Uruguay (Sin Piedad)** `UCA4VRT895OOPPHq-pc2V2CQ` — entrevistas largas.
- **BÚSQUEDA** `UCa2cus7gyarXD8049iaLHBg` — entrevistas semanales a políticos.
- **MEF Uruguay** `UCu6vr8WRDa_4vxKeZZS7sxg` — ruedas de prensa del ministro de Economía.
- Senado/Diputados/Presidencia/Parlamento — ya están en `config/channels.json` (core) y se
  procesan con `pipeline/backfill_whisper.py`; NO duplicados acá.

## Cómo se extraen los tweets de X sin API paga (protocolo de extracción)

X bloqueó el scraping anónimo: snscrape/Twint/Nitter muertos (guest tokens cerrados),
`gallery-dl` exige cookies (prohibido para este repo), `twikit` roto (2026.10),
la API GraphQL anónima con guest token devuelve id "0" (agregado 2026).

**Lo que SÍ sirve (usado por `backfill_x.py`):**
1. **Timeline de un handle**
   `https://syndication.twitter.com/srv/timeline-profile/screen-name/<handle>?showReplies=false`
   -> HTML con `__NEXT_DATA__` JSON embebido, entries `content.tweet` con
   `{id_str, full_text, created_at, mediaDetails, user, permalink, ...}`. Es el mismo
   endpoint del widget de embed oficial (`publish.twitter.com`) — endpoint público, sin
   login. PERO el orden de los id_str es **aleatorio** y **sin cursor de paginación**:
   ventana de ~5 meses (aprox [ahora-2, ahora-1.6] en 2026) — NO es full-history.
2. **Tweet individual (JSON embed)**
   `https://cdn.syndication.twimg.com/tweet-result?id=<id>&token=x&lang=es`
   -> JSON público: `created_at` (fecha real), texto, media, user, counts.
   Aquí sí es exacto y `created_at` es la fecha **real de publicación**.

`backfill_x.py` (modo default, conservador) registra por handle el tweet MÁS RECIENTE
(listado en el campo `latest_tweet_id` del `__NEXT_DATA__`), le baja el JSON embed
(fecha exacta) y lo agrega como línea al JSONL con checksum. No se inventan datos:
lo que la vía pública no resuelve queda fuera del .jsonl y el run queda `partial`
en el ledger con el error explicativo. Modo opcional `--todos` (JPEG de los ~100
tweets de la ventana aleatoria): agrega SOLO los tweets cuya fecha exacta se pudo
confirmar vía `tweet-result`. **Limitación conocida (TODO documentado)**: esta vía
pública NO permite recorrer el history completo ni paginar (los id_str van aleatorios
sin cursor); un extractor de history completo (`mode="history"`) queda como TODO
cuando exista una vía abierta — el schema del .jsonl y del ledger ya lo soportan.

## Errores conocidos / TODOs

- Sin full-history de X: la única vía sin cookies.limita a ventana reciente sin cursor.
- `gallery-dl` está instalado en el .venv pero NO se usa (exige cookies). `twikit` 2.3.3
  instalado, roto en 2026.10 ("Couldn't get KEY_BYTE indices").
- backfill_x.py no borra duplicados del .jsonl: la idempotencia se resuelve al consultar
  (tweet_id + checksum) — mismo tweet re-descargado agrega otra línea igual, el ledger
  muestra las dos corridas.
## Cómo ejecutar la fase 2 (cuando esté, queries del spec)

El spec pide que las queries `que_dijo(nombre, tema|fecha)` / `que_hizo(nombre)` /
`discrepancias(nombre)` sean "naturales". Para eso este módulo deja los datos listos:

- `data/x/*.jsonl` y `data/transcripts/talks/*/**.md` ya cumplen:
  `duckdb -c "SELECT * FROM 'data/x/*.jsonl' WHERE handle='OrsiYamandu'"`
  y el .md del whisper con front-matter ya es greppable (`politico:` en el header).
