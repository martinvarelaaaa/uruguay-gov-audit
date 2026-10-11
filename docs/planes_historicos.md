# planes_historicos

Programas de gobierno de elecciones **anteriores** (2004 al menos, con extensión a
2009/2014/2019). Pipeline `pipeline/backfill_planes_historicos.py`, patrón de
`backfill_planes.py`, ledger source `planes_historicos`.

No toca `config/planes.json` ni `data/planes/<partido>/` (elección vigente): este módulo lee
`config/planes_historicos.json` y escribe en `data/planes/<ano>_<partido>/programa.{pdf,md}`.

## Qué quedó (elección → período → partido)

| Elección | Período | Partidos | Fuente |
|---|---|---|---|
| 2019 | 2020-2025 | FA, PN, PC | PDFs oficiales publicados por la Corte Electoral (expedientes de presentación) |
| 2014 | 2015-2020 | FA, PN, PC | PDFs oficiales publicados por la Corte Electoral |
| 2009 | 2010-2015 | FA, PN | FA: archivo oficial frenteamplio.uy (V Congreso Extraordinario 2008); PN: "Un país independiente, justo y próspero" (Alianza Nacional/Lacalle), alianzanacional.com.uy |
| 2004 | 2005-2010 | — | sin URL verificable estable para FA/PN/PC (queda TODO en el config) |

Cada `programa.md` lleva front-matter con `url`, `checksum: sha256:...`, `fecha` y `nota`.

## Uso

```
python pipeline/backfill_planes_historicos.py             # todos (skip de ya convertidos)
python pipeline/backfill_planes_historicos.py --limit 2   # smoke test
python pipeline/backfill_planes_historicos.py --ano 2014
python pipeline/backfill_planes_historicos.py --partido 2019:fa
```

## Bloqueos

- PC 2010-2015 (elección 2009): el programa colorado no quedó publicado ni en la CE ni en
  la web del partido de forma verificable; TODO en config.
- Elección 2004 (período 2005-2010): los PDFs de FA ("Uruguay Social"/Grandes Líneas
  Programáticas), PN (Larrañaga) y PC (Stirling) no están en URLs estables. TODO en config.
- PC 2014 (Plan Uruguay 2015-2020): la copia oficial de la CE es un PDF comprimido, texto
  OCR-pesado; la conversión docling igual produjo 223 secciones.
