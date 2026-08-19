"""
Genera tendencias.html, categorias.html y nichos-<categoria>.html
-------------------------------------------------------------------
Crea paginas estaticas de contenido (SEO) a partir del ultimo snapshot de
data/history.json. Es texto real en el HTML (no depende de JavaScript para
mostrarse), asi que Google puede leerla e indexarla directamente.

Se sobrescribe cada dia con los datos mas recientes -- una sola URL fuerte
por seccion que acumula autoridad con el tiempo, en vez de generar una
pagina nueva cada dia (que crearia contenido duplicado/debil).

Dos reglas de calidad de datos, para no publicar tendencias inventadas:
  1. Un nicho con interes actual 0/100 no tiene nada que mostrar (no se
     lista: no aporta valor y le resta credibilidad al ranking).
  2. Un nicho con interes real pero sin semana anterior con la que
     comparar se marca como "Nuevo", nunca como una subida del 100% --
     ese porcentaje era un artefacto de dividir por cero, no un dato real.

Uso local:
    python generate_blog.py

Se ejecuta automaticamente en el workflow diario, despues de track_trends.py.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "data" / "history.json"
OUTPUT_FILE = ROOT / "tendencias.html"

CLASS_LABELS = {
    "explosivo": "🚀 Explosivo",
    "en_subida": "📈 En subida",
    "estable": "➡️ Estable",
    "en_caida": "📉 En caída",
    "pico_pasado": "🏔️ Pico ya pasado",
    "nuevo": "🆕 Nuevo",
}

CATEGORY_TITLES = {
    "calculadora": "Calculadoras online más buscadas en España",
    "plantilla": "Plantillas y modelos legales más buscados en España",
    "comparador": "Comparadores de producto más buscados en España",
    "tramite": "Guías de trámites más buscadas en España",
    "generador": "Generadores online más buscados en España",
    "guia": "Guías prácticas más buscadas en España",
    "costes": "Consultas de precios y costes más buscadas en España",
    "meta": "Demanda real de herramientas para buscar nichos de negocio",
    "otros": "Otras ideas de negocio con demanda en España",
}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# Cuantos nichos con crecimiento real se destacan como tarjeta / se listan
# en la tabla completa antes de remitir al dashboard interactivo.
TOP_HIGHLIGHT_COUNT = 5
TABLE_EXTRA_COUNT = 20
NUEVOS_COUNT = 12


def load_history():
    if not HISTORY_FILE.exists():
        return {}
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def fecha_legible(iso_date):
    y, m, d = iso_date.split("-")
    return f"{int(d)} de {MESES[int(m) - 1]} de {y}"


def split_entries(entries):
    """entries: lista de (id, item). Devuelve (visibles_con_crecimiento,
    nuevos_sin_historico, excluidos_sin_interes)."""
    visible = [item for _id, item in entries if item.get("current", 0) > 0]
    excluded_count = len(entries) - len(visible)

    growth = [item for item in visible if item.get("weekly_change_pct") is not None]
    growth.sort(key=lambda it: it["weekly_change_pct"], reverse=True)

    nuevos = [item for item in visible if item.get("weekly_change_pct") is None]
    nuevos.sort(key=lambda it: it["current"], reverse=True)

    return growth, nuevos, excluded_count


def chg_class(pct):
    if pct is None:
        return "flat"
    return "up" if pct > 0 else ("down" if pct < 0 else "flat")


def fmt_pct(pct):
    if pct is None:
        return "—"
    return f"{'+' if pct > 0 else ''}{pct}%"


# ---------- Fragmentos de plantilla compartidos con el resto del sitio ----------

RADAR_MARK_SVG = """<svg class="radar-mark" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="44" class="radar-ring"/>
        <circle cx="50" cy="50" r="29" class="radar-ring"/>
        <circle cx="50" cy="50" r="14" class="radar-ring"/>
        <line x1="6" y1="50" x2="94" y2="50" class="radar-crosshair"/>
        <line x1="50" y1="6" x2="50" y2="94" class="radar-crosshair"/>
        <defs>
          <linearGradient id="sweepGradientMark" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#a33b2b" stop-opacity="0"/>
            <stop offset="100%" stop-color="#a33b2b" stop-opacity="0.55"/>
          </linearGradient>
        </defs>
        <g class="radar-sweep-group">
          <path d="M50,50 L50,6 A44,44 0 0,1 81,19 Z" class="radar-sweep-fill"/>
        </g>
        <circle cx="72" cy="34" r="2.6" class="radar-blip" style="animation-delay:0s"/>
        <circle cx="32" cy="66" r="2.6" class="radar-blip" style="animation-delay:1.4s"/>
        <circle cx="64" cy="72" r="2.6" class="radar-blip" style="animation-delay:2.8s"/>
      </svg>"""

NAV_ITEMS = [
    ("/", "Inicio", "inicio"),
    ("/tendencias.html", "Ranking diario", "tendencias"),
    ("/categorias.html", "Categorías", "categorias"),
    ("/planes.html", "Planes", "planes"),
]


def build_nav(current_slug):
    links = "".join(
        f'<a href="{href}"{" class=\"current\"" if slug == current_slug else ""}>{label}</a>'
        for href, label, slug in NAV_ITEMS
    )
    return f'<nav class="site-nav">\n    <div class="wrap">\n      {links}\n    </div>\n  </nav>'


def build_masthead(current_slug, tagline, fecha, total_tracked):
    return f"""<header class="masthead">
  <div class="wrap">
    <div class="brand">
      {RADAR_MARK_SVG}
      <div>
        <h1>Radar de Nichos</h1>
        <div class="tag">{tagline}</div>
      </div>
    </div>
    <div>
      <div class="subtitle">Actualizado: {fecha}</div>
      <a href="/" style="font-size:0.8rem; color:#a33b2b; font-weight:600; text-decoration:none; font-family:var(--font-mono);">Ver dashboard interactivo →</a>
    </div>
  </div>
  <div class="wrap">
    <div class="trust-bar">
      <div class="trust-item"><div class="num">{total_tracked}</div><div class="label">Nichos con interés real</div></div>
      <div class="trust-item"><div class="num">Diaria</div><div class="label">Frecuencia de actualización</div></div>
      <div class="trust-item"><div class="num">0 €</div><div class="label">Coste, sin registro</div></div>
      <div class="trust-item"><div class="num">100%</div><div class="label">Datos de Google Trends</div></div>
    </div>
  </div>
  {build_nav(current_slug)}
