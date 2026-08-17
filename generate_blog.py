"""
Genera tendencias.html
------------------------
Crea una pagina estatica de contenido (SEO) a partir del ultimo snapshot de
data/history.json. Es texto real en el HTML (no depende de JavaScript para
mostrarse), asi que Google puede leerla e indexarla directamente.

Se sobrescribe cada dia con los datos mas recientes -- una sola URL fuerte
que acumula autoridad con el tiempo, en vez de generar una pagina nueva cada
dia (que crearia contenido duplicado/debil).

Uso local:
    python generate_blog.py

Se ejecuta automaticamente en el workflow diario, despues de track_trends.py.
"""

import json
from datetime import datetime, timezone
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


def load_history():
    if not HISTORY_FILE.exists():
        return {}
    with open(HISTORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def fecha_legible(iso_date):
    y, m, d = iso_date.split("-")
    return f"{int(d)} de {MESES[int(m) - 1]} de {y}"


def build_rows(entries):
    rows = []
    for name, item in entries:
        rows.append(f"""
        <tr>
          <td>{name}</td>
          <td>{item.get('category', 'otros')}</td>
          <td>{CLASS_LABELS.get(item.get('classification'), '')}</td>
          <td>{item['current']}/100</td>
          <td>{'+' if item['weekly_change_pct'] > 0 else ''}{item['weekly_change_pct']}%</td>
        </tr>""")
    return "".join(rows)


FOOTER_NAV = """
  <footer>
    <a href="/">Buscador de nichos</a> ·
    <a href="/planes.html">Funciones y planes</a> ·
    <a href="/tendencias.html">Ranking diario</a> ·
    <a href="/guia-nicho-rentable.html">Guía: nicho rentable</a> ·
    <a href="/herramientas-encontrar-nichos.html">Comparativa de herramientas</a> ·
    <a href="/buscador-de-nichos.html">Qué es este buscador</a>
  </footer>
"""

BRAND_STRIP = """
  <a href="/" class="brand-strip-link">
    <span class="brand-strip-logo">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><rect x="3" y="14" width="4" height="7" rx="1" fill="white"/><rect x="10" y="9" width="4" height="12" rx="1" fill="white"/><rect x="17" y="3" width="4" height="18" rx="1" fill="white"/></svg>
    </span>
    Radar de Nichos
  </a>
"""

BRAND_STRIP_CSS = """
  .brand-strip-link { display:inline-flex; align-items:center; gap:8px; text-decoration:none; color:#14161a; font-weight:800; font-size:0.95rem; margin-bottom:20px; }
  .brand-strip-logo { width:26px; height:26px; border-radius:7px; background:#16a34a; display:flex; align-items:center; justify-content:center; flex-shrink:0; }
"""


def build_category_page(category, entries, fecha):
    title_text = CATEGORY_TITLES.get(category, f"Nichos de tipo {category} en España")
    rows = build_rows(entries)
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
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f7f8fa; color: #14161a; margin: 0; padding: 24px; line-height: 1.6; }}
  .wrap {{ max-width: 800px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; }}
  .updated {{ color: #6b7280; font-size: 0.85rem; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 0.85rem; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; }}
  th {{ color: #6b7280; font-size: 0.75rem; text-transform: uppercase; }}
  a {{ color: #16a34a; }}
  footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 0.8rem; }}
  {BRAND_STRIP_CSS}
</style>
</head>
<body>
<div class="wrap">
  {BRAND_STRIP}
  <h1>{title_text}</h1>
  <div class="updated">Última actualización: {fecha} · datos de Google Trends (España)</div>
  <p>Ranking de nichos de tipo <strong>{category}</strong> detectados por <a href="/">Radar de Nichos</a>, ordenados por crecimiento de interés esta semana.</p>
  <table>
    <thead><tr><th>Nicho</th><th>Categoría</th><th>Clasificación</th><th>Interés</th><th>Cambio semanal</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {FOOTER_NAV}
</div>
</body>
</html>
"""


def build_highlights(top5):
    paragraphs = []
    for name, item in top5:
        paragraphs.append(
            f"<li><strong>{name}</strong> ({item.get('category', 'otros')}) — interés actual de "
            f"{item['current']}/100, con una subida del {item['weekly_change_pct']}% esta semana "
            f"frente a la anterior. Clasificado como {CLASS_LABELS.get(item.get('classification'), '')}.</li>"
        )
    return "".join(paragraphs)


def main():
    history = load_history()
    dates = sorted(history.keys())
    if not dates:
        print("Sin datos todavia, no genero tendencias.html")
        return

    last_date = dates[-1]
    latest = history[last_date]
    entries = sorted(latest.items(), key=lambda kv: kv[1]["weekly_change_pct"], reverse=True)
    # entries es lista de (id, item); necesitamos el nombre legible
    named_entries = [(item["name"], item) for _id, item in entries]

    top5 = named_entries[:5]
    rest = named_entries[5:20]

    fecha = fecha_legible(last_date)

    html = f"""<!DOCTYPE html>
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
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f7f8fa; color: #14161a; margin: 0; padding: 24px; }}
  .wrap {{ max-width: 800px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; }}
  .updated {{ color: #6b7280; font-size: 0.85rem; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 0.85rem; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; }}
  th {{ color: #6b7280; font-size: 0.75rem; text-transform: uppercase; }}
  a.back {{ display: inline-block; margin-top: 24px; color: #16a34a; font-weight: 600; text-decoration: none; }}
  li {{ margin-bottom: 8px; line-height: 1.5; }}
  {BRAND_STRIP_CSS}
</style>
</head>
<body>
<div class="wrap">
  {BRAND_STRIP}
  <h1>Los nichos de negocio con más demanda en España</h1>
  <div class="updated">Última actualización: {fecha} · datos de Google Trends (España)</div>

  <p>Este ranking se genera automáticamente cada día a partir de <a href="/">Radar de Nichos</a>,
  una herramienta gratuita que analiza el interés de búsqueda real en España para detectar
  ideas de negocio con demanda creciente. Estos son los nichos con mayor subida de interés esta
  semana frente a la semana anterior:</p>

  <ul>
    {build_highlights(top5)}
  </ul>

  <h2>Ranking completo de hoy</h2>
  <table>
    <thead>
      <tr><th>Nicho</th><th>Categoría</th><th>Clasificación</th><th>Interés</th><th>Cambio semanal</th></tr>
    </thead>
    <tbody>
      {build_rows(rest)}
    </tbody>
  </table>

  <p>¿Quieres ver el listado completo, filtrar por categoría o comparar con el mes anterior?
  Entra en el <a href="/">dashboard interactivo de Radar de Nichos</a> — es gratis y no necesita registro.</p>

  <a class="back" href="/">← Volver al Radar de Nichos</a>
  {FOOTER_NAV}
</div>
</body>
</html>
"""

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Generado tendencias.html con datos de {last_date} ({len(named_entries)} nichos).")

    # Paginas por categoria
    by_category = {}
    for _id, item in entries:
        cat = item.get("category", "otros")
        by_category.setdefault(cat, []).append((item["name"], item))

    for category, cat_entries in by_category.items():
        cat_entries.sort(key=lambda ne: ne[1]["weekly_change_pct"], reverse=True)
        page_html = build_category_page(category, cat_entries, fecha)
        cat_file = ROOT / f"nichos-{category}.html"
        cat_file.write_text(page_html, encoding="utf-8")
        print(f"Generado nichos-{category}.html ({len(cat_entries)} nichos).")

    # Pagina hub que enlaza todas las categorias activas
    hub_links = "".join(
        f'<li><a href="/nichos-{cat}.html">{CATEGORY_TITLES.get(cat, cat)}</a> — {len(entries_c)} nichos</li>'
        for cat, entries_c in sorted(by_category.items())
    )
    hub_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Todas las categorías de nichos de negocio en España</title>
<meta name="description" content="Explora por categoría todos los nichos de negocio detectados: calculadoras, plantillas, comparadores, trámites y más. Actualizado a diario.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="https://TU-DOMINIO-AQUI/categorias.html">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<meta name="theme-color" content="#16a34a">
<style>
  body {{ font-family: -apple-system, sans-serif; background: #f7f8fa; color: #14161a; margin: 0; padding: 24px; line-height: 1.6; }}
  .wrap {{ max-width: 700px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; }}
  ul {{ padding-left: 20px; }}
  li {{ margin-bottom: 10px; }}
  a {{ color: #16a34a; font-weight: 600; }}
  {BRAND_STRIP_CSS}
</style>
</head>
<body>
<div class="wrap">
  {BRAND_STRIP}
  <h1>Todas las categorías de nichos de negocio</h1>
  <p>Explora por tipo de idea de negocio. Cada categoría se actualiza a diario con datos reales de interés de búsqueda en España.</p>
  <ul>{hub_links}</ul>
  {FOOTER_NAV}
</div>
</body>
</html>
"""
    (ROOT / "categorias.html").write_text(hub_html, encoding="utf-8")
    print(f"Generado categorias.html ({len(by_category)} categorias).")


if __name__ == "__main__":
    main()
