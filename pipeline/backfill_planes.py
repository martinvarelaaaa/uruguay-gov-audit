"""planes_gobierno — baja y convierte los programas de gobierno (elección 2024, período 2025-2030).

Lee config/planes.json (un partido = un PDF), descarga el PDF a
data/planes/<partido>/programa.pdf y lo convierte a markdown
(data/planes/<partido>/programa.md) con front-matter (url, sha256, fecha).

Conversión: docling si está disponible; fallback pdfplumber (extracción simple
página a página). Cada partido se registra en el ledger con source='planes_gobierno'.

Uso:
    python pipeline/backfill_planes.py              # todos los partidos
    python pipeline/backfill_planes.py --limit 2    # primeros 2 (smoke test)
    python pipeline/backfill_planes.py --partido fa # uno solo
    python pipeline/backfill_planes.py --no-skip    # regenera aunque ya exista
"""
import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "pipeline"))
import ledger  # noqa: E402

CONFIG = os.path.join(BASE, "config", "planes.json")
OUT_DIR = os.path.join(BASE, "data", "planes")
SOURCE = "planes_gobierno"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) uruguay-gov-audit/1.0"}


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def download_pdf(url, dest):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180, context=ctx) as resp:
        data = resp.read()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


def sha256_file(path):
    import hashlib as _h
    h = _h.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def convert_docling(pdf_path, md_path):
    """Convierte PDF -> markdown con docling (encabezados/secciones preservados)."""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        return False
    conv = DocumentConverter()
    result = conv.convert(pdf_path)
    md = result.document.export_to_markdown()
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    return True


def convert_pdfplumber(pdf_path, md_path):
    """Fallback: extracción de texto simple con pdfplumber."""
    import pdfplumber
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            txt = page.extract_text() or ""
            parts.append(f"<!-- página {i} -->\n{txt}".strip())
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts) + "\n")
    return True


def count_sections(md):
    """Secciones detectadas: headers markdown (#..####) o saltos <!-- página N -->."""
    headings = re.findall(r"^#{1,4} ", md, flags=re.M)
    if len(headings) >= 3:
        return len(headings)
    return len(re.findall(r"<!-- página (\d+) -->", md))


def write_front_matter(md_path, url, checksum, conv_method, pages=None, partidos_meta=None):
    with open(md_path, encoding="utf-8") as f:
        body = f.read()
    fm = [
        "---",
        f"url: {url}",
        f"checksum: sha256:{checksum}",
        f"fecha: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"conversion: {conv_method}",
    ]
    if pages:
        fm.append(f"paginas: {pages}")
    fm.append("---")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(fm) + "\n\n" + body)
    return len(fm)


def process_partido(key, meta, run_id, skip_existing=True):
    dir_ = os.path.join(OUT_DIR, key)
    pdf_path = os.path.join(dir_, "programa.pdf")
    md_path = os.path.join(dir_, "programa.md")
    url = meta["url_pdf"]
    eid = ledger.record_start(run_id, SOURCE, key, item_url=url,
                              meta={"nombre": meta["nombre"]})
    try:
        if skip_existing and os.path.exists(pdf_path) and os.path.exists(md_path):
            ledger.record_finish(eid, status="skipped", file_path=md_path)
            print(f"[{key}] skipped (ya convertido)")
            return "skipped"

        size = download_pdf(url, pdf_path)
        checksum = sha256_file(pdf_path)
        conv_method = None
        try:
            if convert_docling(pdf_path, md_path):
                conv_method = "docling"
        except Exception as e:
            print(f"[{key}] docling falló: {e}")
        if conv_method is None:
            if convert_pdfplumber(pdf_path, md_path):
                conv_method = "pdfplumber"
        if conv_method is None:
            raise RuntimeError("sin conversor disponible (docling y pdfplumber fallaron)")
        write_front_matter(md_path, url, checksum, conv_method)
        n_sections = count_sections(open(md_path, encoding="utf-8").read())
        ledger.record_finish(eid, status="ok", rows=n_sections, bytes_=size,
                             file_path=md_path, sha256=checksum,
                             meta={"conversion": conv_method, "nombre": meta["nombre"]})
        print(f"[{key}] ok: {size} bytes, {n_sections} secciones, conversión={conv_method}")
        return "ok"
    except Exception as e:
        ledger.record_finish(eid, status="error", error=e, file_path=pdf_path)
        print(f"[{key}] ERROR: {e}")
        return "error"


def main():
    ap = argparse.ArgumentParser(description="Descarga y convierte programas de gobierno (planes_gobierno)")
    ap.add_argument("--limit", type=int, default=None, help="procesar solo los primeros N partidos")
    ap.add_argument("--partido", default=None, help="procesar un solo partido (clave de planes.json)")
    ap.add_argument("--no-skip", action="store_true", help="regenerar aunque el md ya exista")
    args = ap.parse_args()

    cfg = load_config()
    keys = sorted(cfg.keys())
    if args.partido:
        keys = [args.partido] if args.partido in cfg else []
        if not keys:
            print(f"partido desconocido: {args.partido}; opciones: {', '.join(sorted(cfg))}")
            sys.exit(1)
    if args.limit:
        keys = keys[: args.limit]

    run_id = f"planes-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    ledger.start_run(run_id, SOURCE, mode="backfill",
                     note=f"{len(keys)} partido(s): {','.join(keys)}")
    results = {}
    for k in keys:
        results[k] = process_partido(k, cfg[k], run_id, skip_existing=not args.no_skip)
    ok = sum(1 for v in results.values() if v == "ok")
    err = sum(1 for v in results.values() if v == "error")
    status = "ok" if err == 0 and ok > 0 else ("error" if err == len(results) else "partial")
    ledger.finish_run(run_id, status=status, note=f"ok={ok} error={err} skipped={len(results)-ok-err}")
    print(f"{run_id}: ok={ok} err={err} skipped={len(results)-ok-err}")


if __name__ == "__main__":
    main()
