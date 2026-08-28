"""
Kit de lanzamiento SEO ampliado (Premium)
------------------------------------------
Genera un articulo completo listo para publicar (no solo un esquema) para los
nichos con mas potencial, usando la API de Claude. El resultado se guarda en
data/articles.json (cache permanente, indexado por id de nicho) para que:
  - el coste de generacion sea uno por nicho, no uno por usuario ni por visita
  - el frontend (index.html) pueda servir el articulo ya generado a cualquier
    usuario Premium sin llamar a la API en cada peticion

Cada ejecucion genera como mucho ARTICLES_PER_RUN articulos nuevos (controla
el coste diario) priorizando los nichos "explosivo" / "en_subida" que aun no
tengan articulo en cache. Los que ya tienen articulo no se regeneran.

Requiere la variable de entorno ANTHROPIC_API_KEY (secret de GitHub Actions,
igual que TELEGRAM_BOT_TOKEN). Si no esta configurada, el script no falla:
simplemente no genera nada (para no romper el workflow diario si aun no se ha
dado de alta la clave).

Uso local:
    export ANTHROPIC_API_KEY=sk-ant-...
    python generate_articles.py
"""

import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
KEYWORDS_FILE = ROOT / "keywords.json"
HISTORY_FILE = ROOT / "data" / "history.json"
ARTICLES_FILE = ROOT / "data" / "articles.json"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# cuantos articulos nuevos se generan como maximo por ejecucion diaria (esto
# es lo que controla el coste: subir este numero sube el gasto en API cada dia)
ARTICLES_PER_RUN = 3

# orden de prioridad: los nichos con mas tirada primero
CLASSIFICATION_PRIORITY = {
    "explosivo": 0,
    "en_subida": 1,
    "estable": 2,
    "pico_pasado": 3,
    "en_caida": 4,
}

CATEGORY_HINTS = {
    "calculadora": "una calculadora online gratuita",
    "plantilla": "una plantilla o modelo descargable",
    "comparador": "un comparador de productos u opciones",
    "tramite": "una guia de un tramite administrativo",
    "generador": "un generador online gratuito",
    "guia": "una guia practica paso a paso",
}


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:60]


def load_json(path, default):
    """Misma logica de recuperacion que track_trends.py: si el fichero esta
    corrupto, se avisa y se sigue con el valor por defecto en vez de tirar
    todo el script abajo por un problema de datos, no de codigo."""
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"AVISO: {path.name} esta corrupto ({e}) -- se continua con datos vacios.", file=sys.stderr)
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def latest_snapshot(history):
    if not history:
        return {}
    latest_date = sorted(history.keys())[-1]
    return history[latest_date]


def pick_candidates(keywords, snapshot, cache, limit):
    """Nichos sin articulo en cache, ordenados por prioridad de clasificacion."""
    pending = []
    for item in keywords:
        kw_id = item.get("id")
        if not kw_id or kw_id in cache:
            continue
        classification = snapshot.get(kw_id, {}).get("classification", "estable")
        priority = CLASSIFICATION_PRIORITY.get(classification, 5)
        pending.append((priority, item))
    pending.sort(key=lambda pair: pair[0])
    return [item for _, item in pending[:limit]]


def build_prompt(item):
    category_hint = CATEGORY_HINTS.get(item.get("category", ""), "una herramienta o guia online")
    return f"""Eres redactor SEO en espanol de Espana, especializado en paginas de nicho sobre {category_hint}.

Escribe el contenido de lanzamiento para una pagina sobre: "{item['name']}" (busqueda objetivo: "{item['query']}").

Responde UNICAMENTE con un JSON valido, sin texto antes ni despues, con esta forma exacta:
{{
  "title": "titulo SEO de menos de 60 caracteres",
  "meta_description": "meta description de menos de 155 caracteres, con llamada a la accion",
  "body_html": "el articulo completo en HTML (usa <h2>, <p>, <ul>/<li> donde tenga sentido), 500-700 palabras, en espanol de Espana, tono claro y practico, sin relleno generico ni frases vacias, con informacion realmente util para alguien que busca '{item['query']}'. No incluyas <html>, <head> ni <body>, solo el contenido interior."
}}"""


def call_claude(prompt):
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    text = text.strip()
    # por si el modelo envuelve el JSON en ```json ... ``` a pesar de la instruccion
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip())
    return json.loads(text)


def main():
    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY no configurada -- no se genera ningun articulo nuevo hoy.")
        return

    keywords = load_json(KEYWORDS_FILE, [])
    history = load_json(HISTORY_FILE, {})
    cache = load_json(ARTICLES_FILE, {})
    snapshot = latest_snapshot(history)

    candidates = pick_candidates(keywords, snapshot, cache, ARTICLES_PER_RUN)
    if not candidates:
        print("No hay nichos nuevos pendientes de articulo (todos ya tienen cache, o no hay nucleo aun).")
        return

    generated = 0
    for item in candidates:
        try:
            article = call_claude(build_prompt(item))
            required = {"title", "meta_description", "body_html"}
            if not required.issubset(article):
                raise ValueError(f"respuesta incompleta del modelo: {list(article.keys())}")
            cache[item["id"]] = {
                "name": item["name"],
                "query": item["query"],
                "category": item.get("category", "otros"),
                "title": article["title"],
                "meta_description": article["meta_description"],
                "body_html": article["body_html"],
                "model": ANTHROPIC_MODEL,
            }
            generated += 1
            print(f"Articulo generado: {item['name']}")
        except Exception as exc:
            print(f"Fallo generando articulo para {item['name']}: {exc}", file=sys.stderr)

    if generated:
        save_json(ARTICLES_FILE, cache)
    print(f"Listo: {generated} articulo(s) nuevo(s), {len(cache)} en cache total.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Los articulos son un extra Premium, no el nucleo del radar -- si
        # algo inesperado revienta aqui, se avisa y se sale limpio en vez de
        # tirar todo el workflow por un paso que no es critico.
        print(f"AVISO: generate_articles.py fallo de forma inesperada: {exc}", file=sys.stderr)
