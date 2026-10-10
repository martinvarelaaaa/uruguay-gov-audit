# UruguayGovAuditMCP — Informe integrado: data del Estado uruguayo + plan open source

Fecha: 2026-10-10. Informes fuente (detalles completos):
- `reporte_fuentes_estado_uruguay.md` — 49 fuentes oficiales de datos verificadas (tabla + prioridades)
- `informe_transparencia_uruguay.md` — Ley 18.381, procedimientos de acceso, organismos de control
- `estado_uruguay_av/reporte_canales_estado_uruguay.md` — canales YouTube/redes oficiales + pipeline audio
- Stack tech: sección abajo (reporte 4, con links GitHub verificados)

## 1. Qué data existe (resumen ejecutivo)

**~49 fuentes oficiales mapeadas.** Las características decisivas:

- **API CKAN nacional sin clave**: `catalogodatos.gub.uy/api/3/action/package_search` — metapaís entero programático (PDF ~1460, XLS ~188, CSV ~177, SHP ~8 resources indexados). Es LA puerta de entrada.
- **CKANs paralelas**: Parlamento (~24 datasets: diarios de sesiones 1985+, asistencia, proyectos de ley) e Intendencia de Montevideo (159 datasets + CKAN propia).
- **OCDS (Open Contracting)**: ARCE/BUY publica catálogo OCDS 2002–2026 en JSONL bulk — compras del estado completo en estándar internacional. Herramientas open-contracting (kingfisher-collect/process, ocdskit) reutilizables directamente.
- **BCU**: datasets en CKAN + API SOAP de cotizaciones de monedas.
- **Solo scrapeable** (lo más valioso y lo más difícil): diarios de sesiones de parlamento.gub.uy (bloqueo 403 a la home, secciones internas accesibles), IMPO/Rama Jurídica, Tribunal de Cuentas (resoluciones post-2022 vía IMPO), rendiciones de partidos de la Corte Electoral (PDFs + buscador SGPP), dashboards UTE/CND/BPS/BSE, estadísticas vitales MSP (uins.msp.gub.uy), series ANEP.
- **Transparencia activa**: cada organismo publica rendiciones, compras, personal; index de responsables de transparencia por organismo existe como CSV/JSON en CKAN → índice organismo→email para pedidos Ley 18.381.

**Mecanismo de acceso no-open-data (complemento clave del MCP):**
- Ley 18.381: pedido de acceso en 4 vías (portal SAIP solicitudes.gub.uy, formulario web por organismo, email — válido jurídicamente e ideal para automatizar, presencial). Plazo: **20 días hábiles** (no 8) + prórroga de 20. Silencio = positivo; denuncia en UAIP online o acción sumarísima judicial.
- Declaraciones juradas (JUTEP): NO públicas en texto completo; sí listado de omisos y datos derivados legitimmizados (Dictamen 6/023) — a monitorear.
- Financiamiento de partidos: rendiciones PDFs por año, datos abiertos es compromiso del VI Plan de Gobierno Abierto ( dic 2026 — hito a vigilar por el MCP).

## 2. Audiovisual / representantes

- Canales YouTube verificados con IDs UC… (inmutables): @SenadoUY (sesiones Asamblea), @diputados_uy (sesiones + comisiones que citan ministros), Presidencia (~78k subs, conferencias diarias), Canal 5, TV Ciudad, IDM, OPP/INE/BCU/MSP/Aduanas.
- X/Twitter oficiales: @OrsiYamandu, @CancilleriaUy, @MinLubetkinUy, @Minterioruy, @MSPUruguay, @OddoneGabriel (MEF), etc.
- Volumen: ~500–1.000 h/año de sesiones + conferencias diarias.
- Pipeline: yt-dlp (auto-subs primero, gratis) → faster-whisper (español, VAD, timestamps) → índice + LLM. Tiers por costo/calidad.
- Anti-canal-falso: validar contra directorio con backlink al sitio oficial (patrón conlatuya).

