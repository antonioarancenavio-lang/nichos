// Comprueba que una sesion de Stripe Checkout se completo correctamente y
// devuelve el customerId asociado, para que el navegador lo guarde y pueda
// usarlo despues para comprobar el estado de la suscripcion.
const Stripe = require("stripe");

module.exports = async (req, res) => {
  if (!process.env.STRIPE_SECRET_KEY) {
    return res.status(500).json({ error: "Stripe no esta configurado todavia." });
  }
  const stripe = Stripe(process.env.STRIPE_SECRET_KEY);
  const sessionId = req.query.session_id;
  if (!sessionId) return res.status(400).json({ error: "Falta session_id" });

  try {
    const session = await stripe.checkout.sessions.retrieve(sessionId);
    if (session.payment_status === "paid" || session.status === "complete") {
      return res.status(200).json({ active: true, customerId: session.customer });
    }
    res.status(200).json({ active: false });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
};
