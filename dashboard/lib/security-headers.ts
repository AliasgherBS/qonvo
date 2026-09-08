/**
 * Response security headers, applied to every route by `next.config.ts`.
 *
 * The site was serving none of these. That is not a subtle gap: without
 * `X-Frame-Options` any page can be framed, without `Referrer-Policy` the full
 * URL of every page leaks to every outbound link, and without a CSP a single
 * injected script has the run of the origin.
 *
 * Each one below says what it stops, because a header nobody can explain is a
 * header the next person deletes to fix a bug.
 */

/**
 * Origins the app genuinely talks to. Kept here rather than inline in the CSP
 * string so adding one is a deliberate edit in a reviewed list.
 *
 * `apis.google.com` is the Google Picker: `lib/google-picker.ts` injects that
 * script at runtime to let an owner choose a Sheet, and blocking it breaks the
 * Sheets integration. `accounts.google.com` is sign-in.
 */
const GOOGLE_SCRIPTS = ["https://apis.google.com", "https://accounts.google.com"];

/**
 * Cloudflare injects its Web Analytics beacon into responses served through the
 * tunnel. We do not add the tag; the edge does, so blocking it produces a CSP
 * violation on every page load plus a follow-on TypeError from the half-loaded
 * script, and no amount of editing this codebase stops it.
 *
 * Two honest options: allow it, or turn Web Analytics off in the Cloudflare
 * dashboard. Allowed here, because a console full of violations trains everyone
 * to ignore the console, and that costs more than this script does.
 */
const CLOUDFLARE_ANALYTICS = ["https://static.cloudflareinsights.com"];
const GOOGLE_FRAMES = ["https://accounts.google.com", "https://content-sheets.googleapis.com"];
const GOOGLE_CONNECT = ["https://apis.google.com", "https://content-sheets.googleapis.com"];

/** The API host, which is a different origin now the domain is live. */
const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL ?? "";

function csp(): string {
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],

    // 'unsafe-inline' is required and not laziness: Next.js inlines its
    // hydration bootstrap, and ThemeScript sets the theme before first paint
    // specifically to avoid a flash of the wrong one. A nonce would be the
    // right fix and needs middleware-generated nonces threaded through the
    // document, which is a change worth making separately rather than
    // alongside a security-headers pass.
    "script-src": ["'self'", "'unsafe-inline'", ...GOOGLE_SCRIPTS, ...CLOUDFLARE_ANALYTICS],

    // Tailwind emits a stylesheet, but Next also inlines critical CSS.
    "style-src": ["'self'", "'unsafe-inline'"],

    // data: covers inlined icons; blob: covers object URLs used for previews.
    "img-src": ["'self'", "data:", "blob:", "https:"],
    "font-src": ["'self'", "data:"],
    "media-src": ["'self'"],

    // Where fetch/XHR may go. The API is its own origin now, so omitting it
    // would break every authenticated call while curl kept working, which is
    // the exact failure mode CORS already caused once on this project.
    // The beacon reports back to cloudflareinsights.com, so allowing the script
    // without the connect target would swap one console error for another.
    "connect-src": [
      "'self'",
      API_ORIGIN,
      ...GOOGLE_CONNECT,
      ...CLOUDFLARE_ANALYTICS,
    ].filter(Boolean),

    // The Picker renders in an iframe, and Google sign-in may.
    "frame-src": ["'self'", ...GOOGLE_FRAMES],

    // Nobody may frame us. This is the CSP form; X-Frame-Options below is the
    // same intent for older browsers that ignore it.
    "frame-ancestors": ["'none'"],

    // No <base> tag rewriting, and no plugins.
    "base-uri": ["'self'"],
    "object-src": ["'none'"],

    // Forms may only post to us. Stops an injected form exfiltrating a session
    // to somebody else's endpoint.
    "form-action": ["'self'"],
  };

  return Object.entries(directives)
    .map(([key, values]) => `${key} ${values.join(" ")}`)
    .join("; ");
}

export const SECURITY_HEADERS = [
  {
    // Two years, subdomains included. The site is HTTPS-only through the
    // tunnel already; this stops the first request of a session being
    // downgradeable.
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains",
  },
  {
    key: "Content-Security-Policy",
    value: csp(),
  },
  {
    // The reason this pass started. Without it the full URL, query string and
    // all, is sent as `Referer` to every third party the user clicks through
    // to. A provider that appends a session token to its success URL turns
    // that into a credential leak.
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    // Clickjacking. Redundant with frame-ancestors for modern browsers, kept
    // for the ones that only understand this.
    key: "X-Frame-Options",
    value: "DENY",
  },
  {
    // Stops a browser guessing that an uploaded text file is really a script.
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    // Nothing here needs a camera, a microphone or a location, and a page that
    // cannot ask cannot be tricked into asking.
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  },
  {
    // Isolates the browsing context from cross-origin windows that opened it.
    key: "Cross-Origin-Opener-Policy",
    value: "same-origin-allow-popups",
  },
  {
    key: "X-DNS-Prefetch-Control",
    value: "off",
  },
];
