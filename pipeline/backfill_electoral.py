"""resultados_electorales — serie histórica de resultados electorales nacionales de Uruguay.

Completa la serie histórica de elecciones nacionales (presidencial + legislativa) desde 1984
hasta 2024, con resultados por lema/partido, fórmulas/sublemas cuando la fuente los publica
y hojas de votación cuando existen datasets abiertos.

Fuentes, por año (todas oficiales):
  2024, 2019, 2014 — datasets CKAN de la Corte Electoral (catalogodatos.gub.uy):
                     "Desglose de votos" / "Integración de hojas de votación" (CSV del
                     escrutinio primario, por lema y por hoja, con CRV y serie).
                     Metadata del dataset ya inventariada en data/metadata/ckan/.
  2009, 2004     — buscador de escrutinio oficial elecciones.corteelectoral.gub.uy
                     (SSPConsulta.asp: por lema, por sublema, por hoja por departamento)
                     + PDF oficial "Resultados y cargos obtenidos".
  1999, 1989, 1984 — PDF oficial de la Corte Electoral "Resultados y cargos obtenidos"
                     (resultado por partido por departamento + fórmulas intra-partido).

Salida:
  data/electoral/<ANO>_<recurso>.csv      — fuente CKAN cruda (larga duración)
  data/electoral/raw_scrutiny/*.json      — snapshot del buscador de escrutinio (2004/2009)
  data/electoral/historicos_ce/*.pdf|.txt — PDFs oficiales históricos + texto extraído
  data/export/resultados_<ANO>.csv        — export por lema/partido (+ fórmulas si hay)
  data/export/serie_resultados_nacionales.csv — serie completa 1984..2024

Cada descarga se registra en el ledger con source='resultados_electoral' (sha256
+ skip-regresdownloads: si ya existe el archivo no se re-descarga).

Uso:
    python pipeline/backfill_electoral.py              # todo
    python pipeline/backfill_electoral.py --years 2024 2009
    python pipeline/backfill_electoral.py --limit 3    # smoke test (primeros N años)
    python pipeline/backfill_electoral.py --no-skip    # re-descarga
"""
import argparse
import csv
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "pipeline"))
import ledger  # noqa: E402

OUT_DIR = os.path.join(BASE, "data", "electoral")
EXPORT_DIR = os.path.join(BASE, "data", "export")
DOC_DIR = os.path.join(OUT_DIR, "historicos_ce")
SCRUTINY_DIR = os.path.join(OUT_DIR, "raw_scrutiny")
SOURCE = "resultados_electoral"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) uruguay-gov-audit/1.0"}

CKAN_API = "https://catalogodatos.gub.uy/api/3/action"
SCRUTINY_HOST = "https://elecciones.corteelectoral.gub.uy"
CE_PDFS = "https://www.gub.uy/corte-electoral/sites/corte-electoral/files"

DEPTOS = ["ARTIGAS", "CANELONES", "CERROLARGO", "COLONIA", "DURAZNO", "FLORES", "FLORIDA",
          "LAVALLEJA", "MALDONADO", "MONTEVIDEO", "PAYSANDU", "RIONEGRO", "RIVERA",
          "ROCHA", "SALTO", "SANJOSE", "SORIANO", "TACUAREMBO", "TREINTAYTRES"]

# datasets CKAN confirmados (package_search q='elecciones nacionales')
CKAN_DATASETS = {
    "2024": "corte-electoral-elecciones-nacionales-2024",
    "2019": "corte-electoral-elecciones-nacionales-2019",
    "2014": "corte-electoral-elecciones_nacionales_2014",
}
# balotajes (elección presidencial definitiva)
CKAN_BALOTAJE = {
    "2024": "corte-electoral-balotaje_2024",
    "2019": "corte-electoral-balotaje_2019",
    "2014": "corte-electoral-balotaje_2014",
}

