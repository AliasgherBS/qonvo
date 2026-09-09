import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { TENANT_PREFIXES, isOwnerOnlyPath, isTenantPath } from "@/lib/nav-access";
import { cspWithNonce } from "@/lib/security-headers";

/**
 * A fresh nonce for every response, so the CSP can allow our own inline scripts
 * without allowing anybody else's.
 *
 * `crypto.getRandomValues` rather than `Math.random`: a guessable nonce is the
 * same as no nonce, since the whole mechanism is that an injected script cannot
 * know the value. Web Crypto is what the middleware runtime has.
 */
function newNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

/**
 * Attach the nonce so both Next and our own components can find it.
 *
 * Next reads the nonce out of the `Content-Security-Policy` header on the
 * *request* and stamps its hydration bootstrap with it, which is why the header
 * is set on the request as well as the response. `x-nonce` is the copy our own
 * server components read through `headers()`.
 */
function withCsp(response: NextResponse, nonce: string): NextResponse {
  response.headers.set("Content-Security-Policy", cspWithNonce(nonce));
  return response;
}

// `/api/auth/*` must be public — Auth.js's own routes serve login callbacks,
// csrf, and session, and gating them behind auth is a chicken-and-egg lockout
// (caught live: /login redirected to itself, no cookie was ever issued).
// /terms and /privacy must be public too: Google's OAuth verification fetches
// the privacy policy anonymously, and a login redirect reads as "no policy".
const PUBLIC_PREFIXES = [
  "/login",
  "/signup",
  "/forgot-password",
  "/reset-password",
  "/accept-invite",
  "/verify-email",
  "/api/auth",
  "/terms",
  "/privacy",
  // Next's file-convention metadata routes have no file extension, so the
  // matcher's extension exclusion below does not cover them. Social crawlers
  // fetch these anonymously; gating them means a login redirect instead of a
  // preview image, and every share renders blank. Caught live.
  "/opengraph-image",
  "/twitter-image",
];

// Matched exactly, not by prefix — "/" as a prefix would make the whole app public.
const PUBLIC_EXACT = ["/"];

/**
 * Every path prefix in the app that resolves to a real page behind auth.
 *
 * This exists for one reason (teardown A1): a URL that matches no route at all
 * must reach Next's 404 rather than the login redirect. It used to reach the
 * redirect, so a mistyped marketing link asked a stranger to sign in and a
 * crawler recorded a soft 404 instead of a real one.
 *
 * Middleware runs before routing, so it cannot ask Next whether a route
 * exists. It has to be told, and this is the telling. The tenant pages come
 * from lib/nav-access, which the sidebar, the mobile bar and the redirects
 * below already read, so a new tenant page has to be added there regardless.
 * `/account` and `/admin` are the two that list does not cover, by design: it
 * answers "which pages are a tenant's", and those two are neither.
 *
 * Why an omission here cannot make a page public. Middleware is not the only
 * gate. Every route under app/(dashboard) renders inside a layout that calls
 * `auth()` and redirects to /login when there is no session, and every API
 * call those pages make carries the session's bearer token or 401s. Middleware
 * is the gate that makes the redirect fast and gives it a callbackUrl; the
 * layout is the gate that makes it safe. A route accidentally left out of this
 * list therefore still redirects a signed-out visitor to /login, one hop later
 * and without the callbackUrl. A route wrongly left *in* it is gated exactly as
 * it is today. Neither mistake opens anything, which is why the list is allowed
 * to be a list.
 */
const APP_PREFIXES = [...TENANT_PREFIXES, "/account", "/admin"];

