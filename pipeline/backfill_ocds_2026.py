"""Ingesta mensual OCDS 2026: el pack histórico anual de ARCE solo llega a 2025;
el año en curso se obtiene vía /ocds/rss/AAAA/MM (bulk download del estándar OCDS).
Por mes: baja el RSS, extrae links de release, los baja y los concatena en
data/ocds/ocds-2026/MM/a-MM2026.json (compatibles con build_index.import_ocds,
que itera releases[]). Idempotente por archivo mes+prefijo.
"""
import os, sys, json, time, re, urllib.request, urllib.error, xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "ocds", "ocds-2026")
BASE = "http://www.comprasestatales.gub.uy/ocds"
UA = {"User-Agent": "Mozilla/5.0 (govaudit ingesta; contacto martinvarela92@gmail.com)"}
MESES = sys.argv[1].split(",") if len(sys.argv) > 1 else [f"{m:02d}" for m in range(1, 10)]

def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read()

def main():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    total = 0
    for mes in MESES:
        destino = os.path.join(OUT, f"a-{mes}-2026.json")
        if os.path.exists(destino) and os.path.getsize(destino) > 2_000_000:
            print(f"2026-{mes}: ya está, skip")
            continue
        try:
            rss = get(f"{BASE}/rss/2026/{mes}")
        except Exception as e:
            print(f"2026-{mes}: RSS error {e}"); continue
        links = re.findall(rb"<link>(http://www\.comprasestatales\.gub\.uy/ocds/release/[^<]+)</link>", rss)
        links = [l.decode() for l in links]
        # el primero del rss es el propio channel link; filtrar
        links = [l for l in links if "/rss/" not in l]
        # dedup preservando orden (releases pueden repetirse entre llamados/adjudicaciones)
        seen, uniq = set(), []
        for l in links:
            if l not in seen:
                seen.add(l); uniq.append(l)
        rels = []
        for i, l in enumerate(uniq):
            try:
                d = json.loads(get(l))
                r = d.get("releases", [])
                rels.extend(r)
                total += len(r)
            except Exception as e:
                print(f"  {l.rsplit('/',1)[-1]}: {e}")
            if (i+1) % 2000 == 0:
                print(f"  2026-{mes}: {i+1}/{len(uniq)} releases...", flush=True)
        pkg = {"uri": f"{BASE}/rss/2026/{mes}", "version": "1.1",
               "publisher": {"name": "Agencia Reguladora de Compras Estatales"},
               "license": "https://www.gub.uy/agencia-reguladora-compras-estatales",
               "publishedDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "releases": rels}
        with open(destino, "w", encoding="utf8") as f:
            json.dump(pkg, f, ensure_ascii=False)
        print(f"2026-{mes}: {len(uniq)} releases → {len(rels)} guardados, {os.path.getsize(destino)//1024//1024} MB | {time.time()-t0:.0f}s", flush=True)
    print(f"TOTAL releases nuevos: {total}")

if __name__ == "__main__":
    main()