# buscador de escrutinio (SSPConsulta.asp): acto, ruta base, Org, lemas {codigo: nombre}
SCRUTINY = {
    "2009": {
        "acto": "20091025", "base": "Nacionales/2009/20091025/ConsEscrutinio", "org": "1",
        "junta": True, "extra": "",
        "lemas": {"1": "Partido Frente Amplio", "3": "Partido Nacional",
                  "2": "Partido Colorado", "4": "Partido Independiente",
                  "5": "Partido Asamblea Popular"},
    },
    "2004": {
        "acto": "20041031", "base": "Nacionales/2004/20041031", "org": "41",
        "junta": False, "extra": "CantPorc=C",
        "lemas": {"56": "Partido E.P.F.A. N.M.", "54": "Partido Colorado",
                  "55": "Partido Nacional", "62": "Partido Independiente",
                  "63": "Partido de los Trabajadores", "64": "Partido Intransigente",
                  "65": "Partido Liberal", "57": "Partido Unión Cívica"},
    },
}

# PDFs oficiales de la Corte Electoral ("Resultados y cargos obtenidos")
CE_DOCS = {
    "1999": ("elecciones_nacionales_1999.pdf",
             f"{CE_PDFS}/2023-08/elecciones_nacionales_1999.pdf"),
    "2004": ("Elecciones_Nacionales_2004.pdf",
             f"{CE_PDFS}/2024-04/Elecciones%2BNacionales%2B2004.pdf"),
    "2009": ("Elecciones_Nacionales_2009.pdf",
             f"{CE_PDFS}/2023-08/Elecciones_Nacionales_2009.pdf"),
    "1989": ("Eleccion_Nacional_1989.pdf",
             f"{CE_PDFS}/2023-08/Eleccion_Nacional_1989.pdf"),
    "1984": ("Eleccion_Nacional_1984.pdf",
             f"{CE_PDFS}/2023-08/Eleccion_Nacional_1984.pdf"),
}


# ---------------------------------------------------------------- utils
def _http(url, timeout=120):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read()


def http_get(url, retries=3, timeout=90):
    last = None
    for a in range(retries + 1):
        try:
            return _http(url, timeout=timeout).decode("utf-8", "replace")
        except Exception as e:
            last = e
            if a == retries:
                raise
            time.sleep(2)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, run_id, item_id, skip_existing=True):
    """Descarga con ledger + checksum + skip si ya existe idéntico."""
    if skip_existing and os.path.exists(dest) and os.path.getsize(dest) > 0:
        eid = ledger.record_start(run_id, SOURCE, item_id, item_url=url,
                                  meta={"destino": os.path.relpath(dest, BASE)})
        checksum = sha256_file(dest)
        ledger.record_finish(eid, status="skipped", file_path=dest,
                             sha256=checksum, bytes_=os.path.getsize(dest))
        print(f"[{item_id}] skipped (ya existe)")
        return "skipped"
    eid = ledger.record_start(run_id, SOURCE, item_id, item_url=url,
                              meta={"destino": os.path.relpath(dest, BASE)})
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        data = _http(url, timeout=300)
        with open(dest, "wb") as f:
            f.write(data)
        checksum = sha256_file(dest)
        ledger.record_finish(eid, status="ok", bytes_=len(data), file_path=dest,
                             sha256=checksum)
        print(f"[{item_id}] ok: {len(data)} bytes")
        return "ok"
    except Exception as e:
        ledger.record_finish(eid, status="error", error=e, file_path=dest)
        print(f"[{item_id}] ERROR: {e}")
        return "error"


# ------------------------------------------------- CKAN (2024/2019/2014)
def ckan_api(action, **params):
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    return json.loads(_http(f"{CKAN_API}/{action}?{qs}").decode("utf-8"))["result"]


