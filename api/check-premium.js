// Comprueba en tiempo real contra Stripe si un cliente tiene una suscripcion
// activa. No necesita base de datos propia: Stripe es la fuente de verdad.
const Stripe = require("stripe");

module.exports = async (req, res) => {
  if (!process.env.STRIPE_SECRET_KEY) {
    return res.status(200).json({ active: false });
  }
  const stripe = Stripe(process.env.STRIPE_SECRET_KEY);
  const customerId = req.query.customerId;
  if (!customerId) return res.status(200).json({ active: false });

  try {
    const subs = await stripe.subscriptions.list({ customer: customerId, status: "active", limit: 1 });
    res.status(200).json({ active: subs.data.length > 0 });
  } catch (err) {
    res.status(200).json({ active: false });
  }
};
