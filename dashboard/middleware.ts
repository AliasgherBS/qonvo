import { NextResponse } from "next/server";

import { auth } from "@/auth";

const PUBLIC_PATHS = ["/login"];

export default auth((req) => {
  const { nextUrl } = req;
  const isLoggedIn = !!req.auth;
  const isPublicPath = PUBLIC_PATHS.some((path) => nextUrl.pathname.startsWith(path));

  if (!isLoggedIn && !isPublicPath) {
    const loginUrl = new URL("/login", nextUrl.origin);
    loginUrl.searchParams.set("callbackUrl", nextUrl.pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (isLoggedIn && nextUrl.pathname === "/login") {
    return NextResponse.redirect(new URL("/inbox", nextUrl.origin));
  }

  if (isLoggedIn && nextUrl.pathname.startsWith("/admin") && req.auth?.user?.role !== "qonvo_admin") {
    return NextResponse.redirect(new URL("/inbox", nextUrl.origin));
  }

  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