def fetch_ckan_desglose(year, run_id, skip_existing=True):
    ds = CKAN_DATASETS.get(year)
    if not ds:
        return []
    pkg = ckan_api("package_show", id=ds)
    out = []
    for res in pkg.get("resources", []):
        name = (res.get("name") or "").strip().lower()
        if res.get("format", "").upper() == "CSV" and ("desglose" in name or "integraci" in name):
            fn = os.path.basename(urllib.parse.unquote(res["url"]))
            if not fn.startswith(year + "_"):
                fn = f"{year}_{fn}"
            dest = os.path.join(OUT_DIR, fn)
            if download(res["url"], dest, run_id, f"ckan-{year}-{fn}", skip_existing) != "error":
                out.append(dest)
    return out


def fetch_ckan_balotaje(year, run_id, skip_existing=True):
    ds = CKAN_BALOTAJE.get(year)
    if not ds:
        return None
    try:
        pkg = ckan_api("package_show", id=ds)
    except Exception as e:
        print(f"[balotaje-{year}] ERROR package_show: {e}")
        return None
    for res in pkg.get("resources", []):
        if res.get("format", "").upper() == "CSV":
            fn = f"balotaje_{year}.csv"
            dest = os.path.join(OUT_DIR, fn)
            download(res["url"], dest, run_id, f"ckan-balotaje-{year}", skip_existing)
            return dest
    return None


# ------------------------------------------ buscador de escrutinio 2004/2009
def parse_ssp_rows(html):
    """Filas de una consulta SSPConsulta.asp: _STRDSC(1)?_id + _ITOTAL_id."""
    dsc = dict(re.findall(r'name="_STRDSC1?_([^"]+)" value="([^"]*)"', html))
    tot = dict(re.findall(r'name="_ITOTAL_([^"]+)" value="([^"]*)"', html))
    return [(dsc[k].strip(), tot.get(k)) for k in dsc if k in tot]


