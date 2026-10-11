# votaciones_nominales — quién votó cómo en el Parlamento

Dataset de **votaciones nominales** de las cámaras del Parlamento uruguayo
(Senado CSS + Cámara de Representantes CRR), construido desde los **diarios de
sesiones** (versiones taquigráficas, PDF) del portal oficial
`parlamento.gub.uy`, junto con la **asistencia por legislador** de cada sesión.
Es la pieza para auditar "dijo vs. votó".

## Qué baja

1. **Diarios de sesión por cámara y año**: listado HTML del portal
   (`/camarasycomisiones/{senadores|representantes}/plenario/documentos/diarios-de-sesion`),
   página del PDF (`diario-de-sesion/<id>/IMG`) → PDF en `infolegislativa` →
   texto con `pdftotext`.
2. **Parse del texto**: bloque ASISTEN/FALTAN (CSS) o "Asisten los señores
   representantes / Con licencia / Faltan con aviso / Sin aviso" (CRR) →
   asistencia por legislador; bloques de votación → resultado agregado
   ("–15 en 16. Afirmativa", "Ochenta y tres votos afirmativos y siete votos
   negativos en noventa presentes: AFIRMATIVA", CRR con números en letras).
3. **Voto individual**: el portal NO publica el voto nominal como dato
   estructurado (verificado en el spec y contra CNN/CKAN 2026-10-10). Tres
   caminos:
   - el diario declara **votación nominal explícita** ("se registra el voto",
     "A favor: X, y / En contra: ...") → `parse_nominal()` extrae
     nombre→voto;
   - la votación sale por **UNANIMIDAD** → se deriva el voto individual de
     la asistencia (asistieron = a_favor|en_contra, ausentes = ausente);
   - el resto queda **agregado** (`a_favor_n`/`en_contra_n`,
     `voto_agregado=true`).

## Estructura

```
pipeline/backfill_votaciones.py     # motor
config/votaciones.json              # períodos por cámara + rate limit
data/votaciones/<camara>/<año>/<sesion>.json
data/export/votaciones.csv          # export plano (legislador, camara, fecha, proyecto, voto, url)
```

Campos de `data/votaciones/.../<sesion>.json` (schema SQL-friendly):
`camara, periodo, sesion_id, sesion_nro, sesion_fecha, resumen, url_origen
(PDF real), url_pagina (página del portal), checksum (sha256 del PDF),
descargado, asistencia {legislador: asistio|ausente},
votaciones[{orden, titulo, carpeta, resultado, a_favor_n, en_contra_n,
unanimidad, voto_agregado, votacion {legislador: a_favor|en_contra|abstencion|ausente}}]`.

Cada item queda registrado en el ledger (`data/ledger.sqlite3`,
`source='votaciones_nominales'`) con estado, bytes y sha256.

## Nombres de legisladores

Los nombres extraídos del texto (`Asisten: ..., Faltan: ...` y las listas
nominales) se filtran contra el **roster** del módulo de legisladores
(`data/metadata/roster/roster_parlamento.jah`; fallback:
`roster_provisional.json`, generado por OTRO módulo — este solo lo LEE, no lo
genera). El primer token del nombre debe matchear un apellido del roster; eso
elimina ruido del texto taquigráfico. Si el roster no existe, corre una
heurística débil de 1-2 palabras.

## Uso

```bash
# smoke test (3 sesiones más recientes del período):
python pipeline/backfill_votaciones.py --camara senadores --periodo 2026 --limit 3

# cámara de representantes:
python pipeline/backfill_votaciones.py --camara representantes --periodo 2026

# regenerar (re-descarga y re-parsea aunque los JSON existan):
python pipeline/backfill_votaciones.py --camara senadores --periodo 2026 --force
```

El export CSV (`data/export/votaciones.csv`) se regenera al final de cada run
sobre TODOS los JSON presentes en `data/votaciones/`.

## Cobertura y extensión histórica

`cobertura_periodo` declarado en `config/votaciones.json`
(2025-2026 al 2026-10-10; baja backend). El spec
(`docs/src_spec_votaciones.md`, EXTENSIÓN HISTÓRICA) ordena extender hacia
atrás a medida que el portal lo permita (diarios de sesiones + asistencias
desde hace décadas, CKAN del Parlamento desde 1985), con prioridad
2020-2025 → 2015-2020 → 2010-2015 → 2005-2010 → anterior. Para agregar un
período: sumar el año a `periodos.<camara>` en `config/votaciones.json` y
correr el backfill con `--periodo <año>`. Los listados del portal filtran por
año (un run por año); períodos multi-año se agregan año a año.

## Prohibido / límites

- Solo datos públicos (votaciones nominales son públicas por diseño).
- Rate limit: sleep >= 4s entre requests, 1 request en flight; NO tocar la
  home del portal (403 a bots genéricos) — solo URLs profundas del listado y
  de la página del PDF.
- No genera análisis ni reportes: eso es del bot/core (fase 2: como_voto,
  consistencia vs. tweets/talks, coincidencia_partido, mencanables).
