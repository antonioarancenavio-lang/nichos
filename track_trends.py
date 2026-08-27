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
# cuantos dias de historico se conservan (60 es lo minimo que necesita el
# calculo mensual; se deja el doble de margen)
HISTORY_RETENTION_DAYS = 120
# si fallan mas de esta proporcion de consultas, el snapshot de hoy no es
# fiable -- mejor no guardarlo (dejaria "agujeros" falsos en el historico
# de casi todos los nichos) que envenenar la base de datos con un dia malo
CATASTROPHIC_ERROR_RATE = 0.7

# --- Disyuntor de fallos por tasa (no por racha) -----------------------
# Cuando Google Trends bloquea o cambia de pagina, los fallos NO suelen
# venir en racha (ver logs reales: fallan ~1 de cada 3, intercalados con
# exitos) -- una consulta que solo mira "N fallos seguidos" nunca se
# dispara con ese patron. Por eso se mide la tasa de fallo acumulada del
# dia: en cuanto se confirma con una muestra minima que el problema es
# sistemico, se deja de reintentar cada keyword (que solo malgasta 20-60s
# de espera por keyword sin ninguna posibilidad real de exito) y se pasa
# a un solo intento rapido por keyword para terminar la lista sin agotar
# el tiempo limite del workflow.
CIRCUIT_MIN_SAMPLE = 15
CIRCUIT_FAILURE_RATE = 0.5

_total_attempts = 0
_total_failures = 0
_circuit_open = False


def _maybe_open_circuit():
    global _circuit_open
    if _circuit_open or _total_attempts < CIRCUIT_MIN_SAMPLE:
        return
    if _total_failures / _total_attempts >= CIRCUIT_FAILURE_RATE:
        _circuit_open = True
        print(
            f"    AVISO: {_total_failures}/{_total_attempts} consultas han fallado hoy "
            f"({_total_failures / _total_attempts:.0%}) -- Google Trends parece estar "
            f"bloqueando o ha cambiado de pagina. Se deja de reintentar cada keyword "
            f"(ya no serviria de nada) para acabar la lista rapido y no agotar el tiempo "
            f"del workflow."
        )

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:60]


def load_json(path, default):
    """Si el fichero esta corrupto (JSON a medias, disco lleno a mitad de
    escritura anterior, etc.) no queremos que el script reviente sin mas
    -- se intenta restaurar desde el backup que deja save_json() y, si
    tampoco existe o tambien esta mal, se avisa fuerte y se sigue con el
    valor por defecto en vez de tirar todo el proceso abajo."""
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"AVISO GRAVE: {path.name} esta corrupto ({e}).")
        backup_path = path.with_suffix(path.suffix + ".bak")
        if backup_path.exists():
            try:
                with open(backup_path, encoding="utf-8") as f:
                    data = json.load(f)
                print(f"Restaurado {path.name} desde el backup {backup_path.name}.")
                return data
            except json.JSONDecodeError:
                print(f"El backup {backup_path.name} tambien esta corrupto.")
        print(f"Sin backup valido para {path.name} -- se continua con datos vacios.")
        return default