</header>"""


FOOTER_NAV = """<footer class="site-footer">
    <div style="margin-bottom:10px;">
      <a href="/">Buscador de nichos</a> ·
      <a href="/planes.html">Funciones y planes</a> ·
      <a href="/tendencias.html">Ranking diario</a> ·
      <a href="/categorias.html">Categorías</a> ·
      <a href="/guia-nicho-rentable.html">Guía: nicho rentable</a> ·
      <a href="/herramientas-encontrar-nichos.html">Comparativa de herramientas</a> ·
      <a href="/buscador-de-nichos.html">Qué es este buscador</a>
    </div>
    <div style="color:var(--ink-faint); font-family:var(--font-mono); font-size:0.72rem;">Sin anuncios · Sin tracking de terceros · Metodología abierta en la página de inicio</div>
  </footer>"""

FONT_LINKS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/styles.css">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<meta name="theme-color" content="#a33b2b">"""


def build_highlight_cards(items, rank_offset=1):
    cards = []
    for i, item in enumerate(items):
        cls = chg_class(item["weekly_change_pct"])
        arrow = "▲" if cls == "up" else ("▼" if cls == "down" else "→")
        classification = item.get("classification", "estable")
        cards.append(f"""
      <div class="card">
        <div class="card-top"><span class="rank-badge">#{rank_offset + i}</span></div>
        <span class="cat-pill">{item.get('category', 'otros')}</span><span class="class-tag {classification}">{CLASS_LABELS.get(classification, '')}</span>
        <h3>{item['name']}</h3>
        <div class="big-change {cls}"><span class="arrow-icon">{arrow}</span>{fmt_pct(item['weekly_change_pct'])}</div>
        <div class="card-meta">Interés: {item['current']}/100 esta semana</div>
      </div>""")
    return "".join(cards)