def fetch_scrutiny(year, run_id, skip_existing=True):
    cfg = SCRUTINY[year]
    acto, base, org = cfg["acto"], cfg["base"], cfg["org"]
    extra = cfg["extra"]
    jp = "&Junta=0" if cfg["junta"] else ""
    dest = os.path.join(SCRUTINY_DIR, f"{year}_scrutinio.json")
    if skip_existing and os.path.exists(dest):
        eid = ledger.record_start(
            run_id, SOURCE, f"scrutiny-{year}", item_url=f"{SCRUTINY_HOST}/{base}/SSPConsulta.asp",
            meta={"destino": os.path.relpath(dest, BASE)})
        ledger.record_finish(eid, status="skipped", file_path=dest, sha256=sha256_file(dest),
                             bytes_=os.path.getsize(dest))
        print(f"[scrutiny-{year}] skipped (ya existe)")
        return dest
    eid = ledger.record_start(run_id, SOURCE, f"scrutiny-{year}",
                              item_url=f"{SCRUTINY_HOST}/{base}/SSPConsulta.asp",
                              meta={"destino": os.path.relpath(dest, BASE)})
    data = {"year": year, "acto": acto, "por_lema": [], "sublemas": {}, "hojas": {}}
    try:
        url = (f"{SCRUTINY_HOST}/{base}/SSPConsulta.asp?TipoCons=L&Acto={acto}&Org={org}"
               f"&Dpto=&Escrut=P&Circ=V&Lema=&Cargo=2{extra}{jp}")
        data["por_lema"] = parse_ssp_rows(http_get(url))
        n_hojas = 0
        for code, nombre in cfg["lemas"].items():
            u = (f"{SCRUTINY_HOST}/{base}/SSPConsulta.asp?TipoCons=S&Acto={acto}&Org={org}"
                 f"&Dpto=&Escrut=P&Circ=V&Lema={code}&Cargo=2{extra}{jp}")
            try:
                time.sleep(0.5)
                data["sublemas"][nombre] = parse_ssp_rows(http_get(u))
            except Exception:
                data["sublemas"][nombre] = []
            dep_hojas = {}
            for dep in DEPTOS:
                u = (f"{SCRUTINY_HOST}/{base}/SSPConsulta.asp?TipoCons=H&Acto={acto}&Org={org}"
                     f"&Dpto={dep}&Escrut=P&Circ=V&Lema={code}&Cargo=4{extra}{jp}")
                try:
                    time.sleep(0.4)
                    dep_hojas[dep] = parse_ssp_rows(http_get(u))
                except Exception:
                    dep_hojas[dep] = []
            n_hojas += sum(len(v) for v in dep_hojas.values())
            data["hojas"][nombre] = dep_hojas
        os.makedirs(SCRUTINY_DIR, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        rows = len(data["por_lema"]) + sum(len(v) for v in data["sublemas"].values()) + n_hojas
        ledger.record_finish(eid, status="ok", rows=rows, file_path=dest,
                             sha256=sha256_file(dest), bytes_=os.path.getsize(dest))
        print(f"[scrutiny-{year}] ok: lema={len(data['por_lema'])} "
              f"sublemas={len(data['sublemas'])} hojas={n_hojas}")
        return dest
    except Exception as e:
        ledger.record_finish(eid, status="error", error=e, file_path=dest)
        print(f"[scrutiny-{year}] ERROR: {e}")
        return None


def export_scrutiny_lema(year):
    """Export del snapshot scrutiny -> data/export/resultados_<anno>.csv (lema + sublema)."""
    src = os.path.join(SCRUTINY_DIR, f"{year}_scrutinio.json")
    if not os.path.exists(src):
        return None
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    dest = os.path.join(EXPORT_DIR, f"resultados_{year}.csv")
    os.makedirs(EXPORT_DIR, exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["anio", "ambito", "categoria", "candidato_o_partido", "votos"])
        for nombre, votos in data["por_lema"]:
            w.writerow([year, "nacional", "lema", nombre, votos])
        for lema, subs in data["sublemas"].items():
            for nombre, votos in subs:
                w.writerow([year, "nacional", f"sublema:{lema}", nombre, votos])
    return dest


# --------------------------------------------- PDFs oficiales 1984/1989/1999
def fetch_ce_pdfs(run_id, skip_existing=True):
    for year, (fn, url) in CE_DOCS.items():
        dest = os.path.join(DOC_DIR, fn)
        download(url, dest, run_id, f"ce-pdf-{year}", skip_existing)
        txt = dest[:-4] + ".txt"
        if not os.path.exists(txt) and os.path.exists(dest) and os.path.getsize(dest) > 0:
            os.makedirs(os.path.dirname(txt), exist_ok=True)
            pdf_to_txt(dest, txt)


def pdf_to_txt(pdf_path, txt_path):
    """PDF -> texto con pdfplumber (conversión local, no va del ledger como descarga)."""
    from pdfplumber import open as pdf_open
    parts = []
    with pdf_open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    txt = "\n".join(parts)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt)
    return len(txt)


