#!/usr/bin/env node
/**
 * Prove that who-can-see-what agrees everywhere it is asked (teardown V3, B4).
 *
 * `lib/nav-access.ts` is the single answer for four consumers: the sidebar, the
 * mobile bar, the middleware redirect and the layout's rep switch. Three of
 * them quietly disagreeing is how navigation and authorization drift apart, and
 * the module has no other test -- it cannot have an ordinary one, because the
 * middleware imports it in the edge runtime and the dashboard has no test
 * runner. So it is checked here, the way the brand and QR gates are.
 *
 * The parts worth pinning:
 *
 *  - a staff seat sees no owner-only destination, and the middleware sends them
 *    away from the same set (one list, so those cannot diverge);
 *  - the reads a staff seat genuinely needs stay reachable, because
 *    over-correcting is its own failure;
 *  - prefix matching is on path segments. A bare startsWith("/team") also
 *    matches "/teamwork", which only bites once a route with an unlucky name is
 *    added -- so the guard is asserted rather than assumed;
 *  - the two prefix lists are not the same list. OWNER_ONLY is what a *staff
 *    seat* cannot use; TENANT is what a cross-tenant *admin* cannot use.
 *    Confusing them is easy and the failure is silent.
 *
 * Run: npm run verify:nav
 */
import { readFileSync } from "node:fs";

// The module is TypeScript with a single type-only import, so it is read and
// evaluated rather than imported: adding a build step to a gate would mean the
// gate could fail for reasons that have nothing to do with the property.
const source = readFileSync(new URL("../lib/nav-access.ts", import.meta.url), "utf8");
const js = source
  .replace(/^import type .*$/gm, "")
  .replace(/:\s*readonly string\[\]/g, "")
  .replace(/:\s*string(\[\])?/g, "")
  .replace(/:\s*boolean/g, "")
  .replace(/:\s*Role/g, "")
  .replace(/\bas const\b/g, "")
  .replace(/^export /gm, "");

const mod = new Function(
  `${js}\nreturn { OWNER_ONLY_PREFIXES, TENANT_PREFIXES, isOwnerOnlyPath, isTenantPath, canReach };`
)();
const { OWNER_ONLY_PREFIXES, TENANT_PREFIXES, isOwnerOnlyPath, isTenantPath, canReach } = mod;

const failures = [];
const check = (name, actual, expected) => {
  if (actual !== expected) failures.push(`${name}: expected ${expected}, got ${actual}`);
};

// The gate is worthless if the extraction silently produced nothing.
if (!Array.isArray(OWNER_ONLY_PREFIXES) || OWNER_ONLY_PREFIXES.length < 5) {
  console.error(`verify-nav: read only ${OWNER_ONLY_PREFIXES?.length} owner-only prefixes; the parse is wrong`);
  process.exit(1);
}

// --- the set itself, written out rather than read back --------------------
//
// Iterating OWNER_ONLY_PREFIXES only proves the module is self-consistent. It
// cannot notice a page *leaving* the list, which is the direction that costs
// something: delete "/billing" and every assertion below still passes while a
// receptionist gets the billing page back. Verified by doing exactly that --
// the first version of this gate reported success. So the pages that must be
// owner-only are named here, independently.
const MUST_BE_OWNER_ONLY = [
  "/business",     // PUT /api/config, including the payment details the rep reads out
  "/team",         // invites and removals, and seats cost money
  "/billing",      // checkout, plan changes, cancellation
  "/behavior",     // what the rep tells customers
  "/skills",       // what the rep is allowed to do
  "/integrations", // connects and disconnects the business's Google account
  "/onboarding",   // creates a session and shows a pairing QR: re-links the number
];
for (const prefix of MUST_BE_OWNER_ONLY) {
  check(`OWNER_ONLY_PREFIXES protects ${prefix}`, OWNER_ONLY_PREFIXES.includes(prefix), true);
  check(`canReach("staff", "${prefix}") [pinned]`, canReach("staff", prefix), false);
}
// And the reverse: nothing has been added to the list without being considered
// here, so a new owner-only page has to be declared in both places.
for (const prefix of OWNER_ONLY_PREFIXES) {
  if (!MUST_BE_OWNER_ONLY.includes(prefix)) {
    failures.push(`${prefix} is owner-only in lib/nav-access.ts but not listed in this gate; add it (and check it is meant to be hidden from staff, not just gated)`);
  }
}

// --- a staff seat sees, and can load, no owner-only page -------------------
for (const prefix of OWNER_ONLY_PREFIXES) {
  check(`canReach("staff", "${prefix}")`, canReach("staff", prefix), false);
  check(`canReach("staff", "${prefix}/anything")`, canReach("staff", `${prefix}/anything`), false);
  // The sidebar and the middleware must be answering from the same list.
  check(`isOwnerOnlyPath("${prefix}")`, isOwnerOnlyPath(prefix), true);
}

// --- and still reaches the work it is employed to do -----------------------
for (const path of ["/inbox", "/inbox/abc", "/knowledge", "/analytics", "/settings", "/account"]) {
  check(`canReach("staff", "${path}")`, canReach("staff", path), true);
}

// --- an owner reaches everything -----------------------------------------
for (const path of [...OWNER_ONLY_PREFIXES, "/inbox", "/knowledge"]) {
  check(`canReach("owner", "${path}")`, canReach("owner", path), true);
}

// --- a cross-tenant admin has no tenant, so tenant pages 403 for them -----
for (const prefix of TENANT_PREFIXES) {
  check(`canReach("qonvo_admin", "${prefix}")`, canReach("qonvo_admin", prefix), false);
}
check('canReach("qonvo_admin", "/admin")', canReach("qonvo_admin", "/admin"), true);
check('canReach("qonvo_admin", "/admin/audit")', canReach("qonvo_admin", "/admin/audit"), true);

// --- prefixes match segments, not substrings ------------------------------
// "/teamwork" is not "/team". This is the specific bug the module's own
// comment says it is guarding against, so it is the one most worth asserting.
for (const near of ["/teamwork", "/billing-history", "/businesses", "/skillset"]) {
  check(`isOwnerOnlyPath("${near}")`, isOwnerOnlyPath(near), false);
  check(`canReach("staff", "${near}")`, canReach("staff", near), true);
}

// --- the two lists are related, and are not the same ---------------------
for (const prefix of OWNER_ONLY_PREFIXES) {
  check(`TENANT_PREFIXES includes ${prefix}`, TENANT_PREFIXES.includes(prefix), true);
}
if (TENANT_PREFIXES.length === OWNER_ONLY_PREFIXES.length) {
  failures.push("TENANT_PREFIXES and OWNER_ONLY_PREFIXES are the same set; an admin would be able to reach tenant pages, or a staff seat blocked from the inbox");
}
check('isTenantPath("/inbox")', isTenantPath("/inbox"), true);
check('isOwnerOnlyPath("/inbox")', isOwnerOnlyPath("/inbox"), false);

if (failures.length) {
  console.error(`verify-nav: ${failures.length} failure(s)`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
console.log(
  `verify-nav: ${OWNER_ONLY_PREFIXES.length} owner-only and ${TENANT_PREFIXES.length} tenant prefixes agree across sidebar and middleware`
);
