# Spec — módulo `votaciones_nominales` (UruguayGovAuditMCP)

## Objetivo
Bajar el dataset de **votaciones nominales** del Parlamento uruguayo: quién votó cómo (a favor/en contra/abstención/ausente) en cada proyecto de ley, por período. La fuente oficial es el portal del Parlamento (parlamento.gub.uy / www.parlamento.gub.uy — sistemas de asistencia y votación de ambas cámaras). Es la pieza que falta para auditar "dijo vs. votó".

## Patrón obligatorio (igual que resto del repo)
- Usar `pipeline/ledger.py` (`record_start`/`record_finish`) con `source=votaciones_nominales`. Un item por (cámara, período/sesión-batch).
- **Provenance**: URL exacta de la página del portal de donde sale cada registro + fecha de descarga + checksum del archivo.
- **Solo públicos**: votaciones nominales son públicas por diseño (son el registro de accountability preferido de los legisladores).
- Rate limit: sleep >= 4s entre requests y max 1 request en flight; el portal es sensible (la home 403 a bots genéricos — usar headers de navegador real y URLs profundas, NO la home).

## Fuentes (verificar al vuelo; no fiarse de esto)
1. Sistema de Asistencias/Inasistencias del Senado: https://www.parlamento.gub.uy/normativas-y-documentos/... (secciones Asistencias por período — la herramienta del portal "Sistema de gestion de asistencia")
2. Votaciones nominales de Diputados: sección correspondiente en el portal de la Cámara de Representantes — puede estar en las versiones taquigráficas (donde la votación nominal se lista nomina y efecto)
3. Si el portal no expone CSV: los **diarios de sesiones** (versiones taquigráficas) incluyen la nómina de cómo votó cada legislador — descarga de versiones + parse de la sección de votación (regex/parse del texto: "Señor X: A favor / En contra / No concurrió")
4. Datasets CKAN del parlamento (ya en data/metadata/ckan/): revisar si alguno ya trae votaciones estructuradas (grep en metadata antes de reinventar)

## Estructura esperada (en el repo)
```
pipeline/backfill_votaciones.py     # motor: descarga períodos + parse de votación nominal
config/votaciones.json              # {periodo: {...urls si conocidas}, camara: senadores|diputados}
data/votaciones/<camara>/<periodo>/<sesion>.json  # {sesion, fecha, proyecto, titulo, votacion: {legislador: a_favor|en_contra|abstencion|ausente}, url_origen, checksum}
data/export/votaciones.csv          # export plano para git (legislador, camara, fecha, proyecto_id, titulo_corto, voto, url)
data/metadata/roster/roster_parlamento.jah  # (otro módulo en vuelo lo genera; este NO lo genera, solo lo LEE si existe para normalizar nombres)
```

##Schema de la votación (sql-friendly)
```
{ocamara: 'senadores', fecha: '2026-03-12', sesion_id:'...', proyecto: 'radicado 12/2026 o ley 20.xxx',
titulo: '...', votacion: {'Nombre Apellido': 'a_favor', ...},
url_origen: 'https://www.parlamento.gub.uy/...', checksum: '...', descargado: '2026-10-10T22:00'}
```

## Queries que habilitan (fase 2 las cruza el bot)
1. `como_voto(nombre, proyecto/tema/fecha)` → con URL
2. `consistencia(nombre)`: cruzar sus votos con declaraciones (tweets/talks) sobre el mismo tema — la aud contra REAL
3. `coincidencia_partido(partido)` cohesión por partido en votaciones clave
4. `mencanables`: proporción de asistencias en votaciones de un legislador

## Checklist de aceptación (antes de reportar)
- [ ] `python pipeline/backfill_votaciones.py --camara senadores --periodo 2026 --limit 3` corre, deja >=1 sesión parseada con >=5 legisladores y su voto, y filas en el ledger
- [ ] Cada votación con: url_origen + checksum + fecha
- [ ] 0 except sin catch; errores en el ledger
- [ ] Sleep real entre requests
- [ ] README del módulo (docs/votaciones_nominales.md) + cómo contribuir (agregar período/cámara)
- [ ] Commits limpios: (1) código+config, (2) un CSV sample pequeño (solo export si es user-facing)

## Fuera de scope (no hagas)
- Análisis o reportes del análisis (eso es del bot/core después)
- No toques otros backfills, ledger, supervisor, mcp_server (otros agentes en uso)
- No implementes el módulo de roster_parlamento (otro agente lo tiene, en vuelo) — solo LEE su output si ya existe
- Difusión en redes / Facebook / X scraping (otro agente)
