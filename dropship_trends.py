"""
Tendencias diarias por pais (dropshipping)
-------------------------------------------
Saca el listado de busquedas en tendencia de hoy en EEUU y Reino Unido via
trendspyg (alternativa mantenida a pytrends, que esta archivado y ya no
funciona). Es una lista cruda -- no distingue "esto es un producto", asi que
hay que revisarla a ojo para detectar patrones que podrian funcionar en
dropshipping.

Uso local:
    pip install -r requirements.txt
    python dropship_trends.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from trendspyg import download_google_trends_rss

ROOT = Path(__file__).resolve().parent
OUTPUT_FILE = ROOT / "data" / "dropship_trends.json"

# Codigos de pais (ISO de 2 letras) que soporta trendspyg
COUNTRIES = {
    "EEUU": "US",
    "Reino Unido": "GB",
}

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_output():
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_output(data):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Sin credenciales de Telegram, omito el envio.")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        data={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
        timeout=15,
    )
    if resp.status_code != 200:
        print(f"Error enviando mensaje a Telegram: {resp.status_code} {resp.text}", file=sys.stderr)


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    all_data = load_output()
    day_snapshot = {}
    message_lines = [f"\U0001F30E Tendencias de hoy ({today}):\n"]

    for label, code in COUNTRIES.items():
        try:
            trends = download_google_trends_rss(geo=code)
        except Exception as exc:
            print(f"Error consultando tendencias de {label}: {exc}", file=sys.stderr)
            continue

        terms = [f"{t['trend']} ({t.get('traffic', '')})" for t in trends[:20]]
        day_snapshot[label] = terms
        message_lines.append(f"<b>{label}</b>")
        message_lines.extend(f"- {term}" for term in terms[:10])
        message_lines.append("")

    all_data[today] = day_snapshot
    save_output(all_data)

    if day_snapshot:
        send_telegram_message("\n".join(message_lines))
    else:
        print("No se pudo obtener ninguna tendencia hoy.")


if __name__ == "__main__":
    main()
