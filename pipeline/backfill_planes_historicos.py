"""planes_historicos — descarga y convierte programas de gobierno de elecciones anteriores.

A diferencia de backfill_planes.py (elección vigente, config/planes.json), este módulo lee
config/planes_historicos.json (elecciones 2004/2009/2014/2019...) y escribe en
data/planes/<ano>_<partido>/programa.{pdf,md} para NO pisar los de la elección vigente.

NO TOCA config/planes.json ni data/planes/<partido>/.

Salida:
  data/planes/<ano>_<partido>/programa.pdf — PDF fuente
  data/planes/<ano>_<partido>/programa.md  — markdown con front-matter (url, sha256, fecha)

Cada partido se registra en el ledger con source='planes_historicos'.

Uso:
    python pipeline/backfill_planes_historicos.py               # todos
    python pipeline/backfill_planes_historicos.py --limit 2     # smoke test
    python pipeline/backfill_planes_historicos.py --ano 2014
    python pipeline/backfill_planes_historicos.py --partido 2019:fa
    python pipeline/backfill_planes_historicos.py --no-skip     # regenera
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

CONFIG = os.path.join(BASE, "config", "planes_historicos.json")
OUT_DIR = os.path.join(BASE, "data", "planes")
SOURCE = "planes_historicos"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) uruguay-gov-audit/1.0"}


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    return {año: p for año, p in cfg.items() if not año.startswith("_")}


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
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def convert_docling(pdf_path, md_path):
    """PDF -> markdown con docling (sin OCR; son PDFs de texto nativo)."""
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
    except ImportError:
        return False
    opts = PdfPipelineOptions()
    opts.do_ocr = False
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
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
    headings = re.findall(r"^#{1,4} ", md, flags=re.M)
    if len(headings) >= 3:
        return len(headings)
    return len(re.findall(r"<!-- página (\d+) -->", md))


def write_front_matter(md_path, url, checksum, conv_method, pages=None, extra=None):
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
    for k, v in (extra or {}).items():
        fm.append(f"{k}: {v}")
    fm.append("---")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(fm) + "\n\n" + body)
    return len(fm)


def process_item(ano, key, meta, run_id, skip_existing=True):
    dir_ = os.path.join(OUT_DIR, f"{ano}_{key}")
    pdf_path = os.path.join(dir_, "programa.pdf")
    md_path = os.path.join(dir_, "programa.md")
    url = meta["url_pdf"]
    item_id = f"{ano}:{key}"
    eid = ledger.record_start(run_id, SOURCE, item_id, item_url=url,
                              meta={"nombre": meta["nombre"],
                                    "destino": os.path.relpath(dir_, BASE)})
    try:
        if skip_existing and os.path.exists(pdf_path) and os.path.exists(md_path):
            ledger.record_finish(eid, status="skipped", file_path=md_path,
                                 sha256=sha256_file(pdf_path))
            print(f"[{item_id}] skipped (ya convertido)")
            return "skipped"
        size = download_pdf(url, pdf_path)
        checksum = sha256_file(pdf_path)
        conv_method = None
        try:
            if convert_docling(pdf_path, md_path):
                conv_method = "docling"
        except Exception as e:
            print(f"[{item_id}] docling falló: {e}")
        if conv_method is None:
            if convert_pdfplumber(pdf_path, md_path):
                conv_method = "pdfplumber"
        if conv_method is None:
            raise RuntimeError("sin conversor disponible (docling y pdfplumber fallaron)")
        write_front_matter(md_path, url, checksum, conv_method,
                           extra={"nota": meta.get("nota", "")})
        n_sections = count_sections(open(md_path, encoding="utf-8").read())
        ledger.record_finish(eid, status="ok", rows=n_sections, bytes_=size,
                             file_path=md_path, sha256=checksum)
        print(f"[{item_id}] ok: {size} bytes, {n_sections} secciones, conversión={conv_method}")
        return "ok"
    except Exception as e:
        ledger.record_finish(eid, status="error", error=e, file_path=pdf_path)
        print(f"[{item_id}] ERROR: {e}")
        return "error"


def main():
    ap = argparse.ArgumentParser(
        description="Descarga y convierte programas históricos de gobierno (planes_historicos)")
    ap.add_argument("--limit", type=int, default=None, help="procesar solo los primeros N ítems")
    ap.add_argument("--ano", default=None, help="procesar solo un año (p.ej. 2014)")
    ap.add_argument("--partido", default=None, help="procesar uno solo (formato ANO:partido)")
    ap.add_argument("--no-skip", action="store_true", help="regenerar aunque el md ya exista")
    args = ap.parse_args()

    cfg = load_config()
    items = []
    for ano in sorted(cfg, reverse=True):
        for key in sorted(cfg[ano]):
            items.append((ano, key, cfg[ano][key]))
    if args.ano:
        items = [i for i in items if i[0] == args.ano]
    if args.partido:
        ano, key = args.partido.split(":", 1)
        items = [i for i in items if i[0] == ano and i[1] == key]
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("sin ítems")
        sys.exit(1)

    run_id = f"planes-historicos-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    ledger.start_run(run_id, SOURCE, mode="backfill",
                     note=f"{len(items)} ítem(s): {','.join(f'{a}:{k}' for a, k, _ in items)}")
    results = {}
    for ano, key, meta in items:
        results[f"{ano}:{key}"] = process_item(ano, key, meta, run_id,
                                               skip_existing=not args.no_skip)
    ok = sum(1 for v in results.values() if v == "ok")
    err = sum(1 for v in results.values() if v == "error")
    status = "ok" if err == 0 and ok > 0 else ("error" if err == len(results) else "partial")
    ledger.finish_run(run_id, status=status,
                      note=f"ok={ok} error={err} skipped={len(results)-ok-err}")
    print(f"{run_id}: ok={ok} err={err} skipped={len(results)-ok-err}")


if __name__ == "__main__":
    main()