def build_growth_table(items, rank_offset=1):
    rows = []
    for i, item in enumerate(items):
        cls = chg_class(item["weekly_change_pct"])
        classification = item.get("classification", "estable")
        rows.append(f"""
        <tr>
          <td class="rank-cell">#{rank_offset + i}</td>
          <td class="name-cell">{item['name']}</td>
          <td><span class="cat-pill">{item.get('category', 'otros')}</span></td>
          <td><span class="class-tag {classification}">{CLASS_LABELS.get(classification, '')}</span></td>
          <td class="num-cell">{item['current']}/100</td>
          <td class="chg-cell {cls}">{fmt_pct(item['weekly_change_pct'])}</td>
        </tr>""")
    return f"""<table class="content-table">
    <thead>
      <tr><th>#</th><th>Nicho</th><th>Categoría</th><th>Clasificación</th><th>Interés</th><th>Cambio semanal</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>"""


def build_nuevos_table(items):
    if not items:
        return ""
    rows = []
    for item in items:
        rows.append(f"""
        <tr>
          <td class="name-cell">{item['name']}</td>
          <td><span class="cat-pill">{item.get('category', 'otros')}</span></td>
          <td><span class="class-tag nuevo">🆕 Nuevo</span></td>
          <td class="num-cell">{item['current']}/100</td>
        </tr>""")
    table = f"""<table class="content-table">
    <thead>
      <tr><th>Nicho</th><th>Categoría</th><th>Estado</th><th>Interés</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>"""
    return f"""
  <h2>Nichos nuevos en seguimiento <span class="h2-count">— {len(items)}</span></h2>
  <p class="section-lede">Interés de búsqueda real detectado, pero aún sin una semana anterior con la que comparar el crecimiento. En cuanto acumulen histórico, entran en el ranking de arriba.</p>
  {table}"""


def transparency_note(excluded_count):
    if excluded_count <= 0:
        return ""
    return f"""<p class="transparency-note">{excluded_count} nichos más están en seguimiento pero Google Trends no registra
  todavía búsquedas para ellos (interés 0/100) — se excluyen de este ranking hasta que muestren demanda real.</p>"""


def top_and_rest(growth):
    """growth ya viene ordenado desc por weekly_change_pct. Las tarjetas
    destacadas solo deben llevar crecimiento REAL (positivo) -- un nicho en
    caída no es un 'destacado' aunque le toque el puesto #5 por descarte."""
    positive_count = sum(1 for it in growth if it["weekly_change_pct"] > 0)
    top_count = min(positive_count, TOP_HIGHLIGHT_COUNT)
    top = growth[:top_count]
    rest = growth[top_count:top_count + TABLE_EXTRA_COUNT]
    return top, rest


def build_category_page(category, growth, nuevos, excluded_count, fecha, total_tracked):
    title_text = CATEGORY_TITLES.get(category, f"Nichos de tipo {category} en España")
    top, rest = top_and_rest(growth)
    nuevos_shown = nuevos[:NUEVOS_COUNT]

    highlights_html = ""
    if top:
        highlights_html = f"""
  <h2>Con más crecimiento esta semana</h2>
  <div class="content-highlights">{build_highlight_cards(top)}</div>"""

    rest_html = ""
    if rest:
        rest_html = f"""
  <h2>Resto del ranking <span class="h2-count">— {len(rest)}</span></h2>
  {build_growth_table(rest, rank_offset=len(top) + 1)}"""

    empty_html = ""
    if not top and not rest and not nuevos_shown:
        empty_html = '<p class="section-lede">Todavía no hay nichos de esta categoría con interés de búsqueda registrado.</p>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title_text} — actualizado {fecha}</title>
