// Webhook de Telegram. Recibe el mensaje "/start CODIGO" que el usuario envia
// al abrir el enlace generado por api/telegram-link-code.js, resuelve el
// codigo contra Upstash y guarda el chat_id asociado a ese cliente Premium
// para que alert_premium.py pueda escribirle mas adelante.
//
// Configuracion en Telegram (una sola vez, sustituye BOT_TOKEN, TU_DOMINIO y
// UN_SECRETO_TUYO):
//   curl "https://api.telegram.org/botBOT_TOKEN/setWebhook?url=https://TU_DOMINIO/api/telegram-webhook&secret_token=UN_SECRETO_TUYO"
// Y guarda ese mismo UN_SECRETO_TUYO como TELEGRAM_WEBHOOK_SECRET en Vercel.

async function redisGet(key) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/get/${encodeURIComponent(key)}`;
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!resp.ok) return null;
  const data = await resp.json();
  return data.result || null;
}

async function redisSet(key, value) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/set/${encodeURIComponent(key)}/${encodeURIComponent(value)}`;
  await fetch(url, { headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` } });
}

async function redisDel(key) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/del/${encodeURIComponent(key)}`;
  await fetch(url, { headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` } });
}

async function sendTelegramMessage(chatId, text) {
  await fetch(`https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
}

module.exports = async (req, res) => {
  // Verifica que la peticion viene realmente de Telegram, no de cualquiera
  // que adivine la URL del webhook.
  if (process.env.TELEGRAM_WEBHOOK_SECRET) {
    const headerSecret = req.headers["x-telegram-bot-api-secret-token"];
    if (headerSecret !== process.env.TELEGRAM_WEBHOOK_SECRET) {
      return res.status(401).end();
    }
  }

  // Responder 200 siempre y rapido -- Telegram reintenta si no lo hacemos,
  // y no queremos reintentos duplicados de un enlace ya completado.
  res.status(200).end();

  try {
    const update = typeof req.body === "object" && req.body ? req.body : JSON.parse(req.body || "{}");
    const message = update.message;
    if (!message || !message.text) return;

    const chatId = message.chat.id;
    const text = message.text.trim();

    if (!text.startsWith("/start")) {
      await sendTelegramMessage(chatId, "Para vincular tu cuenta, pulsa el botón \"Vincular Telegram\" en Radar de Nichos y usa el enlace que te da.");
      return;
    }

    const parts = text.split(" ");
    const code = parts[1];
    if (!code) {
      await sendTelegramMessage(chatId, "Falta el código de enlace. Vuelve a Radar de Nichos y pulsa \"Vincular Telegram\" de nuevo.");
      return;
    }

    const customerId = await redisGet(`link:${code}`);
    if (!customerId) {
      await sendTelegramMessage(chatId, "Ese código ha caducado o no es válido. Genera uno nuevo desde Radar de Nichos.");
      return;
    }

    await redisSet(`telegram:${customerId}`, String(chatId));
    await redisDel(`link:${code}`);
    await sendTelegramMessage(chatId, "✅ Cuenta vinculada. A partir de ahora te aviso aquí en cuanto un nicho entre en \"Explosivo\".");
  } catch (err) {
    console.error("Error en telegram-webhook:", err);
  }
};
