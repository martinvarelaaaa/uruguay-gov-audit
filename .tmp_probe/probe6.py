"""Probe 6: PDF download works from salto + colonia; check response headers."""
import time, httpx

HEADERS = {"User-Agent": "uruguay-gov-audit/0.1 (auditoria ciudadana; open source)"}
client = httpx.Client(timeout=60, follow_redirects=True, headers=HEADERS)

TESTS = [
    ("salto-doc", "https://www.salto.gub.uy/sites/default/files/2026-09/313112026-la-compra-de-camion-cn-caja-volcadora-msa.pdf"),
]
for name, u in TESTS:
    r = client.get(u)
    print(name, r.status_code, len(r.content), r.headers.get("content-type"), str(r.url)[:90])
    time.sleep(3)
