"""
Alertas de oportunidad temprana (Premium)
-------------------------------------------
Cada dia, tras actualizar data/history.json, comprueba que nichos han
entrado HOY en la clasificacion "explosivo" (es decir, ayer no lo estaban y
hoy si) y avisa por email a los usuarios Premium activos.

No hace falta base de datos propia de usuarios: Stripe ya sabe quien tiene
una suscripcion activa y su email, asi que se consulta directamente ahi
(igual que hace api/check-premium.js). El envio de email se hace con Resend
(API sencilla, capa gratuita de sobra para esto).

Solo alerta en el dia en que un nicho ENTRA en "explosivo" (no todos los dias
que se mantiene ahi), para no saturar el correo. Guarda en
data/last_alert_sent.json que fecha fue la ultima avisada, para no reenviar
si el workflow se relanza a mano el mismo dia.

Requiere las variables de entorno:
  STRIPE_SECRET_KEY   -- misma clave que usan las funciones de api/

Y, para al menos uno de los dos canales:
  RESEND_API_KEY, RESEND_FROM_EMAIL          -- email (via Resend)
  TELEGRAM_BOT_TOKEN, UPSTASH_REDIS_REST_URL,
  UPSTASH_REDIS_REST_TOKEN                   -- Telegram (via el bot ya
                                                 vinculado con api/telegram-*.js)

SITE_URL es opcional (enlace incluido en los mensajes).

Si no hay ningun canal configurado, el script no falla: simplemente no envia
nada (para no romper el workflow diario mientras no esten dadas de alta).

Uso local:
    export STRIPE_SECRET_KEY=sk_live_...
    export RESEND_API_KEY=re_...
    export RESEND_FROM_EMAIL="Radar de Nichos <alertas@tu-dominio.com>"
    python alert_premium.py
"""

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "data" / "history.json"
LAST_ALERT_FILE = ROOT / "data" / "last_alert_sent.json"

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "")
SITE_URL = os.environ.get("SITE_URL", "https://radar-de-nichos.vercel.app")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
UPSTASH_REDIS_REST_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")


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


def find_new_explosive(history):
    dates = sorted(history.keys())
    if len(dates) < 1:
        return None, []
    today = dates[-1]
    today_snapshot = history[today]
    prev_snapshot = history[dates[-2]] if len(dates) >= 2 else {}

    new_explosive = []
    for kw_id, item in today_snapshot.items():
        if item.get("classification") != "explosivo":
            continue
        was_explosive_yesterday = prev_snapshot.get(kw_id, {}).get("classification") == "explosivo"
        if not was_explosive_yesterday:
            new_explosive.append(item)
    return today, new_explosive


def fetch_active_subscriber_customers():
    """Lista (customer_id, email) de clientes con una suscripcion activa en
    Stripe, paginando si hace falta. Sin SDK de stripe -- llamada REST directa."""
    customers = []
    starting_after = None
    while True:
        params = {"status": "active", "limit": 100, "expand[]": "data.customer"}
        if starting_after:
            params["starting_after"] = starting_after
        resp = requests.get(
            "https://api.stripe.com/v1/subscriptions",
            params=params,
            auth=(STRIPE_SECRET_KEY, ""),
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        for sub in data.get("data", []):
            customer = sub.get("customer")
            if isinstance(customer, dict) and customer.get("id"):
                customers.append({"id": customer["id"], "email": customer.get("email")})
        if data.get("has_more") and data.get("data"):
            starting_after = data["data"][-1]["id"]
        else:
            break
    return customers


def redis_get(key):
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_REST_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("result")
    except requests.exceptions.RequestException as exc:
        print(f"Error de red consultando Upstash ({key}): {exc}", file=sys.stderr)
        return None


def send_telegram_message(chat_id, text):
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"Error enviando Telegram a chat {chat_id}: {resp.status_code} {resp.text}", file=sys.stderr)
            return False
        return True
    except requests.exceptions.RequestException as exc:
        print(f"Error de red enviando Telegram a chat {chat_id}: {exc}", file=sys.stderr)
        return False


