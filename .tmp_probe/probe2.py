"""Probe variants for cerro-largo & lavalleja + robots.txt for all domains."""
import time, httpx

HEADERS = {"User-Agent": "uruguay-gov-audit/0.1 (auditoria ciudadana; open source)"}
client = httpx.Client(timeout=25, follow_redirects=True, headers=HEADERS)

VARIANTS = {
    "cerro-largo": ["https://www.cerrolargo.gub.uy/", "http://www.cerrolargo.gub.uy/", "https://cerrolargo.gub.uy/", "https://www.imc.lg.gub.uy/", "https://www.cerrolargo.uy"],
    "lavalleja": ["https://lavalleja.gub.uy/", "http://www.lavalleja.gub.uy/", "https://www.lavalleja.guy", "http://lavalleja.gub.uy/"],
}
for name, urls in VARIANTS.items():
    for u in urls:
        try:
            r = client.get(u)
            print(name, u, "->", r.status_code, str(r.url)[:80], len(r.content))
            break
        except Exception as e:
            print(name, u, "-> ERR", type(e).__name__)
        time.sleep(2.5)

ROBOTS = ["https://artigas.gub.uy/robots.txt","https://www.cerrolargo.gub.uy/robots.txt","https://www.colonia.gub.uy/robots.txt",
          "https://www.flores.gub.uy/robots.txt","https://www.lavalleja.gub.uy/robots.txt","https://www.maldonado.gub.uy/robots.txt",
          "https://www.paysandu.gub.uy/robots.txt","https://www.rionegro.gub.uy/robots.txt","https://www.rivera.gub.uy/robots.txt",
          "https://www.salto.gub.uy/robots.txt","https://www.soriano.gub.uy/robots.txt","https://www.tacuarembo.gub.uy/robots.txt",
          "https://www.treintaytres.gub.uy/robots.txt"]
for u in ROBOTS:
    try:
        r = client.get(u)
        body = r.text[:400].replace("\n", " | ")
        print("ROBOTS", u.split("/")[2], r.status_code, body[:300])
    except Exception as e:
        print("ROBOTS", u.split("/")[2], "ERR", type(e).__name__)
    time.sleep(2.5)