## 3. Stack recomendado (verificado en GitHub)

| Capa | Elección | Licencia | Por qué |
|---|---|---|---|
| MCP server | Python 3.11+ **FastMCP** | MIT | Patrón de OpenUSPublicDataMCP; adaptador **CKAN reutilizable directo** |
| Scraping APIs | httpx + BeautifulSoup4 | BSD/MIT | CKAN, parlamento interno |
| Scraping pesado | Scrapy (+ patrón kingfisher-collect) | BSD-3 | Pipeline OCDS de compras |
| JS pesado | Playwright | Apache-2.0 | Solo donde haga falta |
| PDF tablas | pdfplumber | MIT | PDFs nativos (TCR, IMM) |
| PDF escaneado/OCR | **Docling** | MIT | Layout+tablas+OCR local, salida Markdown/JSON para RAG; PaddleOCR (Apache) como OCR alternativo; Surya solo si aceptan GPL |
| RAG local | LlamaIndex + **BGE-M3** (embeddings) + LanceDB/Chroma | MIT/Apache | Español-latam fuerte, todo local |
| Esquemas | **Popolo** (personas/legisladores) + OCDS (compras) | — | Estándares internacionales |
| Provenance | caché con "downloaded_at" + checksum, separar fetch/normalize/load | — | Patrón kingfisher-process |

**Referencias MCP de gobierno:** lzinga/us-gov-open-data-mcp (mejor template estructural — módulos por fuente), HappyMonkeyAI/OpenUSPublicDataMCP (adaptadores Socrata/ArcGIS/CKAN), amurshak/congressMCP (tools por dominio).

**Proyectos de otros países donde inspirarse:**
- Argentina: enzonotario/argentinadatos.com (API pública + visor, patrón idéntico a CKAN uy)
- EEUU: openstates/openstates-scrapers (arquitectura scrapers por jurisdicción), unitedstates/congress-legislators (YAML curado de legisladores — modelo para "parlamentarios.uy")
- Brasil: capyvara/tse (Scrapy electoral incremental — modelo para Corte Electoral), dadosabertos.camara.leg.br (API sin key, el norte para parlamento uy)
- Chile: ChileCompra (referencia regional de compras), APIs-Chile (directorio curado)
- México: comprasMX (compras consolidadas)
- **Uruguay directo — integrar no duplicar: okfn/mcp-datos-uruguay ya existe** (dataset compras-ocds con SQLite ~1GB, YAML declarativo). Punto de partida. También: johnblanco/datos-abiertos-uy, uy-datos-abiertos (lectores con trampas documentadas por fuente), org datauy (77 repos, aliada potencial).

## 4. Plan del MCP — tools v1

- `buscar_datasets` — package_search CKAN nacional + facetas (API, sin clave)
- `consultar_compras` — OCDS ARCE (JSONL bulk → SQLite joven con kingfisher/ocdskit)
- `buscar_proyectos_ley` / `sesiones_legislativas` — CKAN parlamento + scrape versiones taquigráficas
- `conferencias_presidencia` / `transcribir_video` — yt-dlp + faster-whisper on demand
- `consulta_cotizaciones` — SOAP BCU
- `pedido_acceso_info` — generador de pedido Ley 18.381 por organismo (usa índice organismo→email de CKAN), tracking de plazos 20 días
- `ocr_documento` — Docling passthrough
- `consulta_presupuesto` — OPP / transparenciapresupuestaria + finanzas departamentales
- Spot electoral / rendiciones Corte Electoral — scrape PDFs SGPP (v2)

Roadmap: (1) fork/extensión de okfn/mcp-datos-uruguay, (2) scrapers OCDS + parlamento con kingfisher/openstates como patrón, (3) módulo audio (yt-dlp+whisper), (4) módulo 18.381 con SAIP/email, (5) publicación como open source con documentación "auditá vos mismo".
