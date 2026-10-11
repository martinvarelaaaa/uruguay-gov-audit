"""Retry de los items CKAN que fallaron: 3 intentos x (verify TLS on/off), timeout 300s.
Descarta 4xx definitivos tras agotar; registra todo en el ledger."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))
import httpx
from ledger import record_start, record_finish, start_run, finish_run, sha256_file

OUT = os.path.join(os.path.dirname(__file__), "..", "data")
META_DIR = os.path.join(OUT, "metadata", "ckan")
DL_DIR = os.path.join(OUT, "ckan", "files")

def resource_map():
    m = {}
    for pm in os.listdir(META_DIR):
        if not pm.endswith('.json'):
            continue
        try:
            p = json.load(open(os.path.join(META_DIR, pm), encoding='utf-8'))
        except Exception:
            continue
        name = p.get('name') or p.get('id')
        m[name] = {r.get('id', f"r{i}"): ((r.get('url') or ''), (r.get('format') or '').upper())
                   for i, r in enumerate(p.get('resources', []))}
    return m

def download_item(eid, url, fname):
    """1 intento HTTP con fallback verify=False. Devuelve 'ok'|'http'|'net'."""
    try:
        for verify in (True, False):
            try:
                with httpx.stream("GET", url, timeout=300, follow_redirects=True, verify=verify,
                                  headers={"User-Agent": "uruguay-gov-audit/0.1"}) as r:
                    r.raise_for_status()
                    os.makedirs(os.path.dirname(fname), exist_ok=True)
                    tmp = fname + ".part"
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                    os.replace(tmp, fname)
                return 'ok'
            except httpx.HTTPStatusError:
                if verify:
                    continue
                return 'http'
            except Exception:
                if verify:
                    continue
                return 'net'
    finally:
        pass
    return 'net'

def run(run_id='ckan-retry'):
    ids = json.load(open(os.path.join(OUT, 'metadata', 'ckan_retry_ids.json'), encoding='utf-8'))
    rm = resource_map()
    start_run(run_id, 'ckan', mode='retry')
    ok = fail = 0
    for item_id in ids:
        pkg, rid = item_id.split('/', 1)
        url, fmt = rm.get(pkg, {}).get(rid, ('', ''))
        fname = os.path.join(DL_DIR, pkg[:80], f"{rid}.{fmt.lower() or 'bin'}")
        if os.path.exists(fname) and os.path.getsize(fname) > 0:
            eid = record_start(run_id, 'ckan', item_id, item_url=url, meta={'dataset': pkg})
            record_finish(eid, 'skipped', file_path=fname, bytes_=os.path.getsize(fname))
            continue
        if not url:
            eid = record_start(run_id, 'ckan', item_id, item_url='', meta={'dataset': pkg})
            record_finish(eid, 'error', error='no metadata/resources for this item')
            fail += 1
            continue
        result = None
        for attempt in range(3):
            eid = record_start(run_id, 'ckan', item_id, item_url=url,
                               meta={'dataset': pkg, 'format': fmt, 'attempt': attempt})
            try:
                result = download_item(eid, url, fname)
            except Exception as e:
                result = 'net'
            if result == 'ok':
                record_finish(eid, "ok", bytes_=os.path.getsize(fname),
                              file_path=os.path.relpath(fname, os.path.dirname(OUT)), sha256=sha256_file(fname))
                ok += 1
                break
            elif result == 'http':
                record_finish(eid, "error", error="HTTP final (no recuperable)")
                fail += 1
                break
            # net: reintentar
            time.sleep(5)
        if result in ('ok', 'http'):
            pass
        elif result is not None:
            record_finish(eid, "error", error="agotados 3 intentos (verify on/off)")
            fail += 1
        time.sleep(1)
    finish_run(run_id, status="ok" if fail == 0 else "partial")
    print(json.dumps({"ok": ok, "fail": fail}, ensure_ascii=False))

if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else 'ckan-retry')
