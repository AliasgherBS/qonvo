import { CONTACT } from "@/lib/contact";

/**
 * Single source of truth for the Terms and Privacy pages.
 *
 * ⚠️ FILL THESE IN before submitting the OAuth client to Google, and before any
 * real customer signs up. Google's reviewers check that the privacy policy names
 * a real, reachable operator; placeholder values are a common rejection reason.
 * These documents are a good-faith starting point, not legal advice - have them
 * reviewed against the jurisdiction you actually operate in.
 */
export const LEGAL = {
  /** Trading name shown throughout both documents. */
  companyName: "Qonvo",
  /** Registered legal entity, if different from the trading name. */
  legalEntity: "Qonvo",
  /** Where you are established - governs the Terms and data-protection claims. */
  jurisdiction: "Pakistan",
  /** Must be a monitored address; Google emails this during verification. */
  contactEmail: CONTACT.email,
  /** Same address, or a dedicated one, for data-deletion and access requests. */
  privacyEmail: CONTACT.email,
  /** Public origin these pages are served from. */
  siteUrl: "https://qonvo.org",
  /** Shown at the top of both documents. */
  lastUpdated: "15 August 2026",
  /**
   * Google Search Console HTML-tag verification token. Rendered into <head> on
   * every page via the root layout's metadata. Google re-checks periodically, so
   * leave it in place after verification succeeds - removing it un-verifies the
   * property, which in turn blocks OAuth app verification.
   */
  googleSiteVerification: "teVyxdgaBnnvMQen7MFi2_OMHrXElkl1ubjK4f5dWl8",
} as const;

/**
 * Google requires this statement, close to verbatim, from any app using its APIs.
 * Reviewers look for it explicitly - don't paraphrase it away.
 */
export const GOOGLE_LIMITED_USE =
  "Qonvo's use and transfer of information received from Google APIs to any other app " +
  "adheres to the Google API Services User Data Policy, including the Limited Use requirements.";
