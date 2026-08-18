/**
 * Single source for anything that names or locates the site.
 *
 * The domain is not settled (qonvo.ai or qonvo.org), so nothing may hardcode
 * it. Set NEXT_PUBLIC_SITE_URL at build time. NEXT_PUBLIC_* is baked in during
 * `next build`, so a bare restart will not pick up a change to it.
 */
export const SITE = {
  url: process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3002",
  name: "Qonvo",
  tagline: "Never miss a customer again.",
  description:
    "Qonvo is an AI customer rep on your own WhatsApp number. It answers in seconds, day or night, in your customer's language, and books appointments, takes orders and logs leads.",
} as const;
