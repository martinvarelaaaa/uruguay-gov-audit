# roster_parlamento

Roster 100% del Parlamento uruguayo, legislatura L (2025–2030): **130 legisladores** — 31 senadores y 99 diputados (96 titulares + 3 que asumieron por suplencias: Cosse→Sabini/Caggiani/Rodríguez González, Fratti→Antonini, Ortuño→Brenta, Civila→González, Blás→Inzaurralde, Lustemberg→Kramer, Etcheverry→Pereyra, Mahía→Gallo Cantera, Reyes Álvarez→González Bergonzoni, Ferreira→Guerrero + suplentes activos).

## Generación

```bash
# 1. scrapes (idempotentes, guardan en data/metadata/roster/)
C:/Users/marti/uruguay-gov-audit/.venv/Scripts/python.exe data/metadata/roster/scrape_fichas.py   # fichas por legislador
C:/Users/marti/uruguay-gov-audit/.venv/Scripts/python.exe data/metadata/roster/bios_extract.py    # PDFs de bio -> texto
# 2. handles X (búsquedas web + verificación de bio en x.com)
#    pipeline/roster_handles.py (requiere sesion con hermes_tools)
# 3. build
C:/Users/marti/uruguay-gov-audit/.venv/Scripts/python.exe pipeline/build_roster.py
```

Salidas:
- `data/metadata/roster/roster_parlamento.json` — array completo (fuente de verdad)
- `data/export/roster_parlamento.csv` — export plano para diffs en git
- ledger: `source='roster_parlamento'`, un item por cámara (`roster_senadores`, `roster_representantes`)

## Schema (por legislador)

```json
{
  "nombre": "Cosse, Carolina",
  "camara": "senadores",                              // senadores | representantes
  "partido": "PARTIDO FRENTE AMPLIO",
  "departamento": "",                                  // diputados: depto por el que ocupan banca
  "lista_sector": "Lista 609",                         // solo cuando la evidencia la muestra (bio/handle)
  "banca_num": null,                                   // el Parlamento no publica número de banca en sus fichas
  "cargo": "Senador de la República por el Lema ...",  // descripción oficial de la ficha
  "cargo_previo": ["Diputado ... XLIX (2020-2025)", "..."],
  "bio_resumen": "...",                                // solo si hay PDF de bio oficial (16 fichas)
  "handle_x": "CosseCarolina",
  "handle_tipo": "personal",                           // personal | institucional
  "handle_confianza": "verified",                       // verified | probable | sin_cuenta
  "mail": "carolina.cosse_sec@parlamento.gub.uy",
  "id_parlamento": "10065",
  "legislaturas": ["Senador ... - Legislatura L (2025-2030)", " ... XLIX (2020-2025)"],
  "fuentes": [{"url": "https://parlamento.gub.uy/camarasycomisiones/legisladores/10065", "fecha": "2026-10-10"}]
}
```

## Cobertura (2026-10-10)

| métrica | valor |
|---|---|
| legisladores | 130 (31 senadores + 99 representantes) |
| con cargo_previo | 79 |
| con mail oficial | 125 |
| con bio oficial (PDF) | 16 |
| con lista/sector explícito | 16 |
| con handle X (verified) | 45 |
| con handle X (probable) | 2 |
| sin cuenta X hallable | 83 |

Partido por cámara: senadores FA 17 / PN 9 / PC 5; representantes FA 48 / PN 29 / PC 17 / CA 2 / IS 2 / PI 1.

## Criterio de verificación de handles

- `verified`: la bio del perfil en x.com menciona el nombre (≥2 tokens), el cargo (senador/diputado/intendente/ministro), o el cargo + partido/sector como evidencia directa; o el propio perfil es vinculado por la ficha/search de primera fuente.
- `probable`: cuenta del sector o lista del legislador (p. ej. `@EmpatiaUruguay` para Kramer, `@laampliafa` para Borbonet) sin mención nominal.
- `sin_cuenta`: sin hallazgo después de 2 pasadas de búsqueda por persona (`"<Nombre> twitter"` y `"<Nombre> twitter perfil @"`) + verificación de bio cuando hubo candidato.

Ambigüedades resueltas a rechazo: `@CarlitoxMoreira` (parodia de Carlos Moreira, 638 seguidores), `@cmoreira` (WordPress dev), `@Sebastian_AOE` (gamer por homónimo en Wikidata), `@MarneOsorioLima` para Silva, Rubenson (es de otra persona), `@AlvaroDelgadoUy` (presidente del PN, no el diputado Delgado Mas), `@DiputadosUY`/`@Parlamento_UY` (cuentas del cuerpo, no personales).

## Cómo actualizar

1. Re-correr `scrape_fichas.py` (resumible por `data/metadata/roster/fichas_pages/`).
2. Re-correr `build_roster.py` — fusiona fichas + handles + bios.
3. Para nuevos handles: agregar a `data/metadata/roster/handles_stage1.json` con el mismo schema (`estado: verificado|probable`, `handle`, `tipo`, `evidencia bio`) y re-correr build.
4. Número de banca: el Parlamento no lo publica por legislador; si aparece una fuente nueva (p. ej. listas de votaciones por banca), agregarla a `banca_num`.