# Resultados nacionales oficiales (TOTALES + porcentajes + cargos) extraídos y verificados
# de los PDFs oficiales de la Corte Electoral (sección "RESULTADO POR PARTIDO POLÍTICO"
# y "CARGOS OBTENIDOS"). Los PDFs quedan en data/electoral/historicos_ce/ (fuente cruda);
# este dict es la tabla curada para la serie exportable.
# Orden historico de elección: 1984, 1989, 1999 (2004/2009 salen del buscador, 2014+ de CKAN).
PDF_TOTALES = {
    "1984": {  # 25/11/1984, habilitados 2.197.503
        "fuente": "Eleccion_Nacional_1984.pdf (sección 4, 6 y 7)",
        "lema": {"Partido Colorado": (777701, "40,28%", {"senadores": 13, "diputados": 41}),
                 "Partido Nacional": (660773, "34,22%", {"senadores": 11, "diputados": 35}),
                 "Partido Demócrata Cristiano": (401104, "20,77%", {"senadores": 6, "diputados": 21}),
                 "Partido Unión Cívica": (45841, "2,37%", {"diputados": 2}),
                 "Partido de los Trabajadores": (488, "0,03%", {}),
                 "Partido Unión Patriótica": (302, "0,02%", {}),
                 "Partido Convergencia": (153, "0,01%", {}),
                 "Votos en blanco": (28082, "1,45%", {}),
                 "Sobres con hojas anuladas": (16487, "0,85%", {})},
        "votantes": 1930931,
    },
    "1989": {  # 26/11/1989, habilitados 2.319.022
        "fuente": "Eleccion_Nacional_1989.pdf (sección 4, 6 y 7)",
        "lema": {"Partido Nacional": (765990, "37,25%", {"senadores": 12, "diputados": 39}),
                 "Partido Colorado": (596964, "29,03%", {"senadores": 9, "diputados": 30}),
                 "Partido Frente Amplio": (418403, "20,35%", {"senadores": 7, "diputados": 21}),
                 "Partido Por el Gobierno del Pueblo": (177453, "8,63%", {"senadores": 2, "diputados": 9}),
                 "Partido Verde Eto-Ecologista": (10835, "0,53%", {}),
                 "Partido Movimiento Justiciero": (441, "0,02%", {}),
                 "Partido de los Trabajadores": (310, "0,02%", {}),
                 "Partido Convergencia": (190, "0,01%", {}),
                 "Votos en blanco": (64284, "3,13%", {}),
                 "Sobres con hojas anuladas": (21485, "1,04%", {})},
        "votantes": 2056355,
    },
    "1994": {  # 27/11/1994. La Corte Electoral no publica online esta elección;
        "fuente": "PDBA Georgetown (fuente: Corte Electoral / IFES) — pres94/uru94",
        "lema": {"Partido Colorado": (656183, "32.5%", {"senadores": 11, "diputados": 32}),
                 "Partido Nacional": (633384, "31.4%", {"senadores": 10, "diputados": 31}),
                 "Partido Encuentro Progresista-Frente Amplio": (620178, "30.8%", {"senadores": 9, "diputados": 31}),
                 "Partido Nuevo Espacio": (104656, "5.1%", {"diputados": 5}),
                 "Fórmula Sanguinetti (candidato presidencial)": (631025, "31.40%", {})},
        "votantes": None,
    },
    "1999": {  # 31/10/1999, habilitados 2.402.160
        "fuente": "elecciones_nacionales_1999.pdf (sección 4, 6 y 7)",
        "lema": {"Partido Encuentro Progresista-Frente Amplio": (861202, "39,06%",
                 {"senadores": 12, "diputados": 40}),
                 "Partido Colorado": (703915, "31,93%", {"senadores": 10, "diputados": 33}),
                 "Partido Nacional": (478980, "21,72%", {"senadores": 7, "diputados": 22}),
                 "Partido Nuevo Espacio": (97943, "4,44%", {"senadores": 1, "diputados": 4}),
                 "Partido Unión Cívica": (5109, "0,23%", {}),
                 "Votos solo por SI": (12840, "0,58%", {}),
                 "Votos en blanco": (22433, "1,02%", {}),
                 "Sobres con hojas anuladas": (22240, "1,01%", {})},
        "votantes": 2204884,
    },
}

# Fórmulas intra-partido (sublemas) — total nacional por fórmula, sección 5 de los PDFs.
PDF_FORMULAS = {
    "1984": {
        "Partido Colorado": {"Sanguinetti - Tarigo": 592061, "Pacheco - Pirán": 183801,
                             "Adjunto": 1839},
        "Partido Nacional": {"Zumarán - Aguire": 554443, "Ortíz - Ferber": 83237,
                             "Payssé - Maeso": 21644},
        "Partido Demócrata Cristiano": {"Crottogini - D'Elía": 401104},
    },
    "1989": {
        "Partido Nacional": {"Lacalle - Aguirre": 444839, "Pereyra - Tourne": 218656,
                             "Alonso - Costa": 101046, "Adjunto": 1449},
        "Partido Colorado": {"Batlle - Sanguinetti": 291944, "Pacheco - Millor": 289222,
                             "Fernández - Vispo": 14482, "Adjunto": 1316},
        "Partido Frente Amplio": {"Seregni - Astori": 418403},
        "Partido Por el Gobierno del Pueblo": {"Batalla - Quijano": 177453},
    },
}


