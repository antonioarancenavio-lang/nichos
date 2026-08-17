// Crea una sesion de pago de Stripe (suscripcion) y devuelve la URL a la que
// redirigir al usuario. Necesita las variables de entorno STRIPE_SECRET_KEY,
// STRIPE_PRICE_ID (mensual), STRIPE_PRICE_ID_ANNUAL (opcional, anual) y
// SITE_URL configuradas en Vercel.
const Stripe = require("stripe");

module.exports = async (req, res) => {
  if (!process.env.STRIPE_SECRET_KEY || !process.env.STRIPE_PRICE_ID) {
    return res.status(500).json({ error: "Stripe no esta configurado todavia (faltan variables de entorno)." });
  }
  const stripe = Stripe(process.env.STRIPE_SECRET_KEY);
  const siteUrl = process.env.SITE_URL || `https://${req.headers.host}`;

  let plan = "monthly";
  try {
    if (req.body && typeof req.body === "object") plan = req.body.plan || "monthly";
    else if (req.body) plan = JSON.parse(req.body).plan || "monthly";
  } catch (e) { /* body vacio o no-JSON, se queda en monthly */ }

  const priceId = (plan === "annual" && process.env.STRIPE_PRICE_ID_ANNUAL)
    ? process.env.STRIPE_PRICE_ID_ANNUAL
    : process.env.STRIPE_PRICE_ID;

  try {
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      success_url: `${siteUrl}/?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${siteUrl}/planes.html`,
    });
    res.status(200).json({ url: session.url });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
};
