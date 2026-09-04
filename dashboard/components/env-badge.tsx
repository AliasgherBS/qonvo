/**
 * Which environment am I looking at?
 *
 * Production renders nothing — the absence of a badge is what "this is real"
 * looks like, and a permanent banner on the live product would be noise. Any
 * other environment says so loudly, because the expensive mistake is doing
 * something destructive while believing you are on staging.
 *
 * Driven by NEXT_PUBLIC_QONVO_ENV, which is baked in at build time, so a
 * staging build cannot accidentally claim to be production at runtime.
 */

const ENV = process.env.NEXT_PUBLIC_QONVO_ENV ?? "production";

const LABELS: Record<string, { text: string; classes: string }> = {
  staging: {
    text: "Staging",
    classes: "bg-accent text-ink",
  },
  development: {
    text: "Local",
    classes: "bg-surface text-paper",
  },
};

export function EnvBadge({ className = "" }: { className?: string }) {
  const label = LABELS[ENV];
  if (!label) return null;

  return (
    <span
      title={`This is the ${label.text.toLowerCase()} environment, not production.`}
      className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-extrabold uppercase tracking-wide ${label.classes} ${className}`}
    >
      {label.text}
    </span>
  );
}

export const IS_PRODUCTION = ENV === "production";
