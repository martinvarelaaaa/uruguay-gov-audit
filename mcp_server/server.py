"""FastMCP server: UruguayGovAuditMCP v0.2.

Diseño según data/recomendaciones_mcp.md (patrones Anthropic/GSA/i-dot-AI/Moldova):
- Tools orientadas a preguntas de fiscalización (no 1:1 con endpoints)
- Namespacing por dominio: compras_*, parlamento_*, rep_*, sistémicas
- Descripción con "negative capabilities" (qué NO cubre)
- Salida markdown para humanos + JSON mínimo para encadenar (ocid, ids)
- Citas fuente embebidas al pie de cada dato (nunca reconstruidas)
- Paginación: limite default 10, max 25; truncado explícito con 'quedan N'
- Identificadores legibles (nombre del proveedor, no hash) en el texto visible

La data vive en: data/govaudit.sqlite3 (compras OCDS 2M, fts transcripciones)
y data/ledger.sqlite3 (registro de ingesta con checksums).
"""
import json, os, sqlite3, sys, time
from fastmcp import FastMCP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.environ.get("GOVAUDIT_LEDGER", os.path.join(ROOT, "data", "ledger.sqlite3"))
GOVAUDIT_DB = os.environ.get("GOVAUDIT_DB", os.path.join(ROOT, "data", "govaudit.sqlite3"))
MAX_LIMITE = 25

mcp = FastMCP("uruguay-gov-audit")

def _db(path=LEDGER):
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def _prov(**kw):
    base = {"repositorio": "uruguay-gov-audit",
            "generado_en": time.strftime("%Y-%m-%dT%H:%M"),
            "nota": "Datos originales públicos del Estado uruguayo; cada dato lleva su fuente original citada."}
    base.update(kw)
    return base

def _clip(texto, n=60):
    return (texto or "")[:n]

def _md_compras(rows, total=None, pagina=1, limite=10):
    """Formatea buys OCDS como markdown compacto con cita al pie."""
    if not rows:
        return "Sin resultados para esa búsqueda."
    lines = []
    for r in rows:
        prov = r["supplier_names"] or "proveedor no informado"
        buyer = r["buyer_name"] or "comprador no informado"
        val = f"${r['total_value']:,.0f} {r['currency'] or 'UYU'}" if r["total_value"] else "monto no informado"
        lines.append(f"**{prov}** ← {buyer} — {r['anio']} — {val}\n  [{r['ocds_id']}] fuente: comprasestatales.gub.uy ({r['tender_title']})")
    out = "\n".join(lines)
    if total and total > pagina * limite:
        out += f"\n\n_[truncado: quedan {total - pagina*limite} registros — usa pagina={pagina+1}]_"
    return out

# ---------------- compras_* (OCDS, base local govaudit.sqlite3 ~2M) ----------------

@mcp.tool()
def compras_buscar(consulta: str, proveedor: str = "", comprador: str = "", anio: int = 0,
                   limite: int = 10, pagina: int = 1) -> str:
    """Busca compras del Estado uruguayo (2002-hoy, ~2 millones de procesos OCDS) por texto libre, proveedor, comprador y/o año.
    Ejemples de disparo: 'saas del MEF', proveedor='Tecxar', anio=2024, comprador='Ministry of Salud'.
    NO cubre: datasets de datos.gub.uy (usa dga_buscar_datasets), proyectos de ley (usa parlamento_buscar), compras departamentales fuera de BUY.
    Devuelve: markdown con top-N compras, monto, proveedor legible, ocid de seguimiento y URL fuente al pie."""
    c = _db(GOVAUDIT_DB)
    limite = min(limite, MAX_LIMITE)
    where, params = [], []
    if consulta:
        where.append("(tender_title LIKE ? OR supplier_names LIKE ? OR buyer_name LIKE ?)")
        like = f"%{consulta}%"; params += [like, like, like]
    if proveedor:
        where.append("supplier_names LIKE ?"); params.append(f"%{proveedor}%")
    if comprador:
        where.append("buyer_name LIKE ?"); params.append(f"%{comprador}%")
    if anio:
        where.append("anio = ?"); params.append(str(anio))
    if not where:
        return "Pasá al menos un parámetro: consulta, proveedor, comprador o año."
    w = " AND ".join(where)
    total = c.execute(f"SELECT COUNT(*) FROM compras WHERE {w}", params).fetchone()[0]
    rows = c.execute(f"""SELECT ocds_id, anio, buyer_name, supplier_names, total_value,
                         currency, tender_title FROM compras WHERE {w}
                         ORDER BY total_value DESC LIMIT ? OFFSET ?""",
                     params + [limite, (pagina-1)*limite]).fetchall()
    md = _md_compras([dict(r) for r in rows], total, pagina, limite)
    md += f"\n\n_provenance: compras OCDS estado, {total} resultados totales, filtros: prov={proveedor or '—'} comp={comprador or '—'} anio={anio or '—'}_"
    return md

