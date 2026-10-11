"""build_roster.py — genera data/metadata/roster/roster_parlamento.json y data/export/roster_parlamento.csv.

Fuentes de verdad (oficiales, en orden de prioridad):
1. Fichas individuales de legisladores: parlamento.gub.uy/camarasycomisiones/legisladores/<id>
   (scraped por data/metadata/roster/scrape_fichas.py -> fichas_legisladores.json)
2. Asistencias legislatura 50 (CKAN parlamento): data/metadata/roster/asistencias_*.json — para
   nombres de suplentes que no figuran en el índice "Conozca sus Legisladores".
3. Biografías oficiales (PDFs) -> data/pdf/roster_bios/text/*.txt para trayectoria.
4. Handles X: pipeline/roster_handles.py (web_search + verificación de bio en x.com)
   -> data/metadata/roster/handles_stage1.json.

Salida: array de legisladores con schema:
{n, camara, partido, departamento, lista_sector, banca_num, cargo, cargo_previo[],
 bio_resumen, handle_x, handle_tipo, handle_confianza, mail, id_parlamento, legislaturas[], fuentes[]}

Los archivos rosters y CSV son data ligera commiteada al repo.
"""
import json, os, re, csv, sys, html, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WK = os.path.join(ROOT, 'data', 'metadata', 'roster')
OUT_JSON = os.path.join(WK, 'roster_parlamento.json')
OUT_CSV = os.path.join(ROOT, 'data', 'export', 'roster_parlamento.csv')
FECHA = '2026-10-10'

def load_json(p):
    return json.load(open(p, encoding='utf-8'))

def cargo_previo_from_legislaturas(legs):
    out = []
    for lg in legs[1:]:
        s = re.sub(r'\s+', ' ', lg or '').strip()
        if s:
            out.append(s)
    return out

BIOPATS = [
    r'(?i)(\b(?:19|20)\d{2}\b[^.\n]{0,110}?(intendente|intendenta|ministr[oa]|subsecretari[oa]|viceministr[oa]|director(?:a)?|presidente(?:a)?|rector(?:a)?|interventor(?:a)?|diputad[oa]|senador(?:a)?|embajador(?:a)?|secretari[oa]|vedelago|cargo)[^.\n]{0,110})',
    r'(?i)(\bdiputad[oa] (?:nacional )?por [^.\n]{0,90})',
    r'(?i)(electo (?:intendente|intendenta) de [^.\n]{0,70})',
]

def extract_cargos_bio(txt, maxn=8):
    res, seen = [], set()
    for p in BIOPATS:
        for m in re.finditer(p, txt):
            s = re.sub(r'\s+', ' ', m.group(1)).strip()
            k = s.lower()[:60]
            if k not in seen:
                seen.add(k)
                res.append(s[:200])
            if len(res) >= maxn:
                return res
    return res

def main():
    fichas = load_json(os.path.join(WK, 'fichas_legisladores.json'))
    handles = load_json(os.path.join(WK, 'handles_stage1.json'))
    sector_names = load_json(os.path.join(WK, 'sector_by_name.json')) if os.path.exists(os.path.join(WK, 'sector_by_name.json')) else {}
    bio_dir = os.path.join(ROOT, 'data', 'pdf', 'roster_bios', 'text')
    roster = []
    for x in fichas:
        hnd = handles.get(x['nombre'], {}) or {}
        estado = hnd.get('estado', 'no_encontrado')
        biotxt = ''
        bp = os.path.join(bio_dir, f"{x['id']}.txt")
        if x['bio_pdf'] and os.path.exists(bp):
            biotxt = open(bp, encoding='utf-8').read()
        legs = [re.sub(r'\s+', ' ', l).strip() for l in x['legislaturas']]
        cargo_previo = extract_cargos_bio(biotxt) if biotxt else cargo_previo_from_legislaturas(legs)
        cam = 'senadores' if x['descripcion'].lower().startswith(('senador', 'presidenta')) else 'representantes'
        dep = re.search(r'departamento de ([A-ZÁÉÍÓÚÑa-záéíóúñ ]+?)(?:\s*$|,|$)', x['descripcion'], flags=re.I)
        dep = dep.group(1).strip().title() if dep else ''
        lista = sector_names.get(x['nombre'], '')
        conf = {'verificado': 'verified', 'probable': 'probable'}.get(estado, 'sin_cuenta')
        fuentes = [{'url': f'https://parlamento.gub.uy/camarasycomisiones/legisladores/{x["id"]}', 'fecha': FECHA}, {'url': 'https://parlamento.gub.uy/sobreelparlamento/legisladores', 'fecha': FECHA}]
        if conf != 'sin_cuenta' and hnd.get('handle'):
            fuentes.append({'url': f'https://x.com/{hnd["handle"]}', 'fecha': FECHA})
        if x['bio_pdf']:
            fuentes.append({'url': 'https://parlamento.gub.uy' + x['bio_pdf'][0], 'fecha': FECHA})
        roster.append({
            'nombre': re.sub(r'\s+', ' ', x['nombre']).strip(),
            'camara': cam,
            'partido': x['lema'] or '',
            'departamento': dep,
            'lista_sector': lista,
            'banca_num': None,
            'cargo': x['descripcion'],
            'cargo_previo': cargo_previo,
            'bio_resumen': (re.sub(r'\s+', ' ', biotxt[:400]).strip() + '...') if biotxt else '',
            'handle_x': (hnd.get('handle') or '') if conf != 'sin_cuenta' else '',
            'handle_tipo': (hnd.get('tipo') or 'personal') if conf != 'sin_cuenta' else '',
            'handle_confianza': conf,
            'mail': (x['mails'][0] if x['mails'] else ''),
            'id_parlamento': x['id'],
            'legislaturas': legs,
            'fuentes': fuentes,
        })
    roster.sort(key=lambda r: (r['camara'] != 'senadores', r['nombre']))
    os.makedirs(WK, exist_ok=True)
    json.dump(roster, open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # CSV
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    cols = ['nombre', 'camara', 'partido', 'departamento', 'lista_sector', 'banca_num', 'cargo',
            'cargo_previo', 'bio_resumen', 'handle_x', 'handle_tipo', 'handle_confianza', 'mail',
            'id_parlamento', 'fuentes']
    with open(OUT_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in roster:
            row = dict(r)
            row['cargo_previo'] = ' | '.join(r['cargo_previo'])
            row['fuentes'] = ' | '.join(x['url'] for x in r['fuentes'])
            w.writerow(row)
    # resumen
    c = collections.Counter(r['camara'] for r in roster)
    h = collections.Counter(r['handle_confianza'] for r in roster)
    resumen = {'total': len(roster), 'camaras': dict(c), 'handles': dict(h),
               'json': OUT_JSON, 'csv': OUT_CSV}
    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    return roster

if __name__ == '__main__':
    main()