# ------------------------------------------------------------- exports
def export_csv_year(year, run_id=None):
    """Export agredado por lema (y fórmulas si hay) -> data/export/resultados_<anno>.csv."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    dest = os.path.join(EXPORT_DIR, f"resultados_{year}.csv")
    rows = []
    if year in PDF_TOTALES:
        d = PDF_TOTALES[year]
        for nombre, (votos, pct, cargos) in d["lema"].items():
            rows.append([year, "nacional", "lema", nombre, votos, pct,
                         cargos.get("senadores"), cargos.get("diputados")])
        for lema, formas in PDF_FORMULAS.get(year, {}).items():
            for nombre, votos in formas.items():
                if votos is not None:
                    rows.append([year, "nacional", f"formula:{lema}", nombre, votos, "", "", ""])
    elif year in ("2004", "2009"):
        src = os.path.join(SCRUTINY_DIR, f"{year}_scrutinio.json")
        if not os.path.exists(src):
            return None
        with open(src, encoding="utf-8") as f:
            data = json.load(f)
        import html as _html
        for nombre, votos in data["por_lema"]:
            rows.append([year, "nacional", "lema", _html.unescape(nombre), votos, "", "", ""])
        for lema, subs in data["sublemas"].items():
            for nombre, votos in subs:
                if (nombre or "").startswith(("Suma", "Circuitos")):
                    continue
                rows.append([year, "nacional", f"formula:{_html.unescape(lema)}",
                             _html.unescape(nombre), votos, "", "", ""])
    elif year in CKAN_DATASETS:
            # desglose CKAN escrutinio primario: votos a hojas (HOJA_EN) agregados por lema
            # + votos a lema directo (VOTO_LEMA) + hojas de votación por lema.
            src = os.path.join(OUT_DIR, f"{year}_desglose-de-votos.csv")
            if not os.path.exists(src):
                return None
            import collections
            tot = collections.Counter()   # HOJA_EN por lema
            vlema = collections.Counter() # VOTO_LEMA directo por lema
            hojas = collections.Counter()
            with open(src, encoding="utf-8-sig") as f:
                import csv as _csv
                rd = _csv.DictReader(f)
                for row in rd:
                    tipo = row.get("TipoRegistro", "")
                    if tipo == "VOTO_LEMA":
                        vlema[row["Lema"]] += int(row["CantidadVotos"])
                    elif tipo == "HOJA_EN":
                        tot[row["Lema"]] += int(row["CantidadVotos"])
                        hojas[(row["Lema"], row["Descripcion1"])] += int(row["CantidadVotos"])
            for lema, votos in sorted(tot.items()):
                rows.append([year, "nacional", "votos a hojas (escrutinio primario)", lema,
                             votos, "", "", ""])
            for lema, votos in sorted(vlema.items()):
                rows.append([year, "nacional", "votos a lema directo", lema, votos, "", "", ""])
            hojas_file = os.path.join(EXPORT_DIR, f"resultados_{year}_hojas.csv")
            os.makedirs(EXPORT_DIR, exist_ok=True)
            with open(hojas_file, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["anio", "partido_o_lema", "hoja", "votos"])
                for (lema, hoja), votos in sorted(hojas.items(), key=lambda x: -x[1]):
                    w.writerow([year, lema, hoja, votos])
            # balotaje (fórmulas presidenciales definitivas) si hay CSV descargado
            bal_file = os.path.join(OUT_DIR, f"balotaje_{year}.csv")
            if os.path.exists(bal_file):
                import collections
                bt = collections.Counter()
                with open(bal_file, encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        for c, v in row.items():
                            if c and c in ("TotalOrsiCosse", "TotalDelgadoRipoll",
                                           "Total_Martinez_Villar", "Total_Lacalle Pou_Argimon",
                                           "Total_Vazquez_Sendic", "Total_Lacalle Pou_Larrañaga"):
                                try:
                                    bt[c.replace("Total_", "").replace("Total", "")] += int(v)
                                except (TypeError, ValueError):
                                    pass
                for formula, votos in sorted(bt.items()):
                    rows.append([year, "nacional", "balotaje (fórmula)", formula, votos, "", "", ""])
    if not rows:
        return None
    with open(dest, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["anio", "ambito", "categoria", "partido_o_lema", "votos", "porcentaje",
                    "senadores", "diputados"])
        w.writerows(rows)
    return dest


def export_serie():
    """Serie completa -> data/export/serie_resultados_nacionales.csv."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    dest = os.path.join(EXPORT_DIR, "serie_resultados_nacionales.csv")
    with open(dest, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["anio", "ambito", "categoria", "partido_o_lema", "votos", "porcentaje",
                    "senadores", "diputados"])
        for year in sorted(set(PDF_TOTALES) | set(SCRUTINY) | set(CKAN_DATASETS)):
            src = os.path.join(EXPORT_DIR, f"resultados_{year}.csv")
            if not os.path.exists(src):
                continue
            import csv as _csv
            with open(src, encoding="utf-8") as g:
                rd = _csv.reader(g)
                next(rd, None)
                f.writelines(r and ",".join(r) + "\n" for r in rd if r)
    return dest


