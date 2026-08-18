// Genera un codigo temporal (15 min) que enlaza a un cliente Premium con su
// cuenta de Telegram. El usuario lo usa enviando /start <codigo> al bot; el
// webhook (api/telegram-webhook.js) completa el enlace guardando su chat_id.
//
// Necesita las mismas variables que ya usa check-premium.js (STRIPE_SECRET_KEY)
// mas UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN (cuenta gratuita en
// upstash.com, sirve como almacen key-value sin gestionar un servidor) y
// TELEGRAM_BOT_USERNAME (el @usuario de tu bot, sin la @).
const Stripe = require("stripe");

const CODE_TTL_SECONDS = 900; // 15 minutos

function randomCode() {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // sin caracteres ambiguos
  let code = "";
  for (let i = 0; i < 6; i++) code += chars[Math.floor(Math.random() * chars.length)];
  return code;
}

async function redisSetex(key, seconds, value) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/setex/${encodeURIComponent(key)}/${seconds}/${encodeURIComponent(value)}`;
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!resp.ok) throw new Error(`Upstash setex fallo: ${resp.status}`);
}

module.exports = async (req, res) => {
  if (!process.env.STRIPE_SECRET_KEY) {
    return res.status(500).json({ error: "Stripe no esta configurado todavia." });
  }
  if (!process.env.UPSTASH_REDIS_REST_URL || !process.env.UPSTASH_REDIS_REST_TOKEN) {
    return res.status(500).json({ error: "El enlace con Telegram todavia no esta configurado (falta Upstash)." });
  }
  if (!process.env.TELEGRAM_BOT_USERNAME) {
    return res.status(500).json({ error: "Falta configurar TELEGRAM_BOT_USERNAME." });
  }

  let customerId;
  try {
    const body = typeof req.body === "object" && req.body ? req.body : JSON.parse(req.body || "{}");
    customerId = body.customerId;
  } catch (e) {
    return res.status(400).json({ error: "Peticion invalida." });
  }
  if (!customerId) return res.status(400).json({ error: "Falta customerId." });

  const stripe = Stripe(process.env.STRIPE_SECRET_KEY);
  try {
    const subs = await stripe.subscriptions.list({ customer: customerId, status: "active", limit: 1 });
    if (subs.data.length === 0) {
      return res.status(403).json({ error: "Esta cuenta no tiene Premium activo." });
    }
  } catch (err) {
    return res.status(500).json({ error: "No se pudo comprobar la suscripcion." });
  }

  const code = randomCode();
  try {
    await redisSetex(`link:${code}`, CODE_TTL_SECONDS, customerId);
  } catch (err) {
    return res.status(500).json({ error: "No se pudo generar el codigo de enlace." });
  }

  res.status(200).json({
    code,
    expiresInSeconds: CODE_TTL_SECONDS,
    deepLink: `https://t.me/${process.env.TELEGRAM_BOT_USERNAME}?start=${code}`,
  });
};