def save_json(path, data, keep_backup=False, compact=False):
    """Escritura atomica: se escribe primero en un fichero temporal en el
    MISMO directorio y solo al final se renombra sobre el definitivo
    (os.replace es atomico en POSIX). Si el proceso se corta a mitad
    (falla la Action, se queda sin memoria, lo que sea), el fichero
    original queda intacto en vez de a medio escribir -- antes una
    interrupcion en mal momento podia dejar el JSON corrupto y tirar
    todo el sitio abajo, porque todo depende de estos ficheros.

    keep_backup=True ademas guarda una copia del contenido ANTERIOR en
    <fichero>.bak antes de sustituirlo, como red de seguridad extra para
    history.json: si un bug (no un crash) escribe datos malos pero
    validos como JSON, el backup permite recuperar el ultimo estado bueno
    a mano.

    compact=True quita la indentacion (para history.json, que el
    navegador descarga entero en cada visita y nadie lee a mano). El
    resto de ficheros se guardan legibles porque sirven tambien como
    registro humano en los diffs de Git."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if keep_backup and path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        try:
            backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass  # el backup es un extra, no bloquea el guardado principal

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def prune_history(history, keep_days=120):
    """Solo hacen falta 60 dias de historico para el calculo mensual
    (values[-60:-30] en analyze_series) -- guardar mas no aporta nada a
    los calculos, solo hace crecer el fichero para siempre y lo hace mas
    lento de descargar en cada visita al dashboard. Se deja un margen
    generoso (120 dias, el doble de lo necesario) en vez del minimo justo."""
    dates = sorted(history.keys())
    if len(dates) <= keep_days:
        return history, 0
    to_drop = dates[:-keep_days]
    for d in to_drop:
        del history[d]
    return history, len(to_drop)


def pct_change(current, previous):
    """Devuelve None cuando no hay una base fiable (semana/mes anterior en 0):
    un salto de 0 a cualquier valor no es una 'subida del 100%' real, es la
    ausencia de histórico. None se trata como 'sin dato suficiente' en vez
    de inventar un porcentaje."""
    if previous > 0:
        return round(((current - previous) / previous) * 100, 1)
    return None


def avg(values):
    return sum(values) / len(values) if values else 0.0


def analyze_series(values):
    current = values[-1]
    yesterday = values[-2] if len(values) >= 2 else current
    daily_change = pct_change(current, yesterday)

    last_week = values[-7:]
    prev_week = values[-14:-7] if len(values) >= 14 else []
    week_avg = avg(last_week)
    weekly_change = pct_change(week_avg, avg(prev_week)) if prev_week else None

    last_month = values[-30:]
    prev_month = values[-60:-30] if len(values) >= 60 else []
    month_avg = avg(last_month)
    monthly_change = pct_change(month_avg, avg(prev_month)) if prev_month else None

    return {
        "current": round(current, 1),
        "daily_change_pct": daily_change,
        "week_avg": round(week_avg, 1),
        "weekly_change_pct": weekly_change,
        "month_avg": round(month_avg, 1),
        "monthly_change_pct": monthly_change,
    }


def fetch_trend(query):
    global _total_attempts, _total_failures, _circuit_open

    last_exc = None
    attempt = 0
    while True:
        attempt += 1
        try:
            env = download_google_trends_explore(query, geo="ES")
            _total_attempts += 1
            break
        except Exception as exc:
            last_exc = exc
            # Se cuenta CADA intento (no solo el resultado final de la
            # keyword) para que el disyuntor detecte el problema en
            # cuestion de segundos, no despues de agotar reintentos
            # completos en 15 keywords seguidas.
            _total_attempts += 1
            _total_failures += 1
            _maybe_open_circuit()
            if _circuit_open or attempt >= MAX_RETRIES:
                raise last_exc
            wait = RETRY_BACKOFF_SECONDS * attempt
            print(f"    Intento {attempt} fallido ({exc}); espero {wait}s y reintento...")
            time.sleep(wait)

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
    sobre el termino. No requiere API key (endpoint publico de busqueda)."""
    try:
        resp = requests.get(
            "https://www.reddit.com/search.json",
            params={"q": query, "limit": 10, "sort": "new"},
            headers={"User-Agent": "radar-nichos/1.0"},
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
    como 'explosivo' un pico de un solo dia (filtro anti-moda-pasajera).

    Dos casos especiales para no inventar tendencias sobre datos vacios:
    - 'sin_interes': Google Trends no registra busquedas (current == 0). No
      hay nada que clasificar todavia; se excluye de los rankings publicos.
    - 'nuevo': hay interes real (current > 0) pero aun no hay una semana/mes
      anterior con el que comparar, asi que no se calcula un % de cambio.
    """
    if stats["current"] == 0:
        return "sin_interes"
    weekly, monthly = stats["weekly_change_pct"], stats["monthly_change_pct"]
    if weekly is None or monthly is None:
        return "nuevo"
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


def score_one(kw_id, query, name, category, day_snapshot, alerts):
    try:
        stats = fetch_trend(query)
    except Exception as exc:
        print(f"  Error consultando '{query}': {exc}", file=sys.stderr)
        return None
    if stats is None:
        return None

    stats["classification"] = classify_trend(stats)
    stats["reddit_mentions"] = fetch_reddit_mentions(query)

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
            if item["query"] not in discarded:
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

    total_for_rate = total if total else 1
    error_rate = (total - len(day_snapshot)) / total_for_rate

    # Guardia de sanidad: si hoy ha fallado la gran mayoria de consultas
    # (Google Trends bloqueando, Chrome roto en el runner, lo que sea), no
    # tiene sentido escribir un snapshot practicamente vacio -- eso
    # envenenaria el historico con un "dia hueco" para casi todos los
    # nichos y desajustaria sus calculos de tendencia. Mejor conservar el
    # ultimo dia bueno y avisar fuerte que guardar basura silenciosamente.
    if error_rate >= CATASTROPHIC_ERROR_RATE:
        print(
            f"AVISO GRAVE: {total - len(day_snapshot)}/{total} consultas fallaron hoy "
            f"({error_rate:.0%}) -- NO se guarda el snapshot de hoy para no danar el historico. "
            f"Se mantiene el ultimo dia bueno."
        )
        alerts.append(
            f"\u26D4 Fallo grave: {error_rate:.0%} de las consultas fallaron hoy. No se ha "
            f"actualizado el historico para no guardar datos malos -- revisa el runner."
        )
    else:
        history[today] = day_snapshot
        history, dropped = prune_history(history, keep_days=HISTORY_RETENTION_DAYS)
        if dropped:
            print(f"Historico podado: {dropped} dia(s) mas antiguos que {HISTORY_RETENTION_DAYS} dias eliminados.")
        save_json(HISTORY_FILE, history, keep_backup=True, compact=True)

    if promoted_names:
        alerts.append(
            "\U0001F195 Nichos nuevos promocionados al radar: " + ", ".join(promoted_names)
        )

    run_log = {
        "fecha": today,
        "total_procesados": total,
        "nucleo_final": len(keywords),
        "promocionados": len(promoted_names),
        "descartados": len(discarded_names),
        "con_datos": len(day_snapshot),
        "con_error": total - len(day_snapshot),
    }
    save_json(RUN_LOG_FILE, run_log)

    if 0.3 <= error_rate < CATASTROPHIC_ERROR_RATE:
        alerts.append(
            f"\u26A0\uFE0F Aviso de salud: {run_log['con_error']}/{total} consultas fallaron hoy "
            f"({error_rate:.0%}). Puede que Google Trends este bloqueando o que algo se haya roto."
        )

    if alerts:
        send_telegram_alert("Radar de nichos \u2014 novedades de hoy:\n\n" + "\n".join(alerts))
    else:
        print("Sin subidas ni promociones relevantes hoy.")

    print(f"\nResumen: {len(keywords)} en nucleo, {len(promoted_names)} promocionados, {len(discarded_names)} descartados.")
    if _circuit_open:
        print(
            f"Disyuntor activado hoy: {_total_failures}/{_total_attempts} consultas fallaron "
            f"({_total_failures / _total_attempts:.0%}) -- probable bloqueo de Google Trends, "
            f"no un fallo del codigo. Revisa el mensaje de error de arriba; si sigue igual "
            f"varios dias seguidos, puede que trendspyg necesite una actualizacion."
        )


if __name__ == "__main__":
    main()
