""" Probe 4: find salto dump-link element tag/type; lavalleja on gub.uy; gabinete structure of 2 sites. """
import time, httpx, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "uruguay-gov-audit/0.1 (auditoria ciudadana; open source)"}
client = httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS, max_redirects=15)

# a) salto: find tags carrying data-href
r = client.get("https://www.salto.gub.uy/licitaciones")
soup = BeautifulSoup(r.text, "html.parser")
n = 0
for el in soup.find_all(attrs={"data-href": True}):
    n += 1
    if n <= 6:
        print("SALTO tag:", el.name, "| kind:", el.get("data-kind"), "| title:", (el.get_text(" ", strip=True) or "")[:70])
        print("     href:", el["data-href"][:150])
print("total data-href:", n)
time.sleep(3)

# b) lavalleja via gub.uy subsite
r = client.get("https://www.gub.uy/intendencia-lavalleja/")
print("GUBUY lavalleja:", r.status_code, str(r.url)[:80], len(r.content))
soup = BeautifulSoup(r.text, "html.parser")
print("  title:", soup.title.get_text(strip=True) if soup.title else "")
for a in soup.find_all("a", href=True):
    t = a.get_text(" ", strip=True).lower()
    h = a["href"].lower()
    if any(k in h or k in t for k in ("rendic", "presupuesto", "compra", "licitac", "autoridad", "transparenc")):
        print("  L:", t[:50], "->", a["href"][:120])
time.sleep(3)

# c) gabinete: colonia (search autoridades/gabinete page) + rionegro page
for name, u in [("salto-estructura", "https://www.salto.gub.uy/estructura"),
                ("rionegro-gabinete", "https://www.rionegro.gub.uy/gabinete-2025-2030/secretario-general/")]:
    r = client.get(u)
    print(name, r.status_code, len(r.content))