<meta name="description" content="Ranking actualizado a diario de {title_text.lower()}, con datos reales de interés de búsqueda. Última actualización: {fecha}.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://TU-DOMINIO-AQUI/nichos-{category}.html">
<meta property="og:type" content="article">
<meta property="og:title" content="{title_text}">
<meta property="og:description" content="Ranking actualizado a diario, con datos reales de Google Trends España.">
<meta property="og:url" content="https://TU-DOMINIO-AQUI/nichos-{category}.html">
<meta property="og:image" content="https://TU-DOMINIO-AQUI/og-image.png">
{FONT_LINKS}
</head>
<body>
{build_masthead('categorias', f'Categoría: {title_text}', fecha, total_tracked)}
<div class="wrap content-wrap">
  <div class="content-hero">
    <div class="updated">Última actualización: {fecha} · datos de Google Trends (España)</div>
    <h1>{title_text}</h1>
    <p class="lede">Ranking de nichos de tipo <strong>{category}</strong> detectados por <a href="/">Radar de Nichos</a>,
    ordenados por crecimiento de interés real esta semana frente a la anterior.</p>
  </div>
  {empty_html}
  {highlights_html}
  {rest_html}
  {build_nuevos_table(nuevos_shown)}
  {transparency_note(excluded_count)}
  <hr class="section-divider">
  <p style="margin-top:24px;">¿Quieres ver todas las categorías o el listado interactivo completo?
  Entra en el <a href="/">dashboard de Radar de Nichos</a> — es gratis y no necesita registro.</p>
</div>
{FOOTER_NAV}
</body>
</html>
"""


def build_tendencias_page(growth, nuevos, excluded_count, fecha, total_tracked):
    top, rest = top_and_rest(growth)
    nuevos_shown = nuevos[:NUEVOS_COUNT]

    highlights_html = ""
    if top:
        highlights_html = f"""
  <h2>Lo más destacado de hoy</h2>
  <div class="content-highlights">{build_highlight_cards(top)}</div>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Los nichos de negocio con más demanda en España — actualizado {fecha}</title>
<meta name="description" content="Ranking actualizado a diario de los nichos de negocio con más crecimiento de búsqueda en España, con datos reales de Google Trends. Última actualización: {fecha}.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://TU-DOMINIO-AQUI/tendencias.html">
<meta property="og:type" content="article">
<meta property="og:title" content="Los nichos de negocio con más demanda en España — {fecha}">
<meta property="og:description" content="Ranking actualizado a diario de los nichos de negocio con más crecimiento de búsqueda en España.">
<meta property="og:url" content="https://TU-DOMINIO-AQUI/tendencias.html">
<meta property="og:image" content="https://TU-DOMINIO-AQUI/og-image.png">
{FONT_LINKS}
</head>
<body>
{build_masthead('tendencias', 'Ranking diario de nichos con más demanda en España', fecha, total_tracked)}
<div class="wrap content-wrap">
  <div class="content-hero">
    <div class="updated">Última actualización: {fecha} · datos de Google Trends (España)</div>
    <h1>Los nichos de negocio con más demanda en España</h1>
    <p class="lede">Este ranking se genera automáticamente cada día a partir de <a href="/">Radar de Nichos</a>,
    una herramienta gratuita que analiza el interés de búsqueda real en Google España para detectar
    ideas de negocio con demanda creciente. Solo entran nichos con interés de búsqueda real: nada de
    porcentajes inflados por falta de datos.</p>
  </div>
  {highlights_html}

  <h2>Resto del ranking <span class="h2-count">— {len(rest)}</span></h2>
  {build_growth_table(rest, rank_offset=len(top) + 1)}

  {build_nuevos_table(nuevos_shown)}

  {transparency_note(excluded_count)}

  <hr class="section-divider">
  <p style="margin-top:24px;">¿Quieres ver el listado completo, filtrar por categoría o comparar con el mes anterior?
  Entra en el <a href="/">dashboard interactivo de Radar de Nichos</a> — es gratis y no necesita registro.</p>
