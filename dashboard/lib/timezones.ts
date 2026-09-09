/**
 * The timezone list for the Business page control (teardown B1, N1, V2).
 *
 * `Intl.supportedValuesOf("timeZone")` returns well over four hundred names.
 * That is the correct set and the wrong control: an owner in Lahore should not
 * scroll past America/Argentina/Salta to find Asia/Karachi. So the list is the
 * browser's own zone first, then the region this product actually sells into,
 * then a short set of common ones, then everything else the runtime knows.
 *
 * Not hard-coded to a single list, because the fallback matters: an owner in a
 * city nobody thought of still has to be able to pick it, and the failure this
 * fixes was precisely a timezone nobody could change.
 */

/** Where Qonvo actually sells. First in the list, after the browser's guess. */
const NEARBY = [
  "Asia/Karachi",
  "Asia/Dubai",
  "Asia/Riyadh",
  "Asia/Kolkata",
  "Asia/Dhaka",
  "Asia/Kabul",
  "Asia/Muscat",
  "Asia/Qatar",
  "Asia/Kuwait",
  "Asia/Bahrain",
];

const COMMON = [
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "Europe/Istanbul",
  "Asia/Singapore",
  "Asia/Kuala_Lumpur",
  "Asia/Jakarta",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Australia/Sydney",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Toronto",
  "Africa/Cairo",
  "Africa/Lagos",
  "Africa/Johannesburg",
];

/**
 * The browser's own timezone, or null when it cannot be determined.
 *
 * This is what the field defaults to for a new tenant, rather than UTC. A
 * default that is right for almost everybody is the whole fix: the previous
 * one was wrong for everybody outside Britain in winter, and wrong silently.
 */
export function browserTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

/** Ordered options: the browser's zone, then nearby, common, and the rest. */
export function timezoneOptions(current?: string): string[] {
  let all: string[] = [];
  try {
    // Not available in every runtime, and a missing list must not empty the
    // control.
    all = Intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    all = [];
  }

  const seen = new Set<string>();
  const ordered: string[] = [];
  const push = (zone: string | null | undefined) => {
    if (!zone || seen.has(zone)) return;
    seen.add(zone);
    ordered.push(zone);
  };

  push(current);
  push(browserTimezone());
  NEARBY.forEach(push);
  COMMON.forEach(push);
  all.forEach(push);

  // A runtime with neither supportedValuesOf nor a resolvable zone still gets
  // a usable list rather than an empty select.
  if (ordered.length === 0) NEARBY.concat(COMMON).forEach(push);
  return ordered;
}

/** The current time in a zone, so the setting confirms itself. */
export function timeIn(zone: string): string | null {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: zone,
      hour: "numeric",
      minute: "2-digit",
      weekday: "short",
    }).format(new Date());
  } catch {
    return null;
  }
}

/** The UTC offset of a zone, as "+05:00". */
export function offsetOf(zone: string): string | null {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: zone,
      timeZoneName: "longOffset",
    }).formatToParts(new Date());
    const name = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
    // "GMT+05:00" -> "+05:00"; plain "GMT" means UTC.
    return name.replace("GMT", "") || "+00:00";
  } catch {
    return null;
  }
}
