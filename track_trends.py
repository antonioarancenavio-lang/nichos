"""
Radar de Nichos
----------------
Consulta el interes de busqueda y las consultas relacionadas (via trendspyg,
alternativa mantenida a pytrends que ya no funciona) para una lista de
nichos/keywords. Calcula variacion diaria, semanal y mensual, guarda el
historico en data/history.json y avisa por Telegram si algun nicho sube
fuerte en semana.

SOBRE "competencia": no existe forma gratuita de saber cuantas webs compiten
de verdad (eso es Ahrefs/Semrush de pago). Lo que SI calculamos aqui es un
INDICE DE OPORTUNIDAD heuristico: demanda (interes semanal) dividida entre
amplitud del nicho (numero de terminos relacionados que devuelve Google).
Es una pista orientativa, no un dato de competencia real -- un nicho con
mucha demanda y pocos terminos relacionados alrededor puntua alto; uno con
mucha demanda pero un ecosistema enorme de terminos relacionados puntua bajo
porque probablemente ya esta muy explotado.

Uso local:
    pip install -r requirements.txt
    python track_trends.py

En GitHub Actions se ejecuta solo cada dia (ver .github/workflows/daily.yml).
Requiere Chrome instalado (ver el workflow). Con muchos nichos la ejecucion
puede tardar bastante (cada consulta tarda entre 10 y 90 segundos) -- es
normal, no hace falta hacer nada.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from trendspyg import download_google_trends_explore

ROOT = Path(__file__).resolve().parent
KEYWORDS_FILE = ROOT / "keywords.json"
HISTORY_FILE = ROOT / "data" / "history.json"

# % de subida semana a semana que dispara una alerta
ALERT_THRESHOLD_PCT = 25
# interes minimo (0-100) para que una subida se considere relevante y no ruido
MIN_INTEREST_FOR_ALERT = 5

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_keywords():
    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(history):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def pct_change(current, previous):
    if previous > 0:
        return ((current - previous) / previous) * 100
    return 100.0 if current > 0 else 0.0


def avg(values):
    return sum(values) / len(values) if values else 0.0


def analyze_series(values):
    """A partir de la serie diaria de Google Trends (timeframe 'today 3-m'),
    calcula el valor actual y la variacion diaria, semanal y mensual."""
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

    # Indice de oportunidad heuristico: demanda semanal / amplitud del nicho.
    # NO es competencia real -- ver aviso arriba en el docstring del fichero.
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


def main():
    keywords = load_keywords()
    history = load_history()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    alerts = []
    day_snapshot = {}

    for i, item in enumerate(keywords, start=1):
        kw_id, query, name = item["id"], item["query"], item["name"]
        print(f"[{i}/{len(keywords)}] Consultando '{query}'...")
        try:
            stats = fetch_trend(query)
        except Exception as exc:
            print(f"  Error consultando '{query}': {exc}", file=sys.stderr)
            continue
        if stats is None:
            continue

        day_snapshot[kw_id] = {"name": name, "query": query, **stats}

        if stats["weekly_change_pct"] >= ALERT_THRESHOLD_PCT and stats["week_avg"] >= MIN_INTEREST_FOR_ALERT:
            alerts.append(
                f"\U0001F4C8 <b>{name}</b>: interes subiendo un {stats['weekly_change_pct']:.0f}% "
                f"esta semana (Google Trends, ES)"
            )

    history[today] = day_snapshot
    save_history(history)

    if alerts:
        send_telegram_alert("Radar de nichos \u2014 subidas detectadas hoy:\n\n" + "\n".join(alerts))
    else:
        print("Sin subidas relevantes hoy.")


if __name__ == "__main__":
    main()