</div>
{FOOTER_NAV}
</body>
</html>
"""


def build_categorias_hub(by_category, fecha, total_tracked):
    tiles = []
    for cat, growth in sorted(by_category.items(), key=lambda kv: -len(kv[1][0]) - len(kv[1][1])):
        cat_growth, cat_nuevos, _ = growth
        count = len(cat_growth) + len(cat_nuevos)
        title_text = CATEGORY_TITLES.get(cat, cat)
        tiles.append(f"""
    <a class="category-tile" href="/nichos-{cat}.html">
      <h3>{title_text}</h3>
      <div class="tile-count">{count}</div>
      <div class="tile-label">nichos en seguimiento</div>
    </a>""")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Todas las categorías de nichos de negocio en España</title>
<meta name="description" content="Explora por categoría todos los nichos de negocio detectados: calculadoras, plantillas, comparadores, trámites y más. Actualizado a diario.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://TU-DOMINIO-AQUI/categorias.html">
{FONT_LINKS}
</head>
<body>
{build_masthead('categorias', 'Explora los nichos de negocio por categoría', fecha, total_tracked)}
<div class="wrap content-wrap">
  <div class="content-hero">
    <div class="updated">Última actualización: {fecha} · datos de Google Trends (España)</div>
    <h1>Todas las categorías de nichos de negocio</h1>
    <p class="lede">Explora por tipo de idea de negocio. Cada categoría se actualiza a diario con datos
    reales de interés de búsqueda en España.</p>
  </div>
  <div class="category-tiles">{''.join(tiles)}</div>
  <hr class="section-divider">
  <p style="margin-top:24px;">¿Prefieres verlo todo junto, filtrar y guardar favoritos?
  Entra en el <a href="/">dashboard interactivo de Radar de Nichos</a> — es gratis y no necesita registro.</p>
</div>
{FOOTER_NAV}
</body>
</html>
"""


def main():
    history = load_history()
    dates = sorted(history.keys())
    if not dates:
        print("Sin datos todavia, no genero tendencias.html")
        return

    last_date = dates[-1]
    latest = history[last_date]
    entries = list(latest.items())
    fecha = fecha_legible(last_date)

    growth, nuevos, excluded_count = split_entries(entries)
    total_tracked = len(growth) + len(nuevos)

    OUTPUT_FILE.write_text(
        build_tendencias_page(growth, nuevos, excluded_count, fecha, total_tracked),
        encoding="utf-8",
    )
    print(f"Generado tendencias.html con datos de {last_date} "
          f"({total_tracked} nichos con interés real, {excluded_count} excluidos sin interés).")

    # Paginas por categoria
    by_category_raw = {}
    for _id, item in entries:
        cat = item.get("category", "otros")
        by_category_raw.setdefault(cat, []).append((_id, item))

    by_category_split = {}
    for cat, cat_entries in by_category_raw.items():
        cat_growth, cat_nuevos, cat_excluded = split_entries(cat_entries)
        by_category_split[cat] = (cat_growth, cat_nuevos, cat_excluded)
        page_html = build_category_page(cat, cat_growth, cat_nuevos, cat_excluded, fecha, total_tracked)
        cat_file = ROOT / f"nichos-{cat}.html"
        cat_file.write_text(page_html, encoding="utf-8")
        print(f"Generado nichos-{cat}.html ({len(cat_growth) + len(cat_nuevos)} nichos con interés real).")

    (ROOT / "categorias.html").write_text(
        build_categorias_hub(by_category_split, fecha, total_tracked),
        encoding="utf-8",
    )
    print(f"Generado categorias.html ({len(by_category_split)} categorias).")


if __name__ == "__main__":
    main()
