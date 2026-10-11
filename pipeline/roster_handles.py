"""Roster handles stage 1: caza de handles X de legisladores vía web_search + verificación bio con web_extract.

Estrategia: web_search "<nombre> <contexto> twitter" (1 query por persona),
el primer resultado x.com con nombre de perfil compatible -> verified=True.
Luego verificación con web_extract de x.com/<handle> extrae la bio y followers.
Budget: búsqueda 1 por persona; se reanuda desde un JSONL de salida. Max 20 búsquedas web_search.
"""
import json, os, time, re, unicodedata, sys
from hermes_tools import web_search, web_extract

WK = r'C:/Users/marti/uruguay-gov-audit/data/metadata/roster'
out_path = os.path.join(WK, 'handles_stage1.json')
roster_path = os.path.join(WK, 'roster_draft.json')

def slug(s, lower=True, keep_space=False):
    n = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return n

def normalize_name(n):
    n = re.sub(r'\s+', ' ', n).strip().lower()
    n = ''.join(c for c in unicodedata.normalize('NFD', n) if unicodedata.category(c) != 'Mn').lower()
    n = n.replace('.', '').replace(',', ' ').replace("(", " ").replace(")", " ")
    return ' '.join(n.split())

def load():
    if os.path.exists(out_path):
        return json.load(open(out_path, encoding='utf-8'))
    return {}

def save(d):
    json.dump(d, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

def name_tokens(n):
    return set(normalize_name(n).split())

def bio_matches(name_tokens, bio, lema_key=None):
    """Un handle 'encaja' si la bio o el displayName contienen >=2 tokens del nombre (o apellido completo)."""
    if not bio: return 0
    b = normalize_name(bio)
    tok = name_tokens
    hits = sum(1 for t in tok if len(t) > 3 and t in b)
    ap = [t for t in tok if len(t) > 4]
    if any(a in b for a in ap):
        return max(hits, 2)
    return hits

def search_handle(nombre, camara, partido, limit=4):
    # query: el nombre más contexto uruguayo
    parts = nombre.split(', ')
    if len(parts) == 2:
        display = f'{parts[1]} {parts[0]}'
    else:
        display = nombre.replace(',', ' ')
    q = f'"{display}" twitter Uruguay {"senador" if camara=="senadores" else "diputado"}'
    try:
        r = web_search(q, limit=limit)
    except Exception as e:
        return {'error': str(e)[:120]}
    for w in r.get('data', {}).get('web', []):
        u = w['url'] or ''
        m = re.match(r'https?://(?:www\.)?x\.com/([A-Za-z0-9_]{1,20})$', u)
        if not m:
            m = re.match(r'https?://(?:www\.)?x\.com/([A-Za-z0-9_]{1,20})(?:\?|/status|/?$)', u)
        if m:
            handle = m.group(1)
            if handle.lower() in ('home', 'i', 'hashtag', 'search', 'intent'):
                continue
            return {'handle': handle, 'titulo': w.get('title', ''), 'desc': w.get('description', ''), 'url': u}
    return {'handle': None, 'datos': [{'url': w.get('url'), 'title': w.get('title', '')} for w in r.get('data', {}).get('web', [])][:4]}

def main():
    done = load()
    roster = json.load(open(roster_path, encoding='utf-8'))
    queries_left = 20
    for x in roster:
        key = x['nombre']
        if key in done and done[key].get('estado') in ('verificado', 'no_encontrado'):
            continue
        if done.get(key, {}).get('handle') and done[key].get('estado') != 'verificado':
            # teentativa previa sin verificar: retomar
            pass
        if queries_left <= 0:
            break
        queries_left -= 1
        res = search_handle(x['nombre'], x['camara'], x['partido'])
        entry = {'consulta': res.get('datos') or res, 'fecha': '2026-10-10'}
        if res.get('handle'):
            u = f'https://x.com/{res["handle"]}'
            try:
                ex = web_extract([u], char_limit=2500)
                bio = ex['results'][0].get('content', '')[:600]
                entry['handle'] = res['handle']
                entry['bio'] = bio
                tok = name_tokens(x['nombre'])
                entry['match'] = bio_matches(tok, bio)
                entry['estado'] = 'verificado' if entry['match'] > 0 else 'no_coincide'
            except Exception as e:
                entry['handle'] = res['handle']
                entry['bio'] = ''
                entry['estado'] = 'sin_extracto'
                entry['err'] = str(e)[:120]
        else:
            entry['estado'] = 'no_encontrado'
            entry['handle'] = None
        done[key] = entry
        print(key, '->', entry.get('estado'), entry.get('handle'), flush=True)
        save(done)
        time.sleep(0.4)
    print('fichas done. queries_left:', queries_left)
    save(done)

if __name__ == '__main__':
    main()
