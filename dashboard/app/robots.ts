import type { MetadataRoute } from "next";

import { SITE } from "@/lib/site";

/**
 * The app itself must never be indexed: those routes are behind auth and would
 * only ever surface as login redirects in search results.
 *
 * And a non-production deployment must not be indexed *at all*. Staging serves
 * the same marketing copy on dev.qonvo.org, so without this it competes with
 * production as duplicate content. The Caddyfile carries an X-Robots-Tag for
 * its staging hosts, but staging reaches the internet through the Cloudflare
 * Tunnel, which applies no headers, so the app has to say it itself. Default
 * "production" matches components/env-badge.tsx: an unset value means the real
 * thing, which is the safe reading for a variable that is baked in at build
 * time and therefore easy to forget.
 */
const IS_PRODUCTION = (process.env.NEXT_PUBLIC_QONVO_ENV ?? "production") === "production";

export default function robots(): MetadataRoute.Robots {
  if (!IS_PRODUCTION) {
    return { rules: { userAgent: "*", disallow: "/" } };
  }
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/inbox",
        "/knowledge",
        "/integrations",
        "/settings",
        "/analytics",
        "/team",
        "/onboarding",
        "/admin",
        "/api/",
        "/backend/",
        "/accept-invite",
        "/reset-password",
      ],
    },
    sitemap: `${SITE.url}/sitemap.xml`,
  };
}
