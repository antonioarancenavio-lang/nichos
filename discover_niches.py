"""
Descubrimiento de nichos
-------------------------
Genera candidatos nuevos de nichos usando el autocompletado de Google (rapido,
sin coste, sin necesitar Chrome) a partir de patrones semilla tipo "calculadora
de...", "modelo de...", "comparador de...", etc. Cada semilla lleva asociada
una categoria (ver discovery_seeds.json) que se hereda por los candidatos que
encuentra, para poder filtrar despues en el dashboard.

Filtra los que ya estan en keywords.json (nucleo permanente) o ya se
descartaron antes, se queda con un lote limitado de candidatos nuevos, y los
deja en data/pending.json para que track_trends.py los evalue hoy mismo.

Uso local:
    pip install -r requirements.txt
    python discover_niches.py
"""

import json
import os
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


def word_set(text):
    stopwords = {"de", "la", "el", "en", "para", "con", "un", "una", "y", "que", "como"}
    return {w for w in normalize(text).split() if w not in stopwords and len(w) > 2}


def is_near_duplicate(candidate_words, known_word_sets, threshold=0.75):
    """Similitud tipo Jaccard: si comparte la mayoria de palabras clave con
    algo que ya esta en seguimiento, se considera casi-duplicado y se descarta
    (evita llenar el nucleo de variaciones triviales del mismo nicho)."""
    if not candidate_words:
        return False
    for known_words in known_word_sets:
        if not known_words:
            continue
        overlap = len(candidate_words & known_words)
        union = len(candidate_words | known_words)
        if union and (overlap / union) >= threshold:
            return True
    return False


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
    """Escritura atomica (temp + rename), igual que en track_trends.py."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


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
    seeds = load_json(SEEDS_FILE, {})
    keywords = load_json(KEYWORDS_FILE, [])
    discarded = load_json(DISCARDED_FILE, [])

    # Si keywords.json tiene alguna entrada mal formada (sin "query"), se
    # ignora esa entrada suelta en vez de tirar todo el descubrimiento abajo
    # -- un dato local raro no deberia impedir que se busquen candidatos
    # nuevos hoy.
    known_normalized = {normalize(item["query"]) for item in keywords if "query" in item}
    known_normalized |= {normalize(q) for q in discarded}
    known_word_sets = [word_set(item["query"]) for item in keywords if "query" in item]

    candidates = []  # lista de (texto, categoria)
    seen_this_run = set()
    seen_word_sets_this_run = []

    for seed, category in seeds.items():
        suggestions = fetch_suggestions(seed)
        print(f"'{seed}' ({category}) -> {len(suggestions)} sugerencias")
        for suggestion in suggestions:
            norm = normalize(suggestion)
            if not norm or norm in known_normalized or norm in seen_this_run:
                continue
            words = word_set(suggestion)
            if is_near_duplicate(words, known_word_sets) or is_near_duplicate(words, seen_word_sets_this_run):
                continue
            seen_this_run.add(norm)
            seen_word_sets_this_run.append(words)
            candidates.append((suggestion, category))

    print(f"\nCandidatos nuevos encontrados: {len(candidates)}")

    selected = candidates[:NEW_CANDIDATES_PER_RUN]
    pending = [
        {"id": f"auto-{slugify(q)}", "name": q.capitalize(), "query": q, "category": category}
        for q, category in selected
    ]

    save_json(PENDING_FILE, pending)
    print(f"Guardados {len(pending)} candidatos en data/pending.json para evaluar hoy.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Descubrir candidatos nuevos es un extra, no el nucleo del radar --
        # si algo inesperado revienta aqui (no solo un fallo de red, que ya
        # esta cubierto arriba), se avisa y se sale limpio en vez de tirar
        # todo el workflow por un paso que no es critico.
        print(f"AVISO: discover_niches.py fallo de forma inesperada: {exc}", file=sys.stderr)
        print("Se continua sin candidatos nuevos hoy -- no afecta al nucleo ya en seguimiento.", file=sys.stderr)
