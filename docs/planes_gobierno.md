# planes_gobierno — programas de gobierno (elección nacional 2024, período 2025-2030)

Baja los programas de gobierno de los partidos políticos uruguayos, los convierte
a markdown estructurado y los deja listos para el índice (`build_index.py`).

## Cómo correr

```bash
# todos los partidos
.venv/Scripts/python.exe pipeline/backfill_planes.py

# smoke test (primeros 2 del config)
.venv/Scripts/python.exe pipeline/backfill_planes.py --limit 2

# un partido puntual (clave de config/planes.json)
.venv/Scripts/python.exe pipeline/backfill_planes.py --partido fa

# regenerar aunque ya exista el .md
.venv/Scripts/python.exe pipeline/backfill_planes.py --no-skip
```

Cada corrida registra en el ledger (`data/ledger.sqlite3`) un run
`source='planes_gobierno'` y un item por partido (status ok/error/skipped,
bytes, sha256, cantidad de secciones en `rows`).

## Salidas

- `data/planes/<partido>/programa.pdf` — PDF original (NUNCA se commitea: >1 MB).
- `data/planes/<partido>/programa.md` — texto estructurado con front-matter:
  `url`, `checksum: sha256:...`, `fecha` (ISO UTC), `conversion` (docling|pdfplumber),
  y en el fallback pdfplumber, marcadores `<!-- página N -->` por página.

## Conversión

1. **docling** (preferido): export a markdown, preserva encabezados/secciones.
   Instalar con `.venv/Scripts/pip.exe install docling` si falta.
2. **pdfplumber** (fallback): extracción de texto simple página a página.
   Instalar con `.venv/Scripts/pip.exe install pdfplumber`.

## Cómo agregar un partido

Solo editar `config/planes.json` y agregar una entrada:

```json
"nuevo": {
  "nombre": "Partido X",
  "url_pdf": "https://.../programa.pdf",
  "url_web": "https://.../"
}
```

La clave es el nombre de la carpeta bajo `data/planes/`. Si el servidor del
partido da problemas de descarga, apuntar `url_pdf` al PDF oficial publicado
por la Corte Electoral (https://www.gub.uy/corte-electoral/comunicacion/publicaciones/programas-gobierno-nacional)
o IMPO (https://www.impo.com.uy/elecciones-nacionales-2024/) — ambos publican
los programas por ley (Ley 18.485).

## Partidos incluidos (2024)

| Clave | Partido | Fuente del PDF |
|---|---|---|
| fa | Frente Amplio | frenteamplio.uy (Bases Programáticas 2025-2030) |
| pn | Partido Nacional | Corte Electoral (partidonacional.com.uy no tiene PDF directo) |
| pc | Partido Colorado | programapartidocolorado.uy ("Contrato con Uruguay") |
| ca | Cabildo Abierto | Corte Electoral |
| pi | Partido Independiente | Corte Electoral |
