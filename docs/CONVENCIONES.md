# CONVENCIONES del pipeline (UruguayGovAuditMCP)

Reglas transversales que toda fuente nueva, config JSON y script de backfill
debe respetar. Basadas en la estructura existente del repo (ledger en
`pipeline/ledger.py`, backfills en `pipeline/backfill_<fuente>.py`, configs en
`config/`, specs de fuente en `docs/src_spec_*.md`).

## 1. Alcance temporal: post-1985 (decisión del owner, 10/10/26)

**Límite oficial: post-1985.** Todo lo previo a 1985 (dictadura 1973-1985 y
antes) queda **FUERA de scope**: no está digitalizado, son archivos físicos.

Por lo tanto:

- Las coberturas y timestamps de los datasets arrancan en **1985** (o el
  primer año disponible posterior — cada legislatura/análisis posterior a esa
  fecha es válido mientras empiece ≥ 1985).
- Todo dataset, fuente o config debe declarar el campo **`cobertura_periodo`**
  explícito en formato `'YYYY-YYYY'` (e.g. `"1985-2026"`). Si una fuente solo
  tiene data desde un año posterior (e.g. planes 2020+), el campo lo refleja
  tal cual (`"2020-2026"`) — no se inventa data retrospectiva, pero el límite
  superior de lo que se colecta nunca baja de 1985 ni el interés se extiende
  hacia lo previo.
- Los reports/tools del MCP que presenten series temporales no deben ofrecer
  slices previos a 1985.

Referencia: la extensión histórica 1985+ del módulo votaciones
(`docs/src_spec_votaciones.md`) sigue esta misma regla — hacia atrás desde el
presente hasta 1985, nunca más allá.

## 2. Formato de fuentes

- Toda fuente nueva = un script `pipeline/backfill_<fuente>.py` que usa el
  ledger (`record_start`/`record_finish` de `pipeline/ledger.py`). Sin
  registro en ledger, la fuente no existe para el sistema de status.
- Config de la fuente en `config/<fuente>.json` con al menos: identificador
  de la fuente, URLs oficiales, y el campo `cobertura_periodo` (§1).
- Solo datos públicos. Cada item descargado lleva provenance: URL origen +
  fecha de descarga + checksum (sha256 en el ledger, front-matter en
  documentos extraídos).
- Rate limit y cortesía con los portales oficiales (sleep entre requests,
  headers de navegador real cuando el portal filtra bots — ver patrón en
  `docs/src_spec_votaciones.md`).

## 3. Regla de citación

Toda afirmación, dato o cifra que salga del sistema hacia un usuario, informe
o tool del MCP debe llevar citación verificable:

- **Fuente primaria primero**: URL exacta del documento/registro oficial del
  que sale el dato (versión taquigráfica, dataset CKAN, OCDS release, PDF del
  programa, video oficial).
- **Checksum cuando aplique**: si el dato viene de un archivo descargado,
  citar con el sha256 que registre el ledger — así la cita es reproducible
  bit a bit.
- **Fecha de acceso**: toda cita incluye cuándo se consultó la fuente
  (`descargado` / `verificado`), porque los portales oficiales se reorganizan.
- Si un dato no puede rastrearse a fuente primaria, se marca como tal
  (`sin_provenance` o nota) y no se presenta como verificado.
