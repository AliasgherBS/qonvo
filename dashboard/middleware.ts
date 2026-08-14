import { NextResponse } from "next/server";

import { auth } from "@/auth";

// `/api/auth/*` must be public — Auth.js's own routes serve login callbacks,
// csrf, and session, and gating them behind auth is a chicken-and-egg lockout
// (caught live: /login redirected to itself, no cookie was ever issued).
const PUBLIC_PATHS = ["/login", "/signup", "/api/auth"];

export default auth((req) => {
  const { nextUrl } = req;

  // Browsers refuse to persist cookies for the `0.0.0.0` host (it's a bind-all
  // address, not a real hostname), so a session cookie set here is silently
  // dropped and every authenticated navigation bounces back to /login. If the
  // dashboard was launched with HOSTNAME=0.0.0.0, that's the URL Next advertises
  // and users end up here — steer them to localhost so auth cookies stick.
  if (nextUrl.hostname === "0.0.0.0") {
    const fixed = new URL(nextUrl.href);
    fixed.hostname = "localhost";
    return NextResponse.redirect(fixed);
  }

  const isLoggedIn = !!req.auth;
  const isPublicPath = PUBLIC_PATHS.some((path) => nextUrl.pathname.startsWith(path));
  const isAdmin = req.auth?.user?.role === "qonvo_admin";

  // Behind a tunnel/reverse-proxy the Host header is the internal target
  // (localhost:3002), so redirects built from nextUrl.origin would bounce the
  // visitor to their own machine. Prefer the forwarded host to keep the public
  // origin intact.
  const fwdHost = req.headers.get("x-forwarded-host");
  const origin = fwdHost
    ? `${req.headers.get("x-forwarded-proto") ?? "https"}://${fwdHost}`
    : nextUrl.origin;

  // A cross-tenant admin has no tenant, so the owner pages (inbox, knowledge,
  // …) 403 for them. Funnel admins to the admin console instead of ever landing
  // them on a broken tenant-scoped page.
  const OWNER_ONLY_PREFIXES = ["/inbox", "/knowledge", "/integrations", "/settings", "/analytics", "/onboarding"];
  const adminHome = "/admin/tenants";

  if (!isLoggedIn && !isPublicPath) {
    const loginUrl = new URL("/login", origin);
    loginUrl.searchParams.set("callbackUrl", nextUrl.pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (isLoggedIn && (nextUrl.pathname === "/login" || nextUrl.pathname === "/signup")) {
    return NextResponse.redirect(new URL(isAdmin ? adminHome : "/inbox", origin));
  }

  // Non-admins can't see /admin/*; admins get pulled off owner-only pages.
  if (isLoggedIn && !isAdmin && nextUrl.pathname.startsWith("/admin")) {
    return NextResponse.redirect(new URL("/inbox", origin));
  }
  if (isLoggedIn && isAdmin && OWNER_ONLY_PREFIXES.some((p) => nextUrl.pathname.startsWith(p))) {
    return NextResponse.redirect(new URL(adminHome, origin));
  }

  return NextResponse.next();
});

export const config = {
  // Exclude /backend/* — it's the API reverse-proxy (the backend does its own
  // JWT auth); middleware must not gate or redirect it.
  matcher: ["/((?!backend|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
