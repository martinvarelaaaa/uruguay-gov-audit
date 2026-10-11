"""Búsqueda de handles X por patrones de nombre usando web_extract (resumible)."""
import json, re, time, unicodedata, os
from hermes_tools import web_extract

WK = r'C:/Users/marti/uruguay-gov-audit/data/metadata/roster'
OUT = os.path.join(WK, 'guess_found_1.json')
polit_pat = re.compile(r'(?i)(diputad|senador|intendenc|pol[ií]ti|candidat|lista ?\d|frente amplio|partido nacional|partido colorado|cabildo|asamblea|cámara camara|parlamento|ministr|uruguay)')

def normh(s):
    s = ''.join(ch for ch in unicodedata.normalize('NFD', s) if unicodedata.category(ch) != 'Mn')
    return re.sub(r'[^A-Za-z0-9]', '', s)

def main():
    guesses = json.load(open(os.path.join(WK, 'handle_guesses.json'), encoding='utf-8'))
    roster = json.load(open(os.path.join(WK, 'roster_draft.json'), encoding='utf-8'))
    done = json.load(open(os.path.join(WK, 'handles_stage1.json'), encoding='utf-8'))
    found = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    tried = set()
    tj_path = os.path.join(WK, 'guess_tried.json')
    if os.path.exists(tj_path):
        tried = set(json.load(open(tj_path, encoding='utf-8')))
    for key, gs in list(guesses.items()):
        if key in tried or done.get(key, {}).get('estado') == 'verificado' or key in found:
            continue
        url_list = [f'https://x.com/{g}' for g in gs[:2] if len(g) > 5]
        tried.add(key)
        for i in range(0, len(url_list), 5):
            chunk = url_list[i:i + 5]
            try:
                r = web_extract(chunk, char_limit=900)
            except Exception:
                continue
            for u, res in zip(chunk, r['results']):
                c = res.get('content') or ''
                h = u.rsplit('/', 1)[1]
                if polit_pat.search(c) and not c.startswith('# @unknown'):
                    found[key] = {'handle': h, 'bio': c[:400], 'fecha': '2026-10-10'}
                    print('FOUND', key, '->', h, flush=True)
            time.sleep(0.4)
        json.dump(sorted(tried), open(tj_path, 'w', encoding='utf-8'))
        if len(found) >= 45:
            break
    json.dump(found, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('tried:', len(tried), 'found:', len(found))

if __name__ == '__main__':
    main()
