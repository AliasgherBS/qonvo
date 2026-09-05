import type { NextConfig } from "next";

// The backend is proxied under /backend/* so the whole app (dashboard + API)
// lives on one origin — needed for a single-URL public tunnel (zrok) with no
// CORS. The destination is read at server start, so it works in standalone.
const INTERNAL_API_URL = process.env.INTERNAL_API_URL ?? "http://localhost:8000";

// Staging builds into .next-staging so a staging and a production build can
// coexist on one box. NEXT_PUBLIC_* values are baked in at build time, so
// sharing one output directory would mean whichever built last wins and the
// other silently serves the wrong API URL and environment badge.
const DIST_DIR = process.env.NEXT_DIST_DIR ?? ".next";

const nextConfig: NextConfig = {
  output: "standalone",
  distDir: DIST_DIR,
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${INTERNAL_API_URL}/:path*` }];
  },
};

export default nextConfig;
