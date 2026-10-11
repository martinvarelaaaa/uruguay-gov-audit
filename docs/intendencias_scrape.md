# Módulo `intendencias_scrape` — webs oficiales de intendencias (fuera de CKAN)

## Qué es

13 intendencias no publican datasets en el catálogo nacional CKAN
(`catalogodatos.gub.uy`) — solo lo hacen Canelones, Durazno, Florida,
Montevideo, Rocha y San José (esas las cubre `backfill_departamentales.py`,
NO re-scrapearlas aquí). Este módulo scrapea directamente las webs oficiales
(.gub.uy) de las 13 restantes para armar el paquete de auditoría departamental:

1. **Presupuesto** quinquenal / modificativas (prioridad 1)
2. **Rendiciones** de cuentas / ejecución (prioridad 2)
3. **Compras / contrataciones** pliegos y llamados locales (prioridad 3)
4. **Gabinete** / autoridades / organigramas (prioridad 4)

Todo fetch queda registrado en `data/ledger.sqlite3` con
`source=intendencias_scrape`, vía las funciones `pipeline/ledger.py`
(record_start/record_finish) — **nunca se hace fetch sin registro**.

## Cómo correr

```bash
# venv del repo SIEMPRE (python del PATH no sirve):
C:/Users/marti/uruguay-gov-audit/.venv/Scripts/python.exe pipeline/backfill_intendencias.py --intendencia salto --limit 5

# todas las intendencias (lento; sleep 3s entre requests):
C:/Users/marti/uruguay-gov-audit/.venv/Scripts/python.exe pipeline/backfill_intendencias.py

# solo descubrimiento, sin bajar archivos:
C:/Users/marti/uruguay-gov-audit/.venv/Scripts/python.exe pipeline/backfill_intendencias.py --dry-run
```

Flags de `--intendencia` admitidos (nombres en `config/intendencias.json`):
artigas, cerro-largo, colonia, flores, lavalleja, maldonado, paysandu,
rionegro, rivera, salto, soriano, tacuarembo, treinta-y-tres.

## Estructura

```
pipeline/backfill_intendencias.py   # motor (httpx + BeautifulSoup)
config/intendencias.json            # UNA entrada por intendencia (ver abajo)
data/intendencias/<nombre>/<cat>_<archivo>.pdf      # archivo crudo (git-ignored)
data/metadata/intendencias/<nombre>/<cat>_<archivo>.json  # provenance por doc
data/metadata/intendencias/_robots/<dominio>.txt    # snapshot robots.txt consultado
```

Cada `<cat>_<archivo>.json` de metadata incluye: URL exacta del documento,
URL de la página que lo enlaza, categoría auditoría, sha256, tamaño, fecha
ISO-8601 de descarga y run_id. El sha256 también queda en el ledger.

## Cómo contribuir / agregar una intendencia

1. Entrar a la web oficial, identificar las **secciones** lógicas (presupuesto,
   rendiciones, compras, gabinete) y las URLs de esas páginas.
2. Agregar UNA entrada en `config/intendencias.json` con esos `seed_urls`
   verificados (no adivinados).
3. Correr `--intendencia <nombre> --dry-run` primero; si la cuenta de
   documentos descubiertos es 0, revisar si los links son directos `.pdf/.xlsx`
   o si el sitio necesita una seed más profunda (agregar la URL de la sub-sección).
4. Correr con `--limit 3` para validar descargas reales + metadata.

Sólo se edita JSON. No hay que tocar el motor.

## Cautelas / limitaciones conocidas

- **Rate limit explícito**: el motor hace `sleep=3s` entre requests, un solo
  request en vuelo (ningún dominio concurrente). No lo bajes: sitio oficial
  puede caerse; un bloqueo por hammering rompe el scrape para todos.
- **robots.txt** de cada dominio ban global (`Disallow: /`). Con él el motor
  NO lo crawlea (no se viola el robots); en la práctica solo Colonia está así,
  y sus PDFs son links directos al home (URLs conocidas disponibles en el
  config), así que la corrida igual los baja como "descarga directa".
- Intendencias con sub-sitio en gub.uy (Cerro Largo, Lavalleja): los hosts
  reales de los links son `www.gub.uy`/`<intendencia>`; el config declara los
  `domain_allow` correspondientes.
- Soriano: sus licitaciones viven en `llamados.soriano.gub.uy` (SPA en
  JavaScript sin HTML estático) — el motor no lo scrapea; para ese caso dará
  0 documentos en `compras` hasta que el sitio los exponga en HTML.
- Tacuarembó y Treinta y Tres: las páginas de autoridades / licitaciones
  enlazan PDFs variados y organigramas — el crawler los categoriza en
  `gabinete` / `compras` por patrón de URL/título.
- No scrapear Facebook/Instagram/TikTok ni compras estatales nacional
  (`comprasestatales.gub.uy`) — seguido en fase 2 (ver spec).

## Cadencia / frescura

La corrida de backfill es idempotente: los archivos ya presentes en
`data/intendencias/` se marcan `skipped` en el ledger sin re-descargar (la
comparación es por existencia local; un documento con contenido nuevo en otra
URL genera otra fila igual). Puede programarse cada 168 horas (semanal). El
supervisor no está modificado para incluir esta cadencia (archivo compartido
con otros procesos en flight); la cadencia objetivo 168h queda anotada aquí
hasta que supervisor.py la incorpore.

## Verificadas y funcionando (fecha de prueba 2026-10-10)

| intendencia | docs descubiertos (límite de corrida) | comentarios |
|---|---|---|
| artigas | 15+ (5 bajados) | transparencia + presupuesto 2026 + rendición 2023 |
| cerro-largo | 0 en secciones | subsitio gub.uy con estructura solo en texto; adquisiciones sin llamados vigentes |
| colonia | 14+ (3 bajados) | robots Disallow-/ respetado; PDFs por URL directa del home |
| flores | 3+ | home con links de datos abiertos (RC 2025, rendiciones) |
| lavalleja | 130 | 10 grupos-page w/ max-depth; necesita seed más fina (115 docs son tomos PDF) |
| maldonado | 6 (3 bajados) | presupuesto 2026-2030 disponible |
| paysandu | 17 | PDF de presupuesto quinquenal 2026-2030 disponible; adquisiciones sin llamados vigentes |
| rionegro | 40 (4 bajados) | WP con presupuestos y formularios |
| rivera | 40 (4 bajados) | w/ secciones presupuesto/rendiciones |
| salto | 23 (5 bajados) | principalmente pliegos de compras |
| soriano | 4 (3 bajados) | presupuesto disponible; licitaciones movidas a llamados.soriano.gub.uy (SPA en JS, no scrapearlo) |
| tacuarembo | 1 | sólo formulario de preferencia; resto del sitio es dinámico |
| treinta-y-tres | 243 (4 bajados) | mucho llamado desde 2020; la mayoría sindical/educativa |
