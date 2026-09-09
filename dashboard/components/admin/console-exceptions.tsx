"use client";

import { AlertTriangle, Check, Radio, ScrollText, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { adminFleet, adminFleetUsage, adminTenants } from "@/lib/api";
import { useApi, useAuthToken } from "@/lib/use-api";

/**
 * What is wrong, before what exists.
 *
 * The console opened on six equal counters: businesses, connected, with
 * knowledge, knowledge sources, messages, cost. Every one of them is a number
 * an operator looks at once a week, rendered at the size of something urgent,
 * above the only screen that can tell you a customer's rep has stopped
 * answering.
 *
 * So this leads instead, and it is deliberately quiet when there is nothing to
 * say: one green line. Nothing here is a new API. Fleet, fleet usage and the
 * tenant list are all already fetched by the pages this sits above, and each
 * exception links to the screen that can act on it, because a count nobody can
 * click is a second thing to go and look up.
 */

/** Anything that is not one of these means the number is not answering. */
const HEALTHY_SESSION_STATES = ["WORKING"];

export function ConsoleExceptions() {
  const token = useAuthToken();
  const fleet = useApi(() => adminFleet.list({ token }), [token]);
  const usage = useApi(() => adminFleetUsage.list({ token }), [token]);
  const tenants = useApi(() => adminTenants.list({ token }), [token]);

  const loading = fleet.loading || usage.loading || tenants.loading;

  if (loading) {
    return <Skeleton className="h-16 w-full rounded-2xl" />;
  }

  const brokenSessions = (fleet.data ?? []).filter(
    (s) => !HEALTHY_SESSION_STATES.includes((s.liveStatus ?? s.status ?? "").toUpperCase()),
  );
  const overLimit = (usage.data ?? []).filter((t) => t.worstState === "over");
  const nearLimit = (usage.data ?? []).filter((t) => t.worstState === "near");
  const suspended = (tenants.data ?? []).filter((t) => t.status === "suspended");
  // Signed up, never connected a number. Not an incident, but the single most
  // useful number in the console: it is the whole of activation.
  const connectedTenantIds = new Set(
    (fleet.data ?? [])
      .filter((s) => HEALTHY_SESSION_STATES.includes((s.liveStatus ?? s.status ?? "").toUpperCase()))
      .map((s) => s.tenantId),
  );
  const neverConnected = (tenants.data ?? []).filter((t) => !connectedTenantIds.has(t.id));

  const exceptions = [
    {
      key: "sessions",
      show: brokenSessions.length > 0,
      tone: "danger" as const,
      icon: <Radio className="h-4 w-4" />,
      title: `${brokenSessions.length} ${brokenSessions.length === 1 ? "number is" : "numbers are"} not answering`,
      detail: brokenSessions
        .map((s) => `${s.tenantName ?? s.name} (${s.liveStatus ?? s.status})`)
        .join(", "),
      href: "/admin/fleet",
      cta: "Open Fleet",
    },
    {
      key: "over",
      show: overLimit.length > 0,
      tone: "danger" as const,
      icon: <ShieldAlert className="h-4 w-4" />,
      title: `${overLimit.length} ${overLimit.length === 1 ? "tenant is" : "tenants are"} over a limit`,
      detail: overLimit.map((t) => t.tenantName ?? t.tenantId.slice(0, 8)).join(", "),
      href: "/admin/usage",
      cta: "Open Usage",
    },
    {
      key: "near",
      show: nearLimit.length > 0,
      tone: "warning" as const,
      icon: <AlertTriangle className="h-4 w-4" />,
      title: `${nearLimit.length} ${nearLimit.length === 1 ? "tenant is" : "tenants are"} close to a limit`,
      detail: nearLimit.map((t) => t.tenantName ?? t.tenantId.slice(0, 8)).join(", "),
      href: "/admin/usage",
      cta: "Open Usage",
    },
    {
      key: "suspended",
      show: suspended.length > 0,
      tone: "warning" as const,
      icon: <ShieldAlert className="h-4 w-4" />,
      title: `${suspended.length} suspended ${suspended.length === 1 ? "business" : "businesses"}`,
      detail: suspended.map((t) => t.name).join(", "),
      href: "/admin/tenants",
      cta: "Open Tenants",
    },
    {
      key: "activation",
      show: neverConnected.length > 0,
      tone: "muted" as const,
      icon: <AlertTriangle className="h-4 w-4" />,
      title: `${neverConnected.length} of ${tenants.data?.length ?? 0} ${
        neverConnected.length === 1 ? "business has" : "businesses have"
      } no working number`,
      detail: neverConnected.map((t) => t.name).join(", "),
      href: "/admin/tenants",
      cta: "Open Tenants",
    },
  ].filter((e) => e.show);

  if (exceptions.length === 0) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-primary/30 bg-primary/5 px-4 py-3 text-sm">
        <Check className="h-4 w-4 shrink-0 text-primary-strong" />
        <span className="font-semibold">
          Nothing needs attention. {tenants.data?.length ?? 0} businesses, all numbers answering and
          inside their limits.
        </span>
        <Link
          href="/admin/audit"
          className="ml-auto inline-flex items-center gap-1.5 text-xs font-semibold text-primary-strong underline-offset-2 hover:underline"
        >
          <ScrollText className="h-3.5 w-3.5" />
          Audit log
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {exceptions.map((e) => (
        <div
          key={e.key}
          className={`flex flex-wrap items-start gap-3 rounded-2xl border px-4 py-3 text-sm ${
            e.tone === "danger"
              ? "border-danger/40 bg-danger/5"
              : e.tone === "warning"
                ? "border-warning/40 bg-warning/5"
                : "border-border bg-surface"
          }`}
        >
          <span
            className={`mt-0.5 shrink-0 ${
              e.tone === "danger"
                ? "text-danger"
                : e.tone === "warning"
                  ? "text-warning"
                  : "text-muted-foreground"
            }`}
          >
            {e.icon}
          </span>
          <div className="min-w-[12rem] flex-1">
            <p className="font-semibold">{e.title}</p>
            {e.detail ? <p className="mt-0.5 text-xs text-muted-foreground">{e.detail}</p> : null}
          </div>
          <Link
            href={e.href}
            className="shrink-0 text-xs font-semibold text-primary-strong underline-offset-2 hover:underline"
          >
            {e.cta}
          </Link>
        </div>
      ))}
    </div>
  );
}