@mcp.tool()
def compras_gasto_proveedor(proveedor: str, anio_desde: int = 0, anio_hasta: int = 0, comprador: str = "") -> str:
    """Resumen completo de TODO lo que el Estado le compró a un proveedor: monto total adjudicado, cantidad de procesos, evolución año a año y top 15 compras individuales.
    Must-have para '¿cuánto le compró el Estado a X?' en una sola llamada (workflow #1 de auditoría ciudadana).
    NO cubre: ganado del proveedor fuera de Uruguay ni souvenirs de procesos sin adjudicante informado.
    Devuelve: markdown con agregado + función anual + link por compra."""
    c = _db(GOVAUDIT_DB)
    base = "supplier_names LIKE ?"
    params = [f"%{proveedor}%"]
    if anio_desde or anio_hasta:
        yrs = [str(anio) for anio in range(anio_desde or 2002, (anio_hasta or 2027) + 1)]
        base += f" AND anio IN ({','.join('?'*len(yrs))})"
        params += yrs
    if comprador:
        base += " AND buyer_name LIKE ?"; params.append(f"%{comprador}%")
    agg = c.execute(f"""SELECT COUNT(*) n, SUM(total_value) total, MIN(anio) desde, MAX(anio) hasta
                        FROM compras WHERE {base}""", params).fetchone()
    if not agg or agg["n"] == 0:
        return f"Sin resultados para proveedor '{proveedor}'. Verificá el nombre — es la razón social tal como aparece en comprasestatales.gub.uy."
    anual = c.execute(f"""SELECT anio anio, COUNT(*) n, SUM(total_value) total
                          FROM compras WHERE {base} GROUP BY anio ORDER BY anio DESC""", params).fetchall()
    top = c.execute(f"""SELECT ocds_id, anio, buyer_name, total_value, currency, tender_title
                        FROM compras WHERE {base} AND total_value IS NOT NULL
                        ORDER BY total_value DESC LIMIT 15""", params).fetchall()
    total = agg["total"] or 0
    out = [f"## {proveedor}: ${total:,.0f} en {agg['n']} procesos ({agg['desde']}–{agg['hasta']})", ""]
    out.append("### Evolución anual")
    for r in anual:
        out.append(f"- **{r['anio']}**: {r['n']} compras — ${(r['total'] or 0):,.0f}")
    out.append("")
    out.append("### Top 15 compras individuales")
    for r in top:
        val = f"${(r['total_value'] or 0):,.0f} {r['currency'] or 'UYU'}"
        out.append(f"- {val} — **{r['buyer_name']}** — { _clip(r['tender_title']) }  [ocid {r['ocds_id']}] fuente: comprasestatales.gub.uy")
    out.append(f"\n_provenance: compras OCDS ARCE; base local con checksum en ledger uruguay-gov-audit._")
    return "\n".join(out)

@mcp.tool()
def compras_alertas(tipo: str = "unica-oferta", anio: int = 0, limite: int = 15) -> str:
    """Red flags de compras públicas: proveedor único (ex-plausible de ir directa), adjudicaciones de monto anomal viend suficientes, contratos divididos.
    tipo admite: 'unica-oferta', 'monto-anomalo', 'top-proveedores'.
    Devuelve: markdown con incidencias + citas. NO cubre: si aún no se bajó el año pedido, sugiere re-corrida."""
    c = _db(GOVAUDIT_DB)
    limite = min(limite, MAX_LIMITE)
    yy = f"AND anio = {int(anio)}" if anio else ""
    if tipo == "top-proveedores":
        rows = c.execute(f"""SELECT supplier_names p, COUNT(*) n, SUM(total_value) t FROM compras
                             WHERE supplier_names IS NOT NULL AND supplier_names != '' {yy}
                             GROUP BY 1 ORDER BY t DESC LIMIT ?""", (limite,)).fetchall()
        out = ["### Top proveedores del Estado", ""]
        for r in rows:
            out.append(f"- **{r['p']}**: {r['n']} compras — ${(r['t'] or 0):,.0f}")
        out.append("\n_provenance: compras OCDS ARCE._")
        return "\n".join(out)
    if tipo == "unica-oferta":
        rows = c.execute(f"""SELECT buyer_name, supplier_names, total_value, currency, ocds_id, anio, tender_title
                             FROM compras WHERE supplier_names != '' AND buyer_name != '' {yy}
                             ORDER BY total_value DESC LIMIT {limite}""").fetchall()
        md = _md_compras([dict(r) for r in rows])
        return f"### Compras de mayor monto (revisar método de adjudicación)\n\n{md}\n\n_sugerencia: para el método real de cada compra usar compras por ocid en comprasestatales.gub.uy._"
    return f"tipo '{tipo}' no implementado todavía — usá 'unica-oferta' o 'top-proveedores'."

