import type { MetadataRoute } from "next";

import { SITE } from "@/lib/site";

/**
 * The app itself must never be indexed: those routes are behind auth and would
 * only ever surface as login redirects in search results.
 */
export default function robots(): MetadataRoute.Robots {
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