def build_telegram_text(niches):
    lines = [f"🚀 {len(niches)} nicho(s) nuevo(s) en Explosivo hoy:", ""]
    for n in niches:
        lines.append(f"• {n['name']} (semana +{n.get('weekly_change_pct', 0):.0f}%, mes +{n.get('monthly_change_pct', 0):.0f}%)")
    lines.append("")
    lines.append(SITE_URL)
    return "\n".join(lines)


def build_email_html(niches):
    items_html = "".join(
        f"<li><strong>{n['name']}</strong> — semana +{n.get('weekly_change_pct', 0):.0f}%, "
        f"mes +{n.get('monthly_change_pct', 0):.0f}%</li>"
        for n in niches
    )
    return f"""
    <div style="font-family:sans-serif; max-width:520px; margin:0 auto;">
      <h2>🚀 {len(niches)} nicho(s) nuevo(s) en Explosivo</h2>
      <p>Acaban de entrar en la clasificación "Explosivo" en el radar de hoy:</p>
      <ul>{items_html}</ul>
      <p><a href="{SITE_URL}" style="background:#16a34a; color:#fff; padding:10px 18px; border-radius:8px; text-decoration:none; font-weight:700;">Ver en el radar</a></p>
      <p style="font-size:0.78rem; color:#6b7280;">Recibes esto por tener Premium activo en Radar de Nichos.</p>
    </div>"""


def send_email(to_email, html):
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": RESEND_FROM_EMAIL,
                "to": [to_email],
                "subject": "🚀 Nuevos nichos explosivos en el radar",
                "html": html,
            },
            timeout=20,
        )
        if resp.status_code >= 300:
            print(f"Error enviando a {to_email}: {resp.status_code} {resp.text}", file=sys.stderr)
            return False
        return True
    except requests.exceptions.RequestException as exc:
        print(f"Error de red enviando a {to_email}: {exc}", file=sys.stderr)
        return False


def main():
    stripe_ready = bool(STRIPE_SECRET_KEY)
    email_ready = bool(RESEND_API_KEY and RESEND_FROM_EMAIL)
    telegram_ready = bool(TELEGRAM_BOT_TOKEN and UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN)

    if not stripe_ready:
        print("Falta STRIPE_SECRET_KEY -- no se puede saber quien es Premium, no se envia nada.")
        return
    if not email_ready and not telegram_ready:
        print("Ni email (Resend) ni Telegram estan configurados -- no se envia ninguna alerta hoy.")
        return

    history = load_json(HISTORY_FILE, {})
    today, new_explosive = find_new_explosive(history)
    if not today:
        print("Sin datos en history.json todavia.")
        return

    if not new_explosive:
        print("Ningun nicho nuevo en 'explosivo' hoy -- no se envia alerta.")
        return

    last_alert = load_json(LAST_ALERT_FILE, {})
    if last_alert.get("date") == today:
        print(f"Ya se envio la alerta de {today} en una ejecucion anterior -- no se repite.")
        return

    try:
        customers = fetch_active_subscriber_customers()
    except Exception as exc:
        print(f"Fallo consultando suscriptores activos en Stripe: {exc}", file=sys.stderr)
        return

    if not customers:
        print("No hay suscriptores Premium activos a los que avisar.")
        return

    email_sent = 0
    telegram_sent = 0

    if email_ready:
        html = build_email_html(new_explosive)
        for customer in customers:
            if customer.get("email") and send_email(customer["email"], html):
                email_sent += 1

    if telegram_ready:
        text = build_telegram_text(new_explosive)
        for customer in customers:
            chat_id = redis_get(f"telegram:{customer['id']}")
            if chat_id and send_telegram_message(chat_id, text):
                telegram_sent += 1

    print(
        f"Alerta de {len(new_explosive)} nicho(s) nuevo(s) en explosivo -- "
        f"email: {email_sent}/{len(customers)}, telegram: {telegram_sent}/{len(customers)}."
    )

    save_json(LAST_ALERT_FILE, {
        "date": today,
        "niches": [n["name"] for n in new_explosive],
        "email_sent": email_sent,
        "telegram_sent": telegram_sent,
    })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Las alertas son un extra Premium, no el nucleo del radar -- si algo
        # inesperado revienta aqui, se avisa y se sale limpio en vez de tirar
        # todo el workflow por un paso que no es critico.
        print(f"AVISO: alert_premium.py fallo de forma inesperada: {exc}", file=sys.stderr)
