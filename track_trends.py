"""
Radar de Nichos
----------------
Consulta el interes de busqueda y las consultas relacionadas (via trendspyg,
alternativa mantenida a pytrends que ya no funciona) para:
  1) el nucleo de nichos ya validados (keywords.json), y
  2) los candidatos nuevos descubiertos hoy (data/pending.json, generado por
     discover_niches.py).

Los candidatos nuevos que superen el umbral de interes minimo se promocionan
automaticamente al nucleo (quedan en seguimiento diario para siempre). Los
que no lo superen se descartan (se anotan en data/discarded.json para no
volver a probarlos).

Para que el nucleo no crezca sin limite, si se supera MAX_CORE_KEYWORDS se
jubila el nicho con peor interes semanal actual antes de anadir uno nuevo.

SOBRE "competencia": no existe forma gratuita de saber cuantas webs compiten
de verdad (eso es Ahrefs/Semrush de pago). El "indice de oportunidad" que
calculamos es una heuristica (demanda semanal / amplitud del nicho), no un
dato real de competencia -- ver detalle en el dashboard.

Uso local:
    pip install -r requirements.txt
    python discover_niches.py   # opcional, genera candidatos nuevos
    python track_trends.py

En GitHub Actions se ejecuta solo cada dia (ver .github/workflows/daily.yml).
Requiere Chrome instalado. Con muchos nichos puede tardar bastante -- normal.
"""

import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
from trendspyg import download_google_trends_explore

ROOT = Path(__file__).resolve().parent
KEYWORDS_FILE = ROOT / "keywords.json"
HISTORY_FILE = ROOT / "data" / "history.json"
PENDING_FILE = ROOT / "data" / "pending.json"
DISCARDED_FILE = ROOT / "data" / "discarded.json"

# % de subida semana a semana que dispara una alerta
ALERT_THRESHOLD_PCT = 25
# interes minimo (0-100) para que una subida se considere relevante y no ruido
MIN_INTEREST_FOR_ALERT = 5
# interes semanal minimo para que un candidato nuevo se promocione al nucleo
PROMOTION_THRESHOLD = 15
# tope maximo de nichos en el nucleo (evita que la ejecucion diaria crezca sin fin)
MAX_CORE_KEYWORDS = 150

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:60]


def load_json(path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def pct_change(current, previous):
    if previous > 0:
        return ((current - previous) / previous) * 100
    return 100.0 if current > 0 else 0.0


def avg(values):
    return sum(values) / len(values) if values else 0.0


def analyze_series(values):
    current = values[-1]
    yesterday = values[-2] if len(values) >= 2 else current
    daily_change = pct_change(current, yesterday)

    last_week = values[-7:]
    prev_week = values[-14:-7] if len(values) >= 14 else []
    week_avg = avg(last_week)
    weekly_change = pct_change(week_avg, avg(prev_week)) if prev_week else 0.0

    last_month = values[-30:]
    prev_month = values[-60:-30] if len(values) >= 60 else []
    month_avg = avg(last_month)
    monthly_change = pct_change(month_avg, avg(prev_month)) if prev_month else 0.0

    return {
        "current": round(current, 1),
        "daily_change_pct": round(daily_change, 1),
        "week_avg": round(week_avg, 1),
        "weekly_change_pct": round(weekly_change, 1),
        "month_avg": round(month_avg, 1),
        "monthly_change_pct": round(monthly_change, 1),
    }


def fetch_trend(query):
    env = download_google_trends_explore(query, geo="ES")

    series = env.get("interest_over_time") or []
    if not series:
        return None
    values = [point["value"] for point in series]
    stats = analyze_series(values)

    related = env.get("related_queries") or {}
    top_related = related.get("top") or []
    breadth = len(top_related)
    sample_terms = [r.get("query", "") for r in top_related[:3]]

    opportunity = round(stats["week_avg"] / (breadth + 1), 2)

    stats["breadth"] = breadth
    stats["sample_terms"] = sample_terms
    stats["opportunity"] = opportunity
    return stats


def send_telegram_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Sin credenciales de Telegram configuradas, omito el envio.")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"Error enviando alerta a Telegram: {resp.status_code} {resp.text}", file=sys.stderr)


def score_one(kw_id, query, name, category, day_snapshot, alerts):
    try:
        stats = fetch_trend(query)
    except Exception as exc:
        print(f"  Error consultando '{query}': {exc}", file=sys.stderr)
        return None
    if stats is None:
        return None

    day_snapshot[kw_id] = {"name": name, "query": query, "category": category, **stats}

    if stats["weekly_change_pct"] >= ALERT_THRESHOLD_PCT and stats["week_avg"] >= MIN_INTEREST_FOR_ALERT:
        alerts.append(
            f"\U0001F4C8 <b>{name}</b>: interes subiendo un {stats['weekly_change_pct']:.0f}% "
            f"esta semana (Google Trends, ES)"
        )
    return stats


def main():
    keywords = load_json(KEYWORDS_FILE, [])
    pending = load_json(PENDING_FILE, [])
    discarded = load_json(DISCARDED_FILE, [])
    history = load_json(HISTORY_FILE, {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    alerts = []
    day_snapshot = {}
    promoted_names = []
    discarded_names = []

    # 1) Nucleo ya validado
    total = len(keywords) + len(pending)
    n = 0
    for item in keywords:
        n += 1
        print(f"[{n}/{total}] (nucleo) Consultando '{item['query']}'...")
        score_one(item["id"], item["query"], item["name"], item.get("category", "otros"), day_snapshot, alerts)

    # 2) Candidatos nuevos descubiertos hoy
    for item in pending:
        n += 1
        category = item.get("category", "otros")
        print(f"[{n}/{total}] (candidato) Consultando '{item['query']}'...")
        stats = score_one(item["id"], item["query"], item["name"], category, day_snapshot, alerts)
        if stats is None:
            continue

        if stats["week_avg"] >= PROMOTION_THRESHOLD:
            keywords.append({"id": item["id"], "name": item["name"], "query": item["query"], "category": category})
            promoted_names.append(item["name"])
        else:
            discarded.append(item["query"])
            discarded_names.append(item["name"])

    # Si el nucleo se paso del limite, jubila los de peor interes semanal actual
    if len(keywords) > MAX_CORE_KEYWORDS:
        keywords.sort(key=lambda kw: day_snapshot.get(kw["id"], {}).get("week_avg", 0), reverse=True)
        retired = keywords[MAX_CORE_KEYWORDS:]
        keywords = keywords[:MAX_CORE_KEYWORDS]
        for kw in retired:
            day_snapshot.pop(kw["id"], None)
            print(f"  Jubilado por limite de nucleo: {kw['name']}")

    save_json(KEYWORDS_FILE, keywords)
    save_json(DISCARDED_FILE, discarded)
    save_json(PENDING_FILE, [])  # ya evaluados, se vacia hasta el proximo descubrimiento

    history[today] = day_snapshot
    save_json(HISTORY_FILE, history)

    if promoted_names:
        alerts.append(
            "\U0001F195 Nichos nuevos promocionados al radar: " + ", ".join(promoted_names)
        )

    if alerts:
        send_telegram_alert("Radar de nichos \u2014 novedades de hoy:\n\n" + "\n".join(alerts))
    else:
        print("Sin subidas ni promociones relevantes hoy.")

    print(f"\nResumen: {len(keywords)} en nucleo, {len(promoted_names)} promocionados, {len(discarded_names)} descartados.")


if __name__ == "__main__":
    main()
