"use client";

/**
 * Which stack am I about to change?
 *
 * The production and staging consoles are pixel-identical and the actions on
 * them are irreversible: delete a tenant, log a session out, reset an owner's
 * password. An operator with both open in two tabs has nothing to tell them
 * apart, which is a bad property for the only screen in the product that can
 * unlink a customer's phone.
 *
 * Derived from the API the browser is talking to rather than a new build-time
 * variable, deliberately. `NEXT_PUBLIC_*` is baked in at build time, so a
 * mislabelled build would keep lying until somebody rebuilt it, whereas the API
 * origin is the thing that actually decides which database the buttons hit.
 */

const PRODUCTION_HOSTS = ["api.qonvo.org"];

/** The staging stack answers on 8010; production dev runs on 8000. */
const STAGING_PORTS = ["8010", "3012"];

export type Environment = { label: string; tone: "danger" | "warning" | "muted"; detail: string };

export function detectEnvironment(apiUrl: string | undefined): Environment {
  let host = "";
  let port = "";
  try {
    const url = new URL(apiUrl ?? "");
    host = url.hostname;
    port = url.port;
  } catch {
    // An unparseable value is not a licence to claim this is staging.
    return { label: "Unknown environment", tone: "warning", detail: apiUrl ?? "no API url set" };
  }

  if (PRODUCTION_HOSTS.includes(host)) {
    return { label: "Production", tone: "danger", detail: host };
  }
  if (STAGING_PORTS.includes(port)) {
    return { label: "Staging", tone: "muted", detail: `${host}:${port}` };
  }
  // Local production stack. Same data as production, so it gets the same colour.
  return { label: "Local (production data)", tone: "danger", detail: `${host}:${port || "80"}` };
}

const TONE: Record<Environment["tone"], string> = {
  danger: "border-danger/40 bg-danger/10 text-danger",
  warning: "border-warning/40 bg-warning/10 text-warning",
  muted: "border-border-strong bg-surface-muted text-muted-foreground",
};

export function EnvBanner() {
  const env = detectEnvironment(process.env.NEXT_PUBLIC_API_URL);

  return (
    <div
      className={`flex flex-wrap items-center gap-2 rounded-xl border px-3 py-1.5 text-xs font-semibold ${TONE[env.tone]}`}
    >
      <span className="inline-block h-2 w-2 shrink-0 rounded-full bg-current" />
      <span>{env.label}</span>
      <span className="font-mono font-normal opacity-70">{env.detail}</span>
      <span className="font-normal opacity-70">
        Actions here are irreversible and attributed to you.
      </span>
    </div>
  );
}
