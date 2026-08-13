# Radar de Nichos

Vigila el interés de búsqueda (Google Trends, España) de una lista de nichos cada día,
guarda el histórico y te avisa por Telegram si alguno sube fuerte.

## Qué mide y qué no

- **Sí mide**: tendencia relativa de interés de búsqueda en Google (0-100), comparando
  la última semana con la anterior. Sirve para comparar nichos entre sí y detectar
  subidas de demanda.
- **No mide**: volumen absoluto de búsquedas ni nivel de competencia (para eso hacen
  falta herramientas de pago tipo Ahrefs/Semrush). Trátalo como una señal para decidir
  dónde mirar más de cerca, no como un veredicto final.

## Puesta en marcha (todo gratis)

1. **Sube esta carpeta a un repo nuevo en GitHub.**

2. **Crea un bot de Telegram** (si no quieres usar uno que ya tengas):
   - Habla con [@BotFather](https://t.me/BotFather) en Telegram → `/newbot` → te da un token.
   - Escríbele algo a tu bot, luego visita
     `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` para sacar tu `chat_id`.

3. **Añade los secrets en GitHub**: Settings → Secrets and variables → Actions:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

4. **Activa GitHub Pages**: Settings → Pages → Source: rama `main`, carpeta `/ (root)`.
   Ahí tendrás el dashboard visible en `https://<tu-usuario>.github.io/<repo>/`.

5. El workflow (`.github/workflows/daily.yml`) se ejecuta solo cada día a las 07:00 UTC.
   También puedes lanzarlo a mano desde la pestaña **Actions → Radar de nichos diario → Run workflow**
   para probarlo ya mismo sin esperar a mañana.

## Tendencias diarias por país (dropshipping)

`dropship_trends.py` saca cada día el top de búsquedas en tendencia en EEUU y
Reino Unido (lista cruda de Google Trends, sin filtrar) y te lo manda por
Telegram. Es material en bruto: Google no te dice qué es un producto, así que
te toca revisar la lista tú y detectar patrones. Se ejecuta automáticamente
junto al radar de nichos en el mismo workflow diario, y se puede ver también
en el dashboard (`index.html`).

Para añadir más países, edita el diccionario `COUNTRIES` en `dropship_trends.py`
con el código de país que usa pytrends (p. ej. `"germany"`, `"france"`).

## Añadir o quitar nichos

Edita `keywords.json`. Cada entrada necesita:

```json
{"id": "identificador-unico", "name": "Nombre para mostrar", "query": "término de búsqueda en Google"}
```

Cuantos más nichos añadas, más tarda la ejecución (Google Trends limita la velocidad
de consultas) — con 8-15 nichos va sobrado para una ejecución diaria.

## Ajustar la sensibilidad de las alertas

En `track_trends.py`:
- `ALERT_THRESHOLD_PCT` — % de subida semanal que dispara aviso (por defecto 25%)
- `MIN_INTEREST_FOR_ALERT` — interés mínimo para no avisar de ruido en nichos con poco volumen
