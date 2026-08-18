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

SOBRE LA FIABILIDAD DE LOS DATOS (procedencia y solidez)
---------------------------------------------------------
- Cada item guardado en data/history.json lleva "source", "last_checked" y
  "stale" para que quede constancia de cuando se consulto de verdad y si el
  dato de hoy es una consulta fresca o un valor heredado de un dia anterior
  porque la consulta de hoy fallo.
- Un fallo puntual de Google Trends (bloqueo temporal, timeout) YA NO borra
  el nicho del radar de un dia para otro: se conserva el ultimo valor valido
  marcado como "stale": true, en vez de hacerlo desaparecer o resetear a 0,
  que seria enganoso.
- Se lleva la cuenta de fallos consecutivos por nicho en data/health.json. Si
  un nicho lleva varios dias seguidos sin poder consultarse, se avisa por
  Telegram por separado (puede que el termino ya no exista o que algo se
  haya roto de verdad, no solo un bloqueo puntual).
- Los candidatos nuevos que fallan por un error tecnico (no por falta de
  datos real) NO se pierden: se quedan en data/pending.json para
  reintentarse en la proxima ejecucion, en vez de evaluarse como "sin
  interes" con datos incompletos.
- Los valores de interes se acotan siempre a 0-100 antes de guardarse, para
  que una respuesta corrupta de la fuente no contamine el historico.
- Todas las escrituras a disco son atomicas (se escribe en un archivo
  temporal y se renombra), asi un fallo a mitad de ejecucion nunca deja un
  data/history.json a medio escribir o corrupto.

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
import time
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
RUN_LOG_FILE = ROOT / "data" / "last_run.json"
HEALTH_FILE = ROOT / "data" / "health.json"

DATA_SOURCE = "google_trends_es"

# % de subida semana a semana que dispara una alerta
ALERT_THRESHOLD_PCT = 25
# interes minimo (0-100) para que una subida se considere relevante y no ruido
MIN_INTEREST_FOR_ALERT = 5
# interes semanal minimo para que un candidato nuevo se promocione al nucleo
PROMOTION_THRESHOLD = 15
# tope maximo de nichos en el nucleo (evita que la ejecucion diaria crezca sin fin)
MAX_CORE_KEYWORDS = 150
# reintentos si trendspyg falla de forma intermitente (timeouts, bloqueos puntuales)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 20
# dias seguidos de fallo tecnico en un mismo nicho antes de avisar por separado
CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 5
# dias seguidos de fallo antes de dejar de reintentar un candidato nuevo (no del nucleo)
CANDIDATE_MAX_RETRY_DAYS = 3

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


class TransientFetchError(Exception):
    """Fallo tecnico (red, timeout, bloqueo puntual) -- se debe reintentar
    otro dia, no se debe interpretar como 'sin demanda real'."""


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
    """Escritura atomica: escribe en un archivo temporal y renombra, para que
    un fallo a mitad de escritura nunca deje el archivo real corrupto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def clamp_0_100(value):
    return max(0.0, min(100.0, value))


def pct_change(current, previous):
    if previous > 0:
        return ((current - previous) / previous) * 100
    return 100.0 if current > 0 else 0.0


def avg(values):
    return sum(values) / len(values) if values else 0.0


def analyze_series(values):
    # Acotamos cada punto a 0-100 antes de nada: si la fuente devuelve algo
    # fuera de rango (respuesta corrupta o cambio de formato aguas arriba),
    # no queremos que se propague al historico ni a las clasificaciones.
    values = [clamp_0_100(v) for v in values]

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
    """Devuelve las estadisticas de un termino, o None si Google Trends
    responde correctamente pero sin datos (sin demanda medible -- resultado
    legitimo). Si hay un fallo tecnico tras agotar los reintentos, lanza
    TransientFetchError en vez de devolver None, para no confundir 'sin
    demanda' con 'no se ha podido consultar'."""
    last_exc = None
    env = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            env = download_google_trends_explore(query, geo="ES")
            break
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_SECONDS * attempt
                print(f"    Intento {attempt} fallido ({exc}); espero {wait}s y reintento...")
                time.sleep(wait)
            else:
                raise TransientFetchError(str(exc)) from exc

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


