# Radar de Nichos

Estudio en expansión continua del interés de búsqueda (Google España) para
detectar oportunidades de negocio. No es una lista fija: cada día descubre
nichos nuevos solo, evalúa si tienen tirón real, y se autogestiona.

## Cómo funciona

1. **`discover_niches.py`** — prueba patrones tipo "calculadora de...",
   "modelo de...", "comparador de..." contra el autocompletado de Google
   (rápido, gratis, sin Chrome) y saca candidatos nuevos que la gente
   realmente busca. Deja hasta 15 candidatos nuevos por ejecución en
   `data/pending.json`.
2. **`track_trends.py`** — evalúa el interés real (Google Trends) tanto del
   núcleo ya validado (`keywords.json`) como de los candidatos nuevos de hoy.
   Los candidatos que superen un mínimo de interés (`PROMOTION_THRESHOLD`,
   por defecto 15/100) se promocionan automáticamente al núcleo y quedan en
   seguimiento diario para siempre. Los que no, se descartan y se anotan en
   `data/discarded.json` para no volver a probarlos.
3. Si el núcleo supera el límite (`MAX_CORE_KEYWORDS`, por defecto 150), se
   jubila el nicho con peor interés semanal actual antes de añadir uno nuevo
   — así la ejecución diaria no crece sin control.
4. **`index.html`** — dashboard con 4 pestañas: Top 10 diario, semanal,
   mensual y por índice de oportunidad, sobre todo lo que hay en seguimiento
   ese día (núcleo + lo recién promocionado).

## Qué mide y qué no

- **Interés (0-100)**: tendencia relativa de búsqueda en Google España,
  comparando su propio pico de los últimos 3 meses. No es volumen absoluto.
- **Índice de oportunidad**: heurística (demanda semanal ÷ nº de términos
  relacionados), NO es competencia real. Eso requiere herramientas de pago
  (Ahrefs, Semrush). Es una pista para investigar más, no un veredicto.

## Puesta en marcha (todo gratis)

1. Sube esta carpeta a un repo en GitHub.
2. Crea un bot de Telegram con [@BotFather](https://t.me/BotFather) (opcional,
   solo para recibir avisos) y saca tu `chat_id` visitando
   `https://api.telegram.org/bot<TU_TOKEN>/getUpdates` tras escribirle algo.
3. Añade los secrets en GitHub: Settings → Secrets and variables → Actions:
   `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
4. Activa GitHub Pages: Settings → Pages → Source: rama `main`, carpeta
   `/ (root)`.
5. El workflow (`.github/workflows/daily.yml`) corre solo cada día. También
   se puede lanzar a mano desde Actions → Run workflow.
6. Si usas Vercel en vez de GitHub Pages, añade un `vercel.json` con
   `{"buildCommand": "", "outputDirectory": ".", "framework": null}` en la
   raíz para que sirva los archivos estáticos sin intentar ejecutar Python.

## Activar el sistema de pago (Premium)

La web ya distingue entre gratis y Premium (Top 10 vs lista completa, 3
favoritos vs ilimitados, CSV bloqueado vs disponible). Para que el botón
"Hazte Premium" cobre de verdad, hace falta conectar Stripe:

1. Crea una cuenta en [stripe.com](https://stripe.com) (gratis, solo cobra
   comisión por transacción, sin coste fijo).
2. En el panel de Stripe, crea un producto de tipo suscripción (por ejemplo
   "Radar de Nichos Premium", 9€/mes) y copia el ID del precio (`price_...`).
3. Copia también tu clave secreta (`sk_live_...` o `sk_test_...` para probar
   primero sin cobrar de verdad).
4. En Vercel: Settings → Environment Variables, añade:
   - `STRIPE_SECRET_KEY` → tu clave secreta
   - `STRIPE_PRICE_ID` → el ID del precio mensual que creaste
   - `STRIPE_PRICE_ID_ANNUAL` → (opcional) el ID de un segundo precio anual, si quieres ofrecer el descuento anual que aparece en /planes.html
   - `SITE_URL` → tu dominio, por ejemplo `https://radar-nichos.vercel.app`
5. Vuelve a desplegar (Vercel lo hace solo al detectar el push, o dale a
   "Redeploy" manualmente).

Con eso, `/api/create-checkout`, `/api/verify-session` y `/api/check-premium`
ya funcionan de verdad. Sin esas variables configuradas, el botón "Hazte
Premium" avisa de que el pago aún no está activado, sin romper nada más.

**No hace falta base de datos propia** — Stripe es la fuente de verdad sobre
quién tiene suscripción activa; el navegador solo guarda el ID de cliente de
Stripe en `localStorage` y se comprueba en cada visita.

Para cambiar qué es gratis y qué es Premium, edita en `index.html`:
- `FREE_LIMIT` — cuántos nichos ve el plan gratis por pestaña (por defecto 10)
- `FREE_FAVORITES_LIMIT` — favoritos máximos en gratis (por defecto 3)
- `PREMIUM_PRICE_LABEL` — el texto del precio que se muestra en la web

## Ajustar el comportamiento

En `track_trends.py`:
- `PROMOTION_THRESHOLD` — interés mínimo para que un candidato nuevo pase al núcleo
- `MAX_CORE_KEYWORDS` — tope de nichos en seguimiento permanente
- `ALERT_THRESHOLD_PCT` / `MIN_INTEREST_FOR_ALERT` — sensibilidad de las alertas de Telegram

En `discover_niches.py`:
- `NEW_CANDIDATES_PER_RUN` — cuántos candidatos nuevos se prueban cada día
- `discovery_seeds.json` — patrones semilla; añade o quita los que quieras

## Nota sobre el tiempo de ejecución

Con muchos nichos en seguimiento, la ejecución diaria puede tardar bastante
(cada consulta de Google Trends tarda entre 10 y 90 segundos). Es normal y
no requiere hacer nada — GitHub Actions lo ejecuta en segundo plano.
