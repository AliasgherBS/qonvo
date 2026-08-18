/**
 * The only place contact details may live. `npm run verify:brand` fails if an
 * email address or phone number appears anywhere else in app/, components/ or
 * lib/.
 *
 * The WhatsApp line is answered by Qonvo itself, running the product with our
 * own knowledge loaded. That is deliberate: the contact button is a live demo,
 * and the copy leads with that rather than hiding it. Email is the fallback
 * for anyone who wants a person.
 */
export const CONTACT = {
  whatsapp: "+92 319 4505305",
  whatsappHref: "https://wa.me/923194505305",
  email: "alihuzezzy@gmail.com",
  emailHref: "mailto:alihuzezzy@gmail.com",
} as const;
