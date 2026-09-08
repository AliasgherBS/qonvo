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
  // hello@ rather than a personal address: it is an alias on the one Zoho
  // mailbox, so it costs nothing, it survives a change of personal provider,
  // and it can be handed to someone else without handing over an account.
  // See docs/EMAIL-SETUP.md.
  email: "hello@qonvo.org",
  emailHref: "mailto:hello@qonvo.org",
  // Where a signed-in customer is sent (teardown V7). The dashboard said
  // "contact support if you need it moved" and named a channel that appeared
  // nowhere in the product: no address, no link, no help destination in the
  // navigation. Another alias on the same mailbox, so it costs nothing and
  // matches QONVO_EMAIL_REPLY_TO. See docs/EMAIL-SETUP.md.
  support: "support@qonvo.org",
  supportHref: "mailto:support@qonvo.org",
} as const;
