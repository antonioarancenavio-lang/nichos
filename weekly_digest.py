"""
Envia el resumen semanal GRATIS a quien se ha apuntado en la web
(distinto de las alertas Premium de alert_premium.py). Pensado para
correr una vez por semana (ver .github/workflows/daily.yml, se dispara
solo con el cron de los lunes).

Mismo nivel de detalle que el resto del plan gratuito: nombre, categoria,
tendencia (flecha) e interes por rango -- nunca la cifra exacta, eso sigue
siendo el gancho para pasarse a Premium. El objetivo de este email no es
dar el dato completo, es traer de vuelta al sitio a gente que no iba a
volver por su cuenta.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_blog as gb  # reutiliza slugify, chg_class, interest_bucket, split_entries, etc.

ROOT = Path(__file__).resolve().parent
LAST_SENT_FILE = ROOT / "data" / "last_digest_sent.json"

UPSTASH_REDIS_REST_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "")
SITE_URL = os.environ.get("SITE_URL", "https://TU-DOMINIO-AQUI")

TOP_N = 8


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"AVISO: {path.name} esta corrupto ({e}) -- se continua con datos vacios.", file=sys.stderr)
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_subscribers():
    if not (UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN):
        print("Sin credenciales de Upstash -- no se puede leer la lista de suscriptores.")
        return []
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_REST_URL}/smembers/digest:subscribers",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_REST_TOKEN}"},
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"Error leyendo suscriptores de Upstash: {resp.status_code}", file=sys.stderr)
            return []
        return resp.json().get("result", []) or []
    except requests.exceptions.RequestException as exc:
        print(f"Error de red leyendo suscriptores: {exc}", file=sys.stderr)
        return []


def build_email_html(top_movers, fecha):
    rows = []
    for item in top_movers:
        cls = gb.chg_class(item["weekly_change_pct"])
        arrow = "▲" if cls == "up" else ("▼" if cls == "down" else "→")
        color = "#2f7d4f" if cls == "up" else ("#a33b2b" if cls == "down" else "#7a7a7a")
        slug = gb.slugify(item["name"])
        rows.append(f"""
        <tr>
          <td style="padding:10px 0; border-bottom:1px solid #e5ddd0;">
            <a href="{SITE_URL}/nicho-{slug}.html" style="color:#1c1812; text-decoration:none; font-weight:600;">{gb.esc(item['name'])}</a>
            <div style="font-size:12px; color:#8a8578; margin-top:2px;">{item.get('category', 'otros')} · interés: {gb.interest_bucket(item['current'])}</div>
          </td>
          <td style="padding:10px 0; border-bottom:1px solid #e5ddd0; text-align:right; color:{color}; font-weight:700; font-family:monospace;">{arrow}</td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html lang="es"><body style="margin:0; padding:0; background:#e5ddd0; font-family:-apple-system,Segoe UI,sans-serif;">
<div style="max-width:520px; margin:0 auto; padding:28px 20px;">
  <div style="background:#faf7f0; border:1px solid #e5ddd0; border-top:3px solid #a33b2b; border-radius:6px; padding:26px 24px;">
    <div style="font-size:12px; letter-spacing:0.05em; text-transform:uppercase; color:#8a8578; margin-bottom:4px;">Radar de Nichos · resumen semanal</div>
    <h1 style="font-size:20px; margin:0 0 4px; color:#1c1812;">Lo que más ha crecido esta semana</h1>
    <div style="font-size:13px; color:#8a8578; margin-bottom:20px;">{fecha}</div>
    <table style="width:100%; border-collapse:collapse;">
      {''.join(rows)}
    </table>
    <p style="font-size:13px; color:#5a5548; margin-top:22px; line-height:1.6;">
      Cifras exactas, ranking completo y kit de lanzamiento SEO por nicho, con
      <a href="{SITE_URL}/planes.html" style="color:#a33b2b; font-weight:600;">Radar de Nichos Premium</a>.
    </p>
    <a href="{SITE_URL}/tendencias.html" style="display:inline-block; margin-top:6px; background:#a33b2b; color:#fff; text-decoration:none; padding:10px 18px; border-radius:4px; font-weight:600; font-size:14px;">Ver ranking completo →</a>
  </div>
  <p style="text-align:center; font-size:11px; color:#8a8578; margin-top:16px;">
    Recibes esto porque te apuntaste en {SITE_URL}. <a href="{SITE_URL}/api/unsubscribe-digest?email={{EMAIL}}" style="color:#8a8578;">Darse de baja</a>.
  </p>
</div>
</body></html>"""


def send_email(to_email, html_template):
    html = html_template.replace("{EMAIL}", to_email)
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from": RESEND_FROM_EMAIL,
                "to": [to_email],
                "subject": "📈 Lo que más ha crecido esta semana — Radar de Nichos",
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
    if not (RESEND_API_KEY and RESEND_FROM_EMAIL):
        print("Sin RESEND_API_KEY/RESEND_FROM_EMAIL configurados -- no se envia el resumen semanal.")
        return

    history = gb.load_history()
    dates = sorted(history.keys())
    if not dates:
        print("Sin datos todavia, no se envia el resumen semanal.")
        return

    last_date = dates[-1]
    entries = list(history[last_date].items())
    growth, _nuevos, _excluded = gb.split_entries(entries)
    top_movers = [item for item in growth if item["weekly_change_pct"] and item["weekly_change_pct"] > 0][:TOP_N]

    if not top_movers:
        print("Sin subidas relevantes esta semana -- no se envia el resumen (mejor nada que un email vacio).")
        return

    subscribers = get_subscribers()
    if not subscribers:
        print("Sin suscriptores todavia -- no hay a quien enviar.")
        return

    fecha = gb.fecha_legible(last_date)
    html_template = build_email_html(top_movers, fecha)

    sent, failed = 0, 0
    for email in subscribers:
        if send_email(email, html_template):
            sent += 1
        else:
            failed += 1

    print(f"Resumen semanal: {sent} enviados, {failed} fallidos, de {len(subscribers)} suscriptores.")
    save_json(LAST_SENT_FILE, {
        "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "enviados": sent,
        "fallidos": failed,
        "total_suscriptores": len(subscribers),
    })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # El resumen semanal es un extra, no el nucleo del radar -- si algo
        # inesperado revienta aqui, se avisa y se sale limpio en vez de
        # tirar todo el workflow por un paso que no es critico.
        print(f"AVISO: weekly_digest.py fallo de forma inesperada: {exc}", file=sys.stderr)
