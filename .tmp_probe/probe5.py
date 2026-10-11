"""Probe 5: salto licitaciones page content (how are docs listed?), salto estructura/autoridades names."""
import time, httpx, re
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "uruguay-gov-audit/0.1 (auditoria ciudadana; open source)"}
client = httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS, max_redirects=15)

# salto licitaciones: print main content region text + anchors with .pdf/.xlsx
r = client.get("https://www.salto.gub.uy/licitaciones")
soup = BeautifulSoup(r.text, "html.parser")
main = soup.find("main") or soup.find("div", class_=re.compile("content|region|main"))
if main:
    txt = main.get_text("\n", strip=True)
    print("=== salto licitaciones main text (first 1500) ===")
    print(txt[:1500])
pdfs = [a["href"] for a in soup.find_all("a", href=True) if re.search(r"\.(pdf|xlsx|xls|csv)", a["href"], re.I)]
print("pdf links:", pdfs[:10])
time.sleep(3)

# salto autoridades: names present?
r = client.get("https://www.salto.gub.uy/estructura")
soup = BeautifulSoup(r.text, "html.parser")
main = soup.find("main") or soup
txt = main.get_text("\n", strip=True)
print("=== salto estructura text (first 1200) ===")
print(txt[:1200])
