"""
Radar de Nichos
----------------
Consulta Google Trends (gratis, sin API key) para una lista de nichos/keywords,
guarda el historico diario en data/history.json y envia una alerta por Telegram
si el interes de algun nicho sube por encima del umbral definido.

Uso local:
    pip install -r requirements.txt
    python track_trends.py

En GitHub Actions se ejecuta solo cada dia (ver .github/workflows/daily.yml).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from pytrends.request import TrendReq

ROOT = Path(__file__).resolve().parent
KEYWORDS_FILE = ROOT / "keywords.json"
HISTORY_FILE = ROOT / "data" / "history.json"

# % de subida semana a semana que dispara una alerta
ALERT_THRESHOLD_PCT = 25
# interes minimo (0-100) para que una subida se considere relevante y no ruido
MIN_INTEREST_FOR_ALERT = 5
# reintentos si Google Trends bloquea/limita la peticion (comun en IPs de nube)
MAX_RETRIES = 4
RETRY_BACKOFF_SECONDS = 30

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


def fetch_trend(pytrends, query):
    """Devuelve (media ultimas 4 semanas, media 4 semanas previas) de interes 0-100.
    Reintenta con espera si Google Trends devuelve error de bloqueo/limite (429)."""
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            pytrends.build_payload([query], timeframe="today 3-m", geo="ES")
            df = pytrends.interest_over_time()
            break
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS * attempt
                print(f"  Intento {attempt} fallido para '{query}' ({exc}); espero {wait}s y reintento...")
                time.sleep(wait)
            else:
                raise last_exc

    if df.empty:
        return None
    values = df[query].tolist()
    if len(values) >= 8:
        recent, previous = values[-4:], values[-8:-4]
    elif len(values) > 4:
        recent, previous = values[-4:], values[:-4]
    else:
        recent, previous = values, []
    recent_avg = sum(recent) / len(recent) if recent else 0
    previous_avg = sum(previous) / len(previous) if previous else 0
    return recent_avg, previous_avg


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

    pytrends = TrendReq(hl="es-ES", tz=60)

    alerts = []
    day_snapshot = {}

    for item in keywords:
        kw_id, query, name = item["id"], item["query"], item["name"]
        try:
            result = fetch_trend(pytrends, query)
        except Exception as exc:
            print(f"Error consultando '{query}': {exc}", file=sys.stderr)
            continue
        if result is None:
            continue

        recent_avg, previous_avg = result
        if previous_avg > 0:
            change_pct = ((recent_avg - previous_avg) / previous_avg) * 100
        else:
            change_pct = 100 if recent_avg > 0 else 0

        day_snapshot[kw_id] = {
            "name": name,
            "query": query,
            "recent_avg": round(recent_avg, 1),
            "previous_avg": round(previous_avg, 1),
            "change_pct": round(change_pct, 1),
        }

        if change_pct >= ALERT_THRESHOLD_PCT and recent_avg >= MIN_INTEREST_FOR_ALERT:
            alerts.append(f"\U0001F4C8 <b>{name}</b>: interes subiendo un {change_pct:.0f}% (Google Trends, ES)")

        time.sleep(5)  # pausa entre nichos para no disparar el limite de Google

    history[today] = day_snapshot
    save_history(history)

    if alerts:
        send_telegram_alert("Radar de nichos \u2014 subidas detectadas hoy:\n\n" + "\n".join(alerts))
    else:
        print("Sin subidas relevantes hoy.")


if __name__ == "__main__":
    main()
