// Suscripcion al resumen semanal GRATIS (nichos que mas subieron esa
// semana). Distinto de api/waitlist.js (esa es la lista de espera de
// Premium) -- aqui el email se guarda en un SET de Upstash (no una lista)
// porque necesitamos que no se repita: a este si le vamos a mandar
// correos de verdad cada semana, y un email duplicado significaria
// mandarle el mismo correo dos veces a la misma persona.

function isValidEmail(email) {
  return typeof email === "string" && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= 200;
}

async function redisSetAdd(key, member) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/sadd/${encodeURIComponent(key)}/${encodeURIComponent(member)}`;
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
    // Degrada con elegancia: el mensaje de "apuntado" se muestra igual en
    // el frontend aunque no se pueda guardar de verdad, para no romper la
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
    const stored = await redisSetAdd("digest:subscribers", email);
    res.status(200).json({ ok: true, stored });
  } catch (err) {
    res.status(200).json({ ok: true, stored: false });
  }
};
