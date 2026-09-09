import type { Role } from "@/lib/api";

/**
 * Who may reach which page, in one place (teardown V3).
 *
 * The sidebar branched on `qonvo_admin` or not, so there was no staff branch at
 * all: a receptionist saw Business, Team and Billing exactly as an owner did.
 * Until the authorization fix that shipped alongside this, most of those pages
 * also worked when clicked.
 *
 * This lives in its own module rather than in the sidebar because four places
 * need the same answer -- the sidebar, the mobile bar, the middleware redirect
 * and the layout's rep switch -- and three of them silently disagreeing is how
 * navigation and authorization drift apart. It has to stay free of runtime
 * imports so the middleware can use it in the edge runtime; the `Role` import
 * is type-only and is erased.
 *
 * Hiding rather than marking, which is the choice the teardown left open. For a
 * receptionist in a small business, a Billing entry that answers 403 is worse
 * than no Billing entry: it looks like the product is broken rather than like
 * the page is not theirs. The owner is the one who needs it and the owner can
 * see it.
 */

/**
 * Pages that only an owner can do anything useful on.
 *
 * Each one's primary action is owner-gated in the API, so a staff seat would
 * land on a form that refuses to save. Reads a staff seat genuinely needs
 * (their plan's limits, what the rep is configured to do) stay open on the API
 * and are surfaced where they work rather than on a page they cannot use.
 */
export const OWNER_ONLY_PREFIXES = [
  "/business", // PUT /api/config, including the payment details the rep reads out
  "/team", // invites and removals, and seats cost money
  "/billing", // checkout, plan changes, cancellation
  "/behavior", // PUT /api/config: what the rep tells customers
  "/skills", // PUT /api/config
  "/integrations", // connects and disconnects a business's Google account
  "/onboarding", // creates a session and shows a pairing QR: re-links the number
] as const;

/**
 * Tenant-scoped pages, which a cross-tenant admin has no tenant for.
 *
 * Distinct from the list above and easy to confuse with it: these are pages an
 * *admin* cannot use, not pages a *staff seat* cannot use.
 */
export const TENANT_PREFIXES = [
  "/inbox",
  "/knowledge",
  "/analytics",
  "/settings",
  ...OWNER_ONLY_PREFIXES,
] as const;

function matches(pathname: string, prefixes: readonly string[]): boolean {
  // Exact, or a path segment. A bare `startsWith("/team")` also matches
  // "/teamwork", which is the kind of thing that only shows up once a route
  // with an unlucky name is added.
  return prefixes.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export function isOwnerOnlyPath(pathname: string): boolean {
  return matches(pathname, OWNER_ONLY_PREFIXES);
}

export function isTenantPath(pathname: string): boolean {
  return matches(pathname, TENANT_PREFIXES);
}

/** Whether this role should be allowed to load this page at all. */
export function canReach(role: Role, pathname: string): boolean {
  if (role === "qonvo_admin") return !isTenantPath(pathname);
  if (role === "staff") return !isOwnerOnlyPath(pathname);
  return true;
}
