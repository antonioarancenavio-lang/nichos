// Baja del resumen semanal. Enlace simple por GET para que funcione con un
// solo clic desde el email (asi tiene que ser: la LSSI exige que darse de
// baja sea facil, un formulario con login no vale).

async function redisSetRemove(key, member) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/srem/${encodeURIComponent(key)}/${encodeURIComponent(member)}`;
  const resp = await fetch(url, {
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  return resp.ok;
}

module.exports = async (req, res) => {
  const email = (req.query.email || "").toString().trim().toLowerCase();
  res.setHeader("Content-Type", "text/html; charset=utf-8");

  if (!email || !process.env.UPSTASH_REDIS_REST_URL) {
    return res.status(400).send(pageHtml("Enlace no válido.", false));
  }

  try {
    await redisSetRemove("digest:subscribers", email);
    return res.status(200).send(pageHtml(`${email} se ha dado de baja del resumen semanal. No recibirás más correos.`, true));
  } catch (err) {
    return res.status(200).send(pageHtml("No se pudo procesar la baja, inténtalo de nuevo en unos minutos.", false));
  }
};

function pageHtml(message, ok) {
  return `<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Baja del resumen semanal</title>
<meta name="robots" content="noindex">
<style>body{font-family:system-ui,sans-serif; background:#faf7f0; color:#1c1812; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:20px;}
.box{max-width:420px; text-align:center; background:#fff; border:1px solid #e5ddd0; border-radius:6px; padding:32px 28px;}
a{color:#a33b2b;}</style></head>
<body><div class="box"><p>${ok ? '✓' : '⚠️'} ${message}</p><p><a href="/">Volver a Radar de Nichos</a></p></div></body></html>`;
}
