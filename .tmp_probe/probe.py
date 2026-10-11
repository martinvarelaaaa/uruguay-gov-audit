"""Probe: fetch homepage of each intendencia domain, list nav links matching doc keywords.
Temporary exploration script — not part of the module.
"""
import json, time, re, httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

DOMAINS = {
    "artigas": "https://artigas.gub.uy",
    "cerro-largo": "https://www.cerrolargo.gub.uy",
    "colonia": "https://www.colonia.gub.uy",
    "flores": "https://www.flores.gub.uy",
    "lavalleja": "https://www.lavalleja.gub.uy",
    "maldonado": "https://www.maldonado.gub.uy",
    "paysandu": "https://www.paysandu.gub.uy",
    "rionegro": "https://www.rionegro.gub.uy",
    "rivera": "https://www.rivera.gub.uy",
    "salto": "https://www.salto.gub.uy",
    "soriano": "https://www.soriano.gub.uy",
    "tacuarembo": "https://www.tacuarembo.gub.uy",
    "treinta-y-tres": "https://www.treintaytres.gub.uy",
}

KEYWORDS = ["presupuesto", "rendicion", "rendición", "contaduria", "contaduría",
            "compras", "contratacion", "contrataciones", "licitacion", "licitaciones",
            "autoridades", "gabinete", "intendente", "secretario", "director-general",
            "transparencia", "documents", "gestion-documental", "ordenanz"]

HEADERS = {"User-Agent": "uruguay-gov-audit/0.1 (auditoria ciudadana; open source)"}

out = {}
client = httpx.Client(timeout=30, follow_redirects=True, headers=HEADERS)
for name, base in DOMAINS.items():
    info = {"base": str(client.build_request("GET", base).url)}
    try:
        r = client.get(base)
        info["status"] = r.status_code
        info["final_url"] = str(r.url)
        soup = BeautifulSoup(r.text, "html.parser")
        info["title"] = (soup.title.get_text(strip=True) if soup.title else "")
        links = []
        seen = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True).lower()
            low = href.lower()
            if any(k in low or k in text for k in KEYWORDS):
                full = urljoin(info["final_url"], href)
                if full not in seen and urlparse(full).path not in ("", "/") or any(k in low for k in (".pdf", ".xlsx", ".xls", ".csv")):
                    seen.add(full)
                    links.append({"t": text[:60], "u": full[:160]})
        info["links"] = links[:40]
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    out[name] = info
    print(name, info.get("status"), "->", len(info.get("links", [])), "links", info.get("error", ""))
    time.sleep(2.5)

with open("C:/Users/marti/uruguay-gov-audit/.tmp_probe/probe_home.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("saved")
