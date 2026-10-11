# resultados_electorales

Serie histórica de resultados electorales **nacionales** (presidencial + legislativa) de
Uruguay: 1984, 1989, 1999, 2004, 2009, 2014, 2019, 2024. Pipeline: `pipeline/backfill_electoral.py`,
ledger source `resultados_electoral`.

## Qué se inventarió (ya existía en el repo)

En `data/metadata/ckan/` y `data/ckan/files/` ya estaban los datasets de la Corte Electoral de:

- Elecciones Nacionales 2024, 2019, 2014 (CSV: Desglose de votos, Integración de hojas de
  votación, Totales generales por CRV, Plan Circuital)
- Balotaje 2014 y 2024
- Elecciones Internas 2024, Departamentales y Municipales 2025, Referéndum 2022, balotaje
  interno de otras elecciones (caja notarial / Conaprole / Profesionales 2016-2017)

## Qué agregó este backfill

| Año | Fuente | Nivel de detalle |
|---|---|---|
| 2024/2019/2014 | CKAN Corte Electoral (dataset elections + **balotaje**) | votos a hoja por lema/CRV (escrutinio primario), hojas de votación, fórmulas del balotaje |
| 2009/2004 | Buscador de escrutinio oficial `elecciones.corteelectoral.gub.uy` (SSPConsulta.asp) + PDF oficial "Resultados y cargos obtenidos" | por lema, por sublema/fórmula y por hoja de votación por departamento |
| 1999/1989/1984 | PDF oficial de la Corte Electoral ("Resultados y cargos obtenidos") | por partido por departamento + fórmulas intra-partido (sección 5) + cargos (secciones 6-7) |

Las cifras de 1984/1989/1999/2004/2009 están **curadas del PDF/buscador oficial** y quedan
en el propio script (PDF_TOTALES / PDF_FORMULAS); los PDFs fuente quedan en
`data/electoral/historicos_ce/` con su texto extraído.

> Nota: los totales del buscador de 2004/2009 corresponden al escrutinio primario
> validado y difieren levemente del definitivo del PDF (diferencias por votos observados).

## Archivos

- `data/electoral/<ANO>_desglose-de-votos.csv` — CKAN 2024/2019/2014 (crudo, larga duración)
- `data/electoral/<ANO>-integracion-de-hojas...csv` — íntegro por hoja (grande)
- `data/electoral/balotaje_<ANO>.csv` — balotajes CKAN 2014/2019/2024
- `data/electoral/raw_scrutiny/<ANO>_scrutinio.json` — snapshot buscador 2004/2009
  (por lema + sublemas + hojas por departamento)
- `data/electoral/historicos_ce/*.pdf|*.txt` — PDFs oficiales 1984-2009 + texto
- `data/export/resultados_<ANO>.csv` — export agregado por lema (+ fórmulas + balotaje)
- `data/export/resultados_<ANO>_hojas.csv` — hojas de votación CKAN (2024/2019/2014)
- `data/export/serie_resultados_nacionales.csv` — serie completa 1984..2024

## Uso

```
python pipeline/backfill_electoral.py                # todo (skip ya descargado)
python pipeline/backfill_electoral.py --years 2024 2009
python pipeline/backfill_electoral.py --limit 3      # smoke test
python pipeline/backfill_electoral.py --no-skip      # re-descarga
```

## Cobertura y bloqueos

- Serie completa: **1984..2024 todas las elecciones nacionales** (excepto 1994 — la Corte
  Electoral no publica dataset ni buscador de esa elección en línea; quedó afuera).
- Hoja de votación total nacional: disponible vía CKAN para 2014/2019/2024; para 2004/2009
  el buscador la expone solo por departamento (queda capturada por departamento en el JSON).
- 1999/1984/1989: nivel hoja no existe digitalizado; el detalle disponible es por partido
  (por departamento) y fórmulas intra-partido.
