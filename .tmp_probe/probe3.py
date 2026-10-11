"""Probe 3: colonia robots full-ban check on homepage path; lavalleja http works (232B page, likely
JS or tiny page) — inspect; salto section pages and their PDF links."""
import time, httpx, json
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {"User-Agent": "uruguay-gov-audit/0.1 (auditoria ciudadana; open source)"}
client = httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS, max_redirects=10)

# 1) colonia: robots says Disallow / for * — check whether it really serves homepage (we got 200 before)
r = client.get("https://www.colonia.gub.uy")
print("colonia robots-full-ban but homepage:", r.status_code, len(r.content))

time.sleep(3)
# 2) lavalleja http content
r = client.get("http://www.lavalleja.gub.uy/", headers=HEADERS)
print("lavalleja len:", len(r.content), r.status_code, r.headers.get("content-type"))
print(r.text[:800])
time.sleep(3)

# 3) salto: hit the 4 section pages and dig PDFs
pdflinks = {}
for path in ["autoridades", "rendicion-de-cuentas", "licitaciones", "presupuesto-quinquenal"]:
    u = f"https://www.salto.gub.uy/{path}"
    try:
        r = client.get(u)
        print("SALTO", path, r.status_code, len(r.content))
        soup = BeautifulSoup(r.text, "html.parser")
        offs = []
        for k, v in [(a.get("data-href"), a.get("data-kind")) for a in soup.find_all("a", attrs={"data-href": True})]:
            print("  dump:", v, str(k)[:120])
            offs.append((v, str(k)[:160]))
        if not offs:
            print("  no data-href; links:")
            for a in soup.find_all("a", href=True)[:15]:
                print("   ", a.get_text(" ", strip=True)[:40], "->", str(urljoin(str(r.url), a["href"]))[:120])
        pdflinks[path] = r.status_code
    except Exception as e:
        print("SALTO", path, "ERR", type(e).__name__, str(e)[:100])
    time.sleep(3.5)
