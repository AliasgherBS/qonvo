import type { MetadataRoute } from "next";

import { SITE } from "@/lib/site";

/** Only the genuinely public, indexable routes. */
const ROUTES = [
  { path: "/", priority: 1, changeFrequency: "weekly" as const },
  { path: "/signup", priority: 0.8, changeFrequency: "monthly" as const },
  { path: "/login", priority: 0.3, changeFrequency: "yearly" as const },
  { path: "/privacy", priority: 0.3, changeFrequency: "yearly" as const },
  { path: "/terms", priority: 0.3, changeFrequency: "yearly" as const },
];

export default function sitemap(): MetadataRoute.Sitemap {
  return ROUTES.map(({ path, priority, changeFrequency }) => ({
    url: `${SITE.url}${path}`,
    lastModified: new Date(),
    changeFrequency,
    priority,
  }));
}