function isAppPath(pathname: string): boolean {
  return APP_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

/**
 * Query parameters that are credentials and must never persist in a URL.
 *
 * Polar appends `customer_session_token` to whatever `success_url` it is given,
 * so a paying customer lands on `/billing?customer_session_token=polar_cst_...`
 * with a live bearer token in the address bar. From there it leaks into browser
 * history, the `Referer` header of every outbound link, any analytics that
 * records the path, and our own access logs.
 *
 * That token is scoped to one customer's billing portal and expires, so this is
 * not catastrophic. It is still a credential in a URL, which should never be
 * true, and we do not need it: portal sessions are minted on demand from the
 * API instead.
 */
const ALWAYS_SENSITIVE = [
  "customer_session_token",
  "customer_session",
  "session_token",
  "access_token",
  "id_token",
  "api_key",
  "apikey",
  "secret",
];

/**
 * `token` is the awkward one, and stripping it blindly breaks the product.
 *
 * Our own password-reset and team-invite emails link to
 * `/reset-password?token=...` and `/accept-invite?token=...`, and both pages
 * read it with `useSearchParams`. Removing it there would silently break every
 * reset and every invitation, which is a worse outcome than the leak this is
 * trying to prevent.
 *
 * All three are single-use by design: a reset token carries a fingerprint of
 * the current password hash and a verification token a fingerprint of the
 * unverified state, so using either invalidates it. A URL that stops working
 * once used is a different risk from one that keeps working.
 */
const TOKEN_PARAM_ALLOWED_ON = ["/reset-password", "/accept-invite", "/verify-email"];

function sensitiveParams(pathname: string): string[] {
  const allowed = TOKEN_PARAM_ALLOWED_ON.some((prefix) => pathname.startsWith(prefix));
  return allowed ? ALWAYS_SENSITIVE : [...ALWAYS_SENSITIVE, "token"];
}

export default auth((req) => {
  const { nextUrl } = req;
  const nonce = newNonce();
  const policy = cspWithNonce(nonce);

  // On the request, for Next to find and apply to its own inline scripts, and
  // for our components to read through headers().
  const requestHeaders = new Headers(req.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);
  const forward = { request: { headers: requestHeaders } };

  // Before anything else, including the auth check: a credential in a URL
  // should not survive one request, and an auth redirect would otherwise carry
  // the whole query string with it to /login.
  //
  // /api/auth is exempt because Auth.js round-trips its own parameters through
  // these routes and rewriting them mid-flow breaks sign-in.
  if (!nextUrl.pathname.startsWith("/api/auth")) {
    const leaked = sensitiveParams(nextUrl.pathname).filter((key) =>
      nextUrl.searchParams.has(key),
    );
    if (leaked.length > 0) {
      const clean = new URL(nextUrl.href);
      for (const key of leaked) clean.searchParams.delete(key);
      return withCsp(NextResponse.redirect(clean), nonce);
    }
  }

  // Browsers refuse to persist cookies for the `0.0.0.0` host (it's a bind-all
  // address, not a real hostname), so a session cookie set here is silently
  // dropped and every authenticated navigation bounces back to /login. If the
  // dashboard was launched with HOSTNAME=0.0.0.0, that's the URL Next advertises
  // and users end up here — steer them to localhost so auth cookies stick.
  if (nextUrl.hostname === "0.0.0.0") {
    const fixed = new URL(nextUrl.href);
    fixed.hostname = "localhost";
    return withCsp(NextResponse.redirect(fixed), nonce);
  }

  // A session without a backend token isn't usable: it happens when Google SSO
  // succeeded at Google but the id_token exchange with our API failed. Treat it
  // as logged out, or the user lands on an inbox where every request 401s.
  const isLoggedIn = !!req.auth && !!req.auth.accessToken;
  const isPublicPath =
    PUBLIC_EXACT.includes(nextUrl.pathname) ||
    PUBLIC_PREFIXES.some((path) => nextUrl.pathname.startsWith(path));
  const isAdmin = req.auth?.user?.role === "qonvo_admin";

  // Behind a tunnel/reverse-proxy the Host header is the internal target
  // (localhost:3002), so redirects built from nextUrl.origin would bounce the
  // visitor to their own machine. Prefer the forwarded host to keep the public
  // origin intact.
  const fwdHost = req.headers.get("x-forwarded-host");
  const origin = fwdHost
    ? `${req.headers.get("x-forwarded-proto") ?? "https"}://${fwdHost}`
    : nextUrl.origin;

  // A cross-tenant admin has no tenant, so the tenant-scoped pages (inbox,
  // knowledge, …) 403 for them. Funnel admins to the admin console instead of
  // ever landing them on a broken page. The prefix lists live in
  // lib/nav-access so this and the two navs cannot disagree about who may go
  // where -- a hidden sidebar entry is decoration if the URL still loads.
  const adminHome = "/admin/tenants";

  // `isAppPath` is the A1 condition: without it, an unmatched URL took this
  // branch and became a login page. With it, an unmatched URL falls all the way
  // through to `NextResponse.next()` at the bottom, Next finds no route for it,
  // and app/not-found.tsx renders with a real 404 status. A signed-in visitor
  // already fell through this way, which is why they were the ones seeing the
  // unstyled default.
  if (!isLoggedIn && !isPublicPath && isAppPath(nextUrl.pathname)) {
    const loginUrl = new URL("/login", origin);
    loginUrl.searchParams.set("callbackUrl", nextUrl.pathname);
    // A Google sign-in that was refused for a reason leaves the reason on the
    // session. Carrying it through means /login can say what happened; without
    // it the user clicks Google, arrives back at the sign-in page, and has no
    // way to tell a refusal from a bug.
    if (req.auth?.authError) loginUrl.searchParams.set("error", req.auth.authError);
    return withCsp(NextResponse.redirect(loginUrl), nonce);
  }

  if (isLoggedIn && (nextUrl.pathname === "/login" || nextUrl.pathname === "/signup")) {
    return withCsp(NextResponse.redirect(new URL(isAdmin ? adminHome : "/inbox", origin)), nonce);
  }

  // Non-admins can't see /admin/*; admins get pulled off owner-only pages.
  if (isLoggedIn && !isAdmin && nextUrl.pathname.startsWith("/admin")) {
    return withCsp(NextResponse.redirect(new URL("/inbox", origin)), nonce);
  }
  if (isLoggedIn && isAdmin && isTenantPath(nextUrl.pathname)) {
    return withCsp(NextResponse.redirect(new URL(adminHome, origin)), nonce);
  }

  // A staff seat has no business on the owner pages, and every one of them
  // refuses its primary action at the API now. Redirecting rather than
  // rendering a form that cannot save: the alternative is a page that looks
  // functional until the moment somebody presses the button.
  if (isLoggedIn && req.auth?.user?.role === "staff" && isOwnerOnlyPath(nextUrl.pathname)) {
    return withCsp(NextResponse.redirect(new URL("/inbox", origin)), nonce);
  }

  return withCsp(NextResponse.next(forward), nonce);
});

export const config = {
  // Exclude /backend/*: it's the API reverse-proxy (the backend does its own
  // JWT auth), so middleware must not gate or redirect it.
  //
  // The static-file extension list must cover every public asset type, not
  // just images. Caught live: /hero.mp4 and /hero.webm fell through to the
  // auth check and 307'd to /login, so the landing hero played nothing for
  // logged-out visitors. txt and xml are listed ahead of need, for the
  // robots, sitemap and llms.txt routes.
  matcher: [
    "/((?!backend|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|mp4|webm|woff2?|txt|xml)$).*)",
  ],
};
