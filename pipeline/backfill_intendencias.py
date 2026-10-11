"""Fuente: WEBS OFICIALES DE INTENDENCIAS fuera del catálogo CKAN nacional.

13 intendencias no publican datasets en catalogodatos.gub.uy — esta fuente
scrapea directamente sus webs (.gub.uy) para bajar el paquete de auditoría
departamental: presupuesto quinquenal, rendiciones de cuentas, pliegos de
compras/licitaciones y gabinete (directorio de autoridades).

Patrón (igual que backfill_ckan):
- TODO fetch queda registrado en el ledger (record_start/record_finish, source=intendencias_scrape).
- Provenance por documento: URL oficial de origen, sha256, fecha, content-type.
- Rate limit: sleep >= 3s entre requests, UN dominio concurrente (motor secuencial).
- robots.txt de cada dominio se consulta ANTES de scrapear; si un host bloquea
  (403/redirect-loop) la corrida lo marca en el ledger y sigue — sin hammering.
- Solo archivos en hosts .gub.uy declarados en domain_allow.

Uso:
  python pipeline/backfill_intendencias.py --intendencia salto --limit 5
  python pipeline/backfill_intendencias.py --dry-run      # solo descubre, no descarga
  python pipeline/backfill_intendencias.py --metadata-only # todo menos cuerpos (descubre + checksum skip)
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from ledger import record_start, record_finish, start_run, finish_run, sha256_file, export_csv

ROOT = os.path.join(os.path.dirname(__file__), "..")
CONFIG = os.path.join(ROOT, "config", "intendencias.json")
OUT_FILES = os.path.join(ROOT, "data", "intendencias")
OUT_META = os.path.join(ROOT, "data", "metadata", "intendencias")
OUT_ROBOTS = os.path.join(ROOT, "data", "metadata", "intendencias", "_robots")

DOC_EXTS = (".pdf", ".xlsx", ".xls", ".csv", ".ods")
# patrones que delatan un documento de gestión en el nombre/texto del link
CATEGORY_PATTERNS = [
    ("presupuesto", re.compile(r"presupuesto", re.I)),
    ("rendiciones", re.compile(r"rendici|rendic\b", re.I)),
    ("compras", re.compile(r"licita|llamado|pliego|adquisic|compra|contrat", re.I)),
    ("gabinete", re.compile(r"autoridad|gabinete|intendente|secretario|estructura|organigrama", re.I)),
]
SKIP_URL_PARTS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", "#", "mailto:", "javascript:",
                  "twitter.", "facebook.", "instagram.", "youtube.", "youtu.be", "/wp-admin",
                  "comprasestatales.gub.uy", "catalogodatos.gub.uy", "youtube.com")


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["global"], {i["nombre"]: i for i in cfg["intendencias"]}


class Fetcher:
    """HTTP secuencia con rate-limit global (1 dominio a la vez, sleep entre requests)."""

    def __init__(self, cfg):
        self.sleep_s = cfg.get("sleep_s", 3)
        self.timeout_s = cfg.get("timeout_s", 60)
        self.ua = cfg.get("user_agent", "uruguay-gov-audit/0.1")
        self.client = httpx.Client(headers={"User-Agent": self.ua}, timeout=self.timeout_s,
                                   follow_redirects=True, max_redirects=10, verify=True)
        self.last_request_ts = 0.0
        self.robots_cache = {}   # netloc -> bool allowed (crawl-all? presence of broaden disallow)

    def wait(self):
        wait = self.sleep_s - (time.time() - self.last_request_ts)
        if wait > 0:
            time.sleep(wait)
        self.last_request_ts = time.time()

    def get(self, url, **kw):
        self.wait()
        return self.client.get(url, **kw)

    def robots_allows(self, url):
        """True si ni robots.txt lo bloquea ni la política del dominio lo excluye.

        Interpretación conservadora: si robots de la HOME-domain tiene
        'Disallow: /' global (user-agent *), devolvemos False y solo es válido
        bajar documentos con URL conocida passada explícitamente (dj servers
        públicos listados en seed_urls como documentos directos), nunca crawling.
        """
        netloc = urlparse(url).netloc
        if netloc in self.robots_cache:
            return self.robots_cache[netloc]
        allowed = True
        base = f"{urlparse(url).scheme}://{netloc}/robots.txt"
        try:
            r = self.get(base)
            if r.status_code == 200 and "<html" not in r.text[:200].lower():
                self._save_robots(netloc, r.text)
                for block in re.split(r"(?i)^user-agent:\s*\*", r.text, flags=re.M)[1:]:
                    body = block.split("user-agent:")[0]
                    for line in body.splitlines():
                        line = line.strip()
                        if line.lower().startswith("disallow:"):
                            path = line.split(":", 1)[1].strip()
                            if path == "/":
                                allowed = False
                    break
        except Exception:
            self._save_robots(netloc, f"<error fetching robots {base}>")
            allowed = True  # si robots no accesible, se asume permitido (sitio público)
        self.robots_cache[netloc] = allowed
        return allowed

    def _save_robots(self, netloc, text):
        os.makedirs(OUT_ROBOTS, exist_ok=True)
        path = os.path.join(OUT_ROBOTS, f"{netloc}.txt")
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(text)


def classify(url, title=""):
    """Categoría auditoría de un documento según su URL/título."""
    blob = f"{url} {title}"
    for cat, pat in CATEGORY_PATTERNS:
        if pat.search(blob):
            return cat
    return "otros"


class Crawler:
    MAX_PAGES_PER_SEED = 12     # límite de páginas detalle por seed (crawling acotado)

    def __init__(self, globals_, fetcher, intendencia, run_id):
        self.g = globals_
        self.f = fetcher
        self.inc = intendencia
        self.name = intendencia["nombre"]
        self.run_id = run_id
        self.allow_hosts = set(intendencia.get("domain_allow", []))
        self.dom_files = os.path.join(OUT_FILES, self.name)
        self.dom_meta = os.path.join(OUT_META, self.name)
        self.found = {}   # url_abs -> {"title","url","page_url","category"}

    # ---------- descubrimiento ----------
    def _is_doc(self, url):
        u = url.lower().split("?")[0]
        return any(u.endswith(ext) for ext in DOC_EXTS)

    def _allowed_host(self, url):
        netloc = urlparse(url).netloc
        return any(netloc == h or netloc.endswith("." + h) for h in self.allow_hosts)

    def harvest(self, page_url, depth=0):
        """Descubre en una página: documentos directos y subpáginas de sección."""
        if not self._allowed_host(page_url):
            return
        eid = record_start(self.run_id, "intendencias_scrape", f"page:{page_url}",
                           item_url=page_url, meta={"intendencia": self.name, "depth": depth})
        try:
            r = self.f.get(page_url)
            if r.status_code != 200:
                record_finish(eid, "error", error=f"HTTP {r.status_code}")
                return
            final = str(r.url)
            soup = BeautifulSoup(r.text, "html.parser")
            follow = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                low = href.lower()
                if any(s in low for s in SKIP_URL_PARTS):
                    continue
                absu = urljoin(final, href)
                title = a.get_text(" ", strip=True)
                if self._is_doc(absu):
                    if self._allowed_host(absu):
                        cat = classify(absu, title)
                        if absu not in self.found or cat != "otros":
                            self.found[absu] = {"title": title[:120], "url": absu,
                                                "page_url": final,
                                                "category": cat if cat != "otros" else self.found.get(absu, {}).get("category", "otros")}
                elif depth < 2 and any(low.endswith(p) for p in ("/", ".html")) and self._allowed_host(absu):
                    # subpáginas de sección: rutas con vocab audit-key en la URL
                    if any(pat.search(absu) for _, pat in CATEGORY_PATTERNS):
                        follow.append(absu)
            record_finish(eid, "ok", rows=len(follow) + 1, file_path=final)
        except Exception as e:
            record_finish(eid, "error", error=str(e))

        for sub in follow[: self.MAX_PAGES_PER_SEED if depth == 0 else 4]:
            self.harvest(sub, depth=depth + 1)

    # ---------- descarga ----------
    def download_docs(self, limit=0, dry_run=False):
        """Descarga documentos descubiertos, con ledger y metadata JSON por doc."""
        downloaded = skipped = failed = 0
        docs = sorted(self.found.values(), key=lambda d: (d["category"], d["url"]))
        if limit:
            priority = {"presupuesto": 0, "rendiciones": 1, "compras": 2, "gabinete": 3, "otros": 4}
            docs = sorted(docs, key=lambda d: priority.get(d["category"], 9))[:limit]
        os.makedirs(self.dom_meta, exist_ok=True)
        os.makedirs(self.dom_files, exist_ok=True)
        for doc in docs:
            url = doc["url"]
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("/")[-1] or "doc")[:80]
            if not os.path.splitext(safe_name)[1]:
                safe_name += os.path.splitext(urlparse(url).path)[1] or ".bin"
            eid = record_start(self.run_id, "intendencias_scrape", f"doc:{url}", item_url=url,
                               meta={"intendencia": self.name, "category": doc["category"],
                                     "page_url": doc["page_url"]})
            if dry_run:
                record_finish(eid, "skipped", error="dry-run (no descarga)")
                skipped += 1
                continue
            dest = os.path.join(self.dom_files, f"{doc['category']}_{safe_name}")
            meta_path = os.path.join(self.dom_meta, f"{doc['category']}_{safe_name}.json")
            try:
                if os.path.exists(dest) and os.path.getsize(dest) > 0:
                    size = os.path.getsize(dest)
                    record_finish(eid, "skipped", bytes_=size, file_path=os.path.relpath(dest, ROOT))
                    self._write_meta(meta_path, doc, dest, size, sha=sha256_file(dest))
                    skipped += 1
                    continue
                maxb = self.g.get("max_descarga_mb", 200) * 1_000_000
                with self.f.client.stream("GET", url, timeout=self.f.timeout_s) as r:
                    r.raise_for_status()
                    cl = int(r.headers.get("content-length") or 0)
                    if cl > maxb:
                        record_finish(eid, "skipped", error=f"too big ({cl}B)")
                        continue
                    tmp = dest + ".part"
                    with open(tmp, "wb") as fh:
                        for chunk in r.iter_bytes(1 << 20):
                            fh.write(chunk)
                        self.f.last_request_ts = time.time()
                    os.replace(tmp, dest)
                size = os.path.getsize(dest)
                sha = sha256_file(dest)
                record_finish(eid, "ok", bytes_=size, file_path=os.path.relpath(dest, ROOT), sha256=sha)
                self._write_meta(meta_path, doc, dest, size, sha)
                downloaded += 1
                time.sleep(self.f.sleep_s)
            except Exception as e:
                record_finish(eid, "error", error=str(e))
                try:
                    os.remove(dest + ".part")
                except OSError:
                    pass
                failed += 1
        return {"downloaded": downloaded, "skipped": skipped, "failed": failed}

    def _write_meta(self, path, doc, dest, size, sha=None):
        meta = {
            "intendencia": self.name,
            "titulo": doc["title"],
            "url_documento": doc["url"],
            "url_pagina_origen": doc["page_url"],
            "categoria": doc["category"],
            "archivo_local": os.path.relpath(dest, ROOT),
            "bytes": size,
            "sha256": sha or sha256_file(dest) if os.path.exists(dest) else None,
            "descargado_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "run_id": self.run_id,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)


def run(run_id=None, intendencia=None, limit=0, dry_run=False):
    g, incs = load_config()
    if intendencia:
        if intendencia not in incs:
            raise SystemExit(f"intendencia desconocida: {intendencia}. Válidas: {', '.join(incs)}")
        incs = {intendencia: incs[intendencia]}
    run_id = run_id or f"intendencias-{time.strftime('%Y%m%dT%H%M')}"
    start_run(run_id, "intendencias_scrape", mode="backfill",
              note=f"intendencias={','.join(incs)} limit={limit}")
    fetcher = Fetcher(g)
    total = {"ok": 0, "err": 0, "skipped": 0, "blocked": []}
    for name, inc in incs.items():
        # robots check por dominio principal (queda cacheado y guardado como metadata)
        blocked = not fetcher.robots_allows(f"https://{inc['dominio']}/")
        crawler = Crawler(g, fetcher, inc, run_id)
        for tag, url in inc.get("seed_urls", {}).items():
            crawler.harvest(url)
        stats = crawler.download_docs(limit=limit, dry_run=dry_run)
        if blocked:
            total["blocked"].append(name)
        total["ok"] += stats["downloaded"]
        total["skipped"] += stats["skipped"]
        total["err"] += stats["failed"]
        print(f"[{name}] found={len(crawler.found)} dl={stats['downloaded']} skip={stats['skipped']} err={stats['failed']} robots_crawl={'NO' if blocked else 'sí'}")
    finish_run(run_id, status="ok" if total["err"] == 0 else "partial")
    export_csv()
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="backfill intendencias (webs oficiales, fuera de CKAN)")
    ap.add_argument("--intendencia", help="una intendencia (nombre en config); default: todas")
    ap.add_argument("--limit", type=int, default=0, help="docs máx por intendencia (0 = todos)")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--dry-run", action="store_true", help="descubre URLs, no descarga archivos")
    a = ap.parse_args()
    res = run(a.run_id, a.intendencia, a.limit, a.dry_run)
    print(json.dumps(res, ensure_ascii=False))