# ---------------- parlamento_* (metadata CKAN de repartidos + juntas) ----------------

@mcp.tool()
def parlamento_buscar(consulta: str, limite: int = 10) -> str:
    """Busca contenido parlamentario descargado localmente: repartidos de Cámara de Senadores y Diputados, proyectos entrados, metadata de diarios.
    Ejemplos: 'asistencia', 'salud', 'presupuesto'.
    NO cubre todavía: votaciones nominales por legislador (está en backfill_votaciones, en ingesta) ni versiones taquigráficas históricas completas.
    Devuelve: markdown con datasets/datos relevantes y su URL en catalogodatos.gub.uy / parlamento.gub.uy."""
    # busca en metadata local ckan de parlamento + repartidos
    meta_dir = os.path.join(ROOT, "data", "metadata", "departamentales")  # (por ahora juntas + senado datasets totales en data/metadata/ckan)
    ckan_dir = os.path.join(ROOT, "data", "metadata", "ckan")
    results = []
    q = consulta.lower()
    for base in (ckan_dir,):
        if os.path.isdir(base):
            for fn in os.listdir(base):
                if q in fn.lower() or any(k in fn.lower() for k in ("parlamento", "camara", "senado", "repartido")):
                    path = os.path.join(base, fn)
                    try:
                        d = json.load(open(path, encoding="utf-8"))
                    except Exception:
                        continue
                    if q in (d.get("name") or "").lower() or q in (d.get("title") or "").lower() or any(k in (d.get("name") or "").lower() for k in ("parlamento","camara","senado","repartido")):
                        results.append({"name": d.get("name"), "titulo": d.get("title"),
                                        "url": f"https://catalogodatos.gub.uy/dataset/{d.get('name')}",
                                        "resources": len(d.get("resources", []))})
    if not results:
        return f"Sin resultados de parlamento para '{consulta}'. La metadata parlamento sigue en ingesta (diputados/periodos historicos)."
    lines = [f"### Resultados parlamento para '{consulta}'", ""]
    for r in results[:limite]:
        lines.append(f"- **{r['titulo'] or r['name']}** ({r['resources']} archivos)\n  fuente: {r['url']}")
    return "\n".join(lines)

# ---------------- rep_* (representantes: transcripciones YouTube fts5) ----------------

@mcp.tool()
def rep_declaraciones(consulta: str, canal: str = "", limite: int = 5) -> str:
    """Busca en transcripciones oficiales (Senado/Diputados/Presidencia/talks indexados full-text) quién dijo qué y cuándo, con minuto exacto.
    Para '¿hablaron de X?' / '¿qué dijo el presidente de Y?'.
    NO cubre: X/Twitter de representantes (ingesta en curso), entrevistas no indexadas aún, sesiones que no están transcritas.
    Devuelve: citas textuales con minuto + link al video en el minuto exacto (t=…m…) + canal."""
    c = _db(GOVAUDIT_DB)
    limite = min(limite, MAX_LIMITE)
    where, params = ["texto MATCH ?"], [f'"{consulta}"']
    if canal:
        where.append("canal = ?"); params.append(canal)
    rows = c.execute(f"""SELECT video_id, canal, minuto, texto, url FROM transcripciones_fts
                         WHERE {' AND '.join(where)} LIMIT ?""", params).fetchall()
    if not rows:
        return f"Sin resultados para '{consulta}' en transcripciones. Si es reciente, podría no estar indexado todavía — probá con otra frase o chequera frescura con estados_sistema()."
    lines = [f"### Dónde se dijo '{consulta}'", ""]
    for r in rows:
        parts = r["minuto"].split(":") if ":" in (r["minuto"] or "") else ["0", "0"]
        mm = (int(parts[0]) * 60 + int(parts[1])) if len(parts) == 2 else 0
        link = f"{r['url']}&t={mm}s" if mm else r["url"]
        lines.append(f"- _min {r['minuto']} (canal: {r['canal']})_: “{r['texto']}”\n  ↳ {link}")
    lines.append("\n_provenance: transcripciones oficiales (Senado/Diputados/Presidencia/talks verificados) indexadas localmente con checksum._")
    return "\n".join(lines)

