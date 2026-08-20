// Guarda un email en la lista de espera de Premium mientras el cobro con
// Stripe todavia no esta activo. Usa Upstash (el mismo almacen clave-valor
// que ya usa api/telegram-link-code.js) como una lista simple -- no hace
// falta ninguna base de datos nueva ni variables de entorno adicionales
// si ya tienes UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN configuradas
// para el enlace de Telegram.
//
// Para leer luego quien se ha apuntado: en la consola de Upstash, ejecuta
// el comando  LRANGE waitlist:premium 0 -1

function isValidEmail(email) {
  return typeof email === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= 200;
}

async function redisListPush(key, value) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/lpush/${encodeURIComponent(key)}/${encodeURIComponent(value)}`;
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  return resp.ok;
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Metodo no permitido" });
  }
  if (!process.env.UPSTASH_REDIS_REST_URL || !process.env.UPSTASH_REDIS_REST_TOKEN) {
    // Degrada con elegancia: el aviso "apuntado" se muestra igual en el
    // frontend aunque no se pueda guardar de verdad, para no romper la
    // experiencia si todavia no has configurado Upstash.
    return res.status(200).json({ ok: true, stored: false });
  }

  let email = "";
  try {
    const body = typeof req.body === "object" && req.body ? req.body : JSON.parse(req.body || "{}");
    email = (body.email || "").trim().toLowerCase();
  } catch (e) {
    return res.status(400).json({ error: "Cuerpo invalido" });
  }

  if (!isValidEmail(email)) {
    return res.status(400).json({ error: "Email no valido" });
  }

  try {
    const stored = await redisListPush("waitlist:premium", `${email}|${new Date().toISOString()}`);
    res.status(200).json({ ok: true, stored });
  } catch (err) {
    res.status(200).json({ ok: true, stored: false });
  }
};
