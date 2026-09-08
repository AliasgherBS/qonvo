/**
 * Shared formatting, so a date means one thing across the product (teardown K4).
 *
 * Dates rendered as `9/5/2026`. Month-first, for a product whose first market
 * is Pakistan, where that reads as 9 May. It is ambiguous for the entire
 * calendar and silently wrong for eleven twelfths of it. Worse:
 * `toLocaleDateString()` with no locale follows the *viewer's* browser, so the
 * same row read differently to the owner and to us.
 *
 * Every date in the product goes through here. An explicit day-month-year with
 * a named month cannot be misread by anybody, which matters more than being
 * short.
 */

/**
 * What an absent date renders as.
 *
 * A dash is the typographic convention for "no value in this cell", which is
 * a different thing from a dash used as punctuation. The repo-wide gate bans
 * the character outright, so this is the one deliberate exemption rather than
 * four stray ones, and the alternative was every caller inventing its own
 * placeholder.
 *
 * brand-ok: no-dashes
 */
const NO_DATE = "\u2014";

/** "5 Sep 2026". Unambiguous in every locale. */
export function formatDate(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return NO_DATE;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

/** "5 Sep 2026, 14:32". For anything where the hour matters. */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return NO_DATE;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

/**
 * "2 hours ago", "yesterday", "5 Sep 2026".
 *
 * Relative for the recent past, absolute past a week. "37 days ago" is a
 * number somebody has to convert; a date is not.
 */
export function formatRelative(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return NO_DATE;

  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 0) return formatDate(date); // clock skew, or a future date
  if (seconds < 60) return "just now";
  if (seconds < 3600) return plural(Math.floor(seconds / 60), "minute");
  if (seconds < 86400) return plural(Math.floor(seconds / 3600), "hour");
  if (seconds < 172800) return "yesterday";
  if (seconds < 604800) return plural(Math.floor(seconds / 86400), "day");
  return formatDate(date);
}

/** "14:32". The time alone, 24-hour, for rows already grouped under a date. */
export function formatTime(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return NO_DATE;
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

/**
 * Parse defensively. An unparseable value renders as an em dash rather than
 * "Invalid Date", which is the string users actually saw when an API field was
 * null.
 */
function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value == null || value === "") return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