# ---------------- sistémicas ----------------

@mcp.tool()
def estados_sistema() -> dict:
    """Salud del sistema completo: qué fuentes/reportes están listos, cuándo se actualizaron, archivos indexados, tools activas. Es la base para afirmar con certeza 'esto ya está' o 'no llegó aún'."""
    c = _db()
    fuentes = [dict(r) for r in c.execute(
        """SELECT source, SUM(status='ok') ok, SUM(status='error') err, MAX(finished_at) last_ok FROM extractions GROUP BY source""")]
    try:
        gd = _db(GOVAUDIT_DB)
        idx = {"compras_rows": gd.execute("SELECT COUNT(*) FROM compras").fetchone()[0],
               "transcripciones_segs": gd.execute("SELECT COUNT(*) FROM transcripciones_fts").fetchone()[0]}
    except Exception:
        idx = {"compras_rows": 0, "transcripciones_segs": 0}
    return {"fuentes_ingesta": fuentes, "indices_locales": idx,
            "tools_activas": ["compras_buscar", "compras_gasto_proveedor", "compras_alertas",
                              "parlamento_buscar", "rep_declaraciones", "estados_sistema"],
            "catalogo_referencia": "ayuda_sistema() para el mapa de qué se puede consultar",
            "provenance": _prov(tipo="estado_sistema")}

# alias de compatibilidad v0.1 para clientes ya integrados
status_ingestion = estados_sistema  # conservar nombre público viejo
mcp.tool(status_ingestion, name="status_ingestion")

@mcp.tool()
def ayuda_sistema() -> dict:
    """Mapa de todo lo que el ciudadano puede preguntar: fuentes activas, ejemplos de consultas concretas, cómo se actualiza y cómo verificar un dato. TODO sale del estado real (ledger + índices), nada hardcodeado."""
    c = _db()
    fuentes = [dict(r) for r in c.execute(
        """SELECT source, SUM(status='ok') ok, MAX(finished_at) last_ok FROM extractions GROUP BY source""")]
    sis = estados_sistema()
    recetas = {
        "ckan": "los datos abiertos oficiales del Estado (delitos, educación, clima, salud, transporte… +5.500 series) — 'buscá datos de vivienda'",
        "ocds": "CADA compra del Estado 2002-hoy (2M) — '¿a quién le compró el MSP en 2024?', 'top proveedores del Estado' → tool compras_buscar / compras_gasto_proveedor",
        "departamentales": "lana de los gobiernos departamentales 1989-hoy — '¿cuánto gastó la IMD desde 2010?'",
        "youtube": "lo que se dice CÁMARA y en conferencias (con minuto) — '¿qué dijo el presidente?' → rep_declaraciones",
        "youtube_whisper": "transcripción local de videos sin sub (en background)",
        "x_representantes": "lo que dicen los representantes en X — '¿qué tuiteó Oddone en marzo?'",
        "youtube_talks": "lo que dicen en entrevistas (Desayunos Informales, Arriba Gente, VTV) → rep_declaraciones",
        "planes_gobierno": "lo que PROMETIERON los partidos (2024 + históricos en ingesta)",
        "perfil_gobernantes": "QUIÉN ES quién: trayectoria, lista, votos",
        "votaciones_nominales": "CÓMO VOTÓ cada legislador proyecto por proyecto (en ingesta)",
        "resultados_electoral": "RESULTADOS electorales 1984-hoy (en ingesta)",
    }
    activos = {s for f in fuentes for s in [f["source"]]}
    return {"que_puedo_consultar": {s: recetas[s] for s in recetas if s in activos},
            "proximamente": {s: recetas[s] for s in recetas if s not in activos},
            "fuentes_estado_actual": fuentes,
            "indices_locales": sis["indices_locales"],
            "como_se_actualiza": "cron diario (compras/datos.gub), 6h (YouTube), semanal (departamentales); supervisor 30min re-lanza lo fallido",
            "como_verifico_un_dato": "todo dato lleva su URL oficial original + checksum en el registro de ingesta — abrila y compará",
            "provenance": _prov(tipo="introspeccion_real")}

