import { FAQ } from "@/lib/faq";
import { SITE } from "@/lib/site";

/**
 * JSON-LD, rendered server-side so crawlers see it without executing anything.
 *
 * FAQPage is generated from the same lib/faq.ts array the visible section
 * renders, so the markup and the page can never disagree.
 *
 * SoftwareApplication carries no `offers` block on purpose: pricing is not
 * decided, and publishing a fabricated or zero price is worse than publishing
 * none. Add `offers` at the same time the visible tiers appear.
 */
export function StructuredData() {
  const data = [
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      name: SITE.name,
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web, WhatsApp",
      url: SITE.url,
      description: SITE.description,
    },
    {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: FAQ.map(({ q, a }) => ({
        "@type": "Question",
        name: q,
        acceptedAnswer: { "@type": "Answer", text: a },
      })),
    },
  ];

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}

/** Emitted once from the root layout, so it applies to every page. */
export function OrganizationData() {
  const data = {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: SITE.name,
    url: SITE.url,
    logo: `${SITE.url}/logo-mark.png`,
    description: SITE.description,
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}
