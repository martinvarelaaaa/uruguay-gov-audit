"""Fuente: VOTACIONES Y ASISTENCIA del Parlamento Uruguay (CSS + CRR), por período.

Qué baja (todo público, URL profunda del portal parlamento.gub.uy):
1. Listado de diarios de sesiones de plenario por cámara
   (/camarasycomisiones/{senadores|representantes}/plenario/documentos/diarios-de-sesion/csv)
2. PDF de cada diario (vía página diario-de-sesion/<id>/IMG -> infolegislativa temporales);
   parse de: ASISTEN/FALTAN (asistencia por legislador), bloques de votación
   "N en M. Afirmativa/Negativa [. UNANIMIDAD]" (CSS) y
   "Ochenta y nueve votos afirmativos y un voto negativo en noventa presentes: AFIRMATIVA"
   o "Setenta y dos en setenta y cuatro: AFIRMATIVA" (CRR, números en letras), + contexto.
3. Asistencias agregadas y detalle por legislador
   (/camarasycomisiones/{camara}/plenario/asistencia-a-sesiones[/json|/<id>/csv]).

Los PERIODOS se toman de config/votaciones.json. Un item de ledger por sesión;
headers de navegador real (la home del portal 403 a bots genéricos; URLs profundas pasan).

Limitación documentada del portal (verificada 2026-10-10): NO existe dato estructurado
de "quién votó cómo" nominal en plenario (ni CSV/JSON en el portal ni en CKAN del Parlamento).
Motor: con UNANIMIDAD deriva el voto individual (asistieron=a_favor|en_contra,
ausentes=ausente); el resto queda agregado (a_favor_n/en_contra_n + voto_agregado=true).
Si el diario declara votación NOMINAL explícita ("A favor: ... / En contra: ..."),
se extraen listas nombre->voto con parse_nominal().
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.error, csv, io, hashlib
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ledger import record_start, record_finish, start_run, finish_run, export_csv, sha256_file

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT_VOT = os.path.join(ROOT, "data", "votaciones")
OUT_EXPORT = os.path.join(ROOT, "data", "export", "votaciones.csv")
TMP = os.path.join(os.environ.get("TEMP", os.path.join(ROOT, "data", "tmp")), "votaciones_pdfs")
ROSTER = os.path.join(ROOT, "data", "metadata", "roster", "roster_parlamento.jah")
ROSTER_FALLBACK = os.path.join(ROOT, "data", "metadata", "roster", "_probe_cards.json")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
      "Accept-Language": "es-ES,es;q=0.9"}
SLEEP_S = 4.0  # rate limit: >=4s entre requests, 1 in flight (llamadas estrictamente secuenciales)

BASE = "https://parlamento.gub.uy"

# ---------------------------------------------------------------- utilidades básicas

def http_get(url, timeout=240, binary=False):
    """GET con UA de navegador. Devuelve str (utf-8, errors=replace) o bytes."""
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
    data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def sleep_rate():
    time.sleep(SLEEP_S)

# ------------------------------------------------- números en letras (CRR) -> dígitos

U = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
     "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
     "trece": 13, "catorce": 14, "quince": 15}
D10 = {"dieciséis": 16, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
       "veinte": 20, "veintiuno": 21, "veintidós": 22, "veintidos": 22, "veintitrés": 23,
       "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiséis": 26,
       "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29}
D20 = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
       "ochenta": 80, "noventa": 90}

_NUM_PAL = "(?:" + "|".join(sorted(list(D10) + list(D20) + list(U), key=len, reverse=True)) + ")"


def letras_a_num(s):
    """'setenta y dos' -> 72; 'veintiocho' -> 28; 'noventa' -> 90; None si no matchea."""
    s = re.sub(r"\s+", " ", (s or "").strip().lower())
    if s in U:
        return U[s]
    if s in D10:
        return D10[s]
    if s in D20:
        return D20[s]
    m = re.match(r"^(treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa)\s+y\s+(\w+)$", s)
    if m and m.group(2) in U:
        return D20[m.group(1)] + U[m.group(2)]
    return None


RE_VOTE_CSS = re.compile(r"[-–—]{1,2}\s*(\d{1,3})\s*en\s*(\d{1,3})\s*[.:]\s*"
                         r"(Afirmativa|Negativa)", re.I)

RE_VOTE_N = re.compile(
    r"[-–—]{1,2}\s*(\d{1,3})\s+(?:votos?\s+)?(?:afirmativos?\s*y\s*(\d{1,3})\s*(?:votos?\s+)?"
    r"negativos?\s*)?en\s*(\d{1,3})(?:\s*presentes)?\s*[:.:]?\s*(AFIRMATIVA|NEGATIVA)", re.I)

RE_VOTE_CRR_LETRAS = re.compile(
    ("((?:%s)(?:\\s+y\\s+(?:%s))?)\\s+votos?\\s+(?:afirmativos?\\s+y\\s+((?:%s)(?:\\s+y\\s+(?:%s))?)\\s+votos?\\s+negativos?"
     "|negativos?\\s+y\\s+((?:%s)(?:\\s+y\\s+(?:%s))?)\\s+votos?\\s+afirmativos?"
     "|afirmativos?|negativos?)"
     "\\s+en\\s+((?:%s)(?:\\s+y\\s+(?:%s))?)(?:\\s+presentes)?\\s*[:.:]?\\s*"
     "(AFIRMATIVA|NEGATIVA)") % (_NUM_PAL, _NUM_PAL, _NUM_PAL, _NUM_PAL, _NUM_PAL, _NUM_PAL,
                                 _NUM_PAL, _NUM_PAL),
    re.I)

# ---------------------------------------------------------------- helpers de texto

def derizar(txt):
    return re.sub(r"\s+", " ", txt)


def _contexto_titulo(pre):
    """Título del asunto votado desde el texto previo: último «...», cabecera 'NN) TIT'
    o mención 'proyecto de ley ...'. Devuelve (titulo, carpeta|None)."""
    carpeta = None
    for m in re.finditer(r"[Cc]arpeta\s*n\.\s*[ºa.]*\s*(\d+)\s*/\s*(\d{4})", pre):
        carpeta = "%s/%s" % (m.group(1), m.group(2))
    if not carpeta:
        m2 = re.search(r"([A-Z]{2,3})\s*/\s*(\d{1,5})\s*/\s*(\d{4})", pre)
        if m2:
            carpeta = "%s/%s" % (m2.group(2), m2.group(3))
    tit = ""
    mq = list(re.finditer(r"«([^»]{0,400})", pre))
    if mq:
        tit = mq[-1].group(1)
    else:
        mh = list(re.finditer(r"\d{1,2}\)\s+([A-ZÁÉÍÓÚÜÑ0-9][^|—–]{10,160})", pre))
        if mh:
            tit = mh[-1].group(1).strip()
        else:
            mproj = list(re.finditer(r"proyecto de ley[^.|]{10,160}", pre, re.I))
            if mproj:
                tit = mproj[-1].group(0)
    if not tit:
        tit = (pre[-180:] or "").strip() or "sin_titulo"
    return tit.strip(" .,;-«»")[:280], carpeta


# ---------------------------------------------------------------- parse del PDF diario

def pdf_a_texto(path_pdf):
    """pdftotext (xpdf, incluido con git-bash) a UTF-8; prueba -layout y plain."""
    out = path_pdf + ".txt"
    for extra in (["-layout"], []):
        try:
            subprocess.run(["pdftotext", "-enc", "UTF-8"] + extra + [path_pdf, out],
                           check=True, capture_output=True, timeout=900)
            txt = open(out, encoding="utf-8", errors="replace").read()
            if txt.strip():
                return txt
        except (subprocess.SubprocessError, OSError):
            continue
    return ""


def parse_asistencia(flat, camara):
    """Bloque ASISTEN:/FALTAN: (CSS) o 'Asisten los señores representantes: ...' +
    'Con licencia: | Faltan con aviso: | Sin aviso:' (CRR) -> dict nombre->asistio|ausente."""
    asist = {}
    if camara == "senadores":
        m = re.search(r"ASISTEN:\s*(.+?)(?:\.\s*(?:FALTAN|3\)|[A-Z]{2,}\)|EJERCEN|OPORTUNAMENTE)|$)", flat, re.S)
        if not m:
            m = re.search(r"ASISTEN(?:\s*los\s*señores\s*senadores)?[:\s]\s*(.+?)(?:\.\s*(?:FALTAN|3\)|OPORTUNAMENTE)|$)",
                          flat, re.S)
    else:
        m = re.search(r"Asisten\s+los\s+señores\s+representantes:?\s+(.+?)(?:\.\s*(?:Con licencia|Faltan|Sin aviso|Actúan|Observaciones|$))",
                      flat, re.S)
    if m:
        blob = re.sub(r"\([^)]{0,90}\)", "", m.group(1))
        for p in re.split(r"\s*,\s*|\s+y\s+", blob):
            nm = p.strip()
            nm = re.sub(r"^(?:el señor|la señora|señor|señora|señores senadores|señores representantes)\s+",
                        "", nm).strip()
            if nm and re.match(r"^[A-ZÁÉÍÓÚÜÑ]", nm) and len(nm) >= 5 and nm[0].isupper() \
                    and "senado" not in nm.lower() and "secretar" not in nm.lower() \
                    and "cámara" not in nm.lower() and "presidente" not in nm.lower():
                asist[nm] = "asistio"
    if camara == "senadores":
        mf = re.search(r"FALTAN:\s*(.+?)(?:\.\s*(?:[A-Z]{2,}\)|3\)|EJERCEN|OPORTUNAMENTE)|$)", flat, re.S)
    else:
        mf = re.search(r"(?:Con licencia|Faltan con aviso|Sin aviso):\s*(.+?)(?:\.\s*(?:Observaciones|Actúan|Sesión|$))",
                       flat, re.S)
    if mf:
        blob = re.sub(r"\([^)]{0,90}\)", "", mf.group(1))
        for p in re.split(r"\s*,\s*|\s+y\s+", blob):
            nm = p.strip()
            nm = re.sub(r"^(?:con licencia[,:\s]*|con aviso[,:\s]*|sin aviso[,:\s]*)", "", nm)
            nm = re.sub(r"^(?:el señor|la señora|señor|señora|señores senadores|señores representantes)\s+",
                        "", nm).strip()
            if nm and re.match(r"^[A-ZÁÉÍÓÚÜÑ]", nm) and len(nm) >= 5 and nm[0].isupper():
                asist.setdefault(nm, "ausente")
    return asist


def parse_nominal(flat):
    """Listas 'A favor: X, y / En contra: ... / Abstenciones: ...' -> dict nombre->voto.
    SOLO activa si el bloque declaró votación nominal ('se registra', 'nominal', 'nominas')."""
    guard = re.search(r"votaci[oó]n\s+nominal|se\s+registra(?:n)?\s+(?:el\s+)?voto|N[oó]minas?|"
                      r"nomin[ae]lmente|voto\s+por\s+voto", flat, re.I)
    if not guard:
        return {}
    out = {}
    for m in re.finditer(r"A\s*favor(?:es)?\s*:?\s*([^«»]{0,900}?)(?=\s*En\s*contra|\s*Abstenciones|$)", flat, re.I):
        for p in re.split(r"\s*,\s*|\s+y\s+", m.group(1)):
            nm = p.strip()
            if nm and re.match(r"^[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]", nm) and len(nm.split()) <= 4:
                out[nm] = "a_favor"
    for m in re.finditer(r"En\s*contra\s*:?\s*([^«»]{0,900}?)(?=\s*Abstenciones|$)", flat, re.I):
        for p in re.split(r"\s*,\s*|\s+y\s+", m.group(1)):
            nm = p.strip()
            if nm and re.match(r"^[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]", nm) and len(nm.split()) <= 4:
                out[nm] = "en_contra"
    for m in re.finditer(r"Abstenciones\s*:?\s*([^«»]{0,600})", flat, re.I):
        for p in re.split(r"\s*,\s*|\s+y\s+", m.group(1)):
            nm = p.strip()
            if nm and re.match(r"^[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]", nm) and len(nm.split()) <= 4:
                out.setdefault(nm, "abstencion")
    return out


def parse_votos(texto, camara):
    """Votaciones de la sesión desde el texto del PDF diario.
    Devuelve (lista de votaciones dict, dict asistencia)."""
    flat = derizar(texto)
    asist = parse_asistencia(flat, camara)
    hits = []

    def addv(start, a_f=None, e_c=None, tot=None, res="afirmativa"):
        unanim = (res == "afirmativa" and e_c == 0) or (a_f is not None and tot is not None and a_f == tot)
        hits.append({"inicio": start, "a_favor_n": a_f, "en_contra_n": e_c,
                     "resultado": res, "unanimidad": bool(unanim)})
        return unanim

    # CSS compacto "–15 en 16. Afirmativa."
    for m in RE_VOTE_CSS.finditer(flat):
        a, b, res = int(m.group(1)), int(m.group(2)), m.group(3).lower()
        e_c = max(0, b - a)
        addv(m.start(), a, e_c, b, res)

    # CSS/CRR numérico extendido "Ochenta y tres votos afirmativos y siete votos negativos en noventa presentes: AFIRMATIVA."
    for m in RE_VOTE_N.finditer(flat):
        a = int(m.group(1)); e_c = int(m.group(2)) if m.group(2) else None; tot = int(m.group(3))
        res = m.group(4).lower()
        e_c = e_c if e_c is not None else max(0, tot - a)
        addv(m.start(), a, e_c, tot, res)

    # CRR letras "Setenta y dos en setenta y cuatro: AFIRMATIVA."
    for m in RE_VOTE_CRR_LETRAS.finditer(flat):
        n1 = letras_a_num(m.group(1))
        n_afir = n_neg = None
        if m.group(2):           # "N votos afirmativos y M votos negativos"
            n_afir, n_neg = n1, letras_a_num(m.group(2))
        elif m.group(3):         # "N votos negativos y M votos afirmativos"
            n_neg, n_afir = n1, letras_a_num(m.group(3))
        else:                    # "N votos afirmativos" o "N votos negativos"
            if "negativos" in (m.group(0) or "").lower():
                n_neg = n1
            else:
                n_afir = n1
        tot = letras_a_num(m.group(4))
        res = m.group(5).lower()
        if n_neg is None:
            if n_afir is not None and tot is not None:
                n_neg = max(0, tot - n_afir)
        addv(m.start(), n_afir, n_neg, tot, res)

    # orden + dedupe (mismas posiciones cercanas entre patrones)
    hits.sort(key=lambda v: v["inicio"])
    dedup, last = [], -1
    for v in hits:
        if v["inicio"] - last < 80:
            continue
        last = v["inicio"]
        dedup.append(v)

    sal = []
    for i, v in enumerate(dedup):
        pre = flat[max(0, v["inicio"] - 1500):v["inicio"]]
        tit, carp = _contexto_titulo(pre)
        nominal = parse_nominal(flat[max(0, v["inicio"] - 2500):v["inicio"] + 400])
        entry = {"orden": i + 1, "titulo": tit, "carpeta": carp,
                 "resultado": v["resultado"], "a_favor_n": v["a_favor_n"],
                 "en_contra_n": v["en_contra_n"], "unanimidad": v["unanimidad"],
                 "voto_agregado": True, "votacion": {}}
        if nominal:
            entry["votacion"].update(nominal)
            entry["voto_agregado"] = False
            for nm in asist:
                if asist[nm] == "ausente":
                    entry["votacion"].setdefault(nm, "ausente")
        elif v["unanimidad"] and asist:
            val = "a_favor" if v["resultado"] == "afirmativa" else "en_contra"
            for nm, st in asist.items():
                entry["votacion"][nm] = val if st == "asistio" else "ausente"
            entry["voto_agregado"] = False
        elif asist:
            # no-unánime agregado: ausentes quedan marcados de todos modos (asistencia conocida)
            for nm, st in asist.items():
                if st == "ausente":
                    entry["votacion"][nm] = "ausente"
        sal.append(entry)
    return sal, asist


# ------------------------------------------------------------ descarga de una sesión

def _lista_diarios(camara, periodo):
    """CSV del portal: filas {Sesión, Fecha dd-mm-aaaa, Diario, Resumen}. Filtra por año."""
    cam = CAMARAS[camara]
    url = "%s/camarasycomisiones/%s/plenario/documentos/diarios-de-sesion/csv?_format=csv" % (BASE, cam["slug"])
    raw = http_get(url)
    rows = list(csv.DictReader(io.StringIO(raw)))
    year = str(periodo)
    # fecha dd-mm-aaaa; si el periodo no matchea el año de la fecha, queda fuera
    out = []
    for r in rows:
        f = (r.get("Fecha") or "").strip()
        m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", f)
        if m and m.group(3) == year:
            out.append({"sesion_nro": r.get("Sesión"), "fecha_ddmmyyyy": f,
                        "fecha_iso": "%s-%s-%s" % (m.group(3), m.group(2), m.group(1)),
                        "diario": r.get("Diario"), "resumen": r.get("Resumen")})
    return out


def _pagina_y_pdf(camara, sesion, run_id=None):
    """URL de provenance (página del diario en el portal) + link del PDF real."""
    cam = CAMARAS[camara]
    n = sesion["diario"]
    nro = (n or "").strip()
    url_pag = "%s/camarasycomisiones/%s/documentos/diario-de-sesion/%s/IMG" % (BASE, cam["slug"], nro)
    html = http_get(url_pag)
    links = sorted(set(re.findall(r'https://infolegislativa\.parlamento\.gub\.uy/temporales/[^"]+', html)))
    return url_pag, links


def descarga_sesion(camara, sesion, run_id, base_dir, force=False):
    """Baja el PDF del diario de sesión y genera data/votaciones/<camara>/<periodo>/<sesion>.json.
    Devuelve dict resumen para el ledger"""
    cam = CAMARAS[camara]
    if not sesion["diario"]:
        return None
    nro = sesion["diario"].strip()
    eid = record_start(run_id, "votaciones_nominales", "%s-%s" % (cam["code"], nro),
                       item_url=sesion.get("_url_pag"), meta={"fecha": sesion["fecha_iso"]})
    url_pag = None
    try:
        sesion_dir = os.path.join(base_dir, camara, str(sesion["fecha_iso"][:4]))
        os.makedirs(sesion_dir, exist_ok=True)
        destino = os.path.join(sesion_dir, "%s%s-s%02d.json" % (cam["code"], sesion["fecha_iso"], int(sesion["sesion_nro"] or 0)))
        if os.path.exists(destino) and not force:
            record_finish(eid, "skipped", file_path=destino)
            return {"status": "skipped", "path": destino}
        url_pag, links = _pagina_y_pdf(camara, sesion)
        sesion["_url_pag"] = url_pag
        if not links:
            record_finish(eid, "error", error="diario sin PDF en %s" % url_pag)
            return {"status": "error", "error": "sin pdf"}
        pdf_url = links[0]
        sleep_rate()
        pdf = http_get(pdf_url, binary=True, timeout=600)
        os.makedirs(TMP, exist_ok=True)
        ppdf = os.path.join(TMP, "dss_%s_%s.pdf" % (cam["code"], nro))
        open(ppdf, "wb").write(pdf)
        sha = hashlib.sha256(pdf).hexdigest()
        texto = pdf_a_texto(ppdf)
        if not texto.strip():
            record_finish(eid, "error", error="pdftotext vacio", bytes_=len(pdf), file_path=ppdf, sha256=sha)
            return {"status": "error", "error": "pdftotext vacio"}
        votos, asist = parse_votos(texto, camara)
        doc = {"camara": camara, "periodo": str(sesion["fecha_iso"][:4]),
               "sesion_id": "%s-s%02d-%s" % (cam["code"], int(sesion["sesion_nro"] or 0), sesion["fecha_iso"]),
               "sesion_nro": sesion["sesion_nro"], "sesion_fecha": sesion["fecha_iso"],
               "url_origen": pdf_url, "url_pagina": url_pag, "diario_nro": nro,
               "checksum": "sha256:" + sha, "descargado": now_iso(),
               "asistencia": asist, "votaciones": votos}
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        record_finish(eid, "ok", rows=len(votos), bytes_=len(pdf), file_path=destino, sha256=sha,
                      meta={"sesion": doc["sesion_id"], "url": pdf_url})
        return {"status": "ok", "path": destino, "votos": len(votos), "asist": len(asist)}
    except Exception as e:
        record_finish(eid, "error", error=str(e))
        return {"status": "error", "error": str(e)}


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ------------------------------------------------------------ export CSV + CLI

def export_plano(base_dir=None):
    """data/export/votaciones.csv con filas por (legislador, camara, fecha, proyecto, voto)."""
    base_dir = base_dir or OUT_VOT
    os.makedirs(os.path.dirname(OUT_EXPORT), exist_ok=True)
    cols = ["legislador", "camara", "fecha", "sesion_id", "proyecto_id", "titulo", "voto",
            "url_origen"]
    n = 0
    with open(OUT_EXPORT, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for root, dirs, files in os.walk(base_dir):
            for fn in files:
                if not fn.endswith(".json"):
                    continue
                p = os.path.join(root, fn)
                try:
                    doc = json.load(open(p, encoding="utf-8"))
                except Exception:
                    continue
                for v in doc.get("votaciones", []):
                    for lg, voto in v.get("votacion", {}).items():
                        w.writerow({"legislador": lg, "camara": doc.get("camara"),
                                    "fecha": doc.get("sesion_fecha"), "sesion_id": doc.get("sesion_id"),
                                    "proyecto_id": v.get("carpeta") or "",
                                    "titulo": (v.get("titulo") or "")[:240],
                                    "voto": voto, "url_origen": doc.get("url_origen", "")})
                        n += 1
    return OUT_EXPORT, n


def run(camara="senadores", periodo=None, limit=None, force=False):
    periodo = str(periodo or datetime.now().year)
    base_dir = OUT_VOT
    run_id = "votaciones-%s-%s-%s" % (camara, periodo, time.strftime("%Y%m%dT%H%M"))
    start_run(run_id, "votaciones_nominales", mode="backfill", note="camara=%s periodo=%s" % (camara, periodo))
    ok = err = skip = 0
    sesiones = _lista_diarios(camara, periodo)
    if limit:
        sesiones = sesiones[:int(limit)]
    for s in sesiones:
        res = descarga_sesion(camara, s, run_id, base_dir, force=force)
        if not res:
            continue
        if res["status"] == "ok":
            ok += 1
        elif res["status"] == "skipped":
            skip += 1
        else:
            err += 1
        sleep_rate()  # el sleep entre requests sesion nueva ya lo hace descarga_sesion tras GET pagina
    finish_run(run_id, status="ok" if err == 0 else "partial")
    export_path, nfilas = export_plano()
    out = {"run": run_id, "camara": camara, "periodo": periodo, "ok": ok, "skipped": skip,
           "errors": err, "csv": export_path, "filas_csv": nfilas}
    print(json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Backfill de votaciones y asistencias del Parlamento")
    ap.add_argument("--camara", choices=list(CAMARAS), default="senadores")
    ap.add_argument("--periodo", default=None, help="año del período (default: año actual)")
    ap.add_argument("--limit", type=int, default=None, help="procesar solo N sesiones (más recientes primero)")
    ap.add_argument("--force", action="store_true", help="re-descargar aunque el JSON exista")
    a = ap.parse_args()
    run(camara=a.camara, periodo=a.periodo, limit=a.limit, force=a.force)

