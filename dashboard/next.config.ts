import type { NextConfig } from "next";

import { SECURITY_HEADERS } from "./lib/security-headers";

// The backend is proxied under /backend/* so the whole app (dashboard + API)
// can live on one origin — needed for the single-URL tunnel era. Nothing in the
// app calls it any more: the API has its own hostname and the browser talks to
// it directly. Kept as an escape hatch.
//
// This value is baked into .next/routes-manifest.json at BUILD time, despite
// reading like a runtime lookup: Next serialises rewrites() into the build
// output. Setting INTERNAL_API_URL on the *container* does NOT change it, so
// the image has to be built with the right value — see dashboard/Dockerfile.
// Verified the hard way: a container built without it proxied to
// http://localhost:8000 and returned 500, while http://api:8000 was reachable
// from that very container.
//
// Runtime reads of INTERNAL_API_URL elsewhere (lib/api.ts, server side) DO
// honour the environment. Only this one is frozen at build time.
const INTERNAL_API_URL = process.env.INTERNAL_API_URL ?? "http://localhost:8000";

// Staging builds into .next-staging so a staging and a production build can
// coexist on one box. NEXT_PUBLIC_* values are baked in at build time, so
// sharing one output directory would mean whichever built last wins and the
// other silently serves the wrong API URL and environment badge.
const DIST_DIR = process.env.NEXT_DIST_DIR ?? ".next";

const nextConfig: NextConfig = {
  output: "standalone",
  distDir: DIST_DIR,
  // The version banner tells an attacker which Next.js CVEs to try. Nothing
  // needs it.
  poweredByHeader: false,
  async headers() {
    // Every route, including the marketing pages: a missing CSP on the landing
    // page is the same origin as the dashboard.
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${INTERNAL_API_URL}/:path*` }];
  },
};

export default nextConfig;