YEARS = ["2024", "2019", "2014", "2009", "2004", "1999", "1994", "1989", "1984"]


def main():
    ap = argparse.ArgumentParser(description="Backfill resultados electorales nacionales")
    ap.add_argument("--years", nargs="*", default=None, help="años a procesar (default: todos)")
    ap.add_argument("--limit", type=int, default=None, help="procesar solo los primeros N años")
    ap.add_argument("--no-skip", action="store_true", help="re-descargar aunque ya exista")
    args = ap.parse_args()

    years = args.years or YEARS
    if args.limit:
        years = years[: args.limit]
    skip = not args.no_skip

    run_id = f"electoral-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    ledger.start_run(run_id, SOURCE, mode="backfill",
                     note=f"años: {','.join(years)} (skip={skip})")
    results = {}
    for year in years:
        if year in CKAN_DATASETS:
            results[year] = fetch_ckan_desglose(year, run_id, skip)
            fetch_ckan_balotaje(year, run_id, skip)
        if year in SCRUTINY:
            results[year] = fetch_scrutiny(year, run_id, skip)
        if year in CE_DOCS:
            fetch_ce_pdfs(run_id, skip)
    # PDFs históricos una vez, textos extraidos, exports
    for year in years:
        if year in CE_DOCS:
            pass  # fetch_ce_pdfs ya procesa todos los años juntos
    for year in sorted(years):
        if year in PDF_TOTALES:
            try:
                export_csv_year(year)
            except Exception as e:
                print(f"[export-{year}] ERROR: {e}")
        elif year in CKAN_DATASETS or year in SCRUTINY:
            try:
                export_csv_year(year)
            except Exception as e:
                print(f"[export-{year}] ERROR: {e}")
    export_serie()
    ok = sum(1 for v in results.values() if v not in (None, "error"))
    err = sum(1 for v in results.values() if v == "error")
    status = "ok" if err == 0 and ok > 0 else ("error" if err == len(results) else "partial")
    ledger.finish_run(run_id, status=status, note=f"ok={ok} error={err}")
    print(f"{run_id}: ok={ok} err={err}")


if __name__ == "__main__":
    main()