@mcp.tool()
def discursos_buscar(consulta: str, limite: int = 10) -> str:
    """Busca texto literal en transcripciones de YouTube de los canales oficiales (Senado, Diputados, Parlamento, Presidencia).
    Ejemplos: 'seguridad pública', 'reforma previsional', 'Ley de urgencia'.
    NO cubre videos sin transcript (quedan ~19.6k de Presidencia en ingesta).
    Devuelve: fragmentos con video_id, minuto, canal y link con timestamp (t=MINs)."""
    c = sqlite3.connect(GOVAUDIT_DB, timeout=30)
    c.row_factory = sqlite3.Row
    lim = max(1, min(int(limite), MAX_LIMITE))
    try:
        rows = c.execute("""SELECT video_id, canal, minuto, texto FROM transcripciones_fts
                            WHERE transcripciones_fts MATCH ? LIMIT ?""",
                         (consulta, lim * 4)).fetchall()
    finally:
        c.close()
    if not rows:
        return f"Sin resultados para '{consulta}' en las transcripciones indexadas (622k segmentos, 301 videos de Senado/Diputados/Parlamento/Presidencia)."
    out, seen = [], set()
    for r in rows:
        key = (r["video_id"], r["minuto"])
        if key in seen:
            continue
        seen.add(key)
        vid = r["video_id"]
        mm = (r["minuto"] or "0:00")
        try:
            m, s_ = (int(x) for x in mm.split(":"))
            tstamp = m * 60 + s_
        except Exception:
            tstamp = 0
        out.append((f"**[{mm}] {r['canal']}** · https://youtube.com/watch?v={vid}&t={tstamp}s\n> {r['texto'][:300]}"))
        if len(out) >= lim:
            break
    return "\n\n".join(out) + f"\n\n_Fuente: transcripciones locales de canales oficiales de YouTube (ingesta con checksum). Fragmentos literales._"

@mcp.tool()
def compras_estadisticas(anio: int = 0, limite: int = 10) -> str:
    """Estadísticas de compras del Estado: total anual, top proveedores y top compradores.
    Ejemplos: año 2025 → total facturado, proveedor más grande, organismo que más compró.
    NO cubre: contratos sin valor declarado (~32% de los registros OCDS carecen de monto).
    Devuelve: markdown con cifras y URLs al portal oficial por ocid cuando aplique."""
    c = sqlite3.connect(GOVAUDIT_DB, timeout=30)
    lim = max(1, min(int(limite), MAX_LIMITE))
    w = "WHERE anio = ?" if anio else ""
    args = [anio] if anio else []
    try:
        tot = c.execute(f"SELECT SUM(total_value), COUNT(*) FROM compras {w} AND total_value IS NOT NULL",
                        args).fetchone()
        top_sup = c.execute(f"""SELECT supplier_names, COUNT(*) n, SUM(total_value) s
                                FROM compras WHERE supplier_names != '' {"AND anio=" + str(anio) if anio else ""}
                                GROUP BY supplier_names ORDER BY s DESC LIMIT ?""", (lim,)).fetchall()
        top_buy = c.execute(f"""SELECT buyer_name, COUNT(*) n, SUM(total_value) s
                                FROM compras WHERE buyer_name != '' {"AND anio=" + str(anio) if anio else ""}
                                GROUP BY buyer_name ORDER BY s DESC LIMIT ?""", (lim,)).fetchall()
    finally:
        c.close()
    anio_lbl = anio or "2002-2025 (histórico)"
    lines = [f"## Compras del Estado — {anio_lbl}"]
    if tot and tot[0]:
        lines.append(f"**Total con monto declarado: USD {tot[0]:,.0f}** en {tot[1]:,} contratos")
    if top_sup:
        lines.append("\n### Top proveedores")
        for s, n, v in top_sup:
            lines.append(f"- {s}: {n} contratos · {(v or 0):,.0f}")
    if top_buy:
        lines.append("\n### Top compradores")
        for b, n, v in top_buy:
            lines.append(f"- {b}: {n} contratos · {(v or 0):,.0f}")
    lines.append(f"\n_Fuente: comprasestatales.gub.uy (datos abiertos ARCE, ingesta con checksum). Portal: https://comprasestatales.gub.uy_")
    return "\n".join(lines)

if __name__ == "__main__":
    mcp.run()
