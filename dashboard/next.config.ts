import type { NextConfig } from "next";

// The backend is proxied under /backend/* so the whole app (dashboard + API)
// lives on one origin — needed for a single-URL public tunnel (zrok) with no
// CORS. The destination is read at server start, so it works in standalone.
const INTERNAL_API_URL = process.env.INTERNAL_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/backend/:path*", destination: `${INTERNAL_API_URL}/:path*` }];
  },
};

export default nextConfig;
