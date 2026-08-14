"""
Descubrimiento de nichos
-------------------------
Genera candidatos nuevos de nichos usando el autocompletado de Google (rapido,
sin coste, sin necesitar Chrome) a partir de patrones semilla tipo "calculadora
de...", "modelo de...", "comparador de...", etc.

Filtra los que ya estan en keywords.json (nucleo permanente) o ya se
descartaron antes, se queda con un lote limitado de candidatos nuevos, y los
deja en data/pending.json para que track_trends.py los evalue hoy mismo.

Uso local:
    pip install -r requirements.txt
    python discover_niches.py
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
SEEDS_FILE = ROOT / "discovery_seeds.json"
KEYWORDS_FILE = ROOT / "keywords.json"
DISCARDED_FILE = ROOT / "data" / "discarded.json"
PENDING_FILE = ROOT / "data" / "pending.json"

# cuantos candidatos nuevos se prueban como maximo por ejecucion (controla
# cuanto crece la carga de trabajo del dia)
NEW_CANDIDATES_PER_RUN = 15


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:60]


def normalize(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower()).strip()


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_suggestions(seed):
    """Autocompletado de Google (endpoint publico, sin API key)."""
    url = "https://www.google.com/complete/search"
    params = {"client": "firefox", "hl": "es", "gl": "es", "q": seed}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data[1] if len(data) > 1 else []
    except Exception as exc:
        print(f"  Error con semilla '{seed}': {exc}", file=sys.stderr)
        return []


def main():
    seeds = load_json(SEEDS_FILE, [])
    keywords = load_json(KEYWORDS_FILE, [])
    discarded = load_json(DISCARDED_FILE, [])

    known_normalized = {normalize(item["query"]) for item in keywords}
    known_normalized |= {normalize(q) for q in discarded}

    candidates = []
    seen_this_run = set()

    for seed in seeds:
        suggestions = fetch_suggestions(seed)
        print(f"'{seed}' -> {len(suggestions)} sugerencias")
        for suggestion in suggestions:
            norm = normalize(suggestion)
            if not norm or norm in known_normalized or norm in seen_this_run:
                continue
            seen_this_run.add(norm)
            candidates.append(suggestion)

    print(f"\nCandidatos nuevos encontrados: {len(candidates)}")

    selected = candidates[:NEW_CANDIDATES_PER_RUN]
    pending = [
        {"id": f"auto-{slugify(q)}", "name": q.capitalize(), "query": q}
        for q in selected
    ]

    save_json(PENDING_FILE, pending)
    print(f"Guardados {len(pending)} candidatos en data/pending.json para evaluar hoy.")


if __name__ == "__main__":
    main()