def fetch_reddit_mentions(query):
    """Señal complementaria gratuita: cuantas discusiones recientes hay en Reddit
    sobre el termino. No requiere API key (endpoint publico de busqueda).
    Devuelve None (no un 0) si no se ha podido comprobar, para no confundir
    'sin menciones' con 'no se ha podido consultar Reddit'."""
    try:
        resp = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": query, "limit": 10, "sort": "new"},
            headers={"User-Agent": "radar-nichos/1.0 (contacto via GitHub)"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return len(data.get("data", {}).get("children", []))
    except Exception:
        return None


def classify_trend(stats):
    """Clasificacion inspirada en Exploding Topics (Regular/Peaked/Exploding),
    pero exigiendo crecimiento sostenido en semana Y mes para evitar marcar
    como 'explosivo' un pico de un solo dia (filtro anti-moda-pasajera)."""
    weekly, monthly = stats["weekly_change_pct"], stats["monthly_change_pct"]
    if weekly >= 25 and monthly >= 15:
        return "explosivo"
    if weekly <= -15 and monthly <= -10:
        return "pico_pasado"
    if weekly >= 10:
        return "en_subida"
    if weekly <= -5:
        return "en_caida"
    return "estable"


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


def score_one(kw_id, query, name, category, today, day_snapshot, alerts, health,
              previous_snapshot, failed_ids):
    """Intenta consultar un termino. Si falla por un motivo tecnico, hereda el
    ultimo valor valido conocido (marcado como stale) en vez de hacer
    desaparecer el nicho del radar por un bloqueo puntual de la fuente."""
    try:
        stats = fetch_trend(query)
    except TransientFetchError as exc:
        print(f"  Fallo tecnico consultando '{query}': {exc}", file=sys.stderr)
        failed_ids.add(kw_id)
        record = health.get(kw_id, {"consecutive_failures": 0, "last_success": None})
        record["consecutive_failures"] = record.get("consecutive_failures", 0) + 1
        health[kw_id] = record

        previous = previous_snapshot.get(kw_id)
        if previous:
            carried = {**previous, "name": name, "query": query, "category": category, "stale": True}
            day_snapshot[kw_id] = carried
            if record["consecutive_failures"] >= CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
                alerts.append(
                    f"\u26A0\uFE0F <b>{name}</b>: lleva {record['consecutive_failures']} dias seguidos "
                    f"sin poder consultarse. Mostrando el ultimo dato valido (de {record.get('last_success', 'fecha desconocida')})."
                )
        return None

    if stats is None:
        # Respuesta correcta de la fuente, pero sin datos de interes -- es un
        # resultado legitimo, no un fallo tecnico.
        return None

    health[kw_id] = {"consecutive_failures": 0, "last_success": today}

    stats["classification"] = classify_trend(stats)
    stats["reddit_mentions"] = fetch_reddit_mentions(query)
    stats["source"] = DATA_SOURCE
    stats["last_checked"] = today
    stats["stale"] = False

    day_snapshot[kw_id] = {"name": name, "query": query, "category": category, **stats}

    if stats["classification"] == "explosivo":
        alerts.append(
            f"\U0001F680 <b>{name}</b>: crecimiento sostenido (semana +{stats['weekly_change_pct']:.0f}%, "
            f"mes +{stats['monthly_change_pct']:.0f}%) \u2014 clasificado como EXPLOSIVO"
        )
    return stats


def main():
    keywords = load_json(KEYWORDS_FILE, [])
    pending = load_json(PENDING_FILE, [])
    discarded = load_json(DISCARDED_FILE, [])
    history = load_json(HISTORY_FILE, {})
    health = load_json(HEALTH_FILE, {})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    previous_dates = sorted(d for d in history.keys() if d < today)
    previous_snapshot = history[previous_dates[-1]] if previous_dates else {}

    alerts = []
    day_snapshot = {}
    promoted_names = []
    discarded_names = []
    failed_ids = set()

    # 1) Nucleo ya validado
    total = len(keywords) + len(pending)
    n = 0
    for item in keywords:
        n += 1
        print(f"[{n}/{total}] (nucleo) Consultando '{item['query']}'...")
        score_one(item["id"], item["query"], item["name"], item.get("category", "otros"),
                  today, day_snapshot, alerts, health, previous_snapshot, failed_ids)

    # 2) Candidatos nuevos descubiertos hoy (o pendientes de dias anteriores
    # que fallaron por un motivo tecnico y se reintentan ahora)
    still_pending = []
    for item in pending:
        n += 1
        category = item.get("category", "otros")
        print(f"[{n}/{total}] (candidato) Consultando '{item['query']}'...")
        stats = score_one(item["id"], item["query"], item["name"], category,
                           today, day_snapshot, alerts, health, previous_snapshot, failed_ids)

        if item["id"] in failed_ids:
            # Fallo tecnico, no una evaluacion real: se reintenta, salvo que
            # ya se haya intentado demasiadas veces (para no quedarse
            # atascado para siempre con un candidato roto).
            retries = item.get("retry_count", 0) + 1
            if retries <= CANDIDATE_MAX_RETRY_DAYS:
                still_pending.append({**item, "retry_count": retries})
            else:
                print(f"  Candidato '{item['query']}' descartado tras {retries} intentos fallidos.")
            continue

        if stats is None:
            discarded.append(item["query"])
            discarded_names.append(item["name"])
        elif stats["week_avg"] >= PROMOTION_THRESHOLD:
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
            health.pop(kw["id"], None)
            print(f"  Jubilado por limite de nucleo: {kw['name']}")

    save_json(KEYWORDS_FILE, keywords)
    save_json(DISCARDED_FILE, discarded)
    save_json(PENDING_FILE, still_pending)
    save_json(HEALTH_FILE, health)

    history[today] = day_snapshot
    save_json(HISTORY_FILE, history)

    if promoted_names:
        alerts.append(
            "\U0001F195 Nichos nuevos promocionados al radar: " + ", ".join(promoted_names)
        )

    stale_count = sum(1 for item in day_snapshot.values() if item.get("stale"))
    run_log = {
        "fecha": today,
        "total_procesados": total,
        "nucleo_final": len(keywords),
        "promocionados": len(promoted_names),
        "descartados": len(discarded_names),
        "con_datos": len(day_snapshot),
        "con_error": len(failed_ids),
        "datos_frescos": len(day_snapshot) - stale_count,
        "datos_heredados_stale": stale_count,
        "reintentando_candidatos": len(still_pending),
    }
    save_json(RUN_LOG_FILE, run_log)

    error_rate = run_log["con_error"] / total if total else 0
    if error_rate >= 0.3:
        alerts.append(
            f"\u26A0\uFE0F Aviso de salud: {run_log['con_error']}/{total} consultas fallaron hoy "
            f"({error_rate:.0%}). Puede que Google Trends este bloqueando o que algo se haya roto."
        )

    if alerts:
        send_telegram_alert("Radar de nichos \u2014 novedades de hoy:\n\n" + "\n".join(alerts))
    else:
        print("Sin subidas ni promociones relevantes hoy.")

    print(
        f"\nResumen: {len(keywords)} en nucleo, {len(promoted_names)} promocionados, "
        f"{len(discarded_names)} descartados, {stale_count} con dato heredado (stale), "
        f"{len(still_pending)} candidatos en reintento."
    )


if __name__ == "__main__":
    main()
