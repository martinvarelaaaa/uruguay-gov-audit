# Spec — módulo `intendencias_scrape` (pipeline paralelo, UruguaiGovAuditMCP)

## Objetivo
Cubrir las 13 intendencias que NO publican en el catálogo nacional CKAN, scraapando directamente sus webs oficiales (presupuesto, rendiciones, contratos/compras locales, gabinete del intendente). Es data clave para audits departamen.

## Patrón obligatorio (igual que resto del repo)
- Usar `pipeline/ledger.py` (`record_start`/`record_finish`) con `source=intendencias_scrape`. Una fila (row) por (intendencia, tipo-doc, archivo). Nunca fetch sin registro.
- **Provenance**: URL exacta de la página web oficial de la intendencia + checksum sha256 + fecha de descarga.
- **Solo datos públicos**: documentos publicados en la web gubernamental gubernamental (gubernamental, .gub.uy). Sin login, sin scraping sobre PDFs con datos personales protegidos (nombres en sueldos individuales filtrarse solo en formato agregado si la web oficial ya los publica así). Rate limit: dormir (sleep) >= 3s entre requests, máx 1 dominio concurrente.
- **Respeto al portal**: revisar robots.txt de cada dominio antes de scrapear. Si una intendencia bloquea (403), marcar a corto plazo e intentar la vía alternativa ( Seeking Alpha en su canal de Telegram/RSS oficial) — reintendar en el siguiente cron, no hot hammer.

## Alcance (intendencias, 19 total)
- **Ya cubiertas por CKAN nacional** (no re-scrapearlas aquí): Canelones, Durazno, Florida, Montevideo, Rocha, San José.
- **A cubrir con scraping (13)**: Artigas, Canelones-check, Cerro Largo, Colonia, Durazno-check, Flores, Lavalleja, Maldonado, Paysandú, Río Negro, Rivera, Salto, Soriano, Tacuarembó, Treinta y Tres — verifiquen en tiempo de run cuáles están fuera de CKAN; alineado a la lista vigente de las webs en: https://www.gub.uy/listado-instituciones (tipo: gobierno departamental).

## Estructura esperada (en el repo)
```
pipeline/backfill_intendencias.py   # motor genérico (httpx + Bs4); descubrimiento de links de PDF/XLS/CSV por dominio
config/intendencias.json            # una entrada por intendencia: {nombre, dominio, secciones: [rendiciones, presupuesto, compras, gabinete], usarios de URL conocidos}
data/metadata/intendencias/<nombre>/<doc>.json   # metadata del documento + provenance
data/intendencias/<nombre>/<archivo>.pdf|xlsx    # archivo crudo (NO git — gitignore ya cubre data/intendencias)
runs/status.json                    # supervisor con cadencia nueva: intentendencias 168h
```

## Qué bajar por intendencia (prioridad auditoría)
1. **Presupuesto anual** (ordenanzas/toes sobre presupuesto)
2. **Rendiciones de cuentas** (informes de ejecución)
3. **Compras/contrataciones** con montos (si la web publica; no confundir con BUY/a nivel nacional)
4. **Gabinete** (director/a general, secret/a general — para el roster de representantes)

## Checklist de aceptación (verifiquen antes de reportar)
- [ ] `python pipeline/backfill_intendencias.py --intendencia salto --limit 5` corre d e v a c i ó n, deja metadata JSONL en disco y filas en el ledger
- [ ] Credenciales no hardcodeadas; dominios de configuración en `config/intendencias.json`
- [ ] Cada documento tiene: URL oficial + checksum + fecha
- [ ] 0 except sin catch; errores van al ledger con mensaje claro
- [ ] Sleep real entre requests (no un sleep fake)
- [ ] README del módulo (docs/intendencias_scrape.md) con cómo correr + cómo contribuir (agregar una intendencia = solo editar JSON)
- [ ] Commits limpios: (1) pipeline + config, (2) primero docs pequeñas de prueba (SMALL: solo metadatos, NUNCA PDFs descargados)
- [ ] Al terminar: reporta qué intendencias funcionaron, cuáles están bloqueadas o no publican данных, archivos generados (paths), commits (hashes)

## Fuera de scope (no hagas)
- Redactar análisis o copys — solo el módulo
- No toques backfill_ckan.py, backfill_ocds.py, backfill_whisper.py, ledger.py, supervisor.py, mcp_server/server.py, backfill_departamentales.py (core permeates at other agents)
- Facebook/Instagram/TikTok de las intendencias (siguiente fase)
- Municipios (139, micro-nivel; regla on-demand)
